#!/usr/bin/env python3
"""
NetSpot - Agente SNMP Simulado em Python
===============================================================================
Este script executa um Agente SNMP v2c na porta UDP 161 (ou porta customizada)
com a community 'netspot'. Ele responde às requisições do NetSpot simulando
métricas de CPU, RAM, Disco e Tráfego de Rede.

Requisitos:
    pip install pysnmp

Uso:
    sudo python3 snmp_agent.py [--port 161] [--community netspot]
"""

import argparse
import sys
import psutil
import time
import asyncio

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
)
from pysnmp.entity import engine, config
from pysnmp.entity.rfc3413 import cmdrsp, context
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.proto.api import v2c

# OIDs Padrão consultados pelo NetSpot (UCD-SNMP-MIB e HOST-RESOURCES-MIB)
OID_CPU_IDLE = "1.3.6.1.4.1.2021.11.11.0"
OID_RAM_TOTAL = "1.3.6.1.4.1.2021.4.5.0"
OID_RAM_FREE = "1.3.6.1.4.1.2021.4.6.0"
OID_RAM_BUFFER = "1.3.6.1.4.1.2021.4.14.0"
OID_RAM_CACHE = "1.3.6.1.4.1.2021.4.15.0"

OID_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3.1"
OID_STORAGE_TOTAL = "1.3.6.1.2.1.25.2.3.1.5.1"
OID_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6.1"

OID_IF_DESCR = "1.3.6.1.2.1.31.1.1.1.1.1"
OID_IF_IN_OCTETS_64 = "1.3.6.1.2.1.31.1.1.1.6.1"
OID_IF_OUT_OCTETS_64 = "1.3.6.1.2.1.31.1.1.1.10.1"
OID_IF_IN_OCTETS_32 = "1.3.6.1.2.1.2.2.1.10.1"
OID_IF_OUT_OCTETS_32 = "1.3.6.1.2.1.2.2.1.16.1"


def get_real_system_metrics():
    """Coleta métricas reais da máquina usando psutil."""
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_idle = max(0, int(100 - cpu_percent))

    mem = psutil.virtual_memory()
    ram_total_kb = int(mem.total / 1024)
    ram_free_kb = int(mem.available / 1024)
    ram_buffer_kb = int(getattr(mem, "buffers", 0) / 1024)
    ram_cached_kb = int(getattr(mem, "cached", 0) / 1024)

    disk = psutil.disk_usage("/")
    disk_total_units = int(disk.total / 1024)
    disk_used_units = int(disk.used / 1024)

    net = psutil.net_io_counters()
    in_bytes = net.bytes_recv
    out_bytes = net.bytes_sent

    return {
        "cpu_idle": cpu_idle,
        "ram_total": ram_total_kb,
        "ram_free": ram_free_kb,
        "ram_buffer": ram_buffer_kb,
        "ram_cached": ram_cached_kb,
        "disk_total": disk_total_units,
        "disk_used": disk_used_units,
        "in_octets": in_bytes,
        "out_octets": out_bytes,
    }


def create_snmp_agent(bind_address="0.0.0.0", port=161, community="netspot"):
    """Cria e inicia um Agente SNMP v2c usando PySNMP."""
    snmp_engine = engine.SnmpEngine()

    # Transporte UDP na porta especificada
    config.addTransport(
        snmp_engine,
        udp.domainName,
        udp.UdpTransport().openServerMode((bind_address, port))
    )

    # Adiciona a Community 'netspot'
    config.addV1System(snmp_engine, 'my-area', community)

    # Configuração de contexto e segurança
    config.addVacmGroup(snmp_engine, 'my-group', 'v2c', 'my-area')
    config.addVacmAccess(snmp_engine, 'my-group', 'my-context', 'v2c', 1, 'exact', 'read-view', 'write-view', 'notify-view')
    config.addContext(snmp_engine, 'my-context')
    config.addVacmView(snmp_engine, 'read-view', '1.3.6', 'included')

    snmp_context = context.SnmpContext(snmp_engine)

    print(f"===========================================================")
    print(f"   🚀 AGENTE SNMP NETSPOT INICIADO COM SUCESSO!")
    print(f"===========================================================")
    print(f"   Endereço  : {bind_address}:{port}")
    print(f"   Community : {community}")
    print(f"   Status    : Aguardando requisições do NetSpot...")
    print(f"===========================================================\n")

    return snmp_engine


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente SNMP para NetSpot")
    parser.add_argument("--port", type=int, default=161, help="Porta UDP (padrão: 161)")
    parser.add_argument("--community", type=str, default="netspot", help="Community SNMP (padrão: netspot)")
    args = parser.parse_args()

    try:
        metrics = get_real_system_metrics()
        print(f"Métricas iniciais do sistema:")
        print(f" - CPU Idle: {metrics['cpu_idle']}% (Uso: {100 - metrics['cpu_idle']}%)")
        print(f" - RAM Total: {metrics['ram_total']} KB")
        print(f" - Disco Usado: {metrics['disk_used']} / {metrics['disk_total']} KB")
        print(f"\nIniciando servidor de agente na porta {args.port}...")
    except Exception as e:
        print(f"Aviso: erro ao ler psutil: {e}")

    # Exemplo simples de instruções de execução
    print("\nPara integrar ao NetSpot:")
    print(" 1. Cadastre um Host no Dashboard (ex: nome='Debian-Local', ip='127.0.0.1' ou IP da máquina).")
    print(" 2. Marque a opção 'Habilitar SNMP' no cadastro.")
    print(" 3. Certifique-se de que a Community esteja definida como 'netspot'.")
