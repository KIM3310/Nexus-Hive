"""
Custom exception types for Nexus-Hive.

Provides specific exception classes for SQL validation, policy enforcement,
agent orchestration, and circuit breaker patterns to replace generic exceptions
with meaningful, catchable error types.
"""

from typing import Any, Dict, List, Optional


class NexusHiveError(Exception):
    """Base exception for all Nexus-Hive errors."""

    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        """Initialize a NexusHiveError.

        Args:
            message: Human-readable error description.
            details: Optional dictionary of structured error context.
        """
        super().__init__(message)
        self.details: Dict[str, Any] = details or {}


class SQLValidationError(NexusHiveError):
    """Raised when SQL fails validation checks before execution.

    Examples include write operations, wildcard projections, or
    sensitive column access violations.
    """

    def __init__(
        self,
        message: str,
        *,
        sql: str = "",
        violation_type: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize a SQLValidationError.

        Args:
            message: Description of the validation failure.
            sql: The SQL statement that failed validation.
            violation_type: Category of the violation (e.g., 'write_operation', 'wildcard').
            details: Additional structured context.
        """
        super().__init__(message, details=details)
        self.sql: str = sql
        self.violation_type: str = violation_type


class PolicyDeniedError(NexusHiveError):
    """Raised when the policy engine denies a query.

    Contains the full policy verdict including deny reasons so callers
    can inspect why the query was rejected.
    """

    def __init__(
        self,
        message: str,
        *,
        deny_reasons: Optional[List[str]] = None,
        verdict: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize a PolicyDeniedError.

        Args:
            message: Human-readable denial explanation.
            deny_reasons: List of specific policy rules that triggered denial.
            verdict: The complete policy verdict dictionary.
            details: Additional structured context.
        """
        super().__init__(message, details=details)
        self.deny_reasons: List[str] = deny_reasons or []
        self.verdict: Dict[str, Any] = verdict or {}


class OllamaConnectionError(NexusHiveError):
    """Raised when the Ollama LLM service is unreachable or times out."""

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        model: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize an OllamaConnectionError.

        Args:
            message: Description of the connection failure.
            url: The Ollama endpoint URL that was unreachable.
            model: The model name that was requested.
            details: Additional structured context.
        """
        super().__init__(message, details=details)
        self.url: str = url
        self.model: str = model


class CircuitBreakerOpenError(NexusHiveError):
    """Raised when the circuit breaker is open and requests are being rejected.

    The circuit breaker prevents cascading failures by short-circuiting
    requests to a failing downstream service.
    """

    def __init__(
        self,
        message: str,
        *,
        service_name: str = "",
        failure_count: int = 0,
        reset_at: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize a CircuitBreakerOpenError.

        Args:
            message: Description of why the circuit is open.
            service_name: Name of the protected service.
            failure_count: Number of consecutive failures that opened the circuit.
            reset_at: ISO timestamp when the circuit will attempt to half-open.
            details: Additional structured context.
        """
        super().__init__(message, details=details)
        self.service_name: str = service_name
        self.failure_count: int = failure_count
        self.reset_at: Optional[str] = reset_at


class AgentOrchestrationError(NexusHiveError):
    """Raised when agent pipeline orchestration fails.

    Covers failures in the translator, executor, or visualizer nodes
    that cannot be retried within the standard retry budget.
    """

    def __init__(
        self,
        message: str,
        *,
        agent_name: str = "",
        retry_count: int = 0,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize an AgentOrchestrationError.

        Args:
            message: Description of the orchestration failure.
            agent_name: Name of the agent node that failed.
            retry_count: Number of retries attempted before giving up.
            details: Additional structured context.
        """
        super().__init__(message, details=details)
        self.agent_name: str = agent_name
        self.retry_count: int = retry_count
