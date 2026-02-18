from Backend.models import CheckResult

def compute_health(ping_result, tcp_result):

    score = 0

    # ---------- Ping ----------
    if ping_result["success"]:
        score += 40

        lat = ping_result.get("latency") or 9999

        if lat < 100:
            score += 20
        elif lat < 300:
            score += 10

    # ---------- TCP ----------
    if tcp_result and tcp_result["success"]:
        score += 40

    if not ping_result["success"] and tcp_result and tcp_result["success"]:
        score += 30  # serviço responde mas ICMP bloqueado

    # ---------- Severidade ----------
    if score >= 90:
        severity = "HEALTHY"
    elif score >= 70:
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
        .filter(CheckResult.host_id == host_id,
                CheckResult.check_type == "tcp")
        .order_by(CheckResult.timestamp.desc())
        .limit(window)
        .all()
    )

    if not rows:
        return None

    ok = sum(1 for r in rows if r.success)
    return round(ok / len(rows) * 100, 2)

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
        .filter(CheckResult.host_id == host_id,
                CheckResult.check_type == "tcp",
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

def refine_severity(base_severity, sla_ping=None, sla_tcp=None, jitter_ping=None, jitter_tcp=None):
    
    sev = base_severity

    # ---------- SLA pior manda ----------
    slas = [s for s in (sla_ping, sla_tcp) if s is not None]

    if slas:
        worst_sla = min(slas)

        if worst_sla < 70:
            return "CRITICAL"
        elif worst_sla < 90 and sev != "CRITICAL":
            sev = "WARNING"

    # ---------- Jitter pior manda ----------
    jitters = [j for j in (jitter_ping, jitter_tcp) if j is not None]

    if jitters:
        worst_jitter = max(jitters)

        if worst_jitter > 300:
            return "CRITICAL"
        elif worst_jitter > 150 and sev not in ("CRITICAL"):
            sev = "DEGRADED"

    return sev

