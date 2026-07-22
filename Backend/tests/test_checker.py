"""
Backend Test Suite - Testes dos Checadores de Rede (Ping, TCP, HTTP, DNS)
===============================================================================
Testa o comportamento assincrono dos checadores de protocolo em Backend.checker.
"""

import pytest
from Backend.checker import (
    resolve_dns_real_sync,
    resolve_dns_real,
    ping_host,
    tcp_check,
    http_check,
)


def test_resolve_dns_real_sync_google():
    """Testa a resolucao sincrona de DNS para um dominio publico."""
    ips, ttl = resolve_dns_real_sync("google.com")
    assert isinstance(ips, list)
    assert len(ips) > 0


@pytest.mark.asyncio
async def test_resolve_dns_real_async_google():
    """Testa a resolucao assincrona de DNS para um dominio publico."""
    ips, ttl = await resolve_dns_real("google.com")
    assert isinstance(ips, list)
    assert len(ips) > 0


@pytest.mark.asyncio
async def test_ping_host_loopback():
    """Testa a checagem de Ping assincrona para o IP de loopback (127.0.0.1)."""
    res = await ping_host("127.0.0.1", count=1, timeout=2)
    assert isinstance(res, dict)
    assert "success" in res
    assert "latency" in res


@pytest.mark.asyncio
async def test_tcp_check_invalid_port():
    """Testa a checagem de porta TCP para uma porta fechada/invalida."""
    res = await tcp_check("127.0.0.1", 59999, timeout=1)
    assert isinstance(res, dict)
    assert res["success"] is False
    assert res["latency"] is None


@pytest.mark.asyncio
async def test_http_check_public_url():
    """Testa a checagem HTTP assincrona para uma URL publica."""
    res = await http_check("https://www.google.com", timeout=5, retries=1)
    assert isinstance(res, dict)
    assert res["success"] is True
    assert res["status_code"] == 200
    assert isinstance(res["latency"], float)
