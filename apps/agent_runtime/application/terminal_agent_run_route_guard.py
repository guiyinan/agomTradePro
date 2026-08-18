"""Fail-closed guard for the reserved queued Terminal Agent routes.

TAR-01 reserves the asynchronous route names, but TAR-02 has not supplied a
durable admission adapter yet.  The interface may expose these paths as a
stable dormant boundary; this module deliberately contains no Django, ORM,
Celery, broker, or legacy inline Agent-service dependency.
"""

from __future__ import annotations

from typing import ClassVar, NoReturn

from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalRunContractError,
)


class TerminalQueuedRuntimeUnavailable(TerminalRunContractError):
    """Stable fail-closed error while queued dispatch is not wired."""

    code: ClassVar[str] = "DISPATCH_UNAVAILABLE"
    status_code: ClassVar[int] = 503
    retry_after_seconds: ClassVar[int] = 60
    reason_code: ClassVar[str] = "queued_runtime_not_wired"

    def __init__(self) -> None:
        """Create the redacted queued-runtime-unavailable error."""

        super().__init__(self.reason_code)


def reject_terminal_queued_route() -> NoReturn:
    """Reject queued intake until TAR-02 supplies durable admission."""

    raise TerminalQueuedRuntimeUnavailable()
