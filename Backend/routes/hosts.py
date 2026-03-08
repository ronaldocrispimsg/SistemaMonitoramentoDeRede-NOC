from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from Backend.database import SessionLocal, get_db
from Backend.metrics import total_downtime, total_incidents, availability_last_10_min
from Backend.models import CheckResult, Host, Alert, Incident, User
from Backend.checker import ping_host, tcp_check, resolve_dns_cached
from Backend.notifications import telegram_health_check
from Backend.schemas import HostCreate, HostUpdate
from Backend.utils import is_ip, normalize_http_url, reverse_dns
from fastapi.security import OAuth2PasswordRequestForm
from Backend.dependencies import get_current_user
from Backend.security import verify_password, create_access_token, hash_password

router = APIRouter()

def _resolve_http_url(address: str, http_url: str | None, port: int | None) -> str | None:
    clean_http = (http_url or "").strip()
    base = clean_http if clean_http else address
    return normalize_http_url(base, port) if base else None

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

            existing_host.http_url = _resolve_http_url(
                data.address,
                data.http_url,
                data.port or existing_host.port
            )

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

        host.http_url = _resolve_http_url(
            data.address,
            data.http_url,
            data.port or host.port
        )

        db.add(host)
        db.commit()
        db.refresh(host)

        return host



@router.get("/hosts/list")
def list_hosts(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    hosts = db.query(Host).filter(Host.active == True).all()
    
    # Métricas em tempo real no objeto antes de enviar
    for h in hosts:
        h.availability_10m = availability_last_10_min(db, h.name)
        
    return hosts


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
                "status_code": c.status_code,
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

    host.http_url = _resolve_http_url(
        data.address,
        data.http_url,
        data.port or host.port
    )

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

@router.get("/hosts/metrics/{host_name}")
def host_metrics(host_name: str, db: Session = Depends(get_db)):
    return {
        "total_incidents": total_incidents(db, host_name),
        "total_downtime_seconds": total_downtime(db, host_name),
        "availability_10m_percent": availability_last_10_min(db, host_name),
    }

@router.get("/hosts/metrics/availability/type/{host_name}")
def availability_type(host_name: str, db: Session = Depends(get_db)):

    host = db.query(Host).filter_by(name=host_name).first()
    if not host:
        return {"ping": [], "tcp": [], "http": []}

    window = 100

    def calc_availability(check_type: str):

        rows = (
            db.query(CheckResult)
            .filter(
                CheckResult.host_id == host.id,
                CheckResult.check_type == check_type
            )
            .order_by(CheckResult.timestamp.desc())
            .limit(200)
            .all()
        )
        rows.reverse()

        points = []
        total = len(rows)
        if total == 0:
            return points
        
        for i in range(1, total + 1):
            start_index = max(0, i - window)
            chunk = rows[start_index:i]

            ok = sum(1 for r in chunk if r.success)
            availability = (ok / len(chunk)) * 100

            points.append({
                "timestamp": chunk[-1].timestamp.isoformat(),
                "availability": round(availability, 2)
            })

        return points

    return {
        "ping": calc_availability("ping"),
        "tcp": calc_availability("tcp"),
        "http": calc_availability("http")
    }
    
@router.get("/hosts/metrics/availability/host/{host_name}")
def availability_host(host_name: str, db: Session = Depends(get_db)):
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

@router.post("/auth/login")
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

@router.post("/auth/first-password")
def first_change_password(data: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):

    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    user.password_hash = hash_password(data["new_password"])
    user.must_change_password = False
    user.attempts = 0

    db.commit()

    return {"message": "Senha alterada com sucesso",
            "logout": True
    }

@router.post("/auth/change-password")
def change_password(data: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):

    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Verifica se conta está bloqueada
    if user.locked:
        raise HTTPException(status_code=403, detail="Conta bloqueada por muitas tentativas")

    # Verifica senha atual
    if not verify_password(data["current_password"], user.password_hash):

        user.attempts += 1

        if user.attempts >= 5:
            user.locked = True
            db.commit()
            raise HTTPException(status_code=403, detail="Conta bloqueada após 5 tentativas")

        db.commit()

        raise HTTPException(
            status_code=401,
            detail=f"Senha atual incorreta ({user.attempts}/5)"
        )

    # Senha correta → reseta tentativas
    user.attempts = 0
    user.password_hash = hash_password(data["new_password"])
    user.must_change_password = False

    db.commit()

    return {"message": "Senha alterada com sucesso"}

@router.get("/incidents/latest")
def get_latest_incidents(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    incidents = (
        db.query(Incident)
        .order_by(Incident.started_time.desc())
        .limit(25)
        .all()
    )
    
    return [
        {
            "id": i.id,
            "host_name": i.host_name,
            "status": i.status,
            "reason": i.reason,
            "started_time": i.started_time.isoformat(),
            "ended_time": i.ended_time.isoformat() if i.ended_time else None,
            "duration": i.duration_seconds
        }
        for i in incidents
    ]

@router.get("/metrics/heatmap/{host_id}")
def get_heatmap(host_id: int, db: Session = Depends(get_db)):
    host = db.query(Host).filter(Host.id == host_id).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    # Escolhe o tipo mais "saudável" recentemente:
    # maior taxa de sucesso e, em empate, menor latência média.
    candidates = []
    for check_type in ("ping", "tcp", "http"):
        rows = (
            db.query(CheckResult)
            .filter(
                CheckResult.host_id == host.id,
                CheckResult.check_type == check_type
            )
            .order_by(CheckResult.timestamp.desc())
            .limit(30)
            .all()
        )

        if not rows:
            continue

        total = len(rows)
        successes = sum(1 for r in rows if r.success)
        success_rate = successes / total

        latencies = [r.latency for r in rows if r.latency is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else float("inf")

        candidates.append((check_type, success_rate, avg_latency))

    if candidates:
        preferred_type = max(candidates, key=lambda item: (item[1], -item[2]))[0]
    else:
        preferred_type = "ping"

    results = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host.id,
            CheckResult.check_type == preferred_type
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(100)
        .all()
    )

    data = []
    for r in results:
        data.append({
            "check_type": r.check_type,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "latency": r.latency,
            "success": r.success,
            "error": r.error
        })

    return data

@router.get("/health/telegram")
def check_telegram():
    return telegram_health_check()
