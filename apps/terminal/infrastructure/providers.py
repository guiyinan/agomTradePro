"""Repository provider re-exports for application composition roots."""

from .http_client import TerminalApiRequestError, TerminalCommandHttpClient
from .repositories import *  # noqa: F401,F403


def get_terminal_command_http_client() -> TerminalCommandHttpClient:
    """Return the default HTTP client for terminal API commands."""
    return TerminalCommandHttpClient()
