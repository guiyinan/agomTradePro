"""Repository provider re-exports for application composition roots."""

from django.contrib.auth import get_user_model

from .http_client import TerminalApiRequestError, TerminalCommandHttpClient  # noqa: F401
from .repositories import *  # noqa: F401,F403


def get_terminal_command_http_client() -> TerminalCommandHttpClient:
    """Return the default HTTP client for terminal API commands."""
    return TerminalCommandHttpClient()


def get_terminal_auth_user(user_id: int):
    """Return a Django user for internal terminal API authentication."""

    return get_user_model()._default_manager.filter(pk=user_id).first()
