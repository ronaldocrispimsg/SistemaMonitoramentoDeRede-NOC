"""
Backend Test Suite - Testes Unitarios de Métricas (Saúde, SLA, Jitter, Tendência)
===============================================================================
Testa todas as funcoes de calculo estatistico do NOC Lite localizadas em Backend.metrics.
"""

import pytest
from Backend.metrics import (
    compute_health,
    classify_trend,
    max_severity,
)


def test_compute_health_perfect():
    """Testa score de saude perfeito (100% de sucesso e latencia baixa)."""
    ping_res = {"success": True, "latency": 15.0}
    tcp_res = {"success": True, "latency": 12.0}
    http_res = {"success": True, "latency": 100.0, "status_code": 200}

    score, status = compute_health(ping_res, tcp_res, http_res)
    assert score == 100
    assert status == "HEALTHY"


def test_compute_health_failure():
    """Testa score de saude com falha generalizada."""
    ping_res = {"success": False, "latency": None}
    tcp_res = {"success": False, "latency": None}
    http_res = {"success": False, "latency": None, "status_code": 500}

    score, status = compute_health(ping_res, tcp_res, http_res)
    assert score < 50
    assert status in ["CRITICAL", "DEGRADED", "DOWN"]


def test_classify_trend():
    """Testa classificacao de tendencia de latencia por inclinacao (slope)."""
    assert classify_trend(0.0) == "STABLE"
    assert classify_trend(20.0) == "DEGRADING"
    assert classify_trend(50.0) == "FAST_DEGRADING"
    assert classify_trend(-20.0) == "IMPROVING"


def test_max_severity():
    """Testa determinacao do nivel maximo de severidade."""
    assert max_severity("HEALTHY", "CRITICAL") == "CRITICAL"
    assert max_severity("WARNING", "HEALTHY") == "WARNING"
    assert max_severity("CRITICAL", "WARNING") == "CRITICAL"
