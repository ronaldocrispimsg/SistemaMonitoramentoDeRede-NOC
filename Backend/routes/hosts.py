from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from Backend.database import SessionLocal
from Backend.models import Host
from Backend.checker import ping_host
from Backend.checker import tcp_check
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

    if not ping_result["success"]:
        host.status = "DOWN"

    elif tcp_result is not None and not tcp_result["success"]: 
        host.status = "DEGRADED"

    else:
        host.status = "UP"

    host.last_check = datetime.now()

    db.commit()

    return {
    "host": host.name,
    "address": host.address,
    "status": host.status,
    "ping": ping_result,
    "tcp": tcp_result
}


