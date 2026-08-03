"""Shared publication-boundary helpers for Data Center HTTP reads."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

PublicationLookup = Callable[[str, str], dict[str, object] | None]
MemberFactLookup = Callable[..., list[str] | None]

PUBLISHED_FACT_TABLES: dict[str, str] = {
    "equity.price.bar": "data_center_price_bar",
    "equity.quote.snapshot": "data_center_quote_snapshot",
    "equity.financial.fact": "data_center_financial_fact",
    "equity.valuation.fact": "data_center_valuation_fact",
    "sector.membership": "data_center_sector_membership",
    "market.news": "data_center_news_fact",
    "market.capital_flow": "data_center_capital_flow_fact",
}


def published_as_of_datetime(publication: dict[str, object] | None) -> datetime | None:
    """Return the publication knowledge boundary as an aware datetime."""

    if not publication:
        return None
    raw_as_of = publication.get("as_of")
    if isinstance(raw_as_of, datetime):
        parsed = raw_as_of
    elif isinstance(raw_as_of, date):
        parsed = datetime.combine(raw_as_of, datetime.min.time(), tzinfo=UTC)
    elif isinstance(raw_as_of, str) and raw_as_of.strip():
        try:
            parsed = datetime.fromisoformat(raw_as_of)
        except ValueError:
            try:
                parsed = datetime.combine(
                    date.fromisoformat(raw_as_of),
                    datetime.min.time(),
                    tzinfo=UTC,
                )
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def published_as_of_date(publication: dict[str, object] | None) -> date | None:
    """Return the date portion of a publication knowledge boundary."""

    as_of = published_as_of_datetime(publication)
    return as_of.date() if as_of is not None else None


def published_bounded_end(
    requested_end: date | None,
    publication: dict[str, object] | None,
) -> date | None:
    """Intersect a requested date upper bound with publication ``as_of``."""

    publication_end = published_as_of_date(publication)
    if publication_end is None:
        return requested_end
    if requested_end is None:
        return publication_end
    return min(requested_end, publication_end)


def published_empty_intersection_response(
    *,
    identity_field: str,
    identity_value: str,
    publication: dict[str, object],
) -> Response:
    """Fail closed when a requested date range lies after publication ``as_of``."""

    publication_key = str(publication.get("publication_key") or "current")
    blocked_reason = "publication_as_of_before_requested_range"
    return Response(
        {
            identity_field: identity_value,
            "total": 0,
            "data": [],
            "status": "blocked",
            "publication_id": publication.get("publication_id"),
            "publication": publication,
            "must_not_use_for_decision": True,
            "blocked_reason": blocked_reason,
            "freshness_status": publication.get("freshness_status", "fresh"),
            "observed_at": publication.get("observed_at"),
            "contract": {
                "mode": "published",
                "publication_key": publication_key,
                "must_not_use_for_decision": True,
                "blocked_reason": blocked_reason,
                "freshness_status": publication.get("freshness_status", "fresh"),
            },
        },
        status=status.HTTP_200_OK,
    )


def published_member_fact_pks_or_block(
    publication: dict[str, object] | None,
    *,
    identity_field: str,
    identity_value: str,
    get_member_fact_pks: MemberFactLookup,
) -> list[str] | None | Response:
    """Resolve one publication's selected fact rows or return a block response."""

    if publication is None:
        return None
    publication_id = publication.get("publication_id")
    dataset_key = publication.get("dataset_key")
    expected_fact_table = PUBLISHED_FACT_TABLES.get(str(dataset_key or ""))
    if not isinstance(publication_id, str) or not isinstance(dataset_key, str):
        return None
    if expected_fact_table is None:
        return None
    member_pks = get_member_fact_pks(
        publication_id,
        dataset_key=dataset_key,
        expected_fact_table=expected_fact_table,
    )
    if member_pks != []:
        return member_pks
    publication_key = str(publication.get("publication_key") or "current")
    blocked_reason = "canonical_publication_members_missing"
    return Response(
        {
            identity_field: identity_value,
            "total": 0,
            "data": [],
            "status": "blocked",
            "publication_id": publication.get("publication_id"),
            "publication": publication,
            "must_not_use_for_decision": True,
            "blocked_reason": blocked_reason,
            "contract": {
                "mode": "published",
                "publication_key": publication_key,
                "must_not_use_for_decision": True,
                "blocked_reason": blocked_reason,
            },
        },
        status=status.HTTP_200_OK,
    )


def apply_published_gate_with_members(
    request: Request,
    *,
    dataset_key: str,
    default_publication_key: str,
    identity_field: str,
    identity_value: str,
    get_publication: PublicationLookup,
    get_freshness_gate: PublicationLookup,
    get_member_fact_pks: MemberFactLookup,
) -> tuple[dict[str, object] | None, Response | None]:
    """Apply freshness and member selection gates for a current-data read."""

    publication, blocked = apply_published_gate(
        request,
        dataset_key=dataset_key,
        default_publication_key=default_publication_key,
        identity_field=identity_field,
        identity_value=identity_value,
        get_publication=get_publication,
        get_freshness_gate=get_freshness_gate,
    )
    if blocked is not None or publication is None:
        return publication, blocked
    member_pks = published_member_fact_pks_or_block(
        publication,
        identity_field=identity_field,
        identity_value=identity_value,
        get_member_fact_pks=get_member_fact_pks,
    )
    if isinstance(member_pks, Response):
        return None, member_pks
    publication["_member_fact_pks"] = member_pks
    return publication, None


def publication_member_pks(publication: dict[str, object] | None) -> list[str] | None:
    """Return validated member ids attached by the shared publication gate."""

    if publication is None:
        return None
    value = publication.get("_member_fact_pks")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def apply_published_gate(
    request: Request,
    *,
    dataset_key: str,
    default_publication_key: str,
    identity_field: str,
    identity_value: str,
    get_publication: PublicationLookup,
    get_freshness_gate: PublicationLookup,
) -> tuple[dict[str, object] | None, Response | None]:
    """Apply an explicit current-publication gate to a Data Center read."""

    mode = str(request.query_params.get("mode", "historical") or "historical").strip().lower()
    if mode not in {"historical", "published"}:
        return None, Response(
            {"detail": "mode must be historical or published"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if mode != "published":
        return None, None
    publication_key = (
        str(request.query_params.get("publication_key", "") or "").strip()
        or default_publication_key
    )
    publication = get_publication(dataset_key, publication_key)
    if publication is not None:
        freshness_gate = get_freshness_gate(dataset_key, publication_key)
        if freshness_gate is not None:
            publication.update(freshness_gate)
        else:
            publication.update(
                {
                    "must_not_use_for_decision": True,
                    "blocked_reason": "publication_freshness_unverified",
                    "freshness_status": "unverified",
                }
            )
        if not bool(publication.get("must_not_use_for_decision")):
            return publication, None
        blocked_reason = str(publication.get("blocked_reason") or "canonical_publication_stale")
        return None, Response(
            {
                identity_field: identity_value,
                "total": 0,
                "data": [],
                "status": "blocked",
                "publication_id": publication.get("publication_id"),
                "publication": publication,
                "must_not_use_for_decision": True,
                "blocked_reason": blocked_reason,
                "freshness_status": publication.get("freshness_status", "unverified"),
                "observed_at": publication.get("observed_at"),
                "age_seconds": publication.get("age_seconds"),
                "max_age_seconds": publication.get("max_age_seconds"),
                "contract": {
                    "mode": "published",
                    "publication_key": publication_key,
                    "must_not_use_for_decision": True,
                    "blocked_reason": blocked_reason,
                    "freshness_status": publication.get("freshness_status", "unverified"),
                },
            },
            status=status.HTTP_200_OK,
        )
    return None, Response(
        {
            identity_field: identity_value,
            "total": 0,
            "data": [],
            "status": "blocked",
            "publication_id": None,
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_missing",
            "contract": {
                "mode": "published",
                "publication_key": publication_key,
                "must_not_use_for_decision": True,
                "blocked_reason": "canonical_publication_missing",
            },
        },
        status=status.HTTP_200_OK,
    )


__all__ = [
    "apply_published_gate",
    "apply_published_gate_with_members",
    "published_member_fact_pks_or_block",
    "publication_member_pks",
    "published_as_of_date",
    "published_as_of_datetime",
    "published_bounded_end",
    "published_empty_intersection_response",
]
