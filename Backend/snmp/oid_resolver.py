"""
Backend SNMP - Motor de Auto-Resolucao e Auto-Correcao de OIDs
===============================================================================
Orquestrador inteligente de OIDs que implementa o fluxo de resiliencia:
Cache -> Teste -> Auto-Correcao por Banco -> Auto-Descoberta (SNMP WALK) -> Update Cache/DB -> Log.
"""

import logging
from typing import Optional, Dict, Any

from Backend.snmp.snmp_client import get_snmp_value, test_snmp_connection, DEFAULT_SNMP_COMMUNITY
from Backend.snmp.oid_cache import get_cached_oids, set_cached_oid, set_cached_oids_bulk
from Backend.snmp.oid_database import KNOWN_OIDS_CPU, KNOWN_OIDS_RAM, KNOWN_OIDS_HOSTNAME, KNOWN_OIDS_UPTIME
from Backend.snmp.snmp_discovery import discover_device_oids

logger = logging.getLogger("netspot.snmp.resolver")


async def resolve_cpu_oid(host_id: int, ip: str, community: Optional[str]) -> Optional[str]:
    """
    Resolve e auto-corrige o OID operacional de CPU para o host especifico.
    """
    comm_str = (community or DEFAULT_SNMP_COMMUNITY).strip() or DEFAULT_SNMP_COMMUNITY

    # 1. Consultar Cache
    cached = get_cached_oids(host_id)
    if cached and "cpu_oid" in cached:
        active_oid = cached["cpu_oid"]
        val = await get_snmp_value(ip, comm_str, active_oid)
        if val is not None:
            return active_oid

        logger.info("[INFO] OID CPU em cache (%s) para host_id=%s falhou. Procurando alternativa...", active_oid, host_id)

    # 2. Testar alternativas do Banco de OIDs
    logger.info("[INFO] Testando alternativas do banco de OIDs para CPU (host_id=%s, ip=%s)...", host_id, ip)
    for entry in KNOWN_OIDS_CPU:
        candidate_oid = entry["oid"]
        val = await get_snmp_value(ip, comm_str, candidate_oid)
        if val is not None:
            logger.info("[INFO] Alternativa encontrada para CPU: %s. Atualizando cache...", candidate_oid)
            set_cached_oid(host_id, "cpu_oid", candidate_oid)
            return candidate_oid

    # 3. Executar SNMP WALK se nenhuma alternativa funcionou
    logger.info("[INFO] Nenhuma alternativa de CPU respondeu. Executando SNMP WALK...")
    discovered = await discover_device_oids(ip, comm_str)
    if "cpu_oid" in discovered:
        new_oid = discovered["cpu_oid"]
        logger.info("[INFO] Novo OID de CPU descoberto via WALK: %s. Salvando...", new_oid)
        set_cached_oid(host_id, "cpu_oid", new_oid)
        return new_oid

    logger.warning("[ERROR] Nao foi possivel localizar OID de CPU valido para host_id=%s (ip=%s)", host_id, ip)
    return None
