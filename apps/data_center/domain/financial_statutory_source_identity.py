"""Exact reference to a retained public statutory source, without encryption claims."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference

FINANCIAL_STATUTORY_SOURCE_IDENTITY_SCHEMA = "financial-statutory-source-identity.v1"


@dataclass(frozen=True, slots=True)
class FinancialStatutorySourceIdentity:
    """Preserve an exact statutory lookup and its actual storage/knowledge identity.

    This reference establishes no official provenance by itself. A qualified
    reader must restore the exact native revision, capture and body. It makes
    no assertions about encrypted storage or keys.
    """

    issuer: str
    document_id: str
    source_version: str
    source_revision_sha256: str
    source_uri: str
    body_reference: StatutorySourceBodyReference
    first_seen_at: datetime
    revision_recorded_at: datetime
    capture_observed_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Require exact native selectors, typed storage and ordered UTC clocks."""

        for name, value, maximum in (
            ("issuer", self.issuer, 240),
            ("document_id", self.document_id, 240),
            ("source_version", self.source_version, 120),
            ("source_uri", self.source_uri, 4096),
        ):
            if (
                type(value) is not str
                or not value
                or value.strip() != value
                or len(value) > maximum
            ):
                raise ValueError(f"statutory source {name} is invalid")
        parsed = urlsplit(self.source_uri)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("statutory source URI must be an exact HTTPS location")
        digest = self.source_revision_sha256
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("statutory source revision digest is invalid")
        if type(self.body_reference) is not StatutorySourceBodyReference:
            raise TypeError("statutory source requires an exact storage-issued body reference")
        self.body_reference.__post_init__()
        for name, clock_value in (
            ("first_seen_at", self.first_seen_at),
            ("revision_recorded_at", self.revision_recorded_at),
            ("capture_observed_at", self.capture_observed_at),
            ("recorded_at", self.recorded_at),
        ):
            if type(clock_value) is not datetime or clock_value.tzinfo is None:
                raise ValueError(f"statutory source {name} must be explicit UTC")
            offset = clock_value.utcoffset()
            if offset is None or offset.total_seconds() != 0:
                raise ValueError(f"statutory source {name} must be explicit UTC")
            try:
                clock_value.astimezone(UTC)
            except (ValueError, OverflowError) as error:
                raise ValueError(f"statutory source {name} is outside UTC range") from error
        if not self.first_seen_at <= self.capture_observed_at <= self.recorded_at:
            raise ValueError("statutory capture observation clocks are not ordered")
        if self.revision_recorded_at > self.recorded_at:
            raise ValueError("statutory revision record postdates capture record")

    @property
    def capture_id(self) -> UUID:
        """Return the exact capture bound by the storage reference."""

        return self.body_reference.capture_id

    @property
    def body_sha256(self) -> str:
        """Return the exact original-body digest."""

        return self.body_reference.body_sha256

    @property
    def body_size_bytes(self) -> int:
        """Return the exact original-body size."""

        return self.body_reference.body_size_bytes

    def to_dict(self) -> dict[str, object]:
        """Serialize an explicit storage-kind branch without manufactured key metadata."""

        self.__post_init__()
        return {
            "schema": FINANCIAL_STATUTORY_SOURCE_IDENTITY_SCHEMA,
            "issuer": self.issuer,
            "document_id": self.document_id,
            "source_version": self.source_version,
            "source_revision_sha256": self.source_revision_sha256,
            "source_uri": self.source_uri,
            "capture_id": str(self.capture_id),
            "body_reference": self.body_reference.reference,
            "body_sha256": self.body_sha256,
            "body_size_bytes": self.body_size_bytes,
            "first_seen_at": self.first_seen_at.isoformat(),
            "revision_recorded_at": self.revision_recorded_at.isoformat(),
            "capture_observed_at": self.capture_observed_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
        }
