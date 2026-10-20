"""Application port for an independently sourced first-position mark."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof


class InitialPositionMarkReader(Protocol):
    """Read a source-backed apply-time valuation mark for one exact instrument."""

    def read_initial_position_mark(
        self,
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> InitialPositionMarkProof | None:
        """Return independently obtained evidence or ``None`` when unavailable.

        Implementations must not synthesize source identity, clocks, hashes,
        or policy fields from the requested instrument. Callers must validate
        the returned proof against the same identity and ``read_at``. This
        protocol has no default implementation or authorized source binding.
        """


__all__ = ("InitialPositionMarkReader",)
