#!/usr/bin/env python3
from __future__ import annotations

"""
Checklist automatizado da lógica de alertas/incidentes.

Este script é um "smoke test" leve (sem framework pesado) para validar
os cenários operacionais mais importantes do NOC Lite.

Como usar:
    PYTHONPATH=. .venv/bin/python Backend/tests/alert_logic_checklist.py

Saída esperada:
    [OK] <cenário ...>
ou
    [FAIL] <cenário ...>

Código de saída:
    0 -> todos os cenários aprovados
    1 -> pelo menos um cenário falhou
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Permite executar o script direto: `python Backend/tests/alert_logic_checklist.py`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Backend.models import Base, Host, CheckResult, Incident
import Backend.utils as utils
import Backend.scheduler as scheduler
from Backend.routes.hosts import infer_probable_cause


def make_session():
    """Cria uma sessão isolada em SQLite in-memory para testes rápidos."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    # autoflush=True para garantir que objetos pendentes sejam visíveis
    # nas consultas durante o próprio teste sem exigir flush manual extra.
    Session = sessionmaker(autocommit=False, autoflush=True, bind=engine)
    return Session()


def make_host(name: str, address: str, port: int | None = None, http_url: str | None = None) -> Host:
    """Monta um Host base para os cenários de teste."""
    return Host(
        name=name,
        address=address,
        port=port,
        http_url=http_url,
        active=True,
        status="UNKNOWN",
        status_ping="UNKNOWN",
        status_tcp="UNKNOWN",
        last_check=datetime.now(timezone.utc),
        health_score=100,
        severity="HEALTHY",
        fail_streak=0,
        success_streak=0,
    )


def open_incident_count(db, host_name: str, incident_type: str | None = None) -> int:
    """
    Conta incidentes abertos de um host.

    Se incident_type for informado, conta apenas daquele tipo.
    """
    rows = db.query(Incident).filter(Incident.host_name == host_name, Incident.status == "OPEN").all()
    if incident_type is None:
        return len(rows)
    return sum(1 for i in rows if utils.parse_incident_type(i.reason) == incident_type)


def run():
    """Executa os 7 cenários do checklist e imprime resultado linha a linha."""
    db = make_session()

    # Captura mensagens de Telegram sem fazer chamada externa real.
    # Isso permite validar "mensagem gerada" sem depender de rede.
    telegram_messages = []
    utils.send_telegram_alert = lambda message: telegram_messages.append(message) or True

    # Limpa estado global de cooldown para o teste começar "limpo".
    scheduler._ALERT_COOLDOWN_STATE.clear()

    results = []

    # ------------------------------------------------------------------
    # 1) ICMP bloqueado não gera incidente
    # ------------------------------------------------------------------
    # Simula ping com falha, mas TCP/HTTP com sucesso.
    # Esperado:
    # - estado UP
    # - check principal HTTP
    # - flag de ICMP bloqueado ativa
    # - causa provável coerente
    # - nenhum incidente aberto
    h1 = make_host("host-icmp", "icmp.example", port=80, http_url="http://icmp.example")
    db.add(h1)
    db.flush()
    db.add(CheckResult(host_id=h1.id, host_name=h1.name, check_type="ping", success=False, latency=None, error="timeout"))
    db.add(CheckResult(host_id=h1.id, host_name=h1.name, check_type="tcp", success=True, latency=20, error=None))
    db.add(CheckResult(host_id=h1.id, host_name=h1.name, check_type="http", success=True, latency=120, error=None, status_code=200))
    h1.status = "UP"
    state, primary, icmp_blocked = scheduler.determine_operational_state(
        h1,
        {"success": False, "latency": None},
        {"success": True, "latency": 20},
        {"success": True, "latency": 120, "status_code": 200},
    )
    cause = infer_probable_cause(db, h1)
    results.append(state == "UP" and primary == "HTTP" and icmp_blocked and "ICMP bloqueado por firewall" in cause and open_incident_count(db, h1.name) == 0)

    # ------------------------------------------------------------------
    # 2) Serviço degradado
    # ------------------------------------------------------------------
    # Simula cenário com HTTP falhando, mas com resposta parcial de serviço.
    # Esperado:
    # - estado DEGRADED
    # - incidente SERVICE_DEGRADED aberto
    h2 = make_host("host-degraded", "degraded.example", port=80, http_url="http://degraded.example")
    db.add(h2)
    db.flush()
    state2, primary2, _ = scheduler.determine_operational_state(
        h2,
        {"success": False, "latency": None},
        {"success": True, "latency": 30},
        {"success": False, "latency": 900, "status_code": 503},
    )
    if state2 == "DEGRADED":
        utils.open_incident(db, h2, "Instabilidade detectada no serviço HTTP", incident_type=utils.INCIDENT_TYPE_SERVICE_DEGRADED, check_used=primary2, auto_commit=False)
        db.commit()
    results.append(state2 == "DEGRADED" and open_incident_count(db, h2.name, utils.INCIDENT_TYPE_SERVICE_DEGRADED) == 1)

    # ------------------------------------------------------------------
    # 3) Serviço indisponível
    # ------------------------------------------------------------------
    # Simula falha total dos checks de serviço.
    # Esperado:
    # - estado DOWN
    # - incidente SERVICE_DOWN aberto
    h3 = make_host("host-down", "down.example", port=80, http_url="http://down.example")
    db.add(h3)
    db.flush()
    state3, primary3, _ = scheduler.determine_operational_state(
        h3,
        {"success": False, "latency": None},
        {"success": False, "latency": None},
        {"success": False, "latency": None, "status_code": None},
    )
    if state3 == "DOWN":
        utils.open_incident(db, h3, "Serviço HTTP indisponível", incident_type=utils.INCIDENT_TYPE_SERVICE_DOWN, check_used=primary3, auto_commit=False)
        db.commit()
    results.append(state3 == "DOWN" and open_incident_count(db, h3.name, utils.INCIDENT_TYPE_SERVICE_DOWN) == 1)

    # ------------------------------------------------------------------
    # 4) DNS failure
    # ------------------------------------------------------------------
    # Abre incidente explícito de DNS.
    # Esperado:
    # - incidente DNS_FAILURE aberto
    h4 = make_host("host-dns", "dns.example")
    db.add(h4)
    db.flush()
    utils.open_incident(db, h4, "Falha na resolução DNS", incident_type=utils.INCIDENT_TYPE_DNS_FAILURE, check_used="DNS", auto_commit=False)
    db.commit()
    results.append(open_incident_count(db, h4.name, utils.INCIDENT_TYPE_DNS_FAILURE) == 1)

    # ------------------------------------------------------------------
    # 5) Recuperação
    # ------------------------------------------------------------------
    # Fecha incidente SERVICE_DOWN e valida:
    # - incidente fechado
    # - mensagem de recuperação gerada
    utils.close_incident(db, h3.name, incident_type=utils.INCIDENT_TYPE_SERVICE_DOWN, auto_commit=False)
    db.commit()
    recovery_ok = (
        open_incident_count(db, h3.name, utils.INCIDENT_TYPE_SERVICE_DOWN) == 0 and
        any(isinstance(m, dict) and m.get("event") == "incident_closed" and m.get("incident_type") == utils.INCIDENT_TYPE_SERVICE_DOWN for m in telegram_messages)
    )
    results.append(recovery_ok)

    # ------------------------------------------------------------------
    # 6) Cooldown de alerta
    # ------------------------------------------------------------------
    # Duas tentativas do mesmo fingerprint dentro da janela.
    # Esperado:
    # - primeira passa
    # - segunda é bloqueada
    first = scheduler._alert_cooldown_passed(999, "DNS_CHANGE", 60, "x->y")
    second = scheduler._alert_cooldown_passed(999, "DNS_CHANGE", 60, "x->y")
    results.append(first and not second)

    # ------------------------------------------------------------------
    # 7) Incidente duplicado
    # ------------------------------------------------------------------
    # Abre duas vezes o mesmo incidente no mesmo host/tipo.
    # Esperado:
    # - apenas 1 incidente aberto (sem duplicação)
    h7 = make_host("host-dup", "dup.example", port=443, http_url="https://dup.example")
    db.add(h7)
    db.flush()
    utils.open_incident(db, h7, "Serviço HTTP indisponível", incident_type=utils.INCIDENT_TYPE_SERVICE_DOWN, check_used="HTTP", auto_commit=False)
    utils.open_incident(db, h7, "Serviço HTTP indisponível", incident_type=utils.INCIDENT_TYPE_SERVICE_DOWN, check_used="HTTP", auto_commit=False)
    db.commit()
    results.append(open_incident_count(db, h7.name, utils.INCIDENT_TYPE_SERVICE_DOWN) == 1)

    labels = [
        "ICMP bloqueado tratado corretamente",
        "Serviço degradado abre incidente correto",
        "Serviço indisponível detectado",
        "DNS failure detectado",
        "Recuperação detectada",
        "Cooldown de alerta funcionando",
        "Incidente duplicado prevenido",
    ]

    # Imprime resultado final em formato simples para leitura rápida.
    all_ok = True
    for label, ok in zip(labels, results):
        if ok:
            print(f"[OK] {label}")
        else:
            print(f"[FAIL] {label}")
            all_ok = False

    db.close()
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    run()
