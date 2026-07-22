"""
Backend SNMP - Catalogo de OIDs Conhecidos
===============================================================================
Este modulo mantem o catalogo expansivel de OIDs conhecidos para CPU, RAM,
Disco, Rede, Uptime e Hostname, cobrindo padroes Linux (UCD-SNMP, Host-Resources),
Windows, Cisco, Mikrotik e MIB-II generica.
"""

from typing import Dict, List

# Catalogos de OIDs organizados por categoria de metrica
KNOWN_OIDS_CPU: List[Dict[str, str]] = [
    {
        "oid": "1.3.6.1.4.1.2021.11.11.0",
        "type": "ucd_cpu_idle",
        "descr": "UCD-SNMP ssCpuIdle (% idle, usage = 100 - idle)"
    },
    {
        "oid": "1.3.6.1.4.1.2021.11.9.0",
        "type": "ucd_cpu_user",
        "descr": "UCD-SNMP ssCpuUser"
    },
    {
        "oid": "1.3.6.1.2.1.25.3.3.1.2",
        "type": "host_resources_cpu",
        "descr": "HOST-RESOURCES-MIB hrProcessorLoad"
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

KNOWN_OIDS_RAM: List[Dict[str, str]] = [
    {
        "total_oid": "1.3.6.1.4.1.2021.4.5.0",
        "free_oid": "1.3.6.1.4.1.2021.4.6.0",
        "buffer_oid": "1.3.6.1.4.1.2021.4.14.0",
        "cache_oid": "1.3.6.1.4.1.2021.4.15.0",
        "type": "ucd_memory",
        "descr": "UCD-SNMP Memory (Total, Free, Buffer, Cache)"
    },
    {
        "oid": "1.3.6.1.2.1.25.2.3.1.6",
        "descr": "HOST-RESOURCES-MIB hrStorageTable Memory"
    },
    {
        "used_oid": "1.3.6.1.4.1.9.9.48.1.1.1.5.1",
        "free_oid": "1.3.6.1.4.1.9.9.48.1.1.1.6.1",
        "type": "cisco_memory",
        "descr": "Cisco Memory Pool"
    }
]

KNOWN_OIDS_UPTIME: List[str] = [
    "1.3.6.1.2.1.1.3.0",        # sysUpTimeInstance
    "1.3.6.1.2.1.25.1.1.0"      # hrSystemUptime
]

KNOWN_OIDS_HOSTNAME: List[str] = [
    "1.3.6.1.2.1.1.5.0",        # sysName
    "1.3.6.1.2.1.1.1.0"         # sysDescr
]

KNOWN_OIDS_STORAGE_TABLE: str = "1.3.6.1.2.1.25.2.3.1"
KNOWN_OIDS_INTERFACES_64: Dict[str, str] = {
    "in": "1.3.6.1.2.1.31.1.1.1.6",     # ifHCInOctets
    "out": "1.3.6.1.2.1.31.1.1.1.10",   # ifHCOutOctets
    "names": "1.3.6.1.2.1.31.1.1.1.1"   # ifName
}
KNOWN_OIDS_INTERFACES_32: Dict[str, str] = {
    "in": "1.3.6.1.2.1.2.2.1.10",       # ifInOctets
    "out": "1.3.6.1.2.1.2.2.1.16",      # ifOutOctets
    "names": "1.3.6.1.2.1.2.2.1.2"      # ifDescr
}
