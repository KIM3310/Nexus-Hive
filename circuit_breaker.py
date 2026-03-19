"""
Circuit breaker implementation for Ollama fallback protection.

Prevents cascading failures by tracking consecutive errors to the Ollama
LLM service and short-circuiting requests when the failure threshold is
exceeded. Automatically recovers after a configurable cooldown period.
"""

import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from exceptions import CircuitBreakerOpenError
from logging_config import logger


class CircuitState(Enum):
    """Possible states for a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker for protecting downstream service calls.

    The circuit breaker monitors consecutive failures and transitions through
    three states:
      - CLOSED: Normal operation; requests pass through.
      - OPEN: Failure threshold exceeded; requests are rejected immediately.
      - HALF_OPEN: After cooldown, one probe request is allowed through.

    Attributes:
        service_name: Name of the protected service for logging.
        failure_threshold: Number of consecutive failures before opening.
        recovery_timeout_sec: Seconds to wait before transitioning to half-open.
    """

    def __init__(
        self,
        service_name: str = "ollama",
        failure_threshold: int = 5,
        recovery_timeout_sec: float = 60.0,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            service_name: Identifier for the downstream service being protected.
            failure_threshold: Consecutive failure count that triggers the circuit to open.
            recovery_timeout_sec: Seconds to wait in OPEN state before allowing a probe.
        """
        self.service_name: str = service_name
        self.failure_threshold: int = failure_threshold
        self.recovery_timeout_sec: float = recovery_timeout_sec

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: Optional[float] = None
        self._lock: threading.Lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Return the current circuit breaker state.

        Automatically transitions from OPEN to HALF_OPEN when the recovery
        timeout has elapsed.

        Returns:
            The current :class:`CircuitState`.
        """
        with self._lock:
            if self._state == CircuitState.OPEN and self._last_failure_time is not None:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout_sec:
                    self._state = CircuitState.HALF_OPEN
                    logger.info(
                        "Circuit breaker transitioning to HALF_OPEN",
                        extra={
                            "extra_fields": {
                                "circuit_service": self.service_name,
                                "elapsed_sec": round(elapsed, 1),
                            }
                        },
                    )
            return self._state

    @property
    def failure_count(self) -> int:
        """Return the current consecutive failure count.

        Returns:
            The number of consecutive failures recorded.
        """
        with self._lock:
            return self._failure_count

    def check(self) -> None:
        """Check whether a request is allowed through the circuit.

        Raises:
            CircuitBreakerOpenError: If the circuit is OPEN and the recovery
                timeout has not yet elapsed.
        """
        current_state = self.state
        if current_state == CircuitState.OPEN:
            reset_at_str: Optional[str] = None
            if self._last_failure_time is not None:
                reset_epoch = self._last_failure_time + self.recovery_timeout_sec
                reset_at_str = datetime.fromtimestamp(
                    reset_epoch, tz=timezone.utc
                ).isoformat()

            raise CircuitBreakerOpenError(
                f"Circuit breaker is OPEN for {self.service_name}; "
                f"{self._failure_count} consecutive failures.",
                service_name=self.service_name,
                failure_count=self._failure_count,
                reset_at=reset_at_str,
            )

    def record_success(self) -> None:
        """Record a successful call, resetting the failure counter and closing the circuit."""
        with self._lock:
            previous_state = self._state
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._last_failure_time = None

        if previous_state != CircuitState.CLOSED:
            logger.info(
                "Circuit breaker CLOSED after successful probe",
                extra={
                    "extra_fields": {
                        "circuit_service": self.service_name,
                        "previous_state": previous_state.value,
                    }
                },
            )

    def record_failure(self) -> None:
        """Record a failed call and potentially open the circuit."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker OPENED due to consecutive failures",
                    extra={
                        "extra_fields": {
                            "circuit_service": self.service_name,
                            "failure_count": self._failure_count,
                            "threshold": self.failure_threshold,
                            "recovery_timeout_sec": self.recovery_timeout_sec,
                        }
                    },
                )
            else:
                logger.debug(
                    "Circuit breaker recorded failure",
                    extra={
                        "extra_fields": {
                            "circuit_service": self.service_name,
                            "failure_count": self._failure_count,
                            "threshold": self.failure_threshold,
                        }
                    },
                )

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None

        logger.info(
            "Circuit breaker manually reset",
            extra={"extra_fields": {"circuit_service": self.service_name}},
        )


# Module-level singleton for the Ollama circuit breaker
ollama_circuit_breaker = CircuitBreaker(
    service_name="ollama",
    failure_threshold=5,
    recovery_timeout_sec=60.0,
)
