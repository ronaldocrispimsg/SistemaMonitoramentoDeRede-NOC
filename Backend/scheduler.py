import logging
import os
import time
import json
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session

from Backend.checker import ping_host, tcp_check, resolve_dns_cached, http_check
from Backend.database import SessionLocal, AsyncSessionLocal
from Backend.utils import (
    open_incident_async,
    close_incident_async,
    consecutive_failures_async,
)
from Backend.metrics import (
    apply_preventive_logic,
    calc_jitter_http,
    calc_jitter_ping,
    calc_jitter_tcp_ports,
    calc_latency_trend_http,
    calc_latency_trend_ping,
    calc_sla_rolling_http,
    calc_sla_rolling_ping,
    calc_sla_rolling_tcp_ports,
    calc_sla_rolling_ping_async,
    calc_sla_rolling_tcp_ports_async,
    calc_sla_rolling_http_async,
    calc_jitter_ping_async,
    calc_jitter_tcp_ports_async,
    calc_jitter_http_async,
    calc_latency_trend_ping_async,
    calc_latency_trend_http_async,
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
    send_telegram_alert_async,
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

logger = logging.getLogger("netspot.scheduler")

ALERT_FAIL_THRESHOLD = 2
ALERT_RECOVER_THRESHOLD = 1
DEGRADED_OPEN_THRESHOLD = 3

_ALERT_COOLDOWN_STATE = {}
_ALERT_COOLDOWN_LOCK = Lock()
_DEGRADED_STREAKS = {}
_DEGRADED_STREAKS_LOCK = Lock()

MONITOR_INTERVAL_SECONDS = int(os.getenv("NETSPOT_MONITOR_INTERVAL_SECONDS", "10"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("NETSPOT_CLEANUP_INTERVAL_SECONDS", "3600"))
SNMP_ALLOWED_COMMUNITY = "netspot"


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
    if bool(getattr(host, "http_enabled", True)):
        return "HTTP"
    if _host_tcp_ports(host):
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
    if not bool(getattr(host, "http_enabled", True)):
        return None

    ports = _host_tcp_ports(host)
    primary_port = ports[0] if ports else None

    if host.http_url:
        return host.http_url
    if primary_port in (80, 443):
        return host.address
    if primary_port:
        return f"{host.address}:{primary_port}"
    return host.address or None


def _host_tcp_ports(host: Host) -> list[int]:
    if host.tcp_ports:
        try:
            parsed = json.loads(host.tcp_ports)
            if isinstance(parsed, list):
                normalized = []
                for p in parsed:
                    try:
                        port = int(p)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= port <= 65535 and port not in normalized:
                        normalized.append(port)
                if normalized:
                    return sorted(normalized)
        except Exception:
            pass

    if host.port and 1 <= int(host.port) <= 65535:
        return [int(host.port)]
    return []


def _aggregate_tcp_results(results: list[dict]) -> dict | None:
    if not results:
        return None

    successes = [r for r in results if r.get("success")]
    if successes:
        best = min(successes, key=lambda r: r.get("latency") or float("inf"))
        return {"success": True, "latency": best.get("latency"), "error": None}

    errors = [str(r.get("error") or "").strip() for r in results]
    errors = [e for e in errors if e]
    return {
        "success": False,
        "latency": None,
        "error": "; ".join(errors) if errors else "tcp_failed",
    }


def _snmp_is_configured(host: Host) -> bool:
    if not bool(getattr(host, "snmp_enabled", False)):
        logger.debug(
            "SNMP ignorado para host=%s: snmp_enabled desativado",
            host.name,
        )
        return False

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


async def _host_check_async(host_id: int) -> None:
    db = AsyncSessionLocal()
    try:
        stmt = select(Host).filter(Host.id == host_id, Host.active.is_(True))
        res = await db.execute(stmt)
        host = res.scalars().first()
        if host is None:
            await db.close()
            return

        old_status = host.status
        old_severity = host.severity
        old_status_normalized = str(old_status or "").strip().upper()
        baseline_pending = bool(getattr(host, "baseline_pending", False))

        dns_result = await resolve_dns_cached(host.address, db)
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
                await send_telegram_alert_async({
                    "event": "dns_ttl_low",
                    "host_name": host.name,
                    "host_address": host.address,
                    "ttl": ttl,
                    "timestamp": datetime.utcnow().isoformat()
                })
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

            await db.flush()

            if await consecutive_failures_async(db, host.id, limit=3, check_types=["dns"]):
                await open_incident_async(
                    db,
                    host,
                    "Falha na resolução DNS",
                    incident_type=INCIDENT_TYPE_DNS_FAILURE,
                    check_used="DNS",
                    auto_commit=False,
                )
                await close_incident_async(
                    db,
                    host.name,
                    incident_type=INCIDENT_TYPE_SERVICE_DOWN,
                    auto_commit=False,
                )
                await close_incident_async(
                    db,
                    host.name,
                    incident_type=INCIDENT_TYPE_SERVICE_DEGRADED,
                    auto_commit=False,
                )

            await db.commit()
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
                await send_telegram_alert_async({
                    "event": "dns_change",
                    "host_name": host.name,
                    "host_address": host.address,
                    "old_ip": old_ip,
                    "new_ip": new_ip,
                    "timestamp": datetime.utcnow().isoformat()
                })

        host.last_resolved_ip = ip
        await close_incident_async(
            db,
            host.name,
            incident_type=INCIDENT_TYPE_DNS_FAILURE,
            auto_commit=False,
        )

        ping_result = await ping_host(ip)

        tcp_results = []
        for tcp_port in _host_tcp_ports(host):
            result = await tcp_check(ip, tcp_port)
            result["port"] = tcp_port
            tcp_results.append(result)

        tcp_result = _aggregate_tcp_results(tcp_results)

        http_result = None
        url = _resolve_host_check_url(host)
        if url:
            http_result = await http_check(url)
            protocol = str(http_result.get("protocol") or "").lower()
            host.last_http_protocol = protocol.upper() if protocol in {"http", "https"} else None
            host.http_latency = http_result.get("latency")
            host.https_latency = None
            host.web_tcp_port = 443 if protocol == "https" else (80 if protocol == "http" else None)
            host.web_tcp_port_latency = None

            async def _probe_aux_port(target_port: int) -> dict:
                existing = next(
                    (r for r in tcp_results if int(r.get("port") or -1) == int(target_port)),
                    None,
                )
                return existing or await tcp_check(ip, int(target_port))

            http_port_result = await _probe_aux_port(80)
            https_port_result = await _probe_aux_port(443)

            host.tcp_http_port_ok = bool(http_port_result.get("success"))
            host.tcp_http_port_latency = (
                http_port_result.get("latency") if host.tcp_http_port_ok else None
            )
            host.tcp_https_port_ok = bool(https_port_result.get("success"))
            host.tcp_https_port_latency = (
                https_port_result.get("latency") if host.tcp_https_port_ok else None
            )

            if host.web_tcp_port == 80:
                host.web_tcp_port_latency = host.tcp_http_port_latency
            elif host.web_tcp_port == 443:
                host.web_tcp_port_latency = host.tcp_https_port_latency
        else:
            host.last_http_protocol = None
            host.http_latency = None
            host.https_latency = None
            host.web_tcp_port = None
            host.web_tcp_port_latency = None
            host.tcp_http_port_ok = None
            host.tcp_http_port_latency = None
            host.tcp_https_port_ok = None
            host.tcp_https_port_latency = None

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
            await send_telegram_alert_async({
                "event": "health_critical",
                "host_name": host.name,
                "host_address": host.address,
                "health_score": score,
                "timestamp": datetime.utcnow().isoformat()
            })

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
                await send_telegram_alert_async({
                    "event": "failure_confirmed",
                    "host_name": host.name,
                    "host_address": host.address,
                    "old_status": old_status,
                    "new_status": new_status,
                    "fail_streak": host.fail_streak,
                    "check_used": primary_check,
                    "timestamp": datetime.utcnow().isoformat()
                })
            elif is_real_recovery:
                db.add(
                    Alert(
                        host_id=host.id,
                        old_status=old_status,
                        new_status="UP_RECOVERED",
                    )
                )
                await send_telegram_alert_async({
                    "event": "recovery",
                    "host_name": host.name,
                    "host_address": host.address,
                    "old_status": old_status,
                    "timestamp": datetime.utcnow().isoformat()
                })

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
            if tcp_results:
                for result in tcp_results:
                    db.add(
                        CheckResult(
                            host_id=host.id,
                            host_name=host.name,
                            check_type="tcp",
                            success=result["success"],
                            latency=result.get("latency"),
                            error=result.get("error"),
                            tcp_port=result.get("port"),
                        )
                    )
            else:
                db.add(
                    CheckResult(
                        host_id=host.id,
                        host_name=host.name,
                        check_type="tcp",
                        success=tcp_result["success"],
                        latency=tcp_result.get("latency"),
                        error=tcp_result.get("error"),
                        tcp_port=None,
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

        await db.flush()

        host.sla_rolling_ping = await calc_sla_rolling_ping_async(db, host.id, 50)
        host.jitter_ms_ping = await calc_jitter_ping_async(db, host.id, 10)

        active_tcp_ports = _host_tcp_ports(host)
        host.sla_rolling_tcp = await calc_sla_rolling_tcp_ports_async(db, host.id, active_tcp_ports, 50)
        host.jitter_ms_tcp = await calc_jitter_tcp_ports_async(db, host.id, active_tcp_ports, 10)

        host.sla_rolling_http = await calc_sla_rolling_http_async(db, host.id, 50)
        host.jitter_ms_http = await calc_jitter_http_async(db, host.id, 10)

        host.slope = await calc_latency_trend_ping_async(db, host.id, 10)
        host.trend = classify_trend(host.slope)

        host.slope_http = await calc_latency_trend_http_async(db, host.id, 10)
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
                snmp_data = await update_host_snmp(host, db)
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

        if final_status == "DOWN" and await consecutive_failures_async(
            db,
            host.id,
            limit=3,
            check_types=primary_checks,
        ):
            await open_incident_async(
                db,
                host,
                f"Serviço {primary_check} indisponível",
                incident_type=INCIDENT_TYPE_SERVICE_DOWN,
                check_used=primary_check,
                auto_commit=False,
            )
            await close_incident_async(
                db,
                host.name,
                incident_type=INCIDENT_TYPE_SERVICE_DEGRADED,
                auto_commit=False,
            )
        elif (
            final_status == "DEGRADED"
            and _get_degraded_streak(host.id) >= DEGRADED_OPEN_THRESHOLD
        ):
            await open_incident_async(
                db,
                host,
                f"Instabilidade detectada no serviço {primary_check}",
                incident_type=INCIDENT_TYPE_SERVICE_DEGRADED,
                check_used=primary_check,
                auto_commit=False,
            )
            await close_incident_async(
                db,
                host.name,
                incident_type=INCIDENT_TYPE_SERVICE_DOWN,
                auto_commit=False,
            )
        elif final_status == "UP" and host.success_streak >= ALERT_RECOVER_THRESHOLD:
            await close_incident_async(
                db,
                host.name,
                incident_type=INCIDENT_TYPE_SERVICE_DOWN,
                auto_commit=False,
            )
            await close_incident_async(
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
                    await send_telegram_alert_async({
                        "event": "preventive_alert",
                        "host_name": host.name,
                        "host_address": host.address,
                        "condition": condition_text,
                        "details": details_text,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    host.last_preventive_alert = datetime.utcnow()

        await db.commit()
    except Exception:
        logger.exception("[HOST ERROR] host_id=%s", host_id)
        await db.rollback()
    finally:
        await db.close()


async def get_active_host_ids() -> list[int]:
    async with AsyncSessionLocal() as db:
        stmt = select(Host.id).filter(Host.active.is_(True))
        rows = await db.execute(stmt)
        return [row[0] for row in rows.all()]


async def process_host_check(host_id: int) -> None:
    await _host_check_async(host_id)


async def check_all_hosts() -> None:
    """
    Compatibilidade com scripts existentes: executa o ciclo de forma síncrona/sequencial.
    """
    host_ids = await get_active_host_ids()
    for host_id in host_ids:
        await process_host_check(host_id)


async def trim_history(db, host_id, check_type, limit=500):
    stmt = (
        select(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == check_type,
        )
        .order_by(CheckResult.timestamp.desc())
        .offset(limit)
    )
    res = await db.execute(stmt)
    old = res.scalars().all()

    for row in old:
        db.delete(row)


async def cleanup_old_data():
    async with AsyncSessionLocal() as db:
        try:
            stmt = select(Host)
            res = await db.execute(stmt)
            hosts = res.scalars().all()
            for host in hosts:
                for c_type in ["ping", "tcp", "http", "dns"]:
                    await trim_history(db, host.id, c_type, limit=30000)
            await db.commit()
            logger.info("Limpeza de histórico concluída.")
        except Exception:
            logger.exception("[CLEANUP ERROR]")
            await db.rollback()


def start_scheduler():
    logger.warning(
        "start_scheduler() está obsoleto; use Backend.monitor_engine via FastAPI lifespan."
    )
