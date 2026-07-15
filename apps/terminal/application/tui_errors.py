"""Application-level errors for published TUI screen navigation."""

from __future__ import annotations


class TuiScreenNavigationError(LookupError):
    """Base error raised when a published TUI screen cannot be opened."""

    error_code = "tui_screen_navigation_error"

    def __init__(self, screen_key: str) -> None:
        self.screen_key = screen_key
        super().__init__(screen_key)


class TuiScreenNotFoundError(TuiScreenNavigationError):
    """Raised when a requested screen key is not published."""

    error_code = "tui_screen_not_found"


class TuiScreenForbiddenError(TuiScreenNavigationError):
    """Raised when the current user is outside a screen's audience."""

    error_code = "tui_screen_forbidden"
