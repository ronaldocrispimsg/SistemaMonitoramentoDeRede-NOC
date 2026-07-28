"""
Backend Services - Pattern Circuit Breaker
===============================================================================
Gerencia o estado de disponibilidade de hosts/dispositivos para evitar
tempestades de polling e esgotamento de portas de socket quando dispositivos estao DOWN.
Estados: CLOSED (Normal), OPEN (Disjuntor aberto - polling pausado), HALF-OPEN (Teste)
"""

import time
import logging

logger = logging.getLogger("netspot.circuit_breaker")


class HostCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 120.0):
        self.failure_threshold = failure_threshold  # N de falhas seguidas para abrir disjuntor
        self.recovery_timeout = recovery_timeout    # Segundos em OPEN antes de tentar HALF-OPEN
        self.failures = {}                          # host_id -> int (consecutive failures)
        self.state = {}                             # host_id -> "CLOSED" | "OPEN" | "HALF-OPEN"
        self.opened_at = {}                         # host_id -> float (timestamp when opened)

    def is_allowed(self, host_id: int) -> bool:
        """
        Retorna True se o polling for permitido para este host,
        ou False se o disjuntor estiver OPEN (em pausa de resguardo).
        """
        current_state = self.state.get(host_id, "CLOSED")

        if current_state == "CLOSED":
            return True

        if current_state == "OPEN":
            opened_time = self.opened_at.get(host_id, 0)
            if time.time() - opened_time >= self.recovery_timeout:
                logger.info(f"[CIRCUIT BREAKER] Host ID={host_id} transitou de OPEN para HALF-OPEN (Testando conectividade).")
                self.state[host_id] = "HALF-OPEN"
                return True
            return False

        if current_state == "HALF-OPEN":
            return True

        return True

    def record_success(self, host_id: int):
        """Registra uma checagem com sucesso e reseta o disjuntor para CLOSED."""
        if self.state.get(host_id) in ["OPEN", "HALF-OPEN"]:
            logger.info(f"[CIRCUIT BREAKER] Host ID={host_id} recuperou conectividade! Disjuntor FECHADO (CLOSED).")
        self.failures[host_id] = 0
        self.state[host_id] = "CLOSED"
        self.opened_at.pop(host_id, None)

    def record_failure(self, host_id: int):
        """Registra uma falha e abre o disjuntor se atingir o limite de falhas consecutivas."""
        count = self.failures.get(host_id, 0) + 1
        self.failures[host_id] = count

        if count >= self.failure_threshold and self.state.get(host_id) != "OPEN":
            logger.warning(
                f"[CIRCUIT BREAKER] Host ID={host_id} atingiu {count} falhas consecutivas. Disjuntor ABERTO (OPEN por {self.recovery_timeout}s)."
            )
            self.state[host_id] = "OPEN"
            self.opened_at[host_id] = time.time()


circuit_breaker = HostCircuitBreaker()
