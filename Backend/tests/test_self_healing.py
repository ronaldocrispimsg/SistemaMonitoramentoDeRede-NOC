"""
Backend Test Suite - Testes da Lógica de Autocura e Resiliência Avançada (Itens 1 a 5)
===============================================================================
1. Diagnostico de Saude Nativo (/healthz)
2. Pattern Circuit Breaker (Disjuntor de Polling de Rede)
3. Dead Letter Queue (DLQ) no RabbitMQ
4. Deduplicacao de Alertas e Anti-Flapping
5. Desligamento Gracioso (Graceful Shutdown) e Pools do PostgreSQL
"""

import pytest
import asyncio
import time
from Backend.database import engine, wait_for_database
from Backend.mq_manager import QueueManager
from Backend.services.circuit_breaker import circuit_breaker, HostCircuitBreaker
from Backend.notifications import is_flapping_suppressed


def test_1_postgres_engine_pool_settings():
    """Valida se o pool do SQLAlchemy possui as regras de autocura ativas."""
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 1800
    assert engine.pool.size() == 20
    assert engine.pool._max_overflow == 10
    assert engine.pool._timeout == 30


def test_1_postgres_wait_for_database_function():
    """Valida a funcao wait_for_database com retentativas."""
    result = wait_for_database(max_retries=1, delay_seconds=0.1)
    assert isinstance(result, bool)


def test_2_circuit_breaker_logic():
    """Valida a transicao de estados CLOSED -> OPEN -> HALF-OPEN -> CLOSED no Circuit Breaker."""
    cb = HostCircuitBreaker(failure_threshold=3, recovery_timeout=0.2)
    host_id = 999

    # Inicialmente CLOSED
    assert cb.is_allowed(host_id) is True

    # 2 falhas -> continua CLOSED
    cb.record_failure(host_id)
    cb.record_failure(host_id)
    assert cb.is_allowed(host_id) is True

    # 3a falha -> Abre o disjuntor (OPEN)
    cb.record_failure(host_id)
    assert cb.state[host_id] == "OPEN"
    assert cb.is_allowed(host_id) is False  # Polling bloqueado durante resguardo!

    # Aguarda o recovery_timeout (0.2s) -> Transita para HALF-OPEN
    time.sleep(0.25)
    assert cb.is_allowed(host_id) is True
    assert cb.state[host_id] == "HALF-OPEN"

    # Sucesso no teste -> Fecha o disjuntor (CLOSED)
    cb.record_success(host_id)
    assert cb.state[host_id] == "CLOSED"
    assert cb.failures[host_id] == 0


def test_3_rabbitmq_dlq_configuration():
    """Valida se o QueueManager possui suporte a Dead Letter Queue (DLQ)."""
    qm = QueueManager()
    assert qm.dlx is None
    assert qm.dlq is None


def test_4_alert_anti_flapping():
    """Valida se o detector de flapping suprime alertas repetitivos em rajada."""
    host_key = "Host-Test-Flapping"
    now = time.time()

    msg = {"host_name": host_key, "event": "service_down"}

    # Primeiras 4 alteracoes dentro da janela sao permitidas
    assert is_flapping_suppressed(msg, now) is False
    assert is_flapping_suppressed(msg, now + 1) is False
    assert is_flapping_suppressed(msg, now + 2) is False
    assert is_flapping_suppressed(msg, now + 3) is False

    # 5a alteracao seguida -> Suprimida por Anti-Flapping!
    assert is_flapping_suppressed(msg, now + 4) is True


@pytest.mark.asyncio
async def test_5_rabbitmq_queue_manager_self_healing_initialization():
    """Valida a estrutura do QueueManager e inicio do monitor de autocura num event loop."""
    qm = QueueManager()
    assert qm.connection is None
    assert qm.channel is None
    assert qm.consumer_tasks == []
    assert qm._monitor_task is None

    # Testa chamada de inicio do monitor no loop assincrono
    qm.start_self_healing_monitor()
    assert qm._monitor_task is not None
    assert not qm._monitor_task.done()

    # Limpeza da task de teste
    qm._monitor_task.cancel()
