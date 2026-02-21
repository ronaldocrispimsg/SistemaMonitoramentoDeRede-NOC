from urllib.parse import urlparse
import socket
import ipaddress
from datetime import datetime
from Backend.models import Incident

def normalize_http_url(url: str, port: int | None) -> str:
    if not url:
        return url

    parsed = urlparse(url)

    if parsed.scheme:
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

# Utils para gerenciamento de incidentes
def open_incident(db, host_name, reason):

    existing = db.query(Incident).filter(
        Incident.host_name == host_name,
        Incident.status == "OPEN"
    ).first()

    if existing:
        return

    incident = Incident(
        host_name=host_name,
        reason=reason
    )

    db.add(incident)
    db.commit()

def close_incident(db, host_name):

    incident = db.query(Incident).filter(
        Incident.host_name == host_name,
        Incident.status == "OPEN"
    ).first()

    if not incident:
        return

    incident.status = "CLOSED"
    incident.ended_at = datetime.utcnow()

    duration = incident.ended_at - incident.started_at
    incident.duration_seconds = int(duration.total_seconds())

    db.commit()
