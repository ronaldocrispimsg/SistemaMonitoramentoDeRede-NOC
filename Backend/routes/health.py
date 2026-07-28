"""
Backend Routes - Healthcheck Endpoint (/healthz)
===============================================================================
Fornece diagnostico rapido de saude dos subsistemas (PostgreSQL e RabbitMQ)
para integracao com Docker Healthcheck, Kubernetes Liveness Probes e SRE.
"""

import logging
from fastapi import APIRouter, Response, status
from sqlalchemy import text
from Backend.database import AsyncSessionLocal
from Backend.mq_manager import mq_manager

logger = logging.getLogger("netspot.health")
router = APIRouter(tags=["Health"])


@router.get("/healthz")
async def health_check(response: Response):
    """
    Endpoint de diagnostico de saude do sistema.
    Retorna HTTP 200 OK se DB e RabbitMQ estiverem ativos,
    ou HTTP 503 Service Unavailable caso algum componente falhe.
    """
    db_ok = False
    mq_ok = False

    # 1. Checa PostgreSQL
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        logger.warning(f"[HEALTHCHECK] Falha ao testar PostgreSQL: {e}")
        db_ok = False

    # 2. Checa RabbitMQ
    try:
        if mq_manager.connection and not mq_manager.connection.is_closed:
            if mq_manager.channel and not mq_manager.channel.is_closed:
                mq_ok = True
    except Exception as e:
        logger.warning(f"[HEALTHCHECK] Falha ao testar RabbitMQ: {e}")
        mq_ok = False

    is_healthy = db_ok and mq_ok

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "HEALTHY" if is_healthy else "UNHEALTHY",
        "database": "UP" if db_ok else "DOWN",
        "rabbitmq": "UP" if mq_ok else "DOWN"
    }
