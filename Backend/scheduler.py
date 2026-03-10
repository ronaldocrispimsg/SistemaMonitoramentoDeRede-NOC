import logging
import os
import time
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy.orm import Session

from Backend.checker import ping_host, tcp_check, resolve_dns_cached, http_check
from Backend.database import SessionLocal, ensure_runtime_schema
from Backend.metrics import (
    apply_preventive_logic,
    calc_jitter_http,
    calc_jitter_ping,
    calc_jitter_tcp,
    calc_latency_trend_http,
    calc_latency_trend_ping,
    calc_sla_rolling_http,
    calc_sla_rolling_ping,
    calc_sla_rolling_tcp,
    classify_trend,
    classify_trend_http,
    compute_health,
    max_severity,
    refine_severity,
)
from Backend.models import Alert, CheckResult, Host
from Backend.notifications import (
    build_dns_change_message,
    build_dns_ttl_low_message,
    build_failure_confirmed_message,
    build_health_critical_message,
    build_preventive_alert_message,
    build_recovery_message,
    send_telegram_alert,
)
from Backend.snmp_engine import (
    can_attempt_snmp,
    register_snmp_failure,
    register_snmp_success,
    snmp_has_usable_data,
    update_host_snmp,
)
from Backend.utils import (
    INCIDENT_TYPE_DNS_FAILURE,
    INCIDENT_TYPE_SERVICE_DEGRADED,
    INCIDENT_TYPE_SERVICE_DOWN,
    close_incident,
    consecutive_failures,
    open_incident,
)

logger = logging.getLogger("noc_lite.scheduler")

ALERT_FAIL_THRESHOLD = 2
ALERT_RECOVER_THRESHOLD = 1
DEGRADED_OPEN_THRESHOLD = 3

_ALERT_COOLDOWN_STATE = {}
_ALERT_COOLDOWN_LOCK = Lock()
_DEGRADED_STREAKS = {}
_DEGRADED_STREAKS_LOCK = Lock()

MONITOR_INTERVAL_SECONDS = int(os.getenv("NOC_MONITOR_INTERVAL_SECONDS", "20"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("NOC_CLEANUP_INTERVAL_SECONDS", "3600"))
SNMP_ALLOWED_COMMUNITY = "noc-lite"


def _alert_cooldown_passed(
    host_id: int,
    alert_type: str,
    cooldown_seconds: int,
    fingerprint: str | None = None,
) -> bool:
    key = (host_id, alert_type, fingerprint or "")
    now_ts = time.time()
    with _ALERT_COOLDOWN_LOCK:
        last_ts = _ALERT_COOLDOWN_STATE.get(key)
        if last_ts is not None and (now_ts - last_ts) < cooldown_seconds:
            return False
        _ALERT_COOLDOWN_STATE[key] = now_ts
        if len(_ALERT_COOLDOWN_STATE) > 10000:
            expire_before = now_ts - max(cooldown_seconds * 2, 300)
            stale = [k for k, ts in _ALERT_COOLDOWN_STATE.items() if ts < expire_before]
            for stale_key in stale:
                _ALERT_COOLDOWN_STATE.pop(stale_key, None)
    return True


def _set_degraded_streak(host_id: int, value: int) -> None:
    with _DEGRADED_STREAKS_LOCK:
        _DEGRADED_STREAKS[host_id] = value


def _increment_degraded_streak(host_id: int) -> int:
    with _DEGRADED_STREAKS_LOCK:
        current = _DEGRADED_STREAKS.get(host_id, 0) + 1
        _DEGRADED_STREAKS[host_id] = current
        return current


def _get_degraded_streak(host_id: int) -> int:
    with _DEGRADED_STREAKS_LOCK:
        return _DEGRADED_STREAKS.get(host_id, 0)


def determine_primary_check(host: Host) -> str:
    if host.http_url:
        return "HTTP"
    if host.port:
        return "TCP"
    return "PING"


def determine_operational_state(host: Host, ping_result, tcp_result, http_result):
    service_up_without_icmp = (
        not ping_result["success"]
        and (
            (tcp_result is not None and tcp_result.get("success"))
            or (http_result is not None and http_result.get("success"))
        )
    )
    primary_check = determine_primary_check(host)

    if primary_check == "HTTP" and http_result is not None:
        if http_result.get("success"):
            return "UP", primary_check, service_up_without_icmp
        tcp_ok = bool(tcp_result and tcp_result.get("success"))
        ping_ok = bool(ping_result.get("success"))
        if tcp_ok or ping_ok:
            return "DEGRADED", primary_check, service_up_without_icmp
        return "DOWN", primary_check, service_up_without_icmp

    if primary_check == "TCP" and tcp_result is not None:
        if tcp_result.get("success"):
            return "UP", primary_check, service_up_without_icmp
        if ping_result.get("success"):
            return "DEGRADED", primary_check, service_up_without_icmp
        return "DOWN", primary_check, service_up_without_icmp

    if ping_result.get("success") or service_up_without_icmp:
        return "UP", primary_check, service_up_without_icmp
    return "DOWN", primary_check, service_up_without_icmp


def _resolve_host_check_url(host: Host) -> str | None:
    if host.http_url:
        return host.http_url
    if host.port in (80, 443):
        protocol = "https" if host.port == 443 else "http"
        return f"{protocol}://{host.address}"
    if host.port:
        return f"http://{host.address}:{host.port}"
    return None


def _snmp_is_configured(host: Host) -> bool:
    community = (host.snmp_community or "").strip().lower()
    if community == SNMP_ALLOWED_COMMUNITY:
        return True

    logger.debug(
        "SNMP ignorado para host=%s: community inválida (%r). Permitida apenas: '%s'",
        host.name,
        host.snmp_community,
        SNMP_ALLOWED_COMMUNITY,
    )
    return False


def _extract_ips_and_ttl(dns_result):
    ips = []
    ttl = None
    ttl_remaining = None

    if isinstance(dns_result, tuple):
        if len(dns_result) == 3:
            ips, ttl, ttl_remaining = dns_result
        elif len(dns_result) == 1:
            ips = dns_result[0]
    elif isinstance(dns_result, list):
        ips = dns_result

    return ips, ttl, ttl_remaining


def _host_check_blocking(host_id: int) -> None:
    ensure_runtime_schema()
    db: Session = SessionLocal()
    try:
        host = (
            db.query(Host)
            .filter(Host.id == host_id, Host.active.is_(True))
            .first()
        )
        if host is None:
            return

        old_status = host.status
        old_severity = host.severity
        old_status_normalized = str(old_status or "").strip().upper()
        baseline_pending = bool(getattr(host, "baseline_pending", False))

        dns_result = resolve_dns_cached(host.address, db)
        ips, ttl, ttl_remaining = _extract_ips_and_ttl(dns_result)

        if ttl is not None:
            host.dns_ttl = ttl
        if ttl_remaining is not None:
            host.dns_ttl_remaining = ttl_remaining

        if ttl is not None and ttl < 60:
            if (
                (
                    not host.last_ttl_alert
                    or (datetime.utcnow() - host.last_ttl_alert).seconds > 3600
                )
                and _alert_cooldown_passed(
                    host.id, "DNS_TTL_LOW", 3600, fingerprint=str(ttl)
                )
            ):
                db.add(
                    Alert(
                        host_id=host.id,
                        alert_type="DNS_TTL_LOW",
                        old_status="ttl",
                        new_status=str(ttl),
                    )
                )
                send_telegram_alert(
                    build_dns_ttl_low_message(host, host.address, ttl, datetime.utcnow())
                )
                host.last_ttl_alert = datetime.utcnow()

        if not ips:
            host.status = "DOWN"
            host.last_resolved_ip = None
            host.last_check = datetime.utcnow()
            if baseline_pending:
                host.baseline_pending = False

            db.add(
                CheckResult(
                    host_id=host.id,
                    host_name=host.name,
                    check_type="dns",
                    success=False,
                    latency=None,
                    error="DNS resolve failed",
                )
            )

            host.fail_streak = (host.fail_streak or 0) + 1
            host.success_streak = 0

            db.flush()

            if consecutive_failures(db, host.id, limit=3, check_types=["dns"]):
                open_incident(
                    db,
                    host,
                    "Falha na resolução DNS",
                    incident_type=INCIDENT_TYPE_DNS_FAILURE,
                    check_used="DNS",
                    auto_commit=False,
                )
                close_incident(
                    db,
                    host.name,
                    incident_type=INCIDENT_TYPE_SERVICE_DOWN,
                    auto_commit=False,
                )
                close_incident(
                    db,
                    host.name,
                    incident_type=INCIDENT_TYPE_SERVICE_DEGRADED,
                    auto_commit=False,
                )

            db.commit()
            return

        db.add(
            CheckResult(
                host_id=host.id,
                host_name=host.name,
                check_type="dns",
                success=True,
                latency=None,
                error=None,
            )
        )

        index = (host.id + int(time.time() / 20)) % len(ips)
        ip = ips[index]

        if host.last_resolved_ip and host.last_resolved_ip not in ips:
            old_ip = host.last_resolved_ip
            new_ip = str(ips)
            if _alert_cooldown_passed(
                host.id, "DNS_CHANGE", 300, fingerprint=f"{old_ip}->{new_ip}"
            ):
                db.add(
                    Alert(
                        host_id=host.id,
                        alert_type="DNS_CHANGE",
                        old_status=old_ip,
                        new_status=new_ip,
                    )
                )
                send_telegram_alert(
                    build_dns_change_message(
                        host,
                        host.address,
                        old_ip,
                        new_ip,
                        datetime.utcnow(),
                    )
                )

        host.last_resolved_ip = ip
        close_incident(
            db,
            host.name,
            incident_type=INCIDENT_TYPE_DNS_FAILURE,
            auto_commit=False,
        )

        ping_result = ping_host(ip)

        tcp_result = None
        if host.port:
            tcp_result = tcp_check(ip, host.port)

        http_result = None
        url = _resolve_host_check_url(host)
        if url:
            http_result = http_check(url)

        score, severity = compute_health(ping_result, tcp_result, http_result)
        host.health_score = score
        host.severity = severity

        if (
            old_severity != "CRITICAL"
            and severity == "CRITICAL"
            and _alert_cooldown_passed(
                host.id,
                "HEALTH_CRITICAL",
                900,
                fingerprint=f"score:{score}",
            )
        ):
            db.add(
                Alert(
                    host_id=host.id,
                    alert_type="HEALTH_CRITICAL",
                    old_status=old_status,
                    new_status=f"score={score}",
                )
            )
            send_telegram_alert(
                build_health_critical_message(
                    host,
                    "health_score",
                    score,
                    datetime.utcnow(),
                )
            )

        new_status, primary_check, service_up_without_icmp = determine_operational_state(
            host,
            ping_result,
            tcp_result,
            http_result,
        )

        host.status = new_status
        if baseline_pending:
            host.baseline_pending = False

        if new_status == "UP":
            host.success_streak = (host.success_streak or 0) + 1
            host.fail_streak = 0
            _set_degraded_streak(host.id, 0)
        elif new_status == "DEGRADED":
            host.success_streak = 0
            host.fail_streak = (host.fail_streak or 0) + 1
            _increment_degraded_streak(host.id)
        else:
            host.fail_streak = (host.fail_streak or 0) + 1
            host.success_streak = 0
            _set_degraded_streak(host.id, 0)

        is_real_recovery = (
            old_status_normalized in {"DOWN", "DEGRADED"}
            and new_status == "UP"
            and host.success_streak >= ALERT_RECOVER_THRESHOLD
        )

        if (not baseline_pending) and old_status and old_status != new_status:
            if service_up_without_icmp and new_status == "UP":
                pass
            elif new_status != "UP" and host.fail_streak >= ALERT_FAIL_THRESHOLD:
                db.add(
                    Alert(
                        host_id=host.id,
                        old_status=old_status,
                        new_status=new_status,
                    )
                )
                send_telegram_alert(
                    build_failure_confirmed_message(
                        host,
                        old_status,
                        new_status,
                        host.fail_streak,
                        datetime.utcnow(),
                        check_used=primary_check,
                    )
                )
            elif is_real_recovery:
                db.add(
                    Alert(
                        host_id=host.id,
                        old_status=old_status,
                        new_status="UP_RECOVERED",
                    )
                )
                send_telegram_alert(
                    build_recovery_message(host, old_status, datetime.utcnow())
                )

        host.last_check = datetime.utcnow()

        db.add(
            CheckResult(
                host_id=host.id,
                host_name=host.name,
                check_type="ping",
                success=ping_result["success"],
                latency=ping_result.get("latency"),
                error=ping_result.get("error"),
            )
        )

        if tcp_result:
            db.add(
                CheckResult(
                    host_id=host.id,
                    host_name=host.name,
                    check_type="tcp",
                    success=tcp_result["success"],
                    latency=tcp_result.get("latency"),
                    error=tcp_result.get("error"),
                )
            )

        if http_result:
            db.add(
                CheckResult(
                    host_id=host.id,
                    host_name=host.name,
                    check_type="http",
                    success=http_result["success"],
                    latency=http_result.get("latency"),
                    error=http_result.get("error"),
                    status_code=http_result.get("status_code"),
                )
            )

        db.flush()

        host.sla_rolling_ping = calc_sla_rolling_ping(db, host.id, 50)
        host.jitter_ms_ping = calc_jitter_ping(db, host.id, 10)

        host.sla_rolling_tcp = calc_sla_rolling_tcp(db, host.id, 50)
        host.jitter_ms_tcp = calc_jitter_tcp(db, host.id, 10)

        host.sla_rolling_http = calc_sla_rolling_http(db, host.id, 50)
        host.jitter_ms_http = calc_jitter_http(db, host.id, 10)

        host.slope = calc_latency_trend_ping(db, host.id, 10)
        host.trend = classify_trend(host.slope)

        host.slope_http = calc_latency_trend_http(db, host.id, 10)
        host.trend_http = classify_trend_http(host.slope_http)

        if service_up_without_icmp:
            host.sla_rolling_ping = None
            host.jitter_ms_ping = None
            host.slope = None
            host.trend = "UNKNOWN"

        host.severity = refine_severity(
            host.severity,
            host.sla_rolling_ping,
            host.sla_rolling_tcp,
            host.sla_rolling_http,
            host.jitter_ms_ping,
            host.jitter_ms_tcp,
            host.jitter_ms_http,
            ignore_ping_metrics=service_up_without_icmp,
        )

        snmp_data = None

        if host.status == "UP" and _snmp_is_configured(host) and can_attempt_snmp(host.id):
            try:
                snmp_data = update_host_snmp(host, db)
            except Exception:
                logger.exception("[SNMP ERROR] host=%s", host.name)
                register_snmp_failure(host.id, host.name)
            else:
                if snmp_has_usable_data(snmp_data):
                    register_snmp_success(host.id)
                else:
                    register_snmp_failure(host.id, host.name)

        preventive_severity, preventive_reasons = apply_preventive_logic(
            host,
            snmp_data,
            ignore_ping_metrics=service_up_without_icmp,
        )

        host.severity = max_severity(host.severity, preventive_severity)

        final_status = host.status
        primary_checks = [primary_check.lower()]

        if final_status == "DOWN" and consecutive_failures(
            db,
            host.id,
            limit=3,
            check_types=primary_checks,
        ):
            open_incident(
                db,
                host,
                f"Serviço {primary_check} indisponível",
                incident_type=INCIDENT_TYPE_SERVICE_DOWN,
                check_used=primary_check,
                auto_commit=False,
            )
            close_incident(
                db,
                host.name,
                incident_type=INCIDENT_TYPE_SERVICE_DEGRADED,
                auto_commit=False,
            )
        elif (
            final_status == "DEGRADED"
            and _get_degraded_streak(host.id) >= DEGRADED_OPEN_THRESHOLD
        ):
            open_incident(
                db,
                host,
                f"Instabilidade detectada no serviço {primary_check}",
                incident_type=INCIDENT_TYPE_SERVICE_DEGRADED,
                check_used=primary_check,
                auto_commit=False,
            )
            close_incident(
                db,
                host.name,
                incident_type=INCIDENT_TYPE_SERVICE_DOWN,
                auto_commit=False,
            )
        elif final_status == "UP" and host.success_streak >= ALERT_RECOVER_THRESHOLD:
            close_incident(
                db,
                host.name,
                incident_type=INCIDENT_TYPE_SERVICE_DOWN,
                auto_commit=False,
            )
            close_incident(
                db,
                host.name,
                incident_type=INCIDENT_TYPE_SERVICE_DEGRADED,
                auto_commit=False,
            )

        if host.severity in ("WARNING", "DEGRADED", "CRITICAL"):
            if (
                not host.last_preventive_alert
                or datetime.utcnow() - host.last_preventive_alert > timedelta(minutes=30)
            ):
                severity_labels = {
                    "WARNING": "Atenção",
                    "DEGRADED": "Degradado",
                    "CRITICAL": "Crítico",
                }
                condition_text = (
                    preventive_reasons[0]
                    if preventive_reasons
                    else "Risco preventivo detectado"
                )
                extra_reasons = (
                    ", ".join(preventive_reasons[1:4])
                    if len(preventive_reasons) > 1
                    else None
                )
                severity_text = severity_labels.get(host.severity, host.severity)
                details_lines = []
                if extra_reasons:
                    details_lines.append(extra_reasons)
                details_lines.append(f"Severidade: {severity_text}")
                details_lines.append(f"Score: {host.health_score}")
                details_text = "\n".join(details_lines)
                prevent_fingerprint = (
                    f"{condition_text}|{extra_reasons or ''}|{severity_text}"
                )
                if _alert_cooldown_passed(
                    host.id,
                    "PREVENTIVE",
                    1800,
                    fingerprint=prevent_fingerprint,
                ):
                    send_telegram_alert(
                        build_preventive_alert_message(
                            host,
                            condition_text,
                            details_text,
                            datetime.utcnow(),
                        )
                    )
                    host.last_preventive_alert = datetime.utcnow()

        db.commit()
    except Exception:
        logger.exception("[HOST ERROR] host_id=%s", host_id)
        db.rollback()
    finally:
        db.close()


def get_active_host_ids() -> list[int]:
    ensure_runtime_schema()
    db: Session = SessionLocal()
    try:
        rows = db.query(Host.id).filter(Host.active.is_(True)).all()
        return [row[0] for row in rows]
    finally:
        db.close()


def process_host_check(host_id: int) -> None:
    _host_check_blocking(host_id)


def check_all_hosts() -> None:
    """
    Compatibilidade com scripts existentes: executa o ciclo de forma síncrona/sequencial.
    """
    host_ids = get_active_host_ids()
    for host_id in host_ids:
        process_host_check(host_id)


def trim_history(db, host_id, check_type, limit=500):
    old = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == check_type,
        )
        .order_by(CheckResult.timestamp.desc())
        .offset(limit)
        .all()
    )

    for row in old:
        db.delete(row)


def cleanup_old_data():
    ensure_runtime_schema()
    db: Session = SessionLocal()
    try:
        hosts = db.query(Host).all()
        for host in hosts:
            for c_type in ["ping", "tcp", "http", "dns"]:
                trim_history(db, host.id, c_type, limit=30000)
        db.commit()
        logger.info("Limpeza de histórico concluída.")
    except Exception:
        logger.exception("[CLEANUP ERROR]")
        db.rollback()
    finally:
        db.close()


def start_scheduler():
    logger.warning(
        "start_scheduler() está obsoleto; use Backend.monitor_engine via FastAPI lifespan."
    )
