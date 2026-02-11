import subprocess
import time
import socket

def resolve_dns(address: str):
    try:
        ip = socket.gethostbyname(address)
        return {
            "success": True,
            "ip": ip
        }
    except socket.gaierror as e:
        return {
            "success": False,
            "error": str(e),
            "ip": None
        }

def ping_host(address: str, count: int = 1, timeout: int = 2):
    
    dns = resolve_dns(address)
    if not dns["success"]:
        return {
            "success": False,
            "latency": None,
            "error": dns["error"]
        }
    
    ip = dns["ip"]

    cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]

    start = time.time() 
    result = subprocess.run(cmd, stdout=subprocess.PIPE)

    latency = round((time.time() - start) * 1000, 2)

    return {
        "success": True if result.returncode == 0 else False,
        "latency": latency,
        "resolved_ip": ip
    }

def tcp_check(address: str, port: int, timeout: int = 5):
       
    dns = resolve_dns(address)
    if not dns["success"]:
        return {
            "success": False,
            "error": dns["error"],
            "latency": None
        }
    
    ip = dns["ip"]

    conexao = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conexao.settimeout(timeout)
    start = time.time()

    try:
        conexao.connect((ip, port))
        latency = round((time.time() - start) * 1000, 2)
        return {
                "success": True,
                "latency": latency,
                "resolved_ip": ip
        }
        
    except Exception as e:
        latency = round((time.time() - start) * 1000, 2)
        return {
                "success": False,
                "error": str(e),
                "latency": latency,
                "resolved_ip": ip
        }
    
    finally:
        if conexao:
            conexao.close()