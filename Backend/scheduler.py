from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import time
from sqlalchemy.orm import Session
from Backend.database import SessionLocal
from Backend.models import Host, CheckResult, Alert
from Backend.checker import ping_host, tcp_check, resolve_dns_cached, http_check
from Backend.metrics import apply_preventive_logic, calc_jitter_http, calc_jitter_ping, calc_jitter_tcp, calc_sla_rolling_http, calc_sla_rolling_ping, calc_sla_rolling_tcp, max_severity, refine_severity, compute_health, calc_latency_trend_ping, classify_trend, calc_latency_trend_http, classify_trend_http
from Backend.notifications import send_telegram_alert
from Backend.snmp_engine import update_host_snmp
from Backend.utils import close_incident, consecutive_failures, open_incident

scheduler = BackgroundScheduler()

ALERT_FAIL_THRESHOLD = 2
ALERT_RECOVER_THRESHOLD = 1

def check_all_hosts():

    db: Session = SessionLocal()
    try:
        hosts = db.query(Host).filter(Host.active == True).all()

        for host in hosts:
            try:
                old_status = host.status
                old_severity = host.severity

                # =====================
                # DNS
                # =====================
                dns_result = resolve_dns_cached(host.address, db)

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

                if ttl is not None:
                    host.dns_ttl = ttl
                if ttl_remaining is not None:
                    host.dns_ttl_remaining = ttl_remaining

                # alerta TTL baixo
                if ttl is not None and ttl < 60:
                    if not host.last_ttl_alert or (datetime.utcnow() - host.last_ttl_alert).seconds > 3600:
                        db.add(Alert(
                            host_id=host.id,
                            alert_type="DNS_TTL_LOW",
                            old_status="ttl",
                            new_status=str(ttl)
                        ))
                        host.last_ttl_alert = datetime.utcnow()

                # =====================
                # DNS FAIL
                # =====================
                if not ips:
                    host.status = "DOWN"
                    host.last_resolved_ip = None
                    host.last_check = datetime.utcnow()

                    db.add(CheckResult(
                        host_id=host.id,
                        host_name=host.name,
                        check_type="dns",
                        success=False,
                        latency=None,
                        error="DNS resolve failed"
                    ))

                    host.fail_streak = (host.fail_streak or 0) + 1
                    host.success_streak = 0

                    db.flush()

                    if consecutive_failures(db, host.id, limit=3, check_types=["dns"]):
                        open_incident(db, host, "Falha na resolução DNS", auto_commit=False)

                    db.commit()
                    continue

                # DNS OK log
                db.add(CheckResult(
                    host_id=host.id,
                    host_name=host.name,
                    check_type="dns",
                    success=True,
                    latency=None,
                    error=None
                ))

                # =====================
                # Escolha IP rotativo
                # =====================
                index = (host.id + int(time.time()/20)) % len(ips)
                ip = ips[index]

                if host.last_resolved_ip and host.last_resolved_ip not in ips:
                    db.add(Alert(
                        host_id=host.id,
                        alert_type="DNS_CHANGE",
                        old_status=host.last_resolved_ip,
                        new_status=str(ips)
                    ))

                host.last_resolved_ip = ip

                # =====================
                # CHECKS
                # =====================
                
                #ping
                ping_result = ping_host(ip)

                #tcp
                tcp_result = None
                if host.port:
                    tcp_result = tcp_check(ip, host.port)
                
                #http
                http_result = None
                url = None

                # Se tiver URL customizada, usa ela
                if host.http_url:
                    url = host.http_url

                # Se não tiver, monta automaticamente
                elif host.port in (80, 443):
                    protocol = "https" if host.port == 443 else "http"
                    url = f"{protocol}://{host.address}"

                # Porta diferente mas definida
                elif host.port:
                    url = f"http://{host.address}:{host.port}"
                    
                # Executa check se montou URL
                if url:
                    http_result = http_check(url)

                score, severity = compute_health(ping_result, tcp_result, http_result)

                host.health_score = score
                host.severity = severity

                if old_severity != "CRITICAL" and severity == "CRITICAL":
                    db.add(Alert(
                        host_id=host.id,
                        alert_type="HEALTH_CRITICAL",
                        old_status=old_status,
                        new_status=f"score={score}"
                    ))

                # =====================
                # STATUS ENGINE (CORRETO)
                # =====================

                if http_result and http_result.get("status_code") and 500 <= http_result["status_code"] < 600:
                    new_status = "CRITICAL"

                elif http_result and not http_result["success"]:
                    new_status = "DEGRADED"
                
                elif not ping_result["success"] and not tcp_result:
                    new_status = "DOWN"
                    
                elif ping_result["success"]:
                    new_status = "UP"

                elif not ping_result["success"] and tcp_result and tcp_result["success"]:
                    new_status = "UP"  # Condicao para ICMP bloqueado, gov.br ou site do if

                elif tcp_result and not tcp_result["success"]:
                    new_status = "DEGRADED"

                else:
                    new_status = "DOWN"

                host.status = new_status

                # =====================
                # STREAK ENGINE
                # =====================
                if new_status == "UP":
                    host.success_streak = (host.success_streak or 0) + 1
                    host.fail_streak = 0

                elif new_status == "DEGRADED":
                    host.success_streak = 0

                else:
                    host.fail_streak = (host.fail_streak or 0) + 1
                    host.success_streak = 0

                # =====================
                # ALERTAS TRANSIÇÃO
                # =====================
                if old_status and old_status != new_status:

                    if new_status != "UP" and host.fail_streak >= ALERT_FAIL_THRESHOLD:
                        db.add(Alert(
                            host_id=host.id,
                            old_status=old_status,
                            new_status=new_status
                        ))

                    elif new_status == "UP" and host.success_streak >= ALERT_RECOVER_THRESHOLD:
                        db.add(Alert(
                            host_id=host.id,
                            old_status=old_status,
                            new_status="UP_RECOVERED"
                        ))

                host.last_check = datetime.utcnow()

                # =====================
                # LOG CHECKS
                # =====================
                db.add(CheckResult(
                    host_id=host.id,
                    host_name=host.name,
                    check_type="ping",
                    success=ping_result["success"],
                    latency=ping_result.get("latency"),
                    error=ping_result.get("error")
                ))

                if tcp_result:
                    db.add(CheckResult(
                        host_id=host.id,
                        host_name=host.name,
                        check_type="tcp",
                        success=tcp_result["success"],
                        latency=tcp_result.get("latency"),
                        error=tcp_result.get("error")
                    ))

                if http_result:
                    db.add(CheckResult(
                        host_id=host.id,
                        host_name=host.name,
                        check_type="http",
                        success=http_result["success"],
                        latency=http_result.get("latency"),
                        error=http_result.get("error"),
                        status_code=http_result.get("status_code")
                    ))

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

    
                host.severity = refine_severity(
                    host.severity,
                    host.sla_rolling_ping,
                    host.sla_rolling_tcp,
                    host.sla_rolling_http,
                    host.jitter_ms_ping,
                    host.jitter_ms_tcp,
                    host.jitter_ms_http
                )

                snmp_data = None

                if host.status == "UP":
                    try:
                        snmp_data = update_host_snmp(host, db)
                    except Exception as e:
                        print(f"[SNMP ERROR] {host.name}: {e}")

                preventive_severity, preventive_reasons = apply_preventive_logic(host, snmp_data)

                host.severity = max_severity(host.severity, preventive_severity)

                final_status = host.status

                primary_checks = ["ping"]
                if host.http_url:
                    primary_checks = ["http"]
                elif host.port:
                    primary_checks = ["tcp"]

                if consecutive_failures(db, host.id, limit=3, check_types=primary_checks):
                    open_incident(db, host, "Host indisponível", auto_commit=False)
                elif final_status == "UP":
                    close_incident(db, host.name, auto_commit=False)
                                    
                if host.severity in ("WARNING", "DEGRADED", "CRITICAL"):
                    if (
                        not host.last_preventive_alert or
                        datetime.utcnow() - host.last_preventive_alert > timedelta(minutes=30)
                    ):
                        reason_text = ", ".join(preventive_reasons[:4]) if preventive_reasons else "Risco detectado"

                        send_telegram_alert(
                            f"⚠️ <b>Alerta Preventivo</b>\n"
                            f"Host: {host.name}\n"
                            f"Endereço: {host.address}\n"
                            f"Severidade: {host.severity}\n"
                            f"Motivos: {reason_text}\n"
                            f"Score: {host.health_score}"
                        )

                        host.last_preventive_alert = datetime.utcnow()

                db.commit()
            except Exception as e:
                print(f"[HOST ERROR] {host.name}: {e}")
                db.rollback()

    except Exception as e:
        print(f"[SCHEDULER ERROR] {e}")

    finally:
        db.close()


def trim_history(db, host_id, check_type, limit=500):
    old = (
        db.query(CheckResult)
        .filter(CheckResult.host_id == host_id,
                CheckResult.check_type == check_type)
        .order_by(CheckResult.timestamp.desc())
        .offset(limit)
        .all()
    )

    for row in old:
        db.delete(row)

def cleanup_old_data():
    db: Session = SessionLocal()
    try:
        # Pega todos os IDs de hosts ativos
        hosts = db.query(Host).all()
        for host in hosts:
            for c_type in ["ping", "tcp", "http", "dns"]:
                trim_history(db, host.id, c_type, limit=100)
        db.commit()
        print(f"[{datetime.now()}] Limpeza de histórico concluída.")
    except Exception as e:
        print(f"[CLEANUP ERROR] {e}")
    finally:
        db.close()

def start_scheduler():
    # Tarefa Principal
    scheduler.add_job(
        check_all_hosts,
        "interval",
        seconds=5,
        id="check_hosts_job",
        replace_existing=True
    )

    # Tarefa de limpeza (roda a cada 1 hora)
    scheduler.add_job(
        cleanup_old_data,
        "interval",
        hours=1,
        id="cleanup_job",
        replace_existing=True
    )

    scheduler.start()
