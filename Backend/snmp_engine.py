from datetime import datetime
import asyncio

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
)

from Backend.models import SNMPMetric


def get_snmp_value(ip, community, oid):
    async def _fetch():
        snmp_engine = SnmpEngine()
        try:
            error_indication, error_status, error_index, var_binds = await get_cmd(
                snmp_engine,
                CommunityData(community, mpModel=1),
                await UdpTransportTarget.create((ip, 161), timeout=1, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )

            if error_indication:
                print(f"Erro SNMP em {ip}: {error_indication}")
                return None

            if error_status:
                print(f"Erro SNMP em {ip}: {error_status.prettyPrint()} no índice {error_index}")
                return None

            return var_binds[0][1]
        finally:
            snmp_engine.close_dispatcher()

    try:
        return asyncio.run(_fetch())
    except Exception as e:
        print(f"Erro SNMP em {ip}: {e}")
        return None
    
def trim_snmp_history(db, host_id, limit=500):
    old_rows = (
        db.query(SNMPMetric)
        .filter(SNMPMetric.host_id == host_id)
        .order_by(SNMPMetric.timestamp.desc())
        .offset(limit)
        .all()
    )

    for row in old_rows:
        db.delete(row)


def update_host_snmp(host, db):
    data = {
        "cpu": None,
        "ram": None,
        "disk": None,
        "network": None
    }

    comm = host.snmp_community or "public"
    ip = host.address

    # CPU %
    cpu_val = get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.11.67.0")
    if cpu_val is not None:
        data["cpu"] = float(cpu_val)
        host.cpu_usage = data["cpu"]

    # RAM %
    ram_total = get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.5.0")
    ram_free = get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.6.0")
    if ram_total is not None and ram_free is not None:
        total = float(ram_total)
        free = float(ram_free)

        if total > 0:
            data["ram"] = round(((total - free) / total) * 100, 2)
            host.ram_usage = data["ram"]

    # Disco % -> índice correto do "/"
    disk_total = get_snmp_value(ip, comm, "1.3.6.1.2.1.25.2.3.1.5.36")
    disk_used = get_snmp_value(ip, comm, "1.3.6.1.2.1.25.2.3.1.6.36")
    if disk_total is not None and disk_used is not None:
        total = float(disk_total)
        used = float(disk_used)

        if total > 0:
            data["disk"] = round((used / total) * 100, 2)
            host.disk_usage = data["disk"]
            host.disk_remaining = round(100 - data["disk"], 2)

        # Rede -> interface enp0s3 índice 2
    net_in = get_snmp_value(ip, comm, "1.3.6.1.2.1.31.1.1.1.6.2")
    net_out = get_snmp_value(ip, comm, "1.3.6.1.2.1.31.1.1.1.10.2")

    now = datetime.utcnow()

    if net_in is not None and net_out is not None:
        current_in = float(net_in)
        current_out = float(net_out)

        data["network"] = {
            "in_octets": current_in,
            "out_octets": current_out,
            "in_bps": None,
            "out_bps": None
        }

        if (
            host.last_net_in_octets is not None and
            host.last_net_out_octets is not None and
            host.last_net_check is not None
        ):
            elapsed = (now - host.last_net_check).total_seconds()

            if elapsed > 0:
                delta_in = current_in - host.last_net_in_octets
                delta_out = current_out - host.last_net_out_octets

                # proteção simples contra reset de contador
                if delta_in < 0:
                    delta_in = 0
                if delta_out < 0:
                    delta_out = 0

                in_bps = (delta_in * 8) / elapsed
                out_bps = (delta_out * 8) / elapsed

                data["network"]["in_bps"] = round(in_bps, 2)
                data["network"]["out_bps"] = round(out_bps, 2)

                host.network_in_bps = data["network"]["in_bps"]
                host.network_out_bps = data["network"]["out_bps"]

                # opcional: total agregado
                host.network_traffic = round(in_bps + out_bps, 2)

        host.last_net_in_octets = current_in
        host.last_net_out_octets = current_out
        host.last_net_check = now

    host.last_snmp_check = datetime.utcnow()

    metric = SNMPMetric(
        host_id=host.id,
        cpu=data["cpu"],
        ram=data["ram"],
        disk=data["disk"],
        network_in_bps=host.network_in_bps,
        network_out_bps=host.network_out_bps,
        network_total_bps=host.network_traffic
    )
    db.add(metric)

    trim_snmp_history(db, host.id, limit=500)

    db.flush()
    return data