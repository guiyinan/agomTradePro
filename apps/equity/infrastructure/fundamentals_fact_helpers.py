"""Canonical fact parsing helpers shared by equity repository slices."""

from __future__ import annotations

from datetime import date, datetime


def parse_fact_date(value: object) -> date | None:
    """Parse a canonical fact date without substituting the request date."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def parse_fact_datetime(value: object) -> datetime | None:
    """Parse an aware canonical observation/fetch timestamp."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def canonical_fact_source(raw_source: str) -> tuple[str, dict[str, object]]:
    """Normalize compatibility DTO lineage without publishing a fake legacy owner."""

    normalized = str(raw_source or "").strip()
    if normalized and normalized.lower() != "unknown" and "legacy" not in normalized.lower():
        return normalized, {}
    extra: dict[str, object] = {}
    if normalized:
        extra["upstream_source"] = normalized
    return "equity_application_port", extra


__all__ = ["canonical_fact_source", "parse_fact_date", "parse_fact_datetime"]
