"""
Backend Test Suite - Fixtures Globais do Pytest
===============================================================================
Este modulo fornece fixtures assincronas reutilizaveis para sessao de banco
de dados, cliente HTTP da API FastAPI e instantes de teste.
"""

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from Backend.main import app
from Backend.database import AsyncSessionLocal


@pytest.fixture(scope="session")
def event_loop():
    """Cria e fornece um event loop para toda a sessao de testes assincronos."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def async_db():
    """Fixture de sessao de banco de dados assincrona para testes."""
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def api_client():
    """Fixture de cliente HTTP assincrono (httpx) conectado a app FastAPI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
