import pysnmp.hlapi

def get_snmp_value(ip, community, oid):
    """Função base para buscar qualquer OID via SNMP v2c"""
    try:
        iterator = pysnmp.hlapi.getCmd(
            pysnmp.hlapi.SnmpEngine(),
            pysnmp.hlapi.CommunityData(community, mpModel=1), # 1 = SNMP v2c
            pysnmp.hlapi.UdpTransportTarget((ip, 161), timeout=1, retries=0),
            pysnmp.hlapi.ContextData(),
            pysnmp.hlapi.ObjectType(pysnmp.hlapi.ObjectIdentity(oid))
        )
        
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)

        if not errorIndication and not errorStatus:
            return varBinds[0][1]
    except Exception as e:
        print(f"Erro SNMP em {ip}: {e}")
    return None

def update_host_snmp(host, db):
    data = {
        "cpu": None,
        "ram": None,
        "disk": None,
        "network": None
    }

    comm = host.snmp_community or "public"
    ip = host.address

    cpu_val = get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.10.1.3.1")
    if cpu_val:
        data["cpu"] = float(str(cpu_val))
        host.cpu_usage = data["cpu"]

    ram_total = get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.5.0")
    ram_free = get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.6.0")
    if ram_total and ram_free:
        total = float(ram_total)
        free = float(ram_free)
        data["ram"] = round(((total - free) / total) * 100, 2)
        host.ram_usage = data["ram"]

    disk_total = get_snmp_value(ip, comm, "1.3.6.1.2.1.25.2.3.1.5.1")
    disk_used = get_snmp_value(ip, comm, "1.3.6.1.2.1.25.2.3.1.6.1")
    if disk_total and disk_used:
        total = float(disk_total)
        used = float(disk_used)
        data["disk"] = round((used / total) * 100, 2)
        host.disk_usage = data["disk"]
        host.disk_remaining = 100 - data["disk"]

    net_in = get_snmp_value(ip, comm, "1.3.6.1.2.1.2.2.1.10.2")
    if net_in:
        data["network"] = float(net_in)
        host.network_traffic = data["network"]

    db.flush()
    return data