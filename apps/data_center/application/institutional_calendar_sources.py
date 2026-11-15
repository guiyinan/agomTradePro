"""Retained public originals and explicit source qualification for calendar reads."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.data_center.domain.institutional_calendar import InstitutionalEvent
from core.exceptions import DataValidationError


@dataclass(frozen=True, slots=True)
class InstitutionalSourcePolicy:
    """Operator-configured, versioned permission for one bounded official source."""

    source_id: str
    event_type: str
    rule_version: str
    catalogue_sha256: str
    timezone_name: str
    attribution: str
    allowed_urls: tuple[str, ...]
    valid_until: datetime

    def __post_init__(self) -> None:
        """Reject incomplete qualification rather than manufacture source authority."""
        for value in (self.source_id, self.event_type, self.rule_version):
            if (
                not value
                or value != value.strip()
                or len(value) > 240
                or any(c.isspace() for c in value)
            ):
                raise _invalid("Source identity or rule version is invalid.")
        if (
            re.fullmatch(r"[0-9a-f]{64}", self.catalogue_sha256) is None
            or not self.attribution.strip()
        ):
            raise _invalid("Source catalogue or attribution is missing.")
        _utc(self.valid_until)
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise _invalid("Source timezone is unknown.") from error
        if not self.allowed_urls or len(set(self.allowed_urls)) != len(self.allowed_urls):
            raise _invalid("Source URL scope is missing or duplicated.")
        for url in self.allowed_urls:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
            ):
                raise _invalid("Source URL must be a public HTTPS permalink.")


@dataclass(frozen=True, slots=True)
class RetainedInstitutionalOriginal:
    """Exact original bytes with real receipt clocks and their qualification version."""

    policy: InstitutionalSourcePolicy
    url: str
    body: bytes
    sha256: str
    first_seen_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Require byte integrity, an approved permalink and honest ordered clocks."""
        _utc(self.first_seen_at)
        _utc(self.recorded_at)
        if (
            self.url not in self.policy.allowed_urls
            or type(self.body) is not bytes
            or not self.body
            or hashlib.sha256(self.body).hexdigest() != self.sha256
            or self.recorded_at < self.first_seen_at
            or self.first_seen_at >= self.policy.valid_until
        ):
            raise _invalid("Original bytes, URL or receipt clocks are invalid.")

    def validate_event(self, event: InstitutionalEvent) -> None:
        """Bind every published event to the exact source and its original clocks."""
        if (
            event.source_id != self.policy.source_id
            or event.event_type != self.policy.event_type
            or event.original_sha256 != self.sha256
            or event.first_seen_at != self.first_seen_at
            or event.recorded_at != self.recorded_at
        ):
            raise _invalid("Event and retained original differ.")


class InstitutionalOriginalRepositoryPort(Protocol):
    """Read retained evidence without exposing storage details to consumers."""

    def read(self, sha256: str) -> RetainedInstitutionalOriginal | None:
        """Return the exact original or an explicit evidence gap."""

    def verify_event(
        self, event: InstitutionalEvent, original: RetainedInstitutionalOriginal
    ) -> bool:
        """Reconstruct event semantics from original bytes, not merely a matching hash."""


def _utc(value: datetime) -> None:
    """Require exact UTC-aware clocks at the external evidence boundary."""
    offset = value.utcoffset() if isinstance(value, datetime) else None
    if offset is None or offset.total_seconds() != 0:
        raise _invalid("Original clocks must be UTC aware.")


def _invalid(message: str) -> DataValidationError:
    """Keep a stable source-integrity failure for every consumer."""
    return DataValidationError(message, code="INSTITUTIONAL_ORIGINAL_INVALID")


__all__ = [
    "InstitutionalOriginalRepositoryPort",
    "InstitutionalSourcePolicy",
    "RetainedInstitutionalOriginal",
]
