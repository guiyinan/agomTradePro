"""Typed publication evidence validation shared by publication boundaries."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from .contracts import KNOWN_PUBLICATION_EVIDENCE_KEYS, PublicationPolicy
from .control_plane import PublicationFactReference, PublicationMember

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")
_RAW_PAYLOAD_SCOPES: Final[frozenset[str]] = frozenset(
    {"batch_response_body", "record_response_body"}
)
_PUBLISHABLE_QUALITY: Final[frozenset[str]] = frozenset({"accepted", "valid", "verified"})

PublicationEvidenceItem = PublicationFactReference | PublicationMember


@dataclass(frozen=True, slots=True)
class _EvidenceView:
    """Common typed view over a reference or frozen publication member."""

    source: str
    source_record_id: str
    observed_at: datetime | None
    available_at: datetime | None
    fetched_at: datetime | None
    source_published_at: datetime | None
    raw_payload_hash: str
    raw_payload_scope: str
    fact_content_hash: str
    quality_status: str


def validate_publication_evidence(
    policy: PublicationPolicy,
    evidence: Sequence[PublicationEvidenceItem],
    *,
    published_at: datetime,
    knowledge_cutoff: datetime | None = None,
) -> None:
    """Fail closed when one publication lacks policy-required evidence.

    ``published_at`` is the canonical publication completion time.  It is
    deliberately distinct from ``source_published_at`` in a member.  Legacy
    policies may carry blank optional metadata, while versioned policies also
    require a normalized fact-content digest regardless of their explicit
    evidence-key list.
    """

    if not isinstance(policy, PublicationPolicy):
        raise TypeError("policy must be a PublicationPolicy")
    _require_aware(published_at, "published_at")
    if knowledge_cutoff is not None:
        _require_aware(knowledge_cutoff, "knowledge_cutoff")
    if not evidence:
        raise ValueError("publication evidence cannot be empty")

    required_keys = tuple(policy.required_evidence)
    unknown_keys = set(required_keys) - KNOWN_PUBLICATION_EVIDENCE_KEYS
    if unknown_keys:
        raise ValueError("publication evidence policy contains unknown keys")
    if len(set(required_keys)) != len(required_keys):
        raise ValueError("publication evidence policy contains duplicate keys")

    for item in evidence:
        view = _view(item)
        _validate_quality(view.quality_status)
        _validate_timestamps(view, published_at, knowledge_cutoff)
        for key in required_keys:
            _require_key(view, key)
        if policy.uses_versioned_evidence:
            _require_sha256(view.fact_content_hash, "fact_content_hash")
        if "raw_payload_hash" in required_keys:
            _require_sha256(view.raw_payload_hash, "raw_payload_hash")
            _require_scope(view.raw_payload_scope)
        if "raw_payload_scope" in required_keys:
            _require_scope(view.raw_payload_scope)


def _view(item: PublicationEvidenceItem) -> _EvidenceView:
    """Convert one supported evidence value to a typed common view."""

    if isinstance(item, PublicationFactReference):
        return _EvidenceView(
            source=item.source,
            source_record_id=item.source_record_id,
            observed_at=item.observed_at,
            available_at=item.available_at,
            fetched_at=item.fetched_at,
            source_published_at=item.source_published_at,
            raw_payload_hash=item.raw_payload_hash,
            raw_payload_scope=item.raw_payload_scope,
            fact_content_hash=item.fact_content_hash,
            quality_status=item.quality_status,
        )
    if isinstance(item, PublicationMember):
        return _EvidenceView(
            source=item.source,
            source_record_id=item.source_record_id,
            observed_at=item.observed_at,
            available_at=item.available_at,
            fetched_at=item.fetched_at,
            source_published_at=item.source_published_at,
            raw_payload_hash=item.raw_payload_hash,
            raw_payload_scope=item.raw_payload_scope,
            fact_content_hash=item.fact_content_hash,
            quality_status=item.quality_status,
        )
    raise TypeError("publication evidence must contain references or members")


def _validate_quality(value: str) -> None:
    """Accept only quality states that are safe for a decision publication."""

    if value not in _PUBLISHABLE_QUALITY:
        raise ValueError("publication evidence quality is not publishable")


def _validate_timestamps(
    view: _EvidenceView,
    published_at: datetime,
    knowledge_cutoff: datetime | None,
) -> None:
    """Validate chronology without imposing a global observed/available order."""

    for field_name, value in (
        ("observed_at", view.observed_at),
        ("available_at", view.available_at),
        ("fetched_at", view.fetched_at),
        ("source_published_at", view.source_published_at),
    ):
        if value is not None:
            _require_aware(value, field_name)
            if value > published_at:
                raise ValueError(f"publication evidence {field_name} is after publication")
            if knowledge_cutoff is not None and value > knowledge_cutoff:
                raise ValueError(f"publication evidence {field_name} exceeds knowledge cutoff")
    if view.observed_at is not None and view.fetched_at is not None:
        if view.observed_at > view.fetched_at:
            raise ValueError("publication evidence observed_at is after fetched_at")
    if view.available_at is not None and view.fetched_at is not None:
        if view.available_at > view.fetched_at:
            raise ValueError("publication evidence available_at is after fetched_at")


def _require_key(view: _EvidenceView, key: str) -> None:
    """Require one named evidence field to be present and meaningful."""

    values: dict[str, object] = {
        "source": view.source,
        "observed_at": view.observed_at,
        "payload_hash": view.raw_payload_hash,
        "raw_payload_hash": view.raw_payload_hash,
        "source_record_id": view.source_record_id,
        "available_at": view.available_at,
        "fetched_at": view.fetched_at,
        "published_at": view.source_published_at,
        "raw_payload_scope": view.raw_payload_scope,
        "fact_content_hash": view.fact_content_hash,
    }
    value = values[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"publication evidence is missing required {key}")


def _require_sha256(value: str, field_name: str) -> None:
    """Require one exact lowercase SHA-256 digest."""

    if _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"publication evidence {field_name} must be lowercase SHA-256")


def _require_scope(value: str) -> None:
    """Require a bounded raw-response scope when raw evidence is governed."""

    if value not in _RAW_PAYLOAD_SCOPES:
        raise ValueError("publication evidence raw_payload_scope is not supported")


def _require_aware(value: datetime, field_name: str) -> None:
    """Require an aware timestamp at the publication boundary."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"publication evidence {field_name} must be timezone-aware")


__all__ = ["PublicationEvidenceItem", "validate_publication_evidence"]
