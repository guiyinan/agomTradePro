"""Broker-execution application exceptions."""


class BrokerExecutionError(Exception):
    """Base application error for broker execution."""


class BrokerExecutionPermissionError(BrokerExecutionError):
    """Raised when an actor cannot access an execution resource."""


class BrokerExecutionNotFoundError(BrokerExecutionError):
    """Raised when a scoped execution resource does not exist."""


class BrokerExecutionConflictError(BrokerExecutionError):
    """Raised for lifecycle or idempotency conflicts."""


class BrokerExecutionValidationError(BrokerExecutionError):
    """Raised for invalid broker-execution inputs."""


class BrokerAgentAuthenticationError(BrokerExecutionPermissionError):
    """Raised when a local Agent request cannot be authenticated."""
