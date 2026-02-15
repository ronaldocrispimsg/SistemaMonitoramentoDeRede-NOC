import subprocess
import time
import socket
import json
from datetime import datetime, timedelta
from Backend.models import DNSCache

def resolve_dns_cached(address: str, db):
    # se já for IP → retorna
    try:
        socket.inet_aton(address)
        return [address]
    except:
        pass

    # procura cache

    record = db.query(DNSCache).filter(
        DNSCache.hostname == address
    ).first()

    now = datetime.utcnow()

    # cache válido

    if record and record.expires_time > now:
        return json.loads(record.ip_list)

    # resolve DNS real

    try:
        info = socket.getaddrinfo(address, None)
        ips = list({item[4][0] for item in info})
    except Exception:
        return []

    # TTL fixo (por enquanto)

    ttl = 300
    expires = now + timedelta(seconds=ttl)

    #  salva cache

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

    db.commit()

    return ips

def ping_host(ip: str, count: int = 1, timeout: int = 2):
    
    cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]

    start = time.time()

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        latency = round((time.time() - start) * 1000, 2)

        if result.returncode == 0:
            return {
                "success": True,
                "error": None,
                "latency": latency
            }
        else:
            return {
                "success": False,
                "error": result.stderr.decode()[:120],  # Limita o erro a 120 caracteres
                "latency": None
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
        conexao = socket.socket(familia_ips, socket.SOCK_STREAM)
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