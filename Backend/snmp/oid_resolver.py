"""
Backend SNMP - Motor de Auto-Resolucao e Auto-Correcao de OIDs
===============================================================================
Orquestrador inteligente de OIDs que implementa o fluxo de resiliencia:
Cache -> Teste -> Auto-Correcao por Banco -> Auto-Descoberta (SNMP WALK) -> Update Cache/DB -> Log.
"""

import logging
from typing import Optional, Dict, Any, Tuple

from Backend.snmp.snmp_client import get_snmp_value, walk_snmp, DEFAULT_SNMP_COMMUNITY
from Backend.snmp.oid_cache import get_cached_oids, set_cached_oid
from Backend.snmp.oid_database import KNOWN_OIDS_CPU, KNOWN_OIDS_RAM, KNOWN_OIDS_STORAGE, KNOWN_OIDS_NETWORK
from Backend.snmp.snmp_discovery import discover_device_oids

logger = logging.getLogger("netspot.snmp.resolver")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        val_str = str(value).strip()
        if not val_str:
            return None
        return float(val_str)
    except (TypeError, ValueError):
        return None


async def resolve_cpu_usage(host_id: int, ip: str, community: Optional[str]) -> Optional[float]:
    """
    Resolve a porcentagem de uso da CPU (0 a 100%) testando MIBs Linux (UCD-Idle) e Windows (hrProcessorLoad).
    """
    comm = (community or DEFAULT_SNMP_COMMUNITY).strip() or DEFAULT_SNMP_COMMUNITY

    # 1. Testar UCD-SNMP ssCpuIdle (Linux)
    idle_val = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.11.11.0"))
    if idle_val is not None:
        return round(max(0.0, min(100.0, 100.0 - idle_val)), 2)

    # 2. Testar HOST-RESOURCES hrProcessorLoad (Windows/Linux)
    cpu_cores = await walk_snmp(ip, comm, "1.3.6.1.2.1.25.3.3.1.2")
    if cpu_cores:
        core_vals = []
        for _, val in cpu_cores:
            flt = _to_float(val)
            if flt is not None and 0.0 <= flt <= 100.0:
                core_vals.append(flt)
        if core_vals:
            return round(sum(core_vals) / len(core_vals), 2)

    # 3. Executar SNMP WALK para caso especial
    discovered = await discover_device_oids(ip, comm)
    if "cpu_oid" in discovered:
        val = _to_float(await get_snmp_value(ip, comm, discovered["cpu_oid"]))
        if val is not None:
            if discovered.get("cpu_type") == "ucd_idle":
                return round(max(0.0, min(100.0, 100.0 - val)), 2)
            return round(max(0.0, min(100.0, val)), 2)

    return None


async def resolve_ram_usage(host_id: int, ip: str, community: Optional[str]) -> Optional[float]:
    """
    Resolve a porcentagem de uso de memoria RAM (0 a 100%) testando MIBs Linux (UCD-Memory) e Windows (Physical Memory).
    """
    comm = (community or DEFAULT_SNMP_COMMUNITY).strip() or DEFAULT_SNMP_COMMUNITY

    # 1. UCD-SNMP Memory (Linux)
    ram_tot = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.5.0"))
    ram_free = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.6.0"))
    ram_buf = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.14.0"))
    ram_cache = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.15.0"))

    if ram_tot is not None and ram_free is not None and ram_tot > 0:
        buf = ram_buf or 0.0
        cch = ram_cache or 0.0
        used = max(0.0, ram_tot - ram_free - buf - cch)
        return round((used / ram_tot) * 100.0, 2)

    # 2. HOST-RESOURCES Physical Memory (Windows)
    rows = await walk_snmp(ip, comm, "1.3.6.1.2.1.25.2.3.1.3")
    ram_idx = None
    for oid, descr in rows:
        clean = descr.strip('"').strip().lower()
        if "physical memory" in clean or "memória física" in clean:
            ram_idx = oid.split(".")[-1]
            break

    if ram_idx:
        tot_units = _to_float(await get_snmp_value(ip, comm, f"1.3.6.1.2.1.25.2.3.1.5.{ram_idx}"))
        used_units = _to_float(await get_snmp_value(ip, comm, f"1.3.6.1.2.1.25.2.3.1.6.{ram_idx}"))
        if tot_units is not None and used_units is not None and tot_units > 0:
            return round((used_units / tot_units) * 100.0, 2)

    return None
