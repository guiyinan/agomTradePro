"""Raw landing and schema-fingerprint value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class RawPayload:
    """Immutable, hash-addressed provider payload before normalization."""

    payload_id: str
    dataset_key: str
    provider_name: str
    payload_hash: str
    schema_fingerprint: str
    payload: dict[str, Any]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    request_params: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    batch_id: str = ""
    content_type: str = "application/json"
    parser_version: str = ""
    redacted: bool = True
    payload_size_bytes: int = 0
    retention_until: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "payload_id",
            "dataset_key",
            "provider_name",
            "payload_hash",
            "schema_fingerprint",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"RawPayload.{name} cannot be empty")
        _aware(self.fetched_at, "RawPayload.fetched_at")
        if self.retention_until is not None:
            _aware(self.retention_until, "RawPayload.retention_until")
            if self.retention_until < self.fetched_at:
                raise ValueError("RawPayload.retention_until cannot precede fetched_at")
        if self.payload_size_bytes < 0:
            raise ValueError("RawPayload.payload_size_bytes cannot be negative")
        if not self.redacted:
            raise ValueError("RawPayload must be redacted before persistence")


@dataclass(frozen=True)
class SchemaFingerprint:
    """Observed schema signature for one dataset/provider combination."""

    fingerprint: str
    dataset_key: str
    provider_name: str
    fields: tuple[str, ...]
    parser_version: str = ""
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sample_count: int = 1

    def __post_init__(self) -> None:
        if not self.fingerprint.strip() or not self.dataset_key.strip() or not self.provider_name.strip():
            raise ValueError("SchemaFingerprint identifiers are required")
        _aware(self.first_seen_at, "SchemaFingerprint.first_seen_at")
        _aware(self.last_seen_at, "SchemaFingerprint.last_seen_at")
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("SchemaFingerprint.last_seen_at cannot precede first_seen_at")
        if self.sample_count < 1:
            raise ValueError("SchemaFingerprint.sample_count must be positive")


__all__ = ["RawPayload", "SchemaFingerprint"]
