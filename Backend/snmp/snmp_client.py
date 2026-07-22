"""
Backend SNMP - Cliente PySNMP Assincrono (Cross-Platform)
===============================================================================
Cliente wrapper assincrono puro PySNMP para execucao de GET, WALK e teste
de conexao SNMP v1/v2c. Compativel com Windows 10/11 e Linux (Debian/Ubuntu).
"""

import logging
from typing import Optional, List, Tuple, Any
from pathlib import Path

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
    next_cmd,
)

logger = logging.getLogger("netspot.snmp.client")

SNMP_TIMEOUT_SECONDS = 2
SNMP_RETRIES = 2
DEFAULT_SNMP_COMMUNITY = "netspot"


async def get_snmp_value(ip: str, community: Optional[str], oid: str) -> Optional[Any]:
    """
    Executa uma consulta GET SNMP v2c para um OID especifico.
    Se a community for None ou vazia, assume 'netspot'.
    """
    comm_str = (community or DEFAULT_SNMP_COMMUNITY).strip() or DEFAULT_SNMP_COMMUNITY
    snmp_engine = SnmpEngine()
    try:
        error_indication, error_status, error_index, var_binds = await get_cmd(
            snmp_engine,
            CommunityData(comm_str, mpModel=1),
            await UdpTransportTarget.create(
                (ip, 161),
                timeout=SNMP_TIMEOUT_SECONDS,
                retries=SNMP_RETRIES,
            ),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )

        if error_indication:
            logger.debug("SNMP GET indication error | ip=%s | oid=%s | err=%s", ip, oid, error_indication)
            return None

        if error_status:
            logger.debug(
                "SNMP GET status error | ip=%s | oid=%s | err=%s",
                ip,
                oid,
                error_status.prettyPrint(),
            )
            return None

        if not var_binds or len(var_binds) == 0:
            return None

        val = var_binds[0][1]
        val_str = str(val)
        if "No Such Object" in val_str or "No Such Instance" in val_str:
            return None

        return val
    except Exception as e:
        logger.debug("SNMP GET exception | ip=%s | oid=%s | err=%s", ip, oid, e)
        return None
    finally:
        snmp_engine.close_dispatcher()


async def walk_snmp(ip: str, community: Optional[str], root_oid: str) -> List[Tuple[str, str]]:
    """
    Executa um SNMP WALK a partir da raiz root_oid.
    Retorna uma lista de tuplas (oid_name, oid_value).
    """
    comm_str = (community or DEFAULT_SNMP_COMMUNITY).strip() or DEFAULT_SNMP_COMMUNITY
    snmp_engine = SnmpEngine()
    results: List[Tuple[str, str]] = []
    current_oid = root_oid

    try:
        while True:
            error_indication, error_status, error_index, var_binds = await next_cmd(
                snmp_engine,
                CommunityData(comm_str, mpModel=1),
                await UdpTransportTarget.create(
                    (ip, 161),
                    timeout=SNMP_TIMEOUT_SECONDS,
                    retries=SNMP_RETRIES,
                ),
                ContextData(),
                ObjectType(ObjectIdentity(current_oid)),
                lexicographicMode=False,
            )

            if error_indication or error_status or not var_binds:
                break

            reached_end = False
            for var_bind in var_binds:
                oid_name = str(var_bind[0])
                oid_val = str(var_bind[1])

                if not oid_name.startswith(f"{root_oid}."):
                    reached_end = True
                    break

                if "No Such" in oid_val:
                    continue

                results.append((oid_name, oid_val))
                current_oid = oid_name

            if reached_end:
                break
    except Exception as e:
        logger.debug("SNMP WALK exception | ip=%s | root_oid=%s | err=%s", ip, root_oid, e)
    finally:
        snmp_engine.close_dispatcher()

    return results


async def test_snmp_connection(ip: str, community: Optional[str]) -> bool:
    """
    Testa se o dispositivo responde a SNMP v2c usando a OID sysUpTimeInstance.
    """
    val = await get_snmp_value(ip, community, "1.3.6.1.2.1.1.3.0")
    if val is not None:
        return True
    val_sys = await get_snmp_value(ip, community, "1.3.6.1.2.1.1.1.0")
    return val_sys is not None
