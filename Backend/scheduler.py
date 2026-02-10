from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from sqlalchemy.orm import Session
from Backend.database import SessionLocal
from Backend.models import Host, CheckResult
from Backend.checker import ping_host, tcp_check

scheduler = BackgroundScheduler()

def check_all_hosts():
    db: Session = SessionLocal()
    try:
        hosts = db.query(Host).all()

        for host in hosts:
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
            
            host.last_check = datetime.now()
            check_log = CheckResult(
            host_name=host.name,
            success=str(ping_result["success"]),
            latency=ping_result.get("latency")
            )
        
        db.add(check_log)
        db.commit()

    finally:
        db.close()

def start_scheduler():
    scheduler.add_job(
        check_all_hosts,
        "interval",
        seconds=20,   # depois deixo por host
        id="check_hosts_job",
        replace_existing=True
    )
    scheduler.start()
