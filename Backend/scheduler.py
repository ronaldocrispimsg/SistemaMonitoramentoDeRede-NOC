from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import time
from sqlalchemy.orm import Session
from Backend.database import SessionLocal
from Backend.models import Host, CheckResult, Alert
from Backend.checker import ping_host, tcp_check, resolve_dns_cached

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

                    trim_history(db, host.id, "dns")
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
                trim_history(db, host.id, "dns")

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
                ping_result = ping_host(ip)

                tcp_result = None
                if host.port:
                    tcp_result = tcp_check(ip, host.port)

                # =====================
                # STATUS ENGINE (CORRETO)
                # =====================
                if tcp_result and tcp_result["success"]:
                    new_status = "UP"

                elif ping_result["success"]:
                    new_status = "UP"

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

                trim_history(db, host.id, "ping")
                if tcp_result:
                    trim_history(db, host.id, "tcp")

                db.commit()

            except Exception as e:
                print(f"[HOST ERROR] {host.name}: {e}")
                db.rollback()

    except Exception as e:
        print(f"[SCHEDULER ERROR] {e}")

    finally:
        db.close()


def trim_history(db, host_id, check_type, limit=100):
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


def start_scheduler():
    scheduler.add_job(
        check_all_hosts,
        "interval",
        seconds=10, 
        id="check_hosts_job",
        replace_existing=True
    )
    scheduler.start()
    

