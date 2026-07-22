"""
Backend Services - Retencao e Purga Automatica de Dados Historicos
===============================================================================
Este modulo executa a limpeza periodica de registros antigos de checagens,
metricas SNMP, alertas resolvidos e incidentes encerrados com base no limite
configurado em NETSPOT_RETENTION_DAYS (padrao: 30 dias).
Definir NETSPOT_RETENTION_DAYS=0 desativa completamente a limpeza.
"""

import os
import logging
from datetime import datetime, timedelta
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from Backend.models import CheckResult, SNMPMetric, Alert, Incident

logger = logging.getLogger("netspot.retention")


def get_retention_days() -> int:
    """
    Retorna o numero de dias de retencao configurado no .env.
    Se for <= 0, a limpeza automatica e DESATIVADA.
    """
    try:
        val = int(os.getenv("NETSPOT_RETENTION_DAYS", "30").strip())
        return val
    except Exception:
        return 30


async def purge_old_data(db: AsyncSession) -> dict:
    """
    Remove registros do banco de dados com data de criacao anterior ao limite de retencao.
    Se NETSPOT_RETENTION_DAYS <= 0, a purga e desativada.
    """
    days = get_retention_days()

    if days <= 0:
        logger.info("[RETENCAO] Limpeza automatica de historico desativada (NETSPOT_RETENTION_DAYS <= 0).")
        return {
            "status": "disabled",
            "retention_days": days,
            "cutoff_date": None,
            "check_results": 0,
            "snmp_metrics": 0,
            "alerts": 0,
            "incidents": 0
        }

    cutoff = datetime.utcnow() - timedelta(days=days)

    purged = {
        "status": "enabled",
        "retention_days": days,
        "cutoff_date": cutoff.isoformat(),
        "check_results": 0,
        "snmp_metrics": 0,
        "alerts": 0,
        "incidents": 0
    }

    try:
        # 1. Purgar CheckResult antigos
        res_checks = await db.execute(
            delete(CheckResult).where(CheckResult.created_at < cutoff)
        )
        purged["check_results"] = res_checks.rowcount or 0

        # 2. Purgar SNMPMetric antigos
        res_snmp = await db.execute(
            delete(SNMPMetric).where(SNMPMetric.timestamp < cutoff)
        )
        purged["snmp_metrics"] = res_snmp.rowcount or 0

        # 3. Purgar Alertas antigos encerrados
        res_alerts = await db.execute(
            delete(Alert).where(Alert.timestamp < cutoff)
        )
        purged["alerts"] = res_alerts.rowcount or 0

        # 4. Purgar Incidentes encerrados antigos
        res_incidents = await db.execute(
            delete(Incident).where(
                Incident.opened_at < cutoff,
                Incident.closed_at.isnot(None)
            )
        )
        purged["incidents"] = res_incidents.rowcount or 0

        await db.commit()

        logger.info(
            f"[RETENCAO] Limpeza concluida ({days} dias): "
            f"{purged['check_results']} checks, {purged['snmp_metrics']} snmp, "
            f"{purged['alerts']} alertas, {purged['incidents']} incidentes removidos."
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"[RETENCAO] Erro ao purgar dados antigos: {e}")

    return purged
