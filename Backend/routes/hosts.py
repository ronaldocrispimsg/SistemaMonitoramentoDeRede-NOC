from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from Backend.database import SessionLocal
from Backend.models import Host
from Backend.checker import ping_host, tcp_check, resolve_dns
from Backend.schemas import HostCreate

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/host/create")
def create_host(data: HostCreate, db: Session = Depends(get_db)):
    host = Host(
        name=data.name,
        address=data.address,
        port=data.port
    )

    resultado_dns = resolve_dns(data.address)  # Verifica se o endereço é válido
    
    if not resultado_dns["success"]:
        raise HTTPException(status_code=400, detail="Endereço inválido")
    else:
        db.add(host)
        db.commit()
        db.refresh(host)

    return host



@router.get("/hosts/list")
def list_hosts(db: Session = Depends(get_db)):
    return db.query(Host).all()


@router.post("/host/check/{host_name}")
def check_host(host_name: str, db: Session = Depends(get_db)):
    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")


    ping_result = ping_host(host.address)
    tcp_result = None

    if host.port is not None:
        tcp_result = tcp_check(host.address, host.port)

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

    return {
        "host": host.name,
        "address": host.address,
        "checks": [
            {
                "type": check.check_type,
                "success": check.success,
                "latency": check.latency,
                "error": check.error,
                "timestamp": check.timestamp.isoformat()
            }
            for check in host.checks
        ]
    }


