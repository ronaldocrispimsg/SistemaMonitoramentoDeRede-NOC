"""
Backend SNMP - Motor de Auto-Descoberta via SNMP WALK
===============================================================================
Executa a descoberta profunda da arvore MIB do dispositivo quando nenhum OID
conhecido do catalogo responde, mapeando automaticamente novos OIDs de CPU, RAM,
Armazenamento e Redes.
"""

import logging
from typing import Dict, Any, Optional

from Backend.snmp.snmp_client import walk_snmp, get_snmp_value

logger = logging.getLogger("netspot.snmp.discovery")


async def discover_device_oids(ip: str, community: Optional[str]) -> Dict[str, Any]:
    """
    Executa varredura profunda no dispositivo e descobre OIDs funcionais.
    Retorna dicionario com os OIDs resolvidos para o dispositivo.
    """
    logger.info("[SNMP DISCOVERY] Iniciando auto-descoberta SNMP WALK para ip=%s", ip)
    discovered: Dict[str, Any] = {}

    # 1. Testar UCD-SNMP CPU Idle
    val_ucd_cpu = await get_snmp_value(ip, community, "1.3.6.1.4.1.2021.11.11.0")
    if val_ucd_cpu is not None:
        try:
            float(val_ucd_cpu)
            discovered["cpu_oid"] = "1.3.6.1.4.1.2021.11.11.0"
            discovered["cpu_type"] = "ucd_idle"
            logger.info("[SNMP DISCOVERY] CPU OID descoberto (UCD-Idle): %s", discovered["cpu_oid"])
        except ValueError:
            pass

    # 2. Se UCD falhar, tentar Host-Resources Processors
    if "cpu_oid" not in discovered:
        hr_cpus = await walk_snmp(ip, community, "1.3.6.1.2.1.25.3.3.1.2")
        if hr_cpus:
            discovered["cpu_oid"] = hr_cpus[0][0]
            discovered["cpu_type"] = "hr_load"
            logger.info("[SNMP DISCOVERY] CPU OID descoberto (HR-Processor): %s", discovered["cpu_oid"])

    # 3. Testar UCD-SNMP RAM
    ram_tot = await get_snmp_value(ip, community, "1.3.6.1.4.1.2021.4.5.0")
    ram_free = await get_snmp_value(ip, community, "1.3.6.1.4.1.2021.4.6.0")
    if ram_tot is not None and ram_free is not None:
        discovered["ram_type"] = "ucd"
        logger.info("[SNMP DISCOVERY] RAM MIB descoberta (UCD-SNMP Real Memory)")

    # 4. Descobrir indice de armazenamento (Disco "/") em Host-Resources
    storages = await walk_snmp(ip, community, "1.3.6.1.2.1.25.2.3.1.3")
    for oid, descr in storages:
        clean_descr = descr.strip('"')
        if clean_descr == "/" or clean_descr.lower().startswith("c:"):
            idx = oid.split(".")[-1]
            discovered["storage_index"] = idx
            logger.info("[SNMP DISCOVERY] Storage Index descoberto: index=%s (%s)", idx, clean_descr)
            break

    # 5. Descobrir melhor interface de rede
    ifaces_64 = await walk_snmp(ip, community, "1.3.6.1.2.1.31.1.1.1.1")
    candidates = []
    for oid, name_val in ifaces_64:
        if_name = name_val.strip('"')
        idx = oid.split(".")[-1]
        if if_name == "lo" or if_name.startswith("docker") or if_name.startswith("veth"):
            continue
        candidates.append((idx, if_name))

    preferred_prefixes = ("enp", "eth", "ens", "wlp", "wlan", "Ethernet")
    selected_iface_idx = None
    for prefix in preferred_prefixes:
        for idx, name in candidates:
            if name.startswith(prefix):
                selected_iface_idx = idx
                break
        if selected_iface_idx:
            break

    if not selected_iface_idx and candidates:
        selected_iface_idx = candidates[0][0]

    if selected_iface_idx:
        discovered["iface_index"] = selected_iface_idx
        logger.info("[SNMP DISCOVERY] Interface de Rede descoberta: index=%s", selected_iface_idx)

    logger.info("[SNMP DISCOVERY] Auto-descoberta finalizada para ip=%s | total_itens=%s", ip, len(discovered))
    return discovered
