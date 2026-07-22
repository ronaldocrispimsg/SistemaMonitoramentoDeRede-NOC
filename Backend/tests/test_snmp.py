"""
Backend Test Suite - Testes do Modulo SNMP Multivendor
===============================================================================
Testa os conversores seguros de valores SNMP, dicionarios de OIDs e
funcoes utilitarias de resolucao de MIBs.
"""

import pytest
from Backend.snmp.oid_database import KNOWN_OIDS_CPU, KNOWN_OIDS_RAM, KNOWN_OIDS_STORAGE, KNOWN_OIDS_NETWORK
from Backend.snmp_engine import _to_float, _compute_delta_octets


def test_to_float_valid():
    """Testa conversao segura de strings e numeros para float."""
    assert _to_float("42.5") == 42.5
    assert _to_float(100) == 100.0
    assert _to_float("0") == 0.0


def test_to_float_invalid():
    """Testa tratamento de None, strings vazias e tipos invalidos sem crash."""
    assert _to_float(None) is None
    assert _to_float("") is None
    assert _to_float(b"") is None
    assert _to_float("invalido") is None


def test_compute_delta_octets_32bit():
    """Testa calculo de delta para contadores de 32-bit (tratando overflow)."""
    # Caso normal
    assert _compute_delta_octets(2000, 1000, 32) == 1000

    # Overflow do contador 32-bit (2^32 = 4294967296)
    modulo = 2 ** 32
    prev = modulo - 500
    curr = 500
    assert _compute_delta_octets(curr, prev, 32) == 1000


def test_compute_delta_octets_64bit():
    """Testa calculo de delta para contadores de 64-bit HC."""
    assert _compute_delta_octets(5000000, 1000000, 64) == 4000000
    assert _compute_delta_octets(100, 500, 64) == 0  # Previne valores negativos


def test_oid_database_catalogs():
    """Testa a presenca das OIDs conhecidas de fabricantes (Linux, Windows, Cisco, Mikrotik)."""
    assert len(KNOWN_OIDS_CPU) >= 3
    assert len(KNOWN_OIDS_RAM) >= 2
    assert "mount_keywords" in KNOWN_OIDS_STORAGE
    assert "if_oper_status" in KNOWN_OIDS_NETWORK
