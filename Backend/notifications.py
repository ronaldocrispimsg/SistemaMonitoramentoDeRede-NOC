import requests
import time
import os
import hashlib
from threading import Lock
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TELEGRAM_BOT_TOKEN = os.getenv("NOC_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("NOC_TELEGRAM_CHAT_ID")
TELEGRAM_ANTISPAM_ENABLED = os.getenv("NOC_TELEGRAM_ANTISPAM_ENABLED", "1") != "0"
TELEGRAM_ANTISPAM_WINDOW_SECONDS = int(os.getenv("NOC_TELEGRAM_ANTISPAM_WINDOW_SECONDS", "120"))
TELEGRAM_ANTISPAM_MAX_ENTRIES = int(os.getenv("NOC_TELEGRAM_ANTISPAM_MAX_ENTRIES", "5000"))
DISPLAY_TIMEZONE = os.getenv("NOC_DISPLAY_TIMEZONE", "America/Sao_Paulo")
STATUS_LABELS = {
    "UP": "Online",
    "DOWN": "Offline",
    "DEGRADED": "Degradado",
    "CRITICAL": "Crítico",
    "UP_RECOVERED": "Online (Recuperado)",
    "UNKNOWN": "Desconhecido",
}

CHECK_LABELS = {
    "HTTP": "HTTP",
    "TCP": "TCP",
    "DNS": "DNS",
    "PING": "PING",
}

INCIDENT_TYPE_LABELS = {
    "DNS_FAILURE": "Falha na resolução DNS",
    "SERVICE_DOWN": "Serviço indisponível",
    "SERVICE_DEGRADED": "Serviço degradado",
    "GENERIC": "Incidente operacional",
}

_TELEGRAM_DEDUP_STATE = {}
_TELEGRAM_DEDUP_LOCK = Lock()
_DISPLAY_TZ = ZoneInfo(DISPLAY_TIMEZONE)


def _fmt_ts(ts=None):
    value = ts or datetime.utcnow()
    if isinstance(value, datetime):
        # Valores sem tz no sistema são UTC; convertemos para timezone de exibição.
        dt = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return dt.astimezone(_DISPLAY_TZ).strftime("%d/%m/%Y %H:%M:%S")
    return str(value)


def _safe_host_name(host):
    return getattr(host, "name", "unknown")


def _safe_host_address(host):
    return getattr(host, "address", "unknown")


def _check_label(check_type: str | None) -> str:
    normalized = str(check_type or "N/A").strip().upper()
    return CHECK_LABELS.get(normalized, normalized)


def _incident_type_label(incident_type: str | None) -> str:
    normalized = str(incident_type or "GENERIC").strip().upper()
    return INCIDENT_TYPE_LABELS.get(normalized, "Incidente operacional")


def build_generic_alert_message(host, status, message, timestamp=None):
    status_label = STATUS_LABELS.get(
        str(status or "").strip().upper(),
        status if status is not None else "Desconhecido"
    )
    return (
        "🚨 ALERTA NETSPOT\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n"
        f"Status: {status_label}\n\n"
        f"Mensagem: {message}\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_preventive_alert_message(host, condition, details, timestamp=None):
    return (
        "⚠️ ALERTA PREVENTIVO\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n\n"
        f"Condição detectada: {condition}\n\n"
        "Detalhes:\n"
        f"{details}\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_dns_change_message(host, domain, old_ip, new_ip, timestamp=None):
    return (
        "🌐 DNS_CHANGE DETECTADO\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Domínio: {domain}\n\n"
        f"IP anterior: {old_ip}\n"
        f"Novo IP: {new_ip}\n\n"
        "Possível alteração de infraestrutura ou balanceamento.\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_dns_ttl_low_message(host, domain, ttl, timestamp=None):
    return (
        "⚠️ DNS TTL BAIXO\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Domínio: {domain}\n\n"
        f"TTL atual: {ttl}s\n\n"
        "TTL muito baixo pode indicar:\n"
        "• Mudança iminente de IP\n"
        "• Failover\n"
        "• Balanceamento dinâmico\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_health_critical_message(host, metric, value, timestamp=None):
    return (
        "🔴 HEALTH CRITICAL\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n\n"
        "Métrica crítica detectada.\n\n"
        "Detalhes:\n"
        f"{metric} = {value}\n\n"
        "Ação recomendada: verificar imediatamente.\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_failure_confirmed_message(host, old_status, new_status, fail_count, timestamp=None, check_used=None):
    old_status_label = STATUS_LABELS.get(
        str(old_status or "").strip().upper(),
        old_status if old_status is not None else "Desconhecido"
    )
    new_status_label = STATUS_LABELS.get(
        str(new_status or "").strip().upper(),
        new_status if new_status is not None else "Desconhecido"
    )
    return (
        "🚨 FALHA CONFIRMADA\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n\n"
        f"Status anterior: {old_status_label}\n"
        f"Novo status: {new_status_label}\n\n"
        f"Check utilizado: {_check_label(check_used)}\n"
        f"Falhas consecutivas detectadas: {fail_count}\n\n"
        "O limite de falhas consecutivas foi atingido.\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_recovery_message(host, old_status, timestamp=None):
    old_status_label = STATUS_LABELS.get(
        str(old_status or "").strip().upper(),
        old_status if old_status is not None else "Desconhecido"
    )
    return (
        "✅ HOST RECUPERADO\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n\n"
        f"Status anterior: {old_status_label}\n"
        "Status atual: Online (Recuperado)\n\n"
        "O serviço voltou a responder normalmente.\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_incident_open_message(host, incident_type, description, timestamp=None):
    return (
        "🚨 INCIDENTE ABERTO\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n\n"
        f"Tipo: {_incident_type_label(incident_type)}\n\n"
        "Descrição:\n"
        f"{description}\n\n"
        f"Horário de abertura: {_fmt_ts(timestamp)}"
    )


def build_incident_dns_message(host, domain, timestamp=None):
    return (
        "🌐 INCIDENTE — FALHA DNS\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Domínio: {domain}\n\n"
        "3 falhas consecutivas na resolução DNS detectadas.\n\n"
        "Possíveis causas:\n"
        "• Servidor DNS indisponível\n"
        "• Domínio expirado\n"
        "• Problema de rede\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_incident_host_unavailable_message(host, check_type, timestamp=None):
    return (
        "🔴 INCIDENTE — SERVIÇO INDISPONÍVEL\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n\n"
        "Falhas consecutivas no check principal.\n\n"
        f"Check utilizado: {_check_label(check_type)}\n\n"
        "Indisponibilidade operacional confirmada.\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )

def build_incident_service_degraded_message(host, check_type, timestamp=None):
    return (
        "⚠️ INCIDENTE — SERVIÇO DEGRADADO\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n\n"
        f"Check utilizado: {_check_label(check_type)}\n\n"
        "Instabilidade detectada no serviço monitorado, com resposta parcial.\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def build_incident_closed_message(host, timestamp=None, incident_type=None):
    recovery_text = "O host voltou ao estado operacional."
    if incident_type == "SERVICE_DEGRADED":
        recovery_text = "A estabilidade operacional foi restabelecida."
    elif incident_type == "SERVICE_DOWN":
        recovery_text = "O serviço voltou a responder normalmente."

    return (
        "✅ INCIDENTE FECHADO AUTOMATICAMENTE\n\n"
        f"Host: {_safe_host_name(host)}\n"
        f"Endereço: {_safe_host_address(host)}\n\n"
        f"{recovery_text}\n\n"
        "Status atual: Online\n\n"
        "Incidente fechado automaticamente.\n\n"
        f"Horário: {_fmt_ts(timestamp)}"
    )


def _message_fingerprint(message) -> str:
    import json
    if isinstance(message, dict):
        normalized = json.dumps(message, sort_keys=True)
    else:
        normalized = " ".join(str(message or "").split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _is_suppressed_by_antispam(message: str, now_ts: float) -> bool:
    if not TELEGRAM_ANTISPAM_ENABLED:
        return False

    fp = _message_fingerprint(message)

    with _TELEGRAM_DEDUP_LOCK:
        last_ts = _TELEGRAM_DEDUP_STATE.get(fp)
        if last_ts is not None and (now_ts - last_ts) < TELEGRAM_ANTISPAM_WINDOW_SECONDS:
            return True

        _TELEGRAM_DEDUP_STATE[fp] = now_ts

        # Limpeza simples para não crescer indefinidamente em runtime longo.
        if len(_TELEGRAM_DEDUP_STATE) > TELEGRAM_ANTISPAM_MAX_ENTRIES:
            expire_before = now_ts - max(TELEGRAM_ANTISPAM_WINDOW_SECONDS * 2, 60)
            stale_keys = [k for k, ts in _TELEGRAM_DEDUP_STATE.items() if ts < expire_before]
            for k in stale_keys:
                _TELEGRAM_DEDUP_STATE.pop(k, None)

    return False

def send_telegram_alert(message):
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False

    now_ts = time.time()
    if _is_suppressed_by_antispam(message, now_ts):
        print("[TELEGRAM ANTISPAM] alerta duplicado suprimido")
        return False

    from Backend.mq_manager import mq_manager
    mq_manager.publish_notification_sync(message)
    return True

async def send_telegram_alert_async(message):
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False

    now_ts = time.time()
    if _is_suppressed_by_antispam(message, now_ts):
        print("[TELEGRAM ANTISPAM] alerta duplicado suprimido")
        return False

    from Backend.mq_manager import mq_manager
    await mq_manager.publish_notification(message)
    return True

def telegram_health_check():

    if not TELEGRAM_BOT_TOKEN:
        return {"status": "ERROR", "message": "Token não configurado"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"

    try:
        start = time.time()

        response = requests.get(url, timeout=5)

        latency = round((time.time() - start) * 1000, 2)

        if response.status_code != 200:
            return {
                "status": "DOWN",
                "latency_ms": latency
            }

        data = response.json()

        if data.get("ok"):
            return {
                "status": "UP",
                "latency_ms": latency,
                "bot": data["result"]["username"]
            }

        return {
            "status": "ERROR",
            "latency_ms": latency
        }

    except Exception as e:
        return {
            "status": "DOWN",
            "message": str(e)
        }
