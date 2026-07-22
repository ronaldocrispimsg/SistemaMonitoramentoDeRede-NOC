"""
Backend SNMP - Catalogo Completo de OIDs e MIBs Multivendor
===============================================================================
Este modulo mantem o catalogo expansivel de OIDs conhecidos para CPU, RAM,
Disco, Rede, Uptime e Hostname, cobrindo padroes Linux (UCD-SNMP, Host-Resources),
Windows (HOST-RESOURCES-MIB), Cisco, Mikrotik, FreeBSD e MIB-II generica.
"""

from typing import Dict, List, Any

# OIDs de CPU por fabricante/MIB
KNOWN_OIDS_CPU: List[Dict[str, str]] = [
    {
        "oid": "1.3.6.1.4.1.2021.11.11.0",
        "type": "ucd_cpu_idle",
        "descr": "UCD-SNMP ssCpuIdle (% idle, usage = 100 - idle)"
    },
    {
        "oid": "1.3.6.1.2.1.25.3.3.1.2",
        "type": "hr_processor_load",
        "descr": "HOST-RESOURCES-MIB hrProcessorLoad (Media por nucleos Windows/Linux)"
    },
    {
        "oid": "1.3.6.1.4.1.2021.11.9.0",
        "type": "ucd_cpu_user",
        "descr": "UCD-SNMP ssCpuUser"
    },
    {
        "oid": "1.3.6.1.4.1.9.9.109.1.1.1.1.5",
        "type": "cisco_cpu",
        "descr": "Cisco cpmCPUTotal5rev"
    },
    {
        "oid": "1.3.6.1.4.1.14988.1.1.1.3.0",
        "type": "mikrotik_cpu",
        "descr": "Mikrotik RouterOS mtxRxCpuLoad"
    }
]

# OIDs de RAM por fabricante/MIB
KNOWN_OIDS_RAM: List[Dict[str, Any]] = [
    {
        "total_oid": "1.3.6.1.4.1.2021.4.5.0",
        "free_oid": "1.3.6.1.4.1.2021.4.6.0",
        "buffer_oid": "1.3.6.1.4.1.2021.4.14.0",
        "cache_oid": "1.3.6.1.4.1.2021.4.15.0",
        "type": "ucd_memory",
        "descr": "UCD-SNMP Memory (Linux Real Memory)"
    },
    {
        "descr_oid": "1.3.6.1.2.1.25.2.3.1.3",
        "size_oid": "1.3.6.1.2.1.25.2.3.1.5",
        "used_oid": "1.3.6.1.2.1.25.2.3.1.6",
        "match_keywords": ["physical memory", "memória física", "ram"],
        "type": "hr_memory",
        "descr": "HOST-RESOURCES-MIB Physical Memory (Windows/Linux)"
    },
    {
        "used_oid": "1.3.6.1.4.1.9.9.48.1.1.1.5.1",
        "free_oid": "1.3.6.1.4.1.9.9.48.1.1.1.6.1",
        "type": "cisco_memory",
        "descr": "Cisco Memory Pool"
    }
]

# OIDs de Armazenamento / Disco
KNOWN_OIDS_STORAGE: Dict[str, Any] = {
    "descr_oid": "1.3.6.1.2.1.25.2.3.1.3",
    "size_oid": "1.3.6.1.2.1.25.2.3.1.5",
    "used_oid": "1.3.6.1.2.1.25.2.3.1.6",
    "mount_keywords": ["/", "c:", "c:\\", "fixed disk"],
    "descr": "HOST-RESOURCES-MIB hrStorageTable"
}

# OIDs de Interfaces de Rede
KNOWN_OIDS_NETWORK: Dict[str, Any] = {
    "if_oper_status": "1.3.6.1.2.1.2.2.1.8",
    "if_name_64": "1.3.6.1.2.1.31.1.1.1.1",
    "if_descr_32": "1.3.6.1.2.1.2.2.1.2",
    "in_octets_64": "1.3.6.1.2.1.31.1.1.1.6",
    "out_octets_64": "1.3.6.1.2.1.31.1.1.1.10",
    "in_octets_32": "1.3.6.1.2.1.2.2.1.10",
    "out_octets_32": "1.3.6.1.2.1.2.2.1.16",
    "descr": "IF-MIB Network Interfaces (64-bit HC & 32-bit Standard)"
}

# OIDs Globais de Sistema
KNOWN_OIDS_UPTIME: List[str] = [
    "1.3.6.1.2.1.1.3.0",        # sysUpTimeInstance
    "1.3.6.1.2.1.25.1.1.0"      # hrSystemUptime
]

KNOWN_OIDS_HOSTNAME: List[str] = [
    "1.3.6.1.2.1.1.5.0",        # sysName
    "1.3.6.1.2.1.1.1.0"         # sysDescr
]
