from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from sqlalchemy.orm import Session
from Backend.database import SessionLocal
from Backend.models import Host, CheckResult, Alert
from Backend.checker import ping_host, tcp_check

scheduler = BackgroundScheduler()

def check_all_hosts():
    db: Session = SessionLocal()
    try:
        hosts = db.query(Host).filter(Host.active == True).all()

        for host in hosts:
            old_status = host.status

            ping_result = ping_host(host.address)
            tcp_result = None

            if host.port is not None:
                tcp_result = tcp_check(host.address, host.port)

            if not ping_result["success"]:
                host.status = "DOWN"

            elif tcp_result is not None and not tcp_result["success"]:
                host.status = "DEGRADED"

            else:
                host.status = "UP"
            
            if old_status is not None:
                if old_status != host.status:
                    alert = Alert(
                        host_id=host.id,
                        old_status=old_status,
                        new_status=host.status
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
    

            trim_history(db, host.id, "ping")

            if tcp_result is not None:
                trim_history(db, host.id, "tcp")

        db.commit()
    except Exception as e:
        print(f"Erro no host {host.name}: {e}")

    finally:
        db.close()

def trim_history(db, host_id, check_type, limit=100):
    old = (
        db.query(CheckResult)
        .filter(CheckResult.host_id == host_id,
                CheckResult.check_type == check_type)
        .order_by(CheckResult.timestamp.desc())
        .offset(limit-1)
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
    

