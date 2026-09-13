"""Application contracts for isolated Evidence V5 read phases."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class AccountOwnerAssignmentEvidenceV5ReadPhase(Protocol):
    """Create one short-lived immutable read phase after source locks."""

    def __call__(self) -> AbstractContextManager[None]:
        """Return a fresh phase whose observations end before mutation."""

        ...


__all__ = ["AccountOwnerAssignmentEvidenceV5ReadPhase"]
