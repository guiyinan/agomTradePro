"""Repository provider re-exports for application composition roots."""

from typing import Any

from django.contrib.auth import get_user_model

from .http_client import (
    TerminalApiRequestError as TerminalApiRequestError,
)
from .http_client import TerminalCommandHttpClient
from .repositories import (
    get_terminal_audit_repository as get_terminal_audit_repository,
)
from .repositories import (
    get_terminal_command_repository as get_terminal_command_repository,
)
from .repositories import (
    get_terminal_runtime_settings_repository as get_terminal_runtime_settings_repository,
)


def get_terminal_command_http_client() -> TerminalCommandHttpClient:
    """Return the default HTTP client for terminal API commands."""
    return TerminalCommandHttpClient()


def get_terminal_auth_user(user_id: int) -> Any:
    """Return a Django user for internal terminal API authentication."""

    return get_user_model()._default_manager.filter(pk=user_id).first()
