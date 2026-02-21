from urllib.parse import urlparse
import socket
import ipaddress

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
