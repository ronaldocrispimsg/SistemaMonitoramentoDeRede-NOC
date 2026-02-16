import subprocess
import time
import socket
import json
import re
import dns.resolver
from datetime import datetime, timedelta
from Backend.models import DNSCache

def resolve_dns_real(address):
    try:
        answers = dns.resolver.resolve(address, "A")
    except:
        try:
            answers = dns.resolver.resolve(address, "AAAA")
        except:
            return [], None

    ips = [r.to_text() for r in answers]

    # TTL real (mínimo é mais seguro)
    ttl = answers.rrset.ttl

    return ips, ttl

def resolve_dns_cached(address: str, db):

    # ---------- já é IP ----------
    try:
        socket.inet_pton(socket.AF_INET, address)
        return [address], None, None
    except:
        pass

    try:
        socket.inet_pton(socket.AF_INET6, address)
        return [address], None, None
    except:
        pass

    # ---------- cache ----------
    record = db.query(DNSCache).filter(
        DNSCache.hostname == address
    ).first()

    now = datetime.utcnow()
    ttl_remaining = 0

    if record:
        ttl_remaining = (record.expires_time - now).total_seconds()

        # cache válido (com margem)
        if ttl_remaining > record.ttl * 0.1:
            return json.loads(record.ip_list), record.ttl, int(ttl_remaining)

    # resolve DNS real
    ips, ttl = resolve_dns_real(address)

    if not ips and record:
        return json.loads(record.ip_list), record.ttl, int(ttl_remaining)
    elif not ips:
        return [], None, None

    ttl = ttl or 60

    expires = now + timedelta(seconds=ttl)

    # ---------- salvar ----------
    if record:
        record.ip_list = json.dumps(ips)
        record.ttl = ttl
        record.resolved_time = now
        record.expires_time = expires
    else:
        record = DNSCache(
            hostname=address,
            ip_list=json.dumps(ips),
            ttl=ttl,
            resolved_time=now,
            expires_time=expires
        )
        db.add(record)

    db.flush()

    return ips, ttl, ttl


def ping_host(ip: str, count: int = 1, timeout: int = 5, max_ms=5000):

    if ":" in ip:
        cmd = ["ping", "-6", "-c", str(count), "-W", str(timeout), ip]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # falhou totalmente
        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr[:120],
                "latency": None
            }

        # extrair RTT real
        match = re.search(r"time[=<]([\d\.]+)\s*ms", result.stdout)

        if not match:
            return {
                "success": False,
                "error": "RTT não encontrado",
                "latency": None
            }

        latency = float(match.group(1))

        # respondeu mas lento demais
        if latency > max_ms:
            return {
                "success": True,
                "error": "high latency",
                "latency": latency
            }

        return {
            "success": True,
            "error": None,
            "latency": latency
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "latency": None
        }

def tcp_check(ip: str, port: int, timeout: int = 5):
       
    start = time.time()

    try:
        familia_ips = socket.AF_INET6 if ":" in ip else socket.AF_INET
        with socket.socket(familia_ips, socket.SOCK_STREAM) as conexao:
            conexao.settimeout(timeout)
            conexao.connect((ip, port))

        latency = round((time.time() - start) * 1000, 2)

        return {
                "success": True,
                "error": None,
                "latency": latency
        }
        
    except Exception as e:
        return {
                "success": False,
                "error": str(e),
                "latency": None
        }
    
    finally:
        try:
             conexao.close()
        except:
             pass