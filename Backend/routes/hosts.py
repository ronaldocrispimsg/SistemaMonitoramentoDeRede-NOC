from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from Backend.database import SessionLocal
from Backend.models import CheckResult, Host, Alert
from Backend.checker import ping_host, tcp_check, resolve_dns_cached
from Backend.schemas import HostCreate, HostUpdate
from Backend.utils import normalize_http_url

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/host/create")
def create_host(data: HostCreate, db: Session = Depends(get_db)):
    
    existing_host = db.query(Host).filter(Host.name == data.name).first()
    
    ips = resolve_dns_cached(data.address, db)  # Verifica se o endereço é válido       
    if not ips:
        raise HTTPException(status_code=400, detail="Endereço inválido")
    
    if existing_host:
        if not existing_host.active:
            existing_host.active = True
            existing_host.active_time = None
            existing_host.status = "UNKNOWN"
            existing_host.last_check = None
            existing_host.address = data.address
            existing_host.port = data.port
            existing_host.http_url = data.http_url

            db.commit()
            db.refresh(existing_host)
            return existing_host
        else:
            raise HTTPException(status_code=409, detail="Host com esse nome já existe")

    else:
        host = Host(
            name=data.name,
            address=data.address,
            port=data.port,
            http_url=data.http_url
        )
        db.add(host)
        db.commit()
        db.refresh(host)

        return host



@router.get("/hosts/list")
def list_hosts(db: Session = Depends(get_db)):
    return db.query(Host).filter(Host.active == True).all()


@router.post("/host/check/{host_name}")
def check_host(host_name: str, db: Session = Depends(get_db)):

    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    ips = resolve_dns_cached(host.address, db)

    if not ips:
        raise HTTPException(400, "DNS fail")

    ip = ips[0]

    ping_result = ping_host(ip)
    tcp_result = None

    if host.port is not None:
        tcp_result = tcp_check(ip, host.port)

    host.status_ping = "UP" if ping_result["success"] else "DOWN"
    host.latency_ping = ping_result["latency"]
    
    if tcp_result is not None:
        host.status_tcp = "UP" if tcp_result["success"] else "DOWN"
        host.latency_tcp = tcp_result["latency"]
    else:
        host.status_tcp = None
        host.latency_tcp = None

    host.last_check = datetime.now()

    if host.status_ping == "DOWN":
        host.status = "DOWN"

    elif host.status_tcp == "DOWN":
        host.status = "DEGRADED"

    else:
        host.status = "UP"

    db.commit()

    return {
    "host": host.name,
    "address": host.address,
    "status": host.status,
    "ping": {
        "status": host.status_ping,
        "latency": host.latency_ping
    },

    "tcp": {
        "status": host.status_tcp,
        "latency": host.latency_tcp
    }
}

@router.get("/host/history/{host_name}")
def host_history(host_name: str, db: Session = Depends(get_db)):
    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    checks = (
        db.query(CheckResult)
        .filter(CheckResult.host_id == host.id)
        .order_by(CheckResult.timestamp.desc())
        .limit(200)
        .all()
    )

    return {
        "host": host.name,
        "address": host.address,
        "checks": [
            {
                "type": c.check_type,
                "success": c.success,
                "latency": c.latency,
                "error": c.error,
                "timestamp": c.timestamp.isoformat()
            }
            for c in checks
        ]
    }

@router.delete("/host/delete/{host_name}")
def delete_host(host_name: str, db: Session = Depends(get_db)):
    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    host.active = False
    host.active_time = datetime.now()
    db.commit()

    return {"detail": "Host desativado com sucesso"}

@router.put("/host/update/{host_name}")
def update_host(host_name: str, data: HostUpdate, db: Session = Depends(get_db)):
    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")
    ips = resolve_dns_cached(data.address, db)

    if not ips:
        raise HTTPException(status_code=400, detail="Endereço inválido. ")
    
    host.address = data.address
    host.port = data.port
    
    if data.http_url is not None:

        normalized_url = normalize_http_url(
            data.http_url,
            data.port or host.port
        )

        host.http_url = normalized_url

    db.commit()

    return {"detail": "Host atualizado com sucesso"}

@router.get("/alerts/list")
def list_alerts(db: Session = Depends(get_db)):
    rows = (
        db.query(Alert, Host.name)
        .join(Host, Host.id == Alert.host_id)
        .order_by(Alert.timestamp.desc())
        .limit(50)
        .all()
    )

    result = []
    for alert, host_name in rows:
        result.append({
            "host_id": alert.host_id,
            "host_name": host_name,
            "old_status": alert.old_status,
            "new_status": alert.new_status,
            "timestamp": alert.timestamp.isoformat()
        })

    return result

@router.get("/host/heatmap/{host_name}")
def heatmap(host_name: str, db: Session = Depends(get_db)):

    host = db.query(Host).filter_by(name=host_name).first()
    if not host:
        raise HTTPException(404, "Host não encontrado")

    since = datetime.utcnow() - timedelta(hours=24)

    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host.id,
            CheckResult.check_type == "ping",
            CheckResult.timestamp >= since
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(1000)

    )

    buckets = {}

    for r in rows:
        bucket = r.timestamp.replace(
            minute=r.timestamp.minute,
            second=0,
            microsecond=0
        )

        buckets.setdefault(bucket, []).append(r.latency)

    result = []

    for t, values in buckets.items():
        lat = [v for v in values if v is not None]
        avg = sum(lat)/len(lat) if lat else None

        result.append({
            "time": t.isoformat(),
            "latency": avg
        })

    return sorted(result, key=lambda x: x["time"])

@router.get("/host/sla_chart/{name}")
def sla_chart(name: str, db: Session = Depends(get_db)):

    host = db.query(Host).filter_by(name=name).first()
    if not host:
        return {"ping": [], "tcp": []}

    window = 20

    # -------------------
    # PING
    # -------------------
    ping_rows = (
        db.query(CheckResult)
        .filter(CheckResult.host_id == host.id,
                CheckResult.check_type == "ping")
        .order_by(CheckResult.timestamp.asc())
        .all()
    )

    ping_out = []

    for i in range(window, len(ping_rows)+1):
        chunk = ping_rows[i-window:i]
        ok = sum(1 for r in chunk if r.success)

        ping_out.append({
            "time": chunk[-1].timestamp,
            "sla": round(ok / window * 100, 2)
        })

    # -------------------
    # TCP
    # -------------------
    tcp_rows = (
        db.query(CheckResult)
        .filter(CheckResult.host_id == host.id,
                CheckResult.check_type == "tcp")
        .order_by(CheckResult.timestamp.asc())
        .all()
    )

    tcp_out = []

    for i in range(window, len(tcp_rows)+1):
        chunk = tcp_rows[i-window:i]
        ok = sum(1 for r in chunk if r.success)

        tcp_out.append({
            "time": chunk[-1].timestamp,
            "sla": round(ok / window * 100, 2)
        })

    # -------------------
    # HTTP
    # -------------------
    http_rows = (
        db.query(CheckResult)
        .filter(CheckResult.host_id == host.id,
                CheckResult.check_type == "http")
        .order_by(CheckResult.timestamp.asc())
        .all()
    )

    http_out = []

    for i in range(window, len(http_rows)+1):
        chunk = http_rows[i-window:i]
        ok = sum(1 for r in chunk if r.success)

        http_out.append({
            "time": chunk[-1].timestamp,
            "sla": round(ok / window * 100, 2)
        })

    return {
        "ping": ping_out,
        "tcp": tcp_out,
        "http": http_out
    }
    

