"""
Backend Test Suite - Testes de Integracao das Rotas da API RESTful
===============================================================================
Testa os endpoints HTTP publicos e protegidos do FastAPI em Backend.routes.
"""

import pytest


@pytest.mark.asyncio
async def test_get_dashboard_summary(api_client):
    """Testa a rota GET /dashboard/summary."""
    response = await api_client.get("/dashboard/summary")
    # Se autenticacao for exigida retorna 401 ou 200 com resumo
    assert response.status_code in [200, 401]
    if response.status_code == 200:
        data = response.json()
        assert "total_hosts" in data or "hosts" in data or "summary" in data


@pytest.mark.asyncio
async def test_get_hosts_list(api_client):
    """Testa a rota GET /hosts/list."""
    response = await api_client.get("/hosts/list")
    assert response.status_code in [200, 401]
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_alerts_list(api_client):
    """Testa a rota GET /alerts/list."""
    response = await api_client.get("/alerts/list")
    assert response.status_code in [200, 401]
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_host_history_debian(api_client):
    """Testa a rota GET /host/history/Debian."""
    response = await api_client.get("/host/history/Debian")
    assert response.status_code in [200, 401, 404]
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, (dict, list))
