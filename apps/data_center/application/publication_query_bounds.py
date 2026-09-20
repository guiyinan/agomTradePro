"""Pure envelopes and knowledge-cutoff bounds for publication queries."""

from __future__ import annotations

from datetime import UTC, date, datetime


def blocked_publication_result(
    gate: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return the stable fail-closed shape for an absent or stale publication."""

    result: dict[str, object] = {
        "rows": [],
        "publication_id": None,
        "published_at": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_missing",
    }
    if gate is not None:
        result.update(gate)
    result["rows"] = []
    result["must_not_use_for_decision"] = True
    return result


def blocked_publication_members_result(
    gate: dict[str, object],
    *,
    reason: str = "canonical_publication_members_missing",
) -> dict[str, object]:
    """Return a stable blocked envelope when selected members are unusable."""

    result = blocked_publication_result(gate)
    result["blocked_reason"] = reason
    return result


def publication_as_of_datetime(gate: dict[str, object]) -> datetime | None:
    """Parse a publication knowledge boundary for current-row upper bounds."""

    raw_as_of = gate.get("as_of")
    if isinstance(raw_as_of, datetime):
        return raw_as_of
    if not isinstance(raw_as_of, str) or not raw_as_of.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw_as_of)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def bounded_end_date(requested: date | None, publication_as_of: date | None) -> date | None:
    """Limit a current-data query to the publication's knowledge boundary."""

    if publication_as_of is None:
        return requested
    if requested is None:
        return publication_as_of
    return min(requested, publication_as_of)


def publication_freshness_gate(
    gate: dict[str, object],
    *,
    observed_at: datetime | None,
    publication_as_of: datetime | None,
    reference: datetime,
    max_age_seconds: int,
) -> dict[str, object]:
    """Apply observation freshness after the complete publication proof passes."""

    oldest_observed_at = observed_at
    # ``as_of`` is the publication's knowledge boundary.  A publication can
    # otherwise look fresh when a member was re-indexed or its ingestion
    # timestamp was refreshed while the selected fact set still represents an
    # older market snapshot.  Current reads must be bounded by both pieces of
    # evidence; use the oldest aware boundary so metadata cannot wash stale
    # facts into a decision-facing response.
    if publication_as_of is not None and oldest_observed_at is not None:
        if (
            publication_as_of.tzinfo is not None
            and publication_as_of.utcoffset() is not None
            and oldest_observed_at.tzinfo is not None
            and oldest_observed_at.utcoffset() is not None
        ):
            oldest_observed_at = min(oldest_observed_at, publication_as_of)
    if oldest_observed_at is None:
        gate.update(
            must_not_use_for_decision=True,
            blocked_reason="publication_observation_missing",
            freshness_status="missing",
        )
        return gate
    if oldest_observed_at.tzinfo is None or oldest_observed_at.utcoffset() is None:
        gate.update(
            must_not_use_for_decision=True,
            blocked_reason="publication_observation_naive",
            freshness_status="invalid",
        )
        return gate
    observed_at_utc = oldest_observed_at.astimezone(UTC)
    age_seconds = max((reference.astimezone(UTC) - observed_at_utc).total_seconds(), 0.0)
    gate["observed_at"] = observed_at_utc.isoformat()
    gate["age_seconds"] = age_seconds
    gate["max_age_seconds"] = max_age_seconds
    if max_age_seconds is not None and age_seconds > max_age_seconds:
        gate.update(
            must_not_use_for_decision=True,
            blocked_reason="canonical_publication_stale",
            freshness_status="stale",
        )
    else:
        gate["freshness_status"] = "fresh"
    return gate
