"""Stable Domain exceptions for Terminal command execution."""


class TerminalCommandExecutionError(RuntimeError):
    """Raised when a command cannot safely complete its configured execution."""


class TerminalAuditPersistenceError(RuntimeError):
    """Raised when a Terminal audit entry cannot be persisted."""
