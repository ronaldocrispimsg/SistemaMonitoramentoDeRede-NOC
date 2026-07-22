from datetime import datetime, timedelta
import asyncio
from sqlalchemy import select

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

from Backend.models import SNMPMetric


SNMP_BURST_FAIL_LIMIT = 3
SNMP_BACKOFF_BASE_SECONDS = 300
SNMP_BACKOFF_MAX_SECONDS = 3600
SNMP_BACKOFF_STATE = {}
SNMP_TIMEOUT_SECONDS = 2
SNMP_RETRIES = 3
COUNTER32_MODULO = 2 ** 32
COUNTER64_FAILOVER_THRESHOLD = 3
COUNTER64_REPROBE_INTERVAL = 30
SNMP_NET_COUNTER_STATE = {}


def snmp_has_usable_data(snmp_data):
    if not isinstance(snmp_data, dict):
        return False

    if any(snmp_data.get(key) is not None for key in ("cpu", "ram", "disk")):
        return True

    network = snmp_data.get("network")
    if isinstance(network, dict):
        return any(network.get(k) is not None for k in ("in_octets", "out_octets", "in_bps", "out_bps"))

    return False


def get_snmp_state(host_id):
    if host_id not in SNMP_BACKOFF_STATE:
        SNMP_BACKOFF_STATE[host_id] = {
            "failures_in_burst": 0,
            "consecutive_failures": 0,
            "backoff_level": 0,
            "pause_until": None,
        }
    return SNMP_BACKOFF_STATE[host_id]


def reset_snmp_backoff(host_id=None):
    if host_id is None:
        total = len(SNMP_BACKOFF_STATE)
        SNMP_BACKOFF_STATE.clear()
        SNMP_NET_COUNTER_STATE.clear()
        return total

    SNMP_NET_COUNTER_STATE.pop(host_id, None)
    return 1 if SNMP_BACKOFF_STATE.pop(host_id, None) is not None else 0


def can_attempt_snmp(host_id):
    state = get_snmp_state(host_id)
    pause_until = state["pause_until"]
    if pause_until and datetime.utcnow() < pause_until:
        return False
    return True


def register_snmp_success(host_id):
    state = get_snmp_state(host_id)
    state["failures_in_burst"] = 0
    state["consecutive_failures"] = 0
    state["backoff_level"] = 0
    state["pause_until"] = None


def register_snmp_failure(host_id, host_name):
    state = get_snmp_state(host_id)
    state["failures_in_burst"] += 1
    state["consecutive_failures"] += 1

    if state["failures_in_burst"] < SNMP_BURST_FAIL_LIMIT:
        return

    level = max(state["backoff_level"], 0)
    wait_seconds = min(SNMP_BACKOFF_BASE_SECONDS * (2 ** level), SNMP_BACKOFF_MAX_SECONDS)
    state["pause_until"] = datetime.utcnow() + timedelta(seconds=wait_seconds)
    state["failures_in_burst"] = 0
    state["backoff_level"] += 1

    print(f"[SNMP BACKOFF] {host_name}: pausado por {wait_seconds}s")


async def get_snmp_value(ip, community, oid):
    snmp_engine = SnmpEngine()
    try:
        comm = (community or "netspot").strip() or "netspot"
        error_indication, error_status, error_index, var_binds = await get_cmd(
            snmp_engine,
            CommunityData(comm, mpModel=1),
            await UdpTransportTarget.create(
                (ip, 161),
                timeout=SNMP_TIMEOUT_SECONDS,
                retries=SNMP_RETRIES,
            ),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )

        if error_indication or error_status or not var_binds:
            return None

        val = var_binds[0][1]
        val_str = str(val)
        if "No Such" in val_str:
            return None

        return val
    except Exception as e:
        print(f"Erro SNMP em {ip}: {e}")
        return None
    finally:
        snmp_engine.close_dispatcher()


async def walk_snmp(ip, community, oid):
    snmp_engine = SnmpEngine()
    results = []
    current_oid = oid
    comm = (community or "netspot").strip() or "netspot"

    try:
        while True:
            error_indication, error_status, error_index, var_binds = await next_cmd(
                snmp_engine,
                CommunityData(comm, mpModel=1),
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
                oid_value = str(var_bind[1])

                if not oid_name.startswith(f"{oid}."):
                    reached_end = True
                    break

                if "No Such" in oid_value:
                    continue

                results.append((oid_name, oid_value))
                current_oid = oid_name

            if reached_end:
                break
    finally:
        snmp_engine.close_dispatcher()

    return results


async def get_storage_index(ip, community, mount_points=("/", "C:", "c:", "C:\\")):
    """Localiza o indice da particao de disco (Linux '/' ou Windows 'C:')"""
    try:
        rows = await walk_snmp(ip, community, "1.3.6.1.2.1.25.2.3.1.3")
        for oid, value in rows:
            clean_val = value.strip('"').strip()
            for mp in mount_points:
                if clean_val == mp or clean_val.startswith(mp):
                    return oid.split(".")[-1]
        return None
    except Exception as e:
        print(f"Erro ao descobrir storage index em {ip}: {e}")
        return None


async def get_ram_storage_index(ip, community):
    """Localiza o indice de Memoria RAM (Physical Memory) em HOST-RESOURCES-MIB (Windows/Linux)"""
    try:
        rows = await walk_snmp(ip, community, "1.3.6.1.2.1.25.2.3.1.3")
        for oid, value in rows:
            clean_val = value.strip('"').strip().lower()
            if "physical memory" in clean_val or "memória física" in clean_val:
                return oid.split(".")[-1]
        return None
    except Exception as e:
        print(f"Erro ao descobrir ram storage index em {ip}: {e}")
        return None


async def get_best_interface_index(ip, community):
    """Localiza o indice da interface de rede fisicamente ATIVA (ifOperStatus == 1) com maior trafego de dados"""
    try:
        oper_statuses = await walk_snmp(ip, community, "1.3.6.1.2.1.2.2.1.8")
        active_indices = []
        for oid, val in oper_statuses:
            if str(val).strip() == "1":  # 1 == UP
                active_indices.append(oid.split(".")[-1])

        if not active_indices:
            # Fallback se a MIB de status nao responder
            names = await walk_snmp(ip, community, "1.3.6.1.2.1.31.1.1.1.1")
            active_indices = [oid.split(".")[-1] for oid, _ in names]

        best_idx = None
        max_octets = -1

        for idx in active_indices:
            in_oct = _to_float(await get_snmp_value(ip, community, f"1.3.6.1.2.1.31.1.1.1.6.{idx}"))
            if in_oct is None:
                in_oct = _to_float(await get_snmp_value(ip, community, f"1.3.6.1.2.1.2.2.1.10.{idx}"))
            
            out_oct = _to_float(await get_snmp_value(ip, community, f"1.3.6.1.2.1.31.1.1.1.10.{idx}"))
            if out_oct is None:
                out_oct = _to_float(await get_snmp_value(ip, community, f"1.3.6.1.2.1.2.2.1.16.{idx}"))

            tot = (in_oct or 0) + (out_oct or 0)
            if tot > max_octets:
                max_octets = tot
                best_idx = idx

        return best_idx
    except Exception as e:
        print(f"Erro ao descobrir interface index em {ip}: {e}")
        return None


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _read_interface_octets_64(ip, community, iface_index):
    in_64 = _to_float(await get_snmp_value(ip, community, f"1.3.6.1.2.1.31.1.1.1.6.{iface_index}"))
    out_64 = _to_float(await get_snmp_value(ip, community, f"1.3.6.1.2.1.31.1.1.1.10.{iface_index}"))
    if in_64 is not None and out_64 is not None:
        return in_64, out_64
    return None, None


async def _read_interface_octets_32(ip, community, iface_index):
    in_32 = _to_float(await get_snmp_value(ip, community, f"1.3.6.1.2.1.2.2.1.10.{iface_index}"))
    out_32 = _to_float(await get_snmp_value(ip, community, f"1.3.6.1.2.1.2.2.1.16.{iface_index}"))
    if in_32 is not None and out_32 is not None:
        return in_32, out_32
    return None, None


def _get_net_counter_state(host_id):
    if host_id not in SNMP_NET_COUNTER_STATE:
        SNMP_NET_COUNTER_STATE[host_id] = {
            "iface_index": None,
            "counter_mode": None,
            "counter64_failures": 0,
            "collections_since_last_64_probe": 0,
        }
    return SNMP_NET_COUNTER_STATE[host_id]


def _reset_network_baseline(host):
    host.last_net_in_octets = None
    host.last_net_out_octets = None
    host.last_net_check = None
    host.network_in_bps = None
    host.network_out_bps = None
    host.network_traffic = None


async def _select_interface_octets(host, ip, community, iface_index):
    state = _get_net_counter_state(host.id)

    if state["iface_index"] != iface_index:
        state["iface_index"] = iface_index
        state["counter_mode"] = None
        state["counter64_failures"] = 0
        state["collections_since_last_64_probe"] = 0
        _reset_network_baseline(host)

    mode = state["counter_mode"]

    if mode is None:
        in_64, out_64 = await _read_interface_octets_64(ip, community, iface_index)
        if in_64 is not None and out_64 is not None:
            state["counter_mode"] = "64"
            state["counter64_failures"] = 0
            state["collections_since_last_64_probe"] = 0
            _reset_network_baseline(host)
            return in_64, out_64, 64, True

        in_32, out_32 = await _read_interface_octets_32(ip, community, iface_index)
        if in_32 is not None and out_32 is not None:
            state["counter_mode"] = "32"
            state["counter64_failures"] = 0
            state["collections_since_last_64_probe"] = 0
            _reset_network_baseline(host)
            return in_32, out_32, 32, True

        return None, None, None, False

    if mode == "64":
        in_64, out_64 = await _read_interface_octets_64(ip, community, iface_index)
        if in_64 is not None and out_64 is not None:
            state["counter64_failures"] = 0
            return in_64, out_64, 64, False

        state["counter64_failures"] += 1
        if state["counter64_failures"] < COUNTER64_FAILOVER_THRESHOLD:
            return None, None, None, False

        in_32, out_32 = await _read_interface_octets_32(ip, community, iface_index)
        if in_32 is not None and out_32 is not None:
            state["counter_mode"] = "32"
            state["counter64_failures"] = 0
            state["collections_since_last_64_probe"] = 0
            _reset_network_baseline(host)
            return in_32, out_32, 32, True

        return None, None, None, False

    probe_counter = int(state.get("collections_since_last_64_probe", 0) or 0)
    if probe_counter >= COUNTER64_REPROBE_INTERVAL:
        in_64, out_64 = await _read_interface_octets_64(ip, community, iface_index)
        state["collections_since_last_64_probe"] = 0
        if in_64 is not None and out_64 is not None:
            state["counter_mode"] = "64"
            state["counter64_failures"] = 0
            _reset_network_baseline(host)
            return in_64, out_64, 64, True

    in_32, out_32 = await _read_interface_octets_32(ip, community, iface_index)
    state["collections_since_last_64_probe"] = int(state.get("collections_since_last_64_probe", 0) or 0) + 1
    if in_32 is not None and out_32 is not None:
        return in_32, out_32, 32, False

    return None, None, None, False


def _compute_delta_octets(current, previous, counter_bits):
    if current is None or previous is None:
        return None

    if counter_bits == 32:
        if previous >= COUNTER32_MODULO or current >= COUNTER32_MODULO:
            return None
        if current >= previous:
            return current - previous
        return (COUNTER32_MODULO - previous) + current

    return max(current - previous, 0)


async def trim_snmp_history(db, host_id, limit=500):
    stmt = (
        select(SNMPMetric)
        .filter(SNMPMetric.host_id == host_id)
        .order_by(SNMPMetric.timestamp.desc())
        .offset(limit)
    )
    res = await db.execute(stmt)
    old_rows = res.scalars().all()

    for row in old_rows:
        await db.delete(row)


async def update_host_snmp(host, db):
    data = {
        "cpu": None,
        "ram": None,
        "disk": None,
        "network": None
    }

    comm = (host.snmp_community or "netspot").strip() or "netspot"
    ip = host.address

    # ---------- 1. CPU (UCD-SNMP Linux ou HOST-RESOURCES Windows) ----------
    cpu_idle = await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.11.11.0")
    if cpu_idle is not None:
        try:
            idle = float(cpu_idle)
            data["cpu"] = round(max(0, min(100, 100 - idle)), 2)
            host.cpu_usage = data["cpu"]
        except (ValueError, TypeError):
            pass

    if data["cpu"] is None:
        # Tentar HOST-RESOURCES hrProcessorLoad (Windows/Linux)
        cpu_cores = await walk_snmp(ip, comm, "1.3.6.1.2.1.25.3.3.1.2")
        if cpu_cores:
            vals = []
            for _, val in cpu_cores:
                try:
                    vals.append(float(val))
                except (ValueError, TypeError):
                    pass
            if vals:
                data["cpu"] = round(sum(vals) / len(vals), 2)
                host.cpu_usage = data["cpu"]

    # ---------- 2. RAM (UCD-SNMP Linux ou HOST-RESOURCES Windows) ----------
    ram_total = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.5.0"))
    ram_free = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.6.0"))
    ram_buffer = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.14.0"))
    ram_cache = _to_float(await get_snmp_value(ip, comm, "1.3.6.1.4.1.2021.4.15.0"))

    if (
        ram_total is not None and
        ram_free is not None and
        ram_buffer is not None and
        ram_cache is not None
    ):
        total = ram_total
        free = ram_free
        buffer = ram_buffer
        cache = ram_cache

        if total > 0:
            used = max(0, total - free - buffer - cache)
            data["ram"] = round((used / total) * 100, 2)
            host.ram_usage = data["ram"]

    if data["ram"] is None:
        # Fallback para HOST-RESOURCES Physical Memory (Windows)
        ram_index = await get_ram_storage_index(ip, comm)
        if ram_index:
            ram_size = _to_float(await get_snmp_value(ip, comm, f"1.3.6.1.2.1.25.2.3.1.5.{ram_index}"))
            ram_used = _to_float(await get_snmp_value(ip, comm, f"1.3.6.1.2.1.25.2.3.1.6.{ram_index}"))
            if ram_size is not None and ram_used is not None:
                tot = ram_size
                usd = ram_used
                if tot > 0:
                    data["ram"] = round((usd / tot) * 100, 2)
                    host.ram_usage = data["ram"]

    # ---------- 3. DISCO (Linux '/' ou Windows 'C:') ----------
    storage_index = await get_storage_index(ip, comm)
    if storage_index:
        disk_total = _to_float(await get_snmp_value(ip, comm, f"1.3.6.1.2.1.25.2.3.1.5.{storage_index}"))
        disk_used = _to_float(await get_snmp_value(ip, comm, f"1.3.6.1.2.1.25.2.3.1.6.{storage_index}"))

        if disk_total is not None and disk_used is not None:
            total = disk_total
            used = disk_used

            if total > 0:
                data["disk"] = round((used / total) * 100, 2)
                host.disk_usage = data["disk"]
                host.disk_remaining = round(100 - data["disk"], 2)

    # ---------- 4. REDE (Melhor interface) ----------
    iface_index = await get_best_interface_index(ip, comm)
    now = datetime.utcnow()

    if iface_index:
        current_in, current_out, counter_bits, baseline_only = await _select_interface_octets(
            host,
            ip,
            comm,
            iface_index,
        )

        if current_in is not None and current_out is not None:
            data["network"] = {
                "in_octets": current_in,
                "out_octets": current_out,
                "in_bps": None,
                "out_bps": None
            }

            if (
                not baseline_only and
                host.last_net_in_octets is not None and
                host.last_net_out_octets is not None and
                host.last_net_check is not None
            ):
                elapsed = (now - host.last_net_check).total_seconds()

                if elapsed > 0:
                    delta_in = _compute_delta_octets(
                        current_in,
                        host.last_net_in_octets,
                        counter_bits,
                    )
                    delta_out = _compute_delta_octets(
                        current_out,
                        host.last_net_out_octets,
                        counter_bits,
                    )

                    if delta_in is not None and delta_out is not None:
                        in_bps = (delta_in * 8) / elapsed
                        out_bps = (delta_out * 8) / elapsed

                        data["network"]["in_bps"] = round(in_bps, 2)
                        data["network"]["out_bps"] = round(out_bps, 2)

                        host.network_in_bps = data["network"]["in_bps"]
                        host.network_out_bps = data["network"]["out_bps"]
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

    await trim_snmp_history(db, host.id, limit=500)

    await db.flush()
    return data
