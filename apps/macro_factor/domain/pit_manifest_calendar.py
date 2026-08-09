"""Canonical target-calendar membership carried by one R3 PIT manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date


def _require_token(value: str, field_name: str, *, maximum: int = 160) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a non-blank bounded token")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PITInferenceCalendarPeriodEvidence:
    """Exact owner-issued inference-period member sealed by a PIT manifest."""

    calendar_id: str
    calendar_version: str
    calendar_hash: str
    period_id: str
    period_start: date
    period_end: date
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        calendar_version: str,
        calendar_hash: str,
        period_id: str,
        period_start: date,
        period_end: date,
    ) -> PITInferenceCalendarPeriodEvidence:
        """Create one exact calendar-owner member with a live content seal."""

        payload = cls._payload(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_hash=calendar_hash,
            period_id=period_id,
            period_start=period_start,
            period_end=period_end,
        )
        return cls(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_hash=calendar_hash,
            period_id=period_id,
            period_start=period_start,
            period_end=period_end,
            content_hash=_hash_payload(payload),
        )

    @staticmethod
    def _payload(
        *,
        calendar_id: str,
        calendar_version: str,
        calendar_hash: str,
        period_id: str,
        period_start: date,
        period_end: date,
    ) -> dict[str, object]:
        return {
            "calendar_id": calendar_id,
            "calendar_version": calendar_version,
            "calendar_hash": calendar_hash,
            "period_id": period_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }

    def __post_init__(self) -> None:
        _require_token(self.calendar_id, "PITInferenceCalendarPeriodEvidence.calendar_id")
        _require_token(
            self.calendar_version,
            "PITInferenceCalendarPeriodEvidence.calendar_version",
        )
        _require_sha256(
            self.calendar_hash,
            "PITInferenceCalendarPeriodEvidence.calendar_hash",
        )
        _require_token(self.period_id, "PITInferenceCalendarPeriodEvidence.period_id")
        if self.period_start > self.period_end:
            raise ValueError("PIT inference calendar period is invalid")
        _require_sha256(self.content_hash, "PITInferenceCalendarPeriodEvidence.content_hash")
        expected = _hash_payload(
            self._payload(
                calendar_id=self.calendar_id,
                calendar_version=self.calendar_version,
                calendar_hash=self.calendar_hash,
                period_id=self.period_id,
                period_start=self.period_start,
                period_end=self.period_end,
            )
        )
        if self.content_hash.lower() != expected:
            raise ValueError("PIT inference calendar member hash does not match content")

    def canonical_payload(self) -> dict[str, object]:
        """Return the exact owner and period membership evidence."""

        return {
            **self._payload(
                calendar_id=self.calendar_id,
                calendar_version=self.calendar_version,
                calendar_hash=self.calendar_hash,
                period_id=self.period_id,
                period_start=self.period_start,
                period_end=self.period_end,
            ),
            "content_hash": self.content_hash,
        }

    def validated_copy(self) -> PITInferenceCalendarPeriodEvidence:
        """Reconstruct the owner member and verify its seal live."""

        return PITInferenceCalendarPeriodEvidence(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            calendar_hash=self.calendar_hash,
            period_id=self.period_id,
            period_start=self.period_start,
            period_end=self.period_end,
            content_hash=self.content_hash,
        )


__all__ = ["PITInferenceCalendarPeriodEvidence"]
