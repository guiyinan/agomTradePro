"""Application-layer repository providers for terminal interface code."""

from __future__ import annotations

from typing import Any, Protocol, cast

from apps.terminal.domain.interfaces import (
    TerminalAuditRepository,
    TerminalCommandRepository,
    TuiActionExecutor,
    TuiMetadataRepository,
)
from apps.terminal.infrastructure.providers import (
    TerminalApiRequestError as TerminalApiRequestError,
)
from apps.terminal.infrastructure.providers import (
    get_terminal_audit_repository as _get_terminal_audit_repository,
)
from apps.terminal.infrastructure.providers import (
    get_terminal_auth_user as _get_terminal_auth_user,
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
from apps.terminal.infrastructure.tui_adapters import (
    get_tui_action_executor as _get_tui_action_executor,
)
from apps.terminal.infrastructure.tui_metadata_repository import (
    get_tui_metadata_repository as _get_tui_metadata_repository,
)


def get_terminal_command_repository() -> TerminalCommandRepository:
    """Return the default terminal command repository."""

    return _get_terminal_command_repository()


def get_terminal_audit_repository() -> TerminalAuditRepository:
    """Return the default terminal audit repository."""

    return _get_terminal_audit_repository()


class TerminalRuntimeSettingsRepositoryProtocol(Protocol):
    """Runtime settings needed by Terminal application services."""

    def has_settings(self) -> bool: ...

    def get_settings(self) -> dict[str, Any]: ...


class TerminalCommandHttpClientProtocol(Protocol):
    """Outbound JSON request surface used by legacy Terminal commands."""

    def request_json(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any],
        timeout: int,
    ) -> tuple[int, Any]: ...


def get_terminal_runtime_settings_repository() -> TerminalRuntimeSettingsRepositoryProtocol:
    """Return the default terminal runtime settings repository."""

    return cast(
        TerminalRuntimeSettingsRepositoryProtocol,
        _get_terminal_runtime_settings_repository(),
    )


def get_terminal_command_http_client() -> TerminalCommandHttpClientProtocol:
    """Return the default terminal command HTTP client."""

    return cast(TerminalCommandHttpClientProtocol, _get_terminal_command_http_client())


def get_terminal_auth_user(user_id: int) -> Any:
    """Return the authenticated user object for internal terminal API calls."""

    return _get_terminal_auth_user(user_id)


def get_tui_metadata_repository() -> TuiMetadataRepository:
    """Return the default published TUI metadata repository."""

    return cast(TuiMetadataRepository, _get_tui_metadata_repository())


def get_tui_action_executor() -> TuiActionExecutor:
    """Return the default TUI action executor."""

    return cast(TuiActionExecutor, _get_tui_action_executor())
