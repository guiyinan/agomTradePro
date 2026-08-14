"""Fail-closed Evidence adapters for legacy Data Center outputs."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

from apps.data_center.application.dtos import QuoteResponse
from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    MethodKind,
    build_legacy_unverified_envelope,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _quote_payload(quote: QuoteResponse) -> dict[str, object]:
    return {
        "age_minutes": quote.age_minutes,
        "asset_code": quote.asset_code,
        "blocked_reason": quote.blocked_reason,
        "current_price": quote.current_price,
        "fetched_at": _utc_text(quote.fetched_at) if quote.fetched_at is not None else None,
        "freshness_status": quote.freshness_status,
        "high": quote.high,
        "is_stale": quote.is_stale,
        "low": quote.low,
        "max_age_hours": quote.max_age_hours,
        "must_not_use_for_decision": quote.must_not_use_for_decision,
        "open": quote.open,
        "prev_close": quote.prev_close,
        "snapshot_at": _utc_text(quote.snapshot_at),
        "source": quote.source,
        "volume": quote.volume,
    }


def build_quote_legacy_evidence_summary(
    quote: QuoteResponse,
    *,
    evaluated_at: datetime,
) -> EvidenceSummaryDTO:
    """Wrap one exact quote as legacy-unverified, display-only Evidence."""

    _require_aware(quote.snapshot_at, "snapshot_at")
    _require_aware(evaluated_at, "evaluated_at")
    if quote.fetched_at is not None:
        _require_aware(quote.fetched_at, "fetched_at")
    if quote.snapshot_at > evaluated_at:
        raise ValueError("quote snapshot_at cannot be later than evaluated_at")
    if quote.fetched_at is not None and quote.fetched_at > evaluated_at:
        raise ValueError("quote fetched_at cannot be later than evaluated_at")
    if not math.isfinite(quote.max_age_hours) or quote.max_age_hours <= 0:
        raise ValueError("quote max_age_hours must be finite and positive")

    payload = _quote_payload(quote)
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except ValueError as error:
        raise ValueError("quote contains a non-finite numeric value") from error
    artifact = ArtifactRef(
        owner="data_center",
        artifact_type="market_quote",
        artifact_id=quote.asset_code,
        artifact_version=_utc_text(quote.snapshot_at),
        content_hash=hashlib.sha256(encoded).hexdigest(),
    )
    envelope = build_legacy_unverified_envelope(
        output_artifact=artifact,
        claim_kind=ClaimKind.OBSERVATION,
        method_kind=MethodKind.IDENTITY,
        evaluated_at=evaluated_at,
        valid_until=evaluated_at + timedelta(hours=quote.max_age_hours),
    )
    return EvidenceSummaryDTO.from_legacy_envelope(envelope=envelope)


__all__ = ["build_quote_legacy_evidence_summary"]
