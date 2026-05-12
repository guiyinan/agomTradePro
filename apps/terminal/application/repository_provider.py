"""Application-layer repository providers for terminal interface code."""

from __future__ import annotations

from apps.terminal.domain.interfaces import TerminalAuditRepository, TerminalCommandRepository
from apps.terminal.infrastructure.providers import (
    TerminalApiRequestError,  # noqa: F401
)
from apps.terminal.infrastructure.providers import (
    get_terminal_audit_repository as _get_terminal_audit_repository,
)
from apps.terminal.infrastructure.providers import (
    get_terminal_command_http_client as _get_terminal_command_http_client,
)
from apps.terminal.infrastructure.providers import (
    get_terminal_command_repository as _get_terminal_command_repository,
)
from apps.terminal.infrastructure.providers import (
    get_terminal_runtime_settings_repository as _get_terminal_runtime_settings_repository,
)


def get_terminal_command_repository() -> TerminalCommandRepository:
    """Return the default terminal command repository."""

    return _get_terminal_command_repository()


def get_terminal_audit_repository() -> TerminalAuditRepository:
    """Return the default terminal audit repository."""

    return _get_terminal_audit_repository()


def get_terminal_runtime_settings_repository():
    """Return the default terminal runtime settings repository."""

    return _get_terminal_runtime_settings_repository()


def get_terminal_command_http_client():
    """Return the default terminal command HTTP client."""

    return _get_terminal_command_http_client()
