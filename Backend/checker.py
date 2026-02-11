import subprocess
import time
import socket

def ping_host(address: str, count: int = 1, timeout: int = 2):
    try:
        start = time.time()
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), address],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        latency = round((time.time() - start) * 1000, 2)

        return {
            "success": result.returncode == 0,
            "latency": latency if result.returncode == 0 else None
        }

    except Exception:
        return {
            "success": False,
            "latency": None
        }

def tcp_check(address: str, port: int, timeout: int = 5):
    start = time.time()
    conexao = None
    
    try:
        conexao = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conexao.settimeout(timeout)
        conexao.connect((address, port))
        tcp_latency = round((time.time() - start) * 1000, 2)
        return {
                "success": True,
                "error": None,
                "tcp_latency": tcp_latency
        }
        
    except socket.timeout:
        tcp_latency = round((time.time() - start) * 1000, 2)
        return {
                "success": False,
                "error": "timeout",
                "tcp_latency": tcp_latency
        }
    
    except socket.error as e:
        tcp_latency = round((time.time() - start) * 1000, 2)
        return {
                "success": False,
                "error": str(e),
                "tcp_latency": tcp_latency
        }
    
    finally:
        if conexao:
            conexao.close()