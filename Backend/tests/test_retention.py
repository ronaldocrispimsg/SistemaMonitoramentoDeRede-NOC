"""
Backend Test Suite - Testes da Politica de Retencao e Purga de Dados
===============================================================================
Testa a leitura de dias de retencao no .env, calculo de data de corte e
desativacao quando NETSPOT_RETENTION_DAYS=0.
"""

import os
import pytest
from Backend.services.retention_service import get_retention_days, purge_old_data


def test_get_retention_days_default():
    """Testa valor padrao de retencao quando nao configurado."""
    if "NETSPOT_RETENTION_DAYS" in os.environ:
        old_val = os.environ.pop("NETSPOT_RETENTION_DAYS")
    else:
        old_val = None

    try:
        assert get_retention_days() == 30
    finally:
        if old_val is not None:
            os.environ["NETSPOT_RETENTION_DAYS"] = old_val


def test_get_retention_days_custom():
    """Testa leitura de valor customizado no .env."""
    os.environ["NETSPOT_RETENTION_DAYS"] = "60"
    assert get_retention_days() == 60

    os.environ["NETSPOT_RETENTION_DAYS"] = "0"
    assert get_retention_days() == 0


@pytest.mark.asyncio
async def test_purge_old_data_disabled(async_db):
    """Testa se NETSPOT_RETENTION_DAYS=0 desativa a purga sem deletar registros."""
    os.environ["NETSPOT_RETENTION_DAYS"] = "0"
    res = await purge_old_data(async_db)

    assert res["status"] == "disabled"
    assert res["check_results"] == 0
    assert res["snmp_metrics"] == 0


@pytest.mark.asyncio
async def test_purge_old_data_enabled(async_db):
    """Testa a execucao da purga quando NETSPOT_RETENTION_DAYS > 0."""
    os.environ["NETSPOT_RETENTION_DAYS"] = "30"
    res = await purge_old_data(async_db)

    assert res["status"] == "enabled"
    assert res["retention_days"] == 30
    assert "cutoff_date" in res
