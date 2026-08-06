"""Django adapter for the exact Portfolio R4 rolling owner query port."""

from __future__ import annotations

from datetime import datetime

from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchOwnerRecord,
)

from .r4_rolling_research_repository import DjangoR4RollingResearchRepository


class DjangoR4RollingResearchExactQuery:
    """Return only exact hash-bound records known and valid at a PIT cutoff."""

    def __init__(
        self,
        repository: DjangoR4RollingResearchRepository | None = None,
    ) -> None:
        self._repository = repository or DjangoR4RollingResearchRepository()

    @property
    def unit_of_work_key(self) -> str:
        """Return the repository's actual database transaction boundary."""

        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        record_id: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R4RollingResearchOwnerRecord | None:
        """Restore a typed record and enforce identity, hash, and PIT validity."""

        if not record_id.strip():
            raise ValueError("record_id cannot be blank")
        if len(expected_record_hash) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in expected_record_hash
        ):
            raise ValueError("expected_record_hash must be a sha256 digest")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        record = self._repository.get(record_id)
        if record is None or record.record_hash.lower() != expected_record_hash.lower():
            return None
        if not record.recorded_at <= as_of < record.valid_until:
            return None
        return R4RollingResearchOwnerRecord.create(record)


__all__ = ["DjangoR4RollingResearchExactQuery"]
