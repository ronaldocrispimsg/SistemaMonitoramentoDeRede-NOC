from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from Backend.database import SessionLocal
from Backend.metrics import get_mttr, total_downtime, total_incidents, availability_last_10_min
from Backend.models import CheckResult, Host, Alert, Incident, User
from Backend.checker import ping_host, tcp_check, resolve_dns_cached
from Backend.schemas import HostCreate, HostUpdate
from Backend.utils import is_ip, normalize_http_url, reverse_dns
from fastapi.security import OAuth2PasswordRequestForm
from Backend.dependencies import get_current_user
from Backend.security import verify_password, create_access_token, hash_password

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/host/create")
def create_host(data: HostCreate, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    existing_host = db.query(Host).filter(Host.name == data.name).first()
    resolved = None

    if is_ip(data.address):
        resolved = reverse_dns(data.address)
    else:
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
            existing_host.hostname_resolved = resolved

            if data.http_url is not None:
                normalized_url = normalize_http_url(data.http_url, data.port or existing_host.port)
                existing_host.http_url = normalized_url

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
            hostname_resolved=resolved,
        )

        if data.http_url is not None:
            normalized_url = normalize_http_url(data.http_url, data.port or host.port)
            host.http_url = normalized_url

        db.add(host)
        db.commit()
        db.refresh(host)

        return host



@router.get("/hosts/list")
def list_hosts(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
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
def delete_host(host_name: str, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    host.active = False
    host.active_time = datetime.now()
    db.commit()

    return {"detail": "Host desativado com sucesso"}

@router.put("/host/update/{host_name}")
def update_host(host_name: str, data: HostUpdate, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    host = db.query(Host).filter(Host.name == host_name).first()
    resolved = None
    
    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")
    
    if is_ip(data.address):
        resolved = reverse_dns(data.address)
    else:
        ips = resolve_dns_cached(data.address, db)

        if not ips:
            raise HTTPException(status_code=400, detail="Endereço inválido. ")
    
    host.address = data.address
    host.port = data.port
    host.hostname_resolved = resolved

    if data.http_url is not None:
        normalized_url = normalize_http_url(data.http_url, data.port or host.port)
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
    
@router.get("/hosts/metrics/{host_name}")
def host_metrics(host_name: str, db: Session = Depends(get_db)):
    return {
        "mttr_seconds": get_mttr(db, host_name),
        "total_incidents": total_incidents(db, host_name),
        "total_downtime_seconds": total_downtime(db, host_name),
        "availability_10m_percent": availability_last_10_min(db, host_name),
    }

from datetime import datetime, timedelta

@router.get("/hosts/metrics/{host_name}/history")
def availability_history(host_name: str, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    points = []

    for i in range(60):
        end = now - timedelta(minutes=i)
        start = end - timedelta(minutes=1)

        incidents = (
            db.query(Incident)
            .filter(
                Incident.host_name == host_name,
                Incident.started_time <= end
            )
            .all()
        )

        downtime = 0

        for incident in incidents:
            s = incident.started_time
            e = incident.ended_time or end

            overlap_start = max(s, start)
            overlap_end = min(e, end)

            if overlap_end > overlap_start:
                downtime += (overlap_end - overlap_start).total_seconds()

        availability = ((60 - downtime) / 60) * 100
        points.append({
            "timestamp": start.isoformat(),
            "availability": round(max(0, availability), 2)
        })

    return list(reversed(points))

@router.get("/hosts/metrics/{host_name}/downtime")
def downtime_history(host_name: str, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    since = now - timedelta(hours=1)

    incidents = (
        db.query(Incident)
        .filter(
            Incident.host_name == host_name,
            Incident.started_time >= since
        )
        .all()
    )

    return [
        {
            "start": i.started_time.isoformat(),
            "end": (i.ended_time or now).isoformat(),
            "duration_seconds": i.duration_seconds
        }
        for i in incidents
    ]

@router.get("/hosts/metrics/{host_name}/error-budget")
def error_budget(host_name: str, db: Session = Depends(get_db)):
    sla = 99.9
    total_period = 30 * 24 * 60 * 60  # 30 dias

    downtime = total_downtime(db, host_name)

    allowed_downtime = total_period * (1 - sla / 100)
    remaining = allowed_downtime - downtime

    return {
        "sla_target": sla,
        "allowed_downtime_seconds": allowed_downtime,
        "used_downtime_seconds": downtime,
        "remaining_seconds": max(0, remaining)
    }

@router.post("/login")
def login(data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data["username"]).first()

    if not user or not verify_password(data["password"], user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    # Aqui geramos o token JWT
    token = create_access_token({"sub": user.username})

    return {
        "access_token": token,
        "token_type": "bearer",
        "must_change_password": user.must_change_password
    }

@router.post("/change-password")
def change_password(data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data["username"]).first()

    user.password_hash = hash_password(data["new_password"])
    user.must_change_password = False

    db.commit()

    return {"message": "Senha alterada com sucesso"}

"""
@router.get("/hosts")
def list_hosts(user: str = Depends(get_current_user)):
    return {"message": f"Acesso permitido para {user}"}
"""
