from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from Backend.database import get_db
from Backend.metrics import total_downtime, total_incidents, availability_last_10_min
from Backend.models import CheckResult, Host, Alert, Incident, User, SNMPMetric
from Backend.checker import ping_host, tcp_check, resolve_dns_cached
from Backend.notifications import telegram_health_check
from Backend.schemas import HostCreate, HostUpdate, LoginRequest, PasswordChangeRequest
from Backend.utils import (
    is_ip,
    reverse_dns,
    resolve_http_url,
    extract_ips_from_dns_result,
    get_last_check,
)
from Backend.dependencies import get_current_user
from Backend.security import verify_password, create_access_token, hash_password

router = APIRouter()

def infer_probable_cause(db: Session, host: Host) -> str:
    last_dns = get_last_check(db, host.id, "dns")
    last_ping = get_last_check(db, host.id, "ping")
    last_tcp = get_last_check(db, host.id, "tcp")
    last_http = get_last_check(db, host.id, "http")

    if host.status == "DOWN":
        if last_dns and not last_dns.success:
            return "Falha na resolução DNS"
        if last_http and not last_http.success and (last_http.status_code or 0) >= 500:
            return f"Serviço HTTP instável (HTTP {last_http.status_code})"
        if host.port is not None and last_tcp and not last_tcp.success:
            return "Porta TCP indisponível"
        if last_ping and not last_ping.success:
            return "Host sem resposta ICMP"
        return "Indisponibilidade geral do host"

    if (
        (host.cpu_usage is not None and host.cpu_usage >= 95) or
        (host.ram_usage is not None and host.ram_usage >= 92) or
        (host.disk_usage is not None and host.disk_usage >= 95)
    ):
        return "Sobrecarga de recursos locais (CPU/RAM/Disco)"

    if last_http and not last_http.success and (last_http.status_code or 0) >= 500:
        return f"Aplicação web com erro HTTP {last_http.status_code}"

    if (
        (host.jitter_ms_ping is not None and host.jitter_ms_ping >= 120) or
        (host.jitter_ms_http is not None and host.jitter_ms_http >= 180) or
        (host.sla_rolling_ping is not None and host.sla_rolling_ping < 95)
    ):
        return "Instabilidade de rede (jitter/perda)"

    if host.severity in ("WARNING", "DEGRADED", "CRITICAL"):
        return "Degradação detectada por métricas preventivas"

    return "Operação normal"

@router.post("/host/create")
def create_host(data: HostCreate, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    existing_host = db.query(Host).filter(Host.name == data.name).first()
    resolved = None

    if is_ip(data.address):
        resolved = reverse_dns(data.address)
    else:
        dns_result = resolve_dns_cached(data.address, db)  # Verifica se o endereço é válido
        ips = extract_ips_from_dns_result(dns_result)
        
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

            existing_host.http_url = resolve_http_url(
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

        host.http_url = resolve_http_url(
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
        h.probable_cause = infer_probable_cause(db, h)
        
    return hosts


@router.post("/host/check/{host_name}")
def check_host(host_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):

    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    dns_result = resolve_dns_cached(host.address, db)
    ips = extract_ips_from_dns_result(dns_result)

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
def host_history(host_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
        dns_result = resolve_dns_cached(data.address, db)
        ips = extract_ips_from_dns_result(dns_result)

        if not ips:
            raise HTTPException(status_code=400, detail="Endereço inválido. ")
    
    host.address = data.address
    host.port = data.port
    host.hostname_resolved = resolved

    host.http_url = resolve_http_url(
        data.address,
        data.http_url,
        data.port or host.port
    )

    db.commit()

    return {"detail": "Host atualizado com sucesso"}

@router.get("/alerts/list")
def list_alerts(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    rows = (
        db.query(Alert, Host)
        .join(Host, Host.id == Alert.host_id)
        .order_by(Alert.timestamp.desc())
        .limit(50)
        .all()
    )

    result = []
    for alert, host in rows:
        availability_10m = availability_last_10_min(db, host.name)
        probable_cause = infer_probable_cause(db, host)

        result.append({
            "host_id": alert.host_id,
            "host_name": host.name,
            "host_address": host.address,
            "host_port": host.port,
            "alert_type": alert.alert_type,
            "old_status": alert.old_status,
            "new_status": alert.new_status,
            "timestamp": alert.timestamp.isoformat(),
            "status": host.status,
            "severity": host.severity,
            "health_score": host.health_score,
            "availability_10m": availability_10m,
            "sla_rolling_ping": host.sla_rolling_ping,
            "sla_rolling_tcp": host.sla_rolling_tcp,
            "sla_rolling_http": host.sla_rolling_http,
            "jitter_ms_ping": host.jitter_ms_ping,
            "jitter_ms_tcp": host.jitter_ms_tcp,
            "jitter_ms_http": host.jitter_ms_http,
            "trend_http": host.trend_http,
            "cpu_usage": host.cpu_usage,
            "ram_usage": host.ram_usage,
            "disk_usage": host.disk_usage,
            "network_traffic": host.network_traffic,
            "network_in_bps": host.network_in_bps,
            "network_out_bps": host.network_out_bps,
            "last_check": host.last_check.isoformat() if host.last_check else None,
            "last_snmp_check": host.last_snmp_check.isoformat() if host.last_snmp_check else None,
            "probable_cause": probable_cause,
        })

    return result

@router.get("/hosts/metrics/{host_name}")
def host_metrics(host_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "total_incidents": total_incidents(db, host_name),
        "total_downtime_seconds": total_downtime(db, host_name),
        "availability_10m_percent": availability_last_10_min(db, host_name),
    }

@router.get("/hosts/metrics/availability/type/{host_name}")
def availability_type(host_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):

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
def availability_host(host_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
def downtime_history(host_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
def login(data: LoginRequest, db: Session = Depends(get_db)):
    username = data.username.strip()
    password = data.password
    user = db.query(User).filter(User.username == username).first()

    if user and user.locked:
        if user.locked_until and user.locked_until <= datetime.utcnow():
            user.locked = False
            user.locked_until = None
            user.attempts = 0
            db.commit()
        else:
            raise HTTPException(status_code=403, detail="Conta bloqueada. Tente novamente mais tarde.")

    if not user or not verify_password(password, user.password_hash):
        if user:
            user.attempts = (user.attempts or 0) + 1
            if user.attempts >= 5:
                user.locked = True
                user.locked_until = datetime.utcnow() + timedelta(minutes=15)
                db.commit()
                raise HTTPException(status_code=403, detail="Conta bloqueada após 5 tentativas. Aguarde 15 minutos.")
            db.commit()
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    user.attempts = 0
    user.locked = False
    user.locked_until = None
    db.commit()

    # Aqui geramos o token JWT
    token = create_access_token({"sub": user.username})

    return {
        "access_token": token,
        "token_type": "bearer",
        "must_change_password": user.must_change_password
    }

@router.post("/auth/first-password")
def first_change_password(data: PasswordChangeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):

    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    user.attempts = 0

    db.commit()

    return {"message": "Senha alterada com sucesso",
            "logout": True
    }

@router.post("/auth/change-password")
def change_password(data: PasswordChangeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):

    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Verifica se conta está bloqueada
    if user.locked:
        raise HTTPException(status_code=403, detail="Conta bloqueada por muitas tentativas")

    # Verifica senha atual
    if not data.current_password:
        raise HTTPException(status_code=400, detail="Senha atual é obrigatória")

    if not verify_password(data.current_password, user.password_hash):

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
    user.password_hash = hash_password(data.new_password)
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

@router.get("/metrics/snmp/{host_name}")
def get_snmp_history(host_name: str, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    host = db.query(Host).filter(Host.name == host_name, Host.active == True).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    rows = (
        db.query(SNMPMetric)
        .filter(SNMPMetric.host_id == host.id)
        .order_by(SNMPMetric.timestamp.desc())
        .limit(180)
        .all()
    )
    rows.reverse()

    return {
        "host": host.name,
        "points": [
            {
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "cpu": r.cpu,
                "ram": r.ram,
                "disk": r.disk,
                "network_in_bps": r.network_in_bps,
                "network_out_bps": r.network_out_bps,
                "network_total_bps": r.network_total_bps
            }
            for r in rows
        ]
    }

@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    hosts = db.query(Host).filter(Host.active == True).all()

    total_hosts = len(hosts)
    up = sum(1 for h in hosts if h.status == "UP")
    degraded = sum(1 for h in hosts if h.status == "DEGRADED")
    down = sum(1 for h in hosts if h.status == "DOWN")

    open_incidents = (
        db.query(Incident)
        .filter(Incident.status == "OPEN")
        .count()
    )
    closed_incidents = (
        db.query(Incident)
        .filter(Incident.status == "CLOSED")
        .count()
    )

    return {
        "total_hosts": total_hosts,
        "up": up,
        "degraded": degraded,
        "down": down,
        "open_incidents": open_incidents,
        "closed_incidents": closed_incidents
    }

@router.get("/health/telegram")
def check_telegram(user: User = Depends(get_current_user)):
    return telegram_health_check()
