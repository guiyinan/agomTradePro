"""Exact Portfolio owner query port for persisted R4 rolling research."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.application.r4_rolling_research_record import R4RollingResearchRecord


def _opaque_key(namespace: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join((namespace, *parts)).encode("utf-8")).hexdigest()
    return f"por4:{digest}"


@dataclass(frozen=True)
class R4RollingResearchOwnerRecord:
    """Neutral exact owner envelope for downstream dependency injection."""

    owner: str
    owner_record_key: str
    record: R4RollingResearchRecord

    @classmethod
    def create(cls, record: R4RollingResearchRecord) -> R4RollingResearchOwnerRecord:
        """Derive opaque owner and unit-of-work keys from an exact record."""

        owner_record_key = _opaque_key(
            "portfolio-r4-owner-record.v1",
            record.record_id,
            record.record_hash,
        )
        return cls(
            owner="portfolio",
            owner_record_key=owner_record_key,
            record=record,
        )

    def __post_init__(self) -> None:
        if self.owner != "portfolio" or self.record.owner != "portfolio":
            raise ValueError("R4 owner record must remain Portfolio-owned")
        expected_owner_key = _opaque_key(
            "portfolio-r4-owner-record.v1",
            self.record.record_id,
            self.record.record_hash,
        )
        if self.owner_record_key != expected_owner_key:
            raise ValueError("R4 owner record key mismatch")


class R4RollingResearchExactQuery(Protocol):
    """Read one exact PIT-valid Portfolio owner record; never latest/current/list."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the opaque database transaction boundary key."""

    def get_exact(
        self,
        *,
        record_id: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R4RollingResearchOwnerRecord | None:
        """Return only an exact hash match known and valid at ``as_of``."""


__all__ = ["R4RollingResearchExactQuery", "R4RollingResearchOwnerRecord"]
