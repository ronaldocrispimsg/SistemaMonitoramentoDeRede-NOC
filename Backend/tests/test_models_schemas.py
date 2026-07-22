"""
Backend Test Suite - Testes de Modelos ORM e Schemas Pydantic
===============================================================================
Valida a instanciacao das entidades de dados e validacoes de DTOs.
"""

import pytest
from Backend.models import Host, CheckResult, SNMPMetric, Alert, Incident
from Backend.schemas import HostCreate, HostUpdate


def test_host_model_instantiation():
    """Testa a instanciacao do modelo Host."""
    host = Host(
        name="Servidor-Teste",
        address="192.168.1.100",
        active=True,
        snmp_enabled=True,
        snmp_community="netspot"
    )
    assert host.name == "Servidor-Teste"
    assert host.address == "192.168.1.100"
    assert host.snmp_community == "netspot"


def test_host_schema_pydantic_validation():
    """Testa a validacao de DTOs Pydantic HostCreate."""
    dto = HostCreate(
        name="Router-Core",
        address="10.0.0.1",
        snmp_community="netspot"
    )
    assert dto.name == "Router-Core"
    assert dto.snmp_community == "netspot"


def test_check_result_model():
    """Testa a instanciacao de CheckResult."""
    cr = CheckResult(
        host_id=1,
        check_type="ping",
        success=True,
        latency=12.5,
        status_code=200
    )
    assert cr.host_id == 1
    assert cr.success is True
    assert cr.latency == 12.5
