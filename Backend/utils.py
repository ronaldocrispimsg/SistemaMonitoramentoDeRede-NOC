from urllib.parse import urlparse
import socket
import ipaddress
from datetime import datetime
from sqlalchemy.orm import Session
from Backend.models import CheckResult, Incident, Host
from Backend.notifications import (
    send_telegram_alert,
    build_incident_dns_message,
    build_incident_host_unavailable_message,
    build_incident_open_message,
    build_incident_closed_message,
)

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


def resolve_http_url(address: str, http_url: str | None, port: int | None) -> str | None:
    clean_http = (http_url or "").strip()
    base = clean_http if clean_http else address
    return normalize_http_url(base, port) if base else None


def extract_ips_from_dns_result(dns_result) -> list[str]:
    if isinstance(dns_result, tuple):
        if dns_result and isinstance(dns_result[0], list):
            return dns_result[0]
        return []
    if isinstance(dns_result, list):
        return dns_result
    return []


def get_last_check(db: Session, host_id: int, check_type: str) -> CheckResult | None:
    return (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == check_type
        )
        .order_by(CheckResult.timestamp.desc())
        .first()
    )

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

    reason_lower = str(reason or "").lower()
    if "dns" in reason_lower:
        msg = build_incident_dns_message(host, host.address, incident.started_time)
    elif "indispon" in reason_lower:
        msg = build_incident_host_unavailable_message(host, "primário", incident.started_time)
    else:
        msg = build_incident_open_message(host, "GENÉRICO", reason or "Incidente aberto", incident.started_time)
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

    host = db.query(Host).filter(Host.name == host_name).first()
    host_stub = type(
        "HostStub",
        (),
        {"name": host_name, "address": host.address if host else "N/A"}
    )()
    send_telegram_alert(build_incident_closed_message(host_stub, incident.ended_time))

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
