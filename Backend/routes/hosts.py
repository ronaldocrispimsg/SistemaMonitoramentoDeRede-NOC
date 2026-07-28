from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import ipaddress
import json
import re
import socket
import subprocess
import xml.etree.ElementTree as ET
import psutil
from Backend.database import get_db
from Backend.metrics import total_downtime, total_incidents, availability_last_10_min
from Backend.models import CheckResult, Host, Alert, Incident, User, SNMPMetric
from Backend.checker import ping_host, tcp_check, resolve_dns_cached_sync
from Backend.notifications import telegram_health_check
from Backend.schemas import (
    HostCreate,
    HostUpdate,
    LoginRequest,
    PasswordChangeRequest,
    NetworkDiscoveryRequest,
    NetworkImportRequest,
)
from Backend.utils import (
    is_ip,
    reverse_dns,
    resolve_http_url,
    extract_ips_from_dns_result,
    get_last_check,
    calculate_availability_points,
    parse_incident_type,
    strip_incident_prefix,
)
from Backend.dependencies import get_current_user
from Backend.security import verify_password, create_access_token, hash_password

router = APIRouter()

_RFC1918_RANGES = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_IGNORED_INTERFACE_PREFIXES = (
    "lo",
    "docker",
    "br-",
    "veth",
    "virbr",
    "tun",
    "tap",
)
_MAX_DISCOVERY_ADDRESSES = 4096


def _apply_snmp_policy(host: Host, snmp_enabled: bool | None, snmp_community: str | None = None) -> None:
    if snmp_enabled is not None:
        host.snmp_enabled = bool(snmp_enabled)
    comm = (snmp_community or getattr(host, "snmp_community", "netspot") or "netspot").strip()
    if not comm:
        comm = "netspot"
    host.snmp_community = comm


def _apply_http_policy(host: Host, http_enabled: bool | None, selected_http: str | None) -> None:
    if http_enabled is not None:
        host.http_enabled = bool(http_enabled)

    host.http_url = resolve_http_url(host.address, selected_http, host.port)

    if not bool(getattr(host, "http_enabled", True)):
        host.last_http_protocol = None
        host.http_latency = None
        host.https_latency = None
        host.web_tcp_port = None
        host.web_tcp_port_latency = None
        host.tcp_http_port_ok = None
        host.tcp_http_port_latency = None
        host.tcp_https_port_ok = None
        host.tcp_https_port_latency = None


def _normalize_ports(raw_ports, fallback_port: int | None = None) -> list[int]:
    candidates = []
    if raw_ports:
        candidates.extend(raw_ports)
    elif fallback_port is not None:
        candidates.append(fallback_port)

    cleaned = []
    seen = set()
    for value in candidates:
        if value in (None, ""):
            continue
        try:
            port = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Porta inválida: {value}")

        if port < 1 or port > 65535:
            raise HTTPException(status_code=400, detail=f"Porta fora da faixa permitida: {port}")
        if port in seen:
            continue
        seen.add(port)
        cleaned.append(port)

    cleaned.sort()
    return cleaned


def _store_host_ports(host: Host, ports: list[int]) -> None:
    host.port = ports[0] if ports else None
    host.tcp_ports = json.dumps(ports) if ports else None


def _host_ports(host: Host) -> list[int]:
    if host.tcp_ports:
        try:
            parsed = json.loads(host.tcp_ports)
            if isinstance(parsed, list):
                normalized = _normalize_ports(parsed, None)
                if normalized:
                    return normalized
        except Exception:
            pass

    if host.port is not None:
        return _normalize_ports([host.port], None)
    return []


def _resolve_http_input(data) -> str | None:
    preferred = (data.url or "").strip() if hasattr(data, "url") else ""
    legacy = (data.http_url or "").strip() if hasattr(data, "http_url") else ""
    return preferred or legacy or None


def _slug_ip_name(ip_value: str) -> str:
    safe = re.sub(r"[^0-9a-zA-Z]+", "-", str(ip_value)).strip("-")
    return f"auto-{safe}" if safe else "auto-host"


def _is_rfc1918_private(network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> bool:
    return any(network.subnet_of(rng) for rng in _RFC1918_RANGES)


def _validate_private_subnet(subnet: str) -> str:
    raw = (subnet or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Subnet é obrigatória")

    try:
        network = ipaddress.ip_network(raw, strict=False)
    except ValueError:
        raise HTTPException(status_code=400, detail="Subnet inválida. Use formato CIDR, ex: 192.168.0.0/24")

    if not _is_rfc1918_private(network):
        raise HTTPException(status_code=400, detail="Subnet deve ser privada RFC1918")

    if network.num_addresses > _MAX_DISCOVERY_ADDRESSES:
        raise HTTPException(status_code=400, detail="Subnet muito grande para varredura automática")

    return str(network)


def _interface_ignored(interface_name: str) -> bool:
    lowered = (interface_name or "").strip().lower()
    return any(lowered.startswith(prefix) for prefix in _IGNORED_INTERFACE_PREFIXES)


def _run_nmap_discovery(subnet: str) -> str:
    try:
        dns_server = None
        try:
            net = ipaddress.ip_network(subnet, strict=False)
            dns_server = str(next(net.hosts()))
        except Exception:
            pass

        nmap_args = ["nmap", "-sn", "-PE", "-PS22,80,443", "-T4", "--max-rtt-timeout", "200ms", "--max-retries", "1"]
        if dns_server:
            nmap_args += ["--dns-servers", dns_server]
        nmap_args += [subnet, "-oX", "-"]

        result = subprocess.run(
            nmap_args,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Nmap não está instalado no servidor")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Descoberta de rede excedeu o tempo limite")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao executar descoberta: {exc}")

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise HTTPException(
            status_code=500,
            detail=f"Nmap retornou erro ({result.returncode}): {stderr or 'erro desconhecido'}",
        )

    return result.stdout or ""


def _parse_nmap_hosts(xml_text: str) -> list[dict]:
    if not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise HTTPException(status_code=500, detail="Resposta XML do Nmap inválida")

    hosts = []
    for host_node in root.findall("host"):
        status = host_node.find("status")
        if status is None or status.attrib.get("state") != "up":
            continue

        ipv4 = None
        for addr in host_node.findall("address"):
            if addr.attrib.get("addrtype") == "ipv4":
                ipv4 = (addr.attrib.get("addr") or "").strip()
                break

        if not ipv4:
            continue

        hostname_value = None
        hostnames = host_node.find("hostnames")
        if hostnames is not None:
            hn = hostnames.find("hostname")
            if hn is not None:
                hostname_value = (hn.attrib.get("name") or "").strip() or None

        hosts.append({
            "address": ipv4,
            "hostname": hostname_value,
        })

    return hosts


def _build_unique_name(base_name: str, used_names: set[str]) -> str:
    candidate = base_name
    suffix = 2
    while candidate in used_names:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _prepare_discovery_result(db: Session, raw_hosts: list[dict]) -> list[dict]:
    if not raw_hosts:
        return []

    addresses = sorted({str(item.get("address") or "").strip() for item in raw_hosts if item.get("address")})
    existing_hosts = db.query(Host).filter(Host.address.in_(addresses)).all()
    existing_ip_set = {h.address for h in existing_hosts}
    used_names = {str(row[0]).strip() for row in db.query(Host.name).all() if row[0]}
    seen_ips = set()

    prepared = []
    temp_idx = 1
    for item in raw_hosts:
        address = str(item.get("address") or "").strip()
        if not address or address in seen_ips:
            continue
        seen_ips.add(address)

        hostname = item.get("hostname")
        base_name = str(hostname).strip() if hostname else _slug_ip_name(address)
        safe_name = _build_unique_name(base_name, used_names)

        prepared.append({
            "id": f"temp-{temp_idx}",
            "name": safe_name,
            "address": address,
            "hostname": hostname,
            "already_exists": address in existing_ip_set,
        })
        temp_idx += 1

    return prepared


def _detect_local_network() -> str | None:
    outbound_ip = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            outbound_ip = sock.getsockname()[0]
    except Exception:
        outbound_ip = None

    try:
        stats_by_iface = psutil.net_if_stats()
    except Exception:
        stats_by_iface = {}

    try:
        interfaces = psutil.net_if_addrs().items()
    except Exception:
        interfaces = []

    candidates = []
    for iface, addrs in interfaces:
        if _interface_ignored(iface):
            continue
        iface_stats = stats_by_iface.get(iface)
        if iface_stats is not None and not iface_stats.isup:
            continue

        for addr in addrs:
            if addr.family != socket.AF_INET:
                continue

            ip = (addr.address or "").strip()
            netmask = (addr.netmask or "").strip()
            if not ip or ip.startswith("127.") or not netmask:
                continue

            try:
                network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
            except ValueError:
                continue

            if not _is_rfc1918_private(network):
                continue

            candidates.append({
                "iface": iface,
                "ip": ip,
                "cidr": str(network),
            })

    if not candidates:
        return None

    if outbound_ip:
        for candidate in candidates:
            if candidate["ip"] == outbound_ip:
                return candidate["cidr"]

    return candidates[0]["cidr"]


def _reset_host_operational_state(host: Host) -> None:
    host.baseline_pending = True
    host.status = "UNKNOWN"
    host.status_ping = None
    host.status_tcp = None
    host.last_check = None
    host.latency_ping = None
    host.latency_tcp = None
    host.fail_streak = 0
    host.success_streak = 0
    host.last_resolved_ip = None
    host.hostname_resolved = None
    host.dns_ttl = None
    host.dns_ttl_remaining = None
    host.last_ttl_alert = None
    host.health_score = 0
    host.severity = "UNKNOWN"
    host.last_preventive_alert = None

    host.cpu_usage = None
    host.ram_usage = None
    host.disk_usage = None
    host.disk_remaining = None
    host.network_traffic = None
    host.network_in_bps = None
    host.network_out_bps = None
    host.last_net_in_octets = None
    host.last_net_out_octets = None
    host.last_net_check = None
    host.last_snmp_check = None

    host.sla_rolling_ping = None
    host.sla_rolling_tcp = None
    host.sla_rolling_http = None
    host.jitter_ms_ping = None
    host.jitter_ms_tcp = None
    host.jitter_ms_http = None
    host.slope = None
    host.trend = "UNKNOWN"
    host.slope_http = None
    host.trend_http = "UNKNOWN"
    host.last_http_protocol = None
    host.http_latency = None
    host.https_latency = None
    host.web_tcp_port = None
    host.web_tcp_port_latency = None
    host.tcp_http_port_ok = None
    host.tcp_http_port_latency = None
    host.tcp_https_port_ok = None
    host.tcp_https_port_latency = None


def _deactivate_host_entity(host: Host) -> None:
    host.active = False
    host.active_time = datetime.utcnow()
    host.deleted_at = datetime.utcnow()


def _is_icmp_blocked_but_service_up(
    host: Host,
    last_ping: CheckResult | None,
    last_tcp: CheckResult | None,
    last_http: CheckResult | None,
) -> bool:
    if not last_ping or last_ping.success:
        return False

    tcp_ok = host.port is not None and bool(last_tcp and last_tcp.success)
    http_ok = bool(last_http and last_http.success)
    return tcp_ok or http_ok

def infer_probable_cause(db: Session, host: Host) -> str:
    last_dns = get_last_check(db, host.id, "dns")
    last_ping = get_last_check(db, host.id, "ping")
    last_tcp = get_last_check(db, host.id, "tcp")
    last_http = get_last_check(db, host.id, "http")
    icmp_blocked_but_service_up = _is_icmp_blocked_but_service_up(
        host,
        last_ping,
        last_tcp,
        last_http,
    )
    host.icmp_blocked_but_service_up = icmp_blocked_but_service_up

    if icmp_blocked_but_service_up:
        return "ICMP bloqueado por firewall\nServiço operando normalmente"

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
    normalized_name = (data.name or "").strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Nome do host é obrigatório")

    existing_host = db.query(Host).filter(Host.name == normalized_name).first()
    resolved = None

    if is_ip(data.address):
        resolved = reverse_dns(data.address)
    else:
        dns_result = resolve_dns_cached_sync(data.address, db)  # Verifica se o endereço é válido
        ips = extract_ips_from_dns_result(dns_result)
        
        if not ips:
            raise HTTPException(status_code=400, detail="Endereço inválido")
                   
    if existing_host:
        if not existing_host.active:
            existing_host.active = True
            existing_host.active_time = None
            existing_host.deleted_at = None
            existing_ports = _host_ports(existing_host)
            if data.ports is None and data.port is None:
                ports = existing_ports
            else:
                ports = _normalize_ports(data.ports, data.port)
            existing_host.address = data.address
            _store_host_ports(existing_host, ports)
            existing_host.hostname_resolved = resolved
            _reset_host_operational_state(existing_host)
            existing_host.hostname_resolved = resolved

            selected_http = _resolve_http_input(data)
            _apply_http_policy(existing_host, data.http_enabled, selected_http)
            _apply_snmp_policy(existing_host, data.snmp_enabled, getattr(data, "snmp_community", "netspot"))

            db.commit()
            db.refresh(existing_host)
            if not existing_host.active:
                raise HTTPException(status_code=500, detail="Falha ao reativar host")
            return existing_host
        else:
            raise HTTPException(status_code=409, detail="Host com esse nome já existe")

    else:
        ports = _normalize_ports(data.ports, data.port)
        selected_http = _resolve_http_input(data)
        comm = (getattr(data, "snmp_community", "netspot") or "netspot").strip() or "netspot"
        host = Host(
            name=normalized_name,
            address=data.address,
            active=True,
            active_time=None,
            deleted_at=None,
            baseline_pending=True,
            status="UNKNOWN",
            status_ping="UNKNOWN",
            status_tcp="UNKNOWN",
            http_enabled=bool(data.http_enabled),
            last_http_protocol=None,
            snmp_enabled=bool(data.snmp_enabled),
            snmp_community=comm,
            hostname_resolved=resolved,
        )
        _store_host_ports(host, ports)

        _apply_http_policy(host, data.http_enabled, selected_http)

        db.add(host)
        db.commit()
        db.refresh(host)
        if not host.active:
            raise HTTPException(status_code=500, detail="Falha ao ativar host recém-criado")

        return host



@router.post("/network/discover")
def network_discover(
    data: NetworkDiscoveryRequest,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    subnet = _validate_private_subnet(data.subnet)
    xml_result = _run_nmap_discovery(subnet)
    parsed_hosts = _parse_nmap_hosts(xml_result)
    hosts = _prepare_discovery_result(db, parsed_hosts)

    return {
        "subnet": subnet,
        "found": len(hosts),
        "hosts": hosts,
    }


@router.get("/network/default-subnet")
def network_default_subnet(user: str = Depends(get_current_user)):
    subnet = _detect_local_network()
    return {"subnet": subnet or None}


@router.post("/network/import")
def network_import(
    data: NetworkImportRequest,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    requested_hosts = list(data.hosts or [])
    results = []

    existing_ip_set = {row[0] for row in db.query(Host.address).all() if row[0]}
    used_names = {row[0] for row in db.query(Host.name).all() if row[0]}
    seen_addresses_in_request = set()
    created_count = 0
    skipped_count = 0

    for item in requested_hosts:
        address = str(item.address or "").strip()
        raw_name = str(item.name or "").strip()

        if not address:
            skipped_count += 1
            results.append({
                "name": raw_name or None,
                "address": address,
                "created": False,
                "reason": "invalid_address",
            })
            continue

        try:
            ipaddress.ip_address(address)
        except ValueError:
            skipped_count += 1
            results.append({
                "name": raw_name or None,
                "address": address,
                "created": False,
                "reason": "invalid_address",
            })
            continue

        if address in seen_addresses_in_request:
            skipped_count += 1
            results.append({
                "name": raw_name or _slug_ip_name(address),
                "address": address,
                "created": False,
                "reason": "duplicate_in_request",
            })
            continue
        seen_addresses_in_request.add(address)

        if address in existing_ip_set:
            skipped_count += 1
            results.append({
                "name": raw_name or _slug_ip_name(address),
                "address": address,
                "created": False,
                "reason": "already_exists",
            })
            continue

        base_name = raw_name or _slug_ip_name(address)
        final_name = _build_unique_name(base_name, used_names)

        host = Host(
            name=final_name,
            address=address,
            port=None,
            tcp_ports=None,
            active=True,
            active_time=None,
            deleted_at=None,
            baseline_pending=True,
            status="UNKNOWN",
            status_ping="UNKNOWN",
            status_tcp="UNKNOWN",
            http_url=None,
            http_enabled=False,
            last_http_protocol=None,
            snmp_enabled=bool(data.snmp_enabled if data.snmp_enabled is not None else True),
            snmp_community=(getattr(data, "snmp_community", "netspot") or "netspot").strip() or "netspot",
        )

        db.add(host)
        existing_ip_set.add(address)
        created_count += 1
        results.append({
            "name": final_name,
            "address": address,
            "created": True,
        })

    db.commit()

    return {
        "requested": len(requested_hosts),
        "created": created_count,
        "skipped": skipped_count,
        "results": results,
    }


@router.get("/hosts/list")
def list_hosts(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    hosts = db.query(Host).filter(Host.active.is_(True)).all()
    open_incident_hosts = {
        row[0]
        for row in db.query(Incident.host_name)
        .filter(Incident.status == "OPEN")
        .all()
    }
    
    # Métricas em tempo real no objeto antes de enviar
    for h in hosts:
        h.ports = _host_ports(h)
        h.url = h.http_url
        h.http_protocol = h.last_http_protocol
        h.availability_10m = availability_last_10_min(db, h.name)
        h.probable_cause = infer_probable_cause(db, h)
        h.icmp_blocked_but_service_up = bool(getattr(h, "icmp_blocked_but_service_up", False))
        h.has_open_incident = h.name in open_incident_hosts
        
    return hosts


@router.post("/host/check/{host_name}")
def check_host(host_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):

    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    dns_result = resolve_dns_cached_sync(host.address, db)
    ips = extract_ips_from_dns_result(dns_result)

    if not ips:
        raise HTTPException(400, "DNS fail")

    ip = ips[0]

    ping_result = ping_host(ip)
    tcp_results = []
    for tcp_port in _host_ports(host):
        result = tcp_check(ip, tcp_port)
        result["port"] = tcp_port
        tcp_results.append(result)

    tcp_result = None
    if tcp_results:
        successes = [r for r in tcp_results if r.get("success")]
        if successes:
            best = min(successes, key=lambda r: r.get("latency") or float("inf"))
            tcp_result = {"success": True, "latency": best.get("latency"), "error": None}
        else:
            tcp_result = {
                "success": False,
                "latency": None,
                "error": "; ".join(filter(None, [r.get("error") for r in tcp_results])) or "tcp_failed",
            }

    icmp_blocked_but_service_up = (
        not ping_result["success"] and
        tcp_result is not None and
        tcp_result.get("success")
    )

    host.status_ping = "UP" if ping_result["success"] else "DOWN"
    host.latency_ping = ping_result["latency"]
    
    if tcp_result is not None:
        host.status_tcp = "UP" if tcp_result["success"] else "DOWN"
        host.latency_tcp = tcp_result["latency"]
    else:
        host.status_tcp = None
        host.latency_tcp = None

    host.last_check = datetime.now()

    if icmp_blocked_but_service_up:
        host.status = "UP"

    elif host.status_ping == "DOWN":
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
    "icmp_blocked_but_service_up": icmp_blocked_but_service_up,
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
                "tcp_port": c.tcp_port,
                "timestamp": c.timestamp.isoformat()
            }
            for c in checks
        ]
    }

@router.get("/hosts/trash")
def list_hosts_trash(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    hosts = (
        db.query(Host)
        .filter(Host.active.is_(False))
        .order_by(Host.deleted_at.desc(), Host.name.asc())
        .all()
    )
    return hosts


@router.post("/hosts/{host_id}/deactivate")
def deactivate_host(
    host_id: int,
    host_name: str = Query(...),
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    host = db.query(Host).filter(Host.id == host_id).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    if not host.active:
        return {"detail": "Host já está na lixeira"}

    if host.name != host_name:
        raise HTTPException(
            status_code=409,
            detail=f"Conflito de identificação: id={host_id} pertence a '{host.name}', não a '{host_name}'",
        )

    _deactivate_host_entity(host)
    db.commit()

    return {"detail": "Host movido para a lixeira com sucesso"}


@router.post("/hosts/{host_id}/restore")
def restore_host(
    host_id: int,
    host_name: str = Query(...),
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    host = db.query(Host).filter(Host.id == host_id).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    if host.active:
        return {"detail": "Host já está ativo"}

    if host.name != host_name:
        raise HTTPException(
            status_code=409,
            detail=f"Conflito de identificação: id={host_id} pertence a '{host.name}', não a '{host_name}'",
        )

    host.active = True
    host.active_time = None
    host.deleted_at = None
    _reset_host_operational_state(host)

    db.commit()
    return {"detail": "Host restaurado com sucesso"}


@router.delete("/hosts/{host_id}/hard-delete")
def hard_delete_host(
    host_id: int,
    host_name: str = Query(...),
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    host = db.query(Host).filter(Host.id == host_id).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    if host.active:
        raise HTTPException(
            status_code=409,
            detail="Host ativo não pode ser removido permanentemente. Mova para lixeira antes.",
        )

    if host.name != host_name:
        raise HTTPException(
            status_code=409,
            detail=f"Conflito de identificação: id={host_id} pertence a '{host.name}', não a '{host_name}'",
        )

    db.query(CheckResult).filter(CheckResult.host_id == host.id).delete(synchronize_session=False)
    db.query(Alert).filter(Alert.host_id == host.id).delete(synchronize_session=False)
    db.query(SNMPMetric).filter(SNMPMetric.host_id == host.id).delete(synchronize_session=False)
    db.query(Incident).filter(Incident.host_name == host.name).delete(synchronize_session=False)
    db.delete(host)
    db.commit()

    return {"detail": "Host removido permanentemente"}


@router.delete("/host/delete/{host_name}")
def delete_host(host_name: str, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    host = db.query(Host).filter(Host.name == host_name).first()

    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")

    if not host.active:
        return {"detail": "Host já está na lixeira"}

    _deactivate_host_entity(host)
    db.commit()

    return {"detail": "Host movido para a lixeira com sucesso"}

@router.put("/host/update/{host_name}")
def update_host(host_name: str, data: HostUpdate, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    host = db.query(Host).filter(Host.name == host_name).first()
    resolved = None
    
    if not host:
        raise HTTPException(status_code=404, detail="Host não encontrado")
    
    if is_ip(data.address):
        resolved = reverse_dns(data.address)
    else:
        dns_result = resolve_dns_cached_sync(data.address, db)
        ips = extract_ips_from_dns_result(dns_result)

        if not ips:
            raise HTTPException(status_code=400, detail="Endereço inválido. ")
    
    if data.ports is None and data.port is None:
        ports = _host_ports(host)
    else:
        ports = _normalize_ports(data.ports, data.port)
    host.address = data.address
    _store_host_ports(host, ports)
    host.hostname_resolved = resolved

    selected_http = _resolve_http_input(data)
    _apply_http_policy(host, data.http_enabled, selected_http)

    if data.snmp_enabled is not None or getattr(data, "snmp_community", None) is not None:
        _apply_snmp_policy(host, data.snmp_enabled, getattr(data, "snmp_community", None))

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
        icmp_blocked_but_service_up = bool(getattr(host, "icmp_blocked_but_service_up", False))

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
            "icmp_blocked_but_service_up": icmp_blocked_but_service_up,
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

    return {
        "ping": calculate_availability_points(db, host.id, "ping"),
        "tcp": calculate_availability_points(db, host.id, "tcp"),
        "http": calculate_availability_points(db, host.id, "http")
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
        if user.locked_until and user.locked_until <= datetime.now():
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
                user.locked_until = datetime.now() + timedelta(minutes=1)
                db.commit()
                raise HTTPException(status_code=403, detail="Conta bloqueada após 5 tentativas. Aguarde 1 minuto.")
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
            "incident_type": parse_incident_type(i.reason),
            "reason_text": strip_incident_prefix(i.reason),
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
