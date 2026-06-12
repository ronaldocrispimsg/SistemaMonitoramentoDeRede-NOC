from urllib.parse import urlparse
import socket
import ipaddress
from datetime import datetime
from Backend.models import CheckResult, Incident
from Backend.notifications import send_telegram_alert

def normalize_http_url(url: str, port: int | None) -> str:
    if not url:
        return url

    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme in ("http", "https"):
        return url

    if "://" in url:
        return url

    if port == 443:
        scheme = "https"
    else:
        scheme = "http"

    return f"{scheme}://{url}"

def reverse_dns(ip: str) -> str | None:
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except Exception:
        return None

def is_ip(address: str) -> bool:
    try:
        ipaddress.ip_address(address)
        return True
    except ValueError:
        return False

def open_incident(db, host, reason, auto_commit=True):
    existing = db.query(Incident).filter(
        Incident.host_name == host.name,
        Incident.status == "OPEN"
    ).first()

    if existing:
        return

    incident = Incident(
        host_name=host.name,
        reason=reason
    )

    db.add(incident)
    if auto_commit:
        db.commit()

    msg = (
        f"<b>🚨 ALERTA NOC LITE</b>\n"
        f"Host: {host.name}\n"
        f"Endereço: {host.address}\n"
        f"Status: DOWN\n"
        f"Motivo: {reason}\n"
        f"Severidade: Crítica"
    )
    send_telegram_alert(msg)

def close_incident(db, host_name, auto_commit=True):

    incident = db.query(Incident).filter(
        Incident.host_name == host_name,
        Incident.status == "OPEN"
    ).first()

    if not incident:
        return

    incident.status = "CLOSED"
    incident.ended_time = datetime.utcnow()

    duration = incident.ended_time - incident.started_time
    incident.duration_seconds = int(duration.total_seconds())

    if auto_commit:
        db.commit()

def consecutive_failures(db, host_id, limit=3, check_types=None):
    query = db.query(CheckResult).filter(CheckResult.host_id == host_id)

    if check_types:
        query = query.filter(CheckResult.check_type.in_(check_types))

    recent = (
        query
        .order_by(CheckResult.timestamp.desc())
        .limit(limit)
        .all()
    )

    if len(recent) < limit:
        return False

    return all(not c.success for c in recent)
