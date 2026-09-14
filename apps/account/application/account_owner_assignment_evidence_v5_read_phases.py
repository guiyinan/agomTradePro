"""Application contracts for isolated Evidence V5 read phases."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar, Token
from typing import Protocol


class AccountOwnerAssignmentEvidenceV5ReadPhase(Protocol):
    """Create one short-lived immutable read phase after source locks."""

    def __call__(self) -> AbstractContextManager[None]:
        """Return a fresh phase whose observations end before mutation."""

        ...


_evidence_v5_read_phase_owner: ContextVar[object | None] = ContextVar(
    "account_owner_assignment_evidence_v5_read_phase_owner",
    default=None,
)


def _current_evidence_v5_read_phase_owner() -> object | None:
    """Return the repository object that owns the active read phase, if any."""

    return _evidence_v5_read_phase_owner.get()


@contextmanager
def _bind_evidence_v5_read_phase_owner(owner: object) -> Iterator[None]:
    """Mark one isolated phase so only its repository may reuse the cache."""

    token: Token[object | None] = _evidence_v5_read_phase_owner.set(owner)
    try:
        yield
    finally:
        _evidence_v5_read_phase_owner.reset(token)


__all__ = ["AccountOwnerAssignmentEvidenceV5ReadPhase"]
