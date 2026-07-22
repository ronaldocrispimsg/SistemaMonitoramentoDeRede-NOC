"""
Backend SNMP - Cache de OIDs por Host
===============================================================================
Gerenciador de cache em memoria (Thread-Safe e Async-Safe) para armazenar os
OIDs operacionais descobertos para cada host, evitando buscas redundantes.
"""

import asyncio
from threading import Lock
from typing import Dict, Any, Optional

_CACHE_LOCK = Lock()
_OID_CACHE: Dict[int, Dict[str, Any]] = {}


def get_cached_oids(host_id: int) -> Optional[Dict[str, Any]]:
    """Retorna os OIDs em cache para o host_id ou None se nao existir."""
    with _CACHE_LOCK:
        cached = _OID_CACHE.get(host_id)
        return dict(cached) if cached else None


def set_cached_oid(host_id: int, key: str, value: Any) -> None:
    """Atualiza uma chave especifica do cache de OIDs de um host."""
    with _CACHE_LOCK:
        if host_id not in _OID_CACHE:
            _OID_CACHE[host_id] = {}
        _OID_CACHE[host_id][key] = value


def set_cached_oids_bulk(host_id: int, oids_dict: Dict[str, Any]) -> None:
    """Substitui ou atualiza o dicionario completo de OIDs em cache para um host."""
    with _CACHE_LOCK:
        if host_id not in _OID_CACHE:
            _OID_CACHE[host_id] = {}
        _OID_CACHE[host_id].update(oids_dict)


def clear_oid_cache(host_id: Optional[int] = None) -> int:
    """Limpa o cache de um host especifico ou de todos os hosts se host_id=None."""
    with _CACHE_LOCK:
        if host_id is None:
            count = len(_OID_CACHE)
            _OID_CACHE.clear()
            return count
        return 1 if _OID_CACHE.pop(host_id, None) is not None else 0
