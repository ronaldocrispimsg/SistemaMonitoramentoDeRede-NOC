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
    build_incident_service_degraded_message,
    build_incident_open_message,
    build_incident_closed_message,
)

INCIDENT_TYPE_DNS_FAILURE = "DNS_FAILURE"
INCIDENT_TYPE_SERVICE_DOWN = "SERVICE_DOWN"
INCIDENT_TYPE_SERVICE_DEGRADED = "SERVICE_DEGRADED"
INCIDENT_TYPE_GENERIC = "GENERIC"


def normalize_incident_type(incident_type: str | None) -> str:
    normalized = str(incident_type or INCIDENT_TYPE_GENERIC).strip().upper()
    valid = {
        INCIDENT_TYPE_DNS_FAILURE,
        INCIDENT_TYPE_SERVICE_DOWN,
        INCIDENT_TYPE_SERVICE_DEGRADED,
        INCIDENT_TYPE_GENERIC,
    }
    return normalized if normalized in valid else INCIDENT_TYPE_GENERIC


def format_incident_reason(incident_type: str, reason: str | None) -> str:
    clean_reason = (reason or "").strip() or "Incidente operacional"
    return f"[{incident_type}] {clean_reason}"


def parse_incident_type(reason: str | None) -> str:
    text = str(reason or "").strip()
    if text.startswith("[") and "]" in text:
        candidate = text[1:text.index("]")]
        return normalize_incident_type(candidate)
    return INCIDENT_TYPE_GENERIC


def strip_incident_prefix(reason: str | None) -> str:
    text = str(reason or "").strip()
    if text.startswith("[") and "]" in text:
        return text[text.index("]") + 1:].strip()
    return text

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

def calculate_availability_points(
    db: Session,
    host_id: int,
    check_type: str,
    window: int = 100,
    sample_limit: int = 200,
) -> list[dict]:
    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == check_type
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(sample_limit)
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

def open_incident(db, host, reason, incident_type=None, check_used=None, auto_commit=True):
    incident_type = normalize_incident_type(incident_type)
    existing = db.query(Incident).filter(
        Incident.host_name == host.name,
        Incident.status == "OPEN"
    ).all()

    for inc in existing:
        if parse_incident_type(inc.reason) == incident_type:
            return inc

    formatted_reason = format_incident_reason(incident_type, reason)

    incident = Incident(
        host_name=host.name,
        reason=formatted_reason
    )

    db.add(incident)
    if auto_commit:
        db.commit()

    if incident_type == INCIDENT_TYPE_DNS_FAILURE:
        msg = build_incident_dns_message(host, host.address, incident.started_time)
    elif incident_type == INCIDENT_TYPE_SERVICE_DOWN:
        msg = build_incident_host_unavailable_message(host, check_used or "N/A", incident.started_time)
    elif incident_type == INCIDENT_TYPE_SERVICE_DEGRADED:
        msg = build_incident_service_degraded_message(host, check_used or "N/A", incident.started_time)
    else:
        msg = build_incident_open_message(host, "GENÉRICO", strip_incident_prefix(formatted_reason), incident.started_time)
    send_telegram_alert(msg)
    return incident

def close_incident(db, host_name, incident_type=None, auto_commit=True):
    normalized_type = normalize_incident_type(incident_type) if incident_type else None

    open_incidents = db.query(Incident).filter(
        Incident.host_name == host_name,
        Incident.status == "OPEN"
    ).order_by(Incident.started_time.asc()).all()

    if not open_incidents:
        return []

    targets = []
    for inc in open_incidents:
        if normalized_type is None or parse_incident_type(inc.reason) == normalized_type:
            targets.append(inc)

    if not targets:
        return []

    host = db.query(Host).filter(Host.name == host_name).first()
    host_stub = type(
        "HostStub",
        (),
        {"name": host_name, "address": host.address if host else "N/A"}
    )()

    closed = []
    for incident in targets:
        incident.status = "CLOSED"
        incident.ended_time = datetime.utcnow()

        duration = incident.ended_time - incident.started_time
        incident.duration_seconds = int(duration.total_seconds())

        send_telegram_alert(
            build_incident_closed_message(
                host_stub,
                incident.ended_time,
                incident_type=parse_incident_type(incident.reason)
            )
        )
        closed.append(incident)

    if auto_commit:
        db.commit()
    return closed

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
