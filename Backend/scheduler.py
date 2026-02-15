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

                ips = resolve_dns_cached(host.address, db)

                if not ips:
                    host.status = "DOWN"
                    
                    check_log_dns= CheckResult(
                        host_id=host.id,
                        host_name=host.name,
                        check_type="dns",
                        success=False,
                        latency=None,
                        error="DNS resolve failed"
                    ) 
                    db.add(check_log_dns)

                    host.fail_streak = (host.fail_streak or 0) + 1
                    host.success_streak = 0
                    
                    if old_status != "DOWN" and host.fail_streak >= ALERT_FAIL_THRESHOLD:
                        alert = Alert(
                            host_id=host.id,
                            old_status=old_status,
                            new_status="DOWN"
                        )
                        db.add(alert)
                        
                    host.last_check = datetime.now()
                    db.flush()
                    trim_history(db, host.id, "dns")

                    continue
                else:
                    check_log_dns= CheckResult(
                        host_id=host.id,
                        host_name=host.name,
                        check_type="dns",
                        success=True,
                        latency=None,
                        error=None
                    )
                    db.add(check_log_dns)
                    db.flush()
                    trim_history(db, host.id, "dns")

                # Rotacao por host.id
                index = (host.id + int(time.time()/20)) % len(ips)
                ip = ips[index] # Usa um IP diferente a cada checagem para balancear a carga, caso haja múltiplos IPs

                # Verifica se o IP mudou desde a última resolução
                if host.last_resolved_ip and host.last_resolved_ip not in ips:
                    alert = Alert(
                            host_id=host.id,
                            alert_type="DNS_CHANGE",
                            old_status=f"old_IP {host.last_resolved_ip}",
                            new_status=f"new_set {ips}"
                    )
                    db.add(alert)


                host.last_resolved_ip = ip  # Armazena o último IP resolvido

                ping_result = ping_host(ip)
                
                tcp_result = None

                if host.port is not None:
                    tcp_result = tcp_check(ip, host.port)

                if not ping_result["success"]:
                    host.status = "DOWN"
                    host.fail_streak = (host.fail_streak or 0) + 1
                    host.success_streak = 0

                elif tcp_result is not None and not tcp_result["success"]:
                    host.status = "DEGRADED"
                    host.fail_streak = (host.fail_streak or 0) + 1
                    host.success_streak = 0

                else:
                    host.status = "UP"
                    host.success_streak = (host.success_streak or 0) + 1
                    host.fail_streak = 0
                
                if old_status is not None and old_status != host.status:
                    # ALERTA DE FALHA CONFIRMADA
                    if host.status != "UP" and host.fail_streak >= ALERT_FAIL_THRESHOLD:
                        alert = Alert(
                            host_id=host.id,
                            old_status=old_status,
                            new_status=host.status
                        )
                        db.add(alert)
                    # ALERTA DE RECUPERAÇÃO CONFIRMADA
                    elif host.status == "UP" and host.success_streak >= ALERT_RECOVER_THRESHOLD:
                        alert = Alert(
                            host_id=host.id,
                            old_status=old_status,
                            new_status="UP_RECOVERED"
                        )
                        db.add(alert)

                host.last_check = datetime.now()

                check_log_ping = CheckResult(
                    host_id=host.id,
                    host_name=host.name,
                    check_type="ping",
                    success=ping_result["success"],
                    latency=ping_result.get("latency"),
                    error=ping_result.get("error")
                )
                db.add(check_log_ping)
            
                if tcp_result is not None:
                    check_log_tcp = CheckResult(
                        host_id=host.id,
                        host_name=host.name,
                        check_type="tcp",
                        success=tcp_result["success"],
                        latency=tcp_result.get("latency"),
                        error=tcp_result.get("error")
                    )
                    db.add(check_log_tcp)

                db.flush()  # Garante que os dados sejam escritos no banco antes de tentar cortar o histórico

                trim_history(db, host.id, "ping")

                if tcp_result is not None:
                    trim_history(db, host.id, "tcp")

            except Exception as e:
                print(f"Erro no host {host.name}: {e}")

        db.commit()

    except Exception as e:
        print(f"Erro no scheduler: {e}")

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
        seconds=20, 
        id="check_hosts_job",
        replace_existing=True
    )
    scheduler.start()
    

