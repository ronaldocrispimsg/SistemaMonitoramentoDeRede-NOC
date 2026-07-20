import asyncio
import platform
import re
import json
import time
import dns.asyncresolver
import dns.resolver
import httpx
import socket
from urllib.parse import urlparse
from datetime import datetime, timedelta
from sqlalchemy import select
from Backend.models import DNSCache

def resolve_dns_real_sync(address):
    try:
        answers = dns.resolver.resolve(address, "A")
    except:
        try:
            answers = dns.resolver.resolve(address, "AAAA")
        except:
            return [], None

    ips = [r.to_text() for r in answers]
    ttl = answers.rrset.ttl
    return ips, ttl

def resolve_dns_cached_sync(address: str, db):
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
    record = db.query(DNSCache).filter(DNSCache.hostname == address).first()

    now = datetime.utcnow()
    ttl_remaining = 0

    if record:
        ttl_remaining = (record.expires_time - now).total_seconds()

        # cache válido (com margem)
        if ttl_remaining > record.ttl * 0.1:
            return json.loads(record.ip_list), record.ttl, int(ttl_remaining)

    # resolve DNS real
    ips, ttl = resolve_dns_real_sync(address)

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

async def resolve_dns_real(address):
    try:
        answers = await dns.asyncresolver.resolve(address, "A")
    except:
        try:
            answers = await dns.asyncresolver.resolve(address, "AAAA")
        except:
            return [], None

    ips = [r.to_text() for r in answers]
    ttl = answers.rrset.ttl
    return ips, ttl

async def resolve_dns_cached(address: str, db):
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
    stmt = select(DNSCache).filter(DNSCache.hostname == address)
    result = await db.execute(stmt)
    record = result.scalars().first()

    now = datetime.utcnow()
    ttl_remaining = 0

    if record:
        ttl_remaining = (record.expires_time - now).total_seconds()

        # cache válido (com margem)
        if ttl_remaining > record.ttl * 0.1:
            return json.loads(record.ip_list), record.ttl, int(ttl_remaining)

    # resolve DNS real
    ips, ttl = await resolve_dns_real(address)

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

    await db.flush()

    return ips, ttl, ttl

async def ping_host(ip: str, count: int = 3, timeout: int = 5, max_ms=5000):
    is_windows = platform.system().lower() == "windows"
    
    if is_windows:
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), ip]
    else:
        if ":" in ip:
            cmd = ["ping", "-6", "-c", str(count), "-W", str(timeout), ip]
        else:
            cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        stdout_str = stdout.decode('utf-8', errors='ignore')
        stderr_str = stderr.decode('utf-8', errors='ignore')

        if proc.returncode != 0:
            return {
                "success": False,
                "error": stderr_str[:120] if stderr_str else "Host inalcançável",
                "latency": None
            }

        match = re.search(r"time[=<]([\d\.]+)\s*ms", stdout_str)

        if not match:
            return {
                "success": False,
                "error": "RTT não encontrado",
                "latency": None
            }

        latency = float(match.group(1))

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

async def tcp_check(ip: str, port: int, timeout: int = 5):
    start = time.time()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass

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

async def _http_attempt(client: httpx.AsyncClient, url: str, timeout=1):
    start = time.time()
    try:
        r = await client.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "NOC-Lite-Monitor"}
        )
        latency = round((time.time() - start) * 1000, 2)
        status_code = r.status_code
        success = 200 <= status_code < 400
        return {
            "success": success,
            "latency": latency,
            "status_code": status_code,
            "error": None
        }
    except httpx.TimeoutException:
        return {"success": False, "latency": None, "status_code": None, "error": "timeout"}
    except httpx.RequestError as e:
        return {"success": False, "latency": None, "status_code": None, "error": "connection_error"}
    except Exception as e:
        return {"success": False, "latency": None, "status_code": None, "error": str(e)}

async def _http_with_retries(client: httpx.AsyncClient, url: str, retries: int = 3, timeout: int = 1):
    last_result = None
    for _ in range(max(1, retries)):
        result = await _http_attempt(client, url, timeout=timeout)
        last_result = result
        if result.get("success"):
            return result
    return last_result or {"success": False, "latency": None, "status_code": None, "error": "http_failed"}

async def http_check(url: str, timeout=1, retries=3):
    parsed = urlparse(url if "://" in url else f"//{url}")
    has_explicit_scheme = parsed.scheme in ("http", "https")

    async with httpx.AsyncClient(verify=False) as client:
        if has_explicit_scheme:
            result = await _http_with_retries(client, url, retries=retries, timeout=timeout)
            result["protocol"] = parsed.scheme
            result["http_latency"] = result.get("latency") if parsed.scheme == "http" and result.get("success") else None
            result["https_latency"] = result.get("latency") if parsed.scheme == "https" and result.get("success") else None
            return result

        base = url.strip()
        https_url = f"https://{base}"
        http_url = f"http://{base}"

        https_result = await _http_with_retries(client, https_url, retries=retries, timeout=timeout)
        if https_result.get("success"):
            https_result["protocol"] = "https"
            https_result["https_latency"] = https_result.get("latency")
            https_result["http_latency"] = None
            return https_result

        http_result = await _http_with_retries(client, http_url, retries=retries, timeout=timeout)
        http_result["protocol"] = "http"
        http_result["https_latency"] = https_result.get("latency") if https_result.get("success") else None
        http_result["http_latency"] = http_result.get("latency") if http_result.get("success") else None
        return http_result
