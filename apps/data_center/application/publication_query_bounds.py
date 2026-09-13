"""Pure envelopes and knowledge-cutoff bounds for publication queries."""

from __future__ import annotations

from datetime import date, datetime


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
