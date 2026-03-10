from datetime import datetime, timedelta
from Backend.models import CheckResult, Incident

def compute_health(ping_result, tcp_result, http_result):
    score = 0
    icmp_blocked_like = (
        not ping_result["success"] and (
            (tcp_result is not None and tcp_result.get("success")) or
            (http_result is not None and http_result.get("success"))
        )
    )

    ping_effective_success = ping_result["success"] or icmp_blocked_like
    ping_effective_latency = ping_result.get("latency")
    if ping_effective_latency is None and icmp_blocked_like:
        # Não há RTT ICMP real quando firewall bloqueia; usa valor neutro para não penalizar saúde.
        ping_effective_latency = 80

    # ---------- Ping ----------
    if ping_effective_success:
        score += 30

        lat = ping_effective_latency or 9999
        if lat < 100:
            score += 15
        elif lat < 300:
            score += 8

    # ---------- TCP ----------
    if tcp_result and tcp_result["success"]:
        score += 30

    # ---------- HTTP ----------
    if http_result:
        status_code = http_result.get("status_code")

        if http_result["success"]:
            score += 25

            if http_result.get("latency") and http_result["latency"] < 500:
                score += 10

        elif status_code and 500 <= status_code < 600:
            score -= 20

        elif status_code and 400 <= status_code < 500:
            score -= 10

    # score máximo e mínimo
    score = max(0, min(100, score))

    # ---------- Severidade ----------
    if score >= 85:
        severity = "HEALTHY"
    elif score >= 65:
        severity = "WARNING"
    elif score >= 40:
        severity = "DEGRADED"
    else:
        severity = "CRITICAL"

    return score, severity

def calc_sla_rolling_ping(db, host_id, window=50):
    rows = (
        db.query(CheckResult)
        .filter(CheckResult.host_id == host_id,
                CheckResult.check_type == "ping")
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if not rows:
        return None

    ok = sum(1 for r in rows if r.success)
    return round(ok / len(rows) * 100, 2)

def calc_sla_rolling_tcp(db, host_id, window=50):
    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == "tcp"
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if not rows:
        return None

    ok = sum(1 for r in rows if r.success)
    return round(ok / len(rows) * 100, 2)

def calc_sla_rolling_http(db, host_id, window=50):

    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == "http"
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if not rows:
        return None

    success_count = sum(1 for r in rows if r.success)

    return round((success_count / len(rows)) * 100, 2)

def calc_jitter_ping(db, host_id, window=10):

    rows = (
        db.query(CheckResult)
        .filter(CheckResult.host_id == host_id,
                CheckResult.check_type == "ping",
                CheckResult.latency != None)
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if len(rows) < 2:
        return None

    values = [r.latency for r in rows]
    values.reverse()

    diffs = [
        abs(values[i] - values[i-1])
        for i in range(1, len(values))
    ]

    return round(sum(diffs)/len(diffs), 2)

def calc_jitter_tcp(db, host_id, window=10):
    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == "tcp",
            CheckResult.latency != None
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if len(rows) < 2:
        return None

    values = [r.latency for r in rows]
    values.reverse()

    diffs = [
        abs(values[i] - values[i-1])
        for i in range(1, len(values))
    ]

    return round(sum(diffs)/len(diffs), 2)


def calc_sla_rolling_tcp_ports(db, host_id, tcp_ports, window=50):
    ports = [int(p) for p in (tcp_ports or []) if p is not None]
    if not ports:
        return None

    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == "tcp",
            CheckResult.tcp_port.in_(ports),
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if not rows:
        return None

    ok = sum(1 for r in rows if r.success)
    return round(ok / len(rows) * 100, 2)


def calc_jitter_tcp_ports(db, host_id, tcp_ports, window=10):
    ports = [int(p) for p in (tcp_ports or []) if p is not None]
    if not ports:
        return None

    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == "tcp",
            CheckResult.tcp_port.in_(ports),
            CheckResult.latency != None,
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if len(rows) < 2:
        return None

    values = [r.latency for r in rows]
    values.reverse()
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    return round(sum(diffs) / len(diffs), 2)

def calc_jitter_http(db, host_id, window=10):

    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == "http",
            CheckResult.success == True,
            CheckResult.latency != None
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if len(rows) < 3:
        return None

    latencies = [r.latency for r in rows]
    latencies.reverse()

    diffs = [abs(latencies[i] - latencies[i-1]) for i in range(1, len(latencies))]

    return round(sum(diffs) / len(diffs), 2)

def refine_severity(
    base_severity,
    sla_ping=None,
    sla_tcp=None,
    sla_http=None,
    jitter_ping=None,
    jitter_tcp=None,
    jitter_http=None,
    ignore_ping_metrics: bool = False
):
    
    sev = base_severity

    # ---------- SLA pior manda ----------
    sla_ping_effective = None if ignore_ping_metrics else sla_ping
    slas = [s for s in (sla_ping_effective, sla_tcp, sla_http) if s is not None]

    if slas:
        worst_sla = min(slas)

        if worst_sla < 70:
            return "CRITICAL"
        elif worst_sla < 90 and sev != "CRITICAL":
            sev = "WARNING"

    # ---------- Jitter pior manda ----------
    jitter_ping_effective = None if ignore_ping_metrics else jitter_ping
    jitters = [j for j in (jitter_ping_effective, jitter_tcp, jitter_http) if j is not None]

    if jitters:
        worst_jitter = max(jitters)

        if worst_jitter > 400:
            return "CRITICAL"
        elif worst_jitter > 200 and sev not in ("CRITICAL"):
            sev = "DEGRADED"

    return sev

def calc_latency_trend_ping(db, host_id, window=10):

    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == "ping",
            CheckResult.success == True,
            CheckResult.latency != None
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if len(rows) < 5:
        return None

    values = [r.latency for r in rows]
    values.reverse()

    # slope simples
    x = list(range(len(values)))

    x_mean = sum(x)/len(x)
    y_mean = sum(values)/len(values)

    num = sum((xi-x_mean)*(yi-y_mean) for xi, yi in zip(x, values))
    den = sum((xi-x_mean)**2 for xi in x)

    if den == 0:
        return 0

    slope = num / den

    return round(slope, 2)

def calc_latency_trend_http(db, host_id, window=10):

    rows = (
        db.query(CheckResult)
        .filter(
            CheckResult.host_id == host_id,
            CheckResult.check_type == "http",
            CheckResult.success == True,
            CheckResult.latency != None
        )
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if len(rows) < 5:
        return None

    values = [r.latency for r in rows]
    values.reverse()

    x = list(range(len(values)))

    x_mean = sum(x) / len(x)
    y_mean = sum(values) / len(values)

    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
    den = sum((xi - x_mean) ** 2 for xi in x)

    if den == 0:
        return 0

    return round(num / den, 2)

def classify_trend(slope):

    if slope is None:
        return "UNKNOWN"

    if slope > 40:
        return "FAST_DEGRADING"

    if slope > 15:
        return "DEGRADING"

    if slope < -15:
        return "IMPROVING"

    return "STABLE"

def classify_trend_http(slope):

    if slope is None:
        return "UNKNOWN"

    if slope < 10:
        return "STABLE"
    elif slope < 40:
        return "RISING"
    elif slope < 80:
        return "DEGRADING"
    else:
        return "CRITICAL"

def total_incidents(db, host_name):
    return (
        db.query(Incident)
        .filter(Incident.host_name == host_name)
        .count()
    )

def total_downtime(db, host_name):
    incidents = (
        db.query(Incident)
        .filter(
            Incident.host_name == host_name,
            Incident.status == "CLOSED",
            Incident.duration_seconds != None
        )
        .all()
    )

    return sum(i.duration_seconds for i in incidents)

def availability_last_10_min(db, host_name):
    now = datetime.utcnow()
    since = now - timedelta(minutes=10)

    incidents = (
    db.query(Incident)
    .filter(
        Incident.host_name == host_name,
        Incident.started_time <= now,
        (Incident.ended_time == None) | (Incident.ended_time >= since)
    )
    .all()
)

    downtime = 0

    for incident in incidents:
        start = incident.started_time
        end = incident.ended_time or now

        overlap_start = max(start, since)
        overlap_end = min(end, now)

        if overlap_end > overlap_start:
            downtime += (overlap_end - overlap_start).total_seconds()

    total_period = 600
    availability = ((total_period - downtime) / total_period) * 100

    return round(max(0, availability), 4)

def apply_preventive_logic(host, snmp_data=None, ignore_ping_metrics: bool = False):
    reasons = []
    preventive_severity = "HEALTHY"

    # Se já caiu, não é preventivo: é crítico operacional
    if host.status == "DOWN":
        return "CRITICAL", ["Host indisponível"]

    if host.status == "DEGRADED":
        preventive_severity = "DEGRADED"
        reasons.append("Serviço degradado")

    # ---------- SLA ----------
    sla_ping = None if ignore_ping_metrics else host.sla_rolling_ping
    sla_values = [
        sla_ping,
        host.sla_rolling_tcp,
        host.sla_rolling_http
    ]

    valid_slas = [v for v in sla_values if v is not None]

    if any(v < 95 for v in valid_slas):
        preventive_severity = max_severity(preventive_severity, "WARNING")
        reasons.append("Queda de taxa de sucesso")

    if any(v < 85 for v in valid_slas):
        preventive_severity = max_severity(preventive_severity, "DEGRADED")
        reasons.append("SLA instável")

    # ---------- Jitter ----------
    jitter_ping = None if ignore_ping_metrics else host.jitter_ms_ping
    jitter_values = [
        jitter_ping,
        host.jitter_ms_tcp,
        host.jitter_ms_http
    ]

    valid_jitters = [v for v in jitter_values if v is not None]

    if any(v > 80 for v in valid_jitters):
        preventive_severity = max_severity(preventive_severity, "WARNING")
        reasons.append("Alta variação de latência")

    if any(v > 150 for v in valid_jitters):
        preventive_severity = max_severity(preventive_severity, "DEGRADED")
        reasons.append("Jitter crítico")

    # ---------- Tendência ----------
    if not ignore_ping_metrics and host.trend in ("SUBINDO", "PIORANDO", "UPWARD"):
        preventive_severity = max_severity(preventive_severity, "WARNING")
        reasons.append("Tendência de piora no ping")

    if host.trend_http in ("SUBINDO", "PIORANDO", "UPWARD"):
        preventive_severity = max_severity(preventive_severity, "WARNING")
        reasons.append("Tendência de piora no HTTP")

    # ---------- SNMP ----------
    if snmp_data:
        cpu = snmp_data.get("cpu")
        ram = snmp_data.get("ram")
        disk = snmp_data.get("disk")

        if cpu is not None and cpu >= 85:
            preventive_severity = max_severity(preventive_severity, "WARNING")
            reasons.append(f"CPU alta ({cpu}%)")

        if cpu is not None and cpu >= 95:
            preventive_severity = max_severity(preventive_severity, "CRITICAL")
            reasons.append(f"CPU crítica ({cpu}%)")

        if ram is not None and ram >= 85:
            preventive_severity = max_severity(preventive_severity, "WARNING")
            reasons.append(f"RAM alta ({ram}%)")

        if ram is not None and ram >= 95:
            preventive_severity = max_severity(preventive_severity, "CRITICAL")
            reasons.append(f"RAM crítica ({ram}%)")

        if disk is not None and disk >= 90:
            preventive_severity = max_severity(preventive_severity, "WARNING")
            reasons.append(f"Disco alto ({disk}%)")

        if disk is not None and disk >= 97:
            preventive_severity = max_severity(preventive_severity, "CRITICAL")
            reasons.append(f"Disco crítico ({disk}%)")

    return preventive_severity, reasons

def max_severity(current, new):
    order = {
        "HEALTHY": 0,
        "WARNING": 1,
        "DEGRADED": 2,
        "CRITICAL": 3
    }
    return new if order[new] > order[current] else current
