"""Infrastructure adapter for the M1-only published daily-close lane."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from uuid import UUID

from django.db import DatabaseError

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.data_center.application.market_calendar import latest_completed_cn_market_session
from apps.data_center.application.public_published_queries import get_published_price_bar_series
from apps.data_center.application.query_use_cases import latest_daily_market_observation_is_current
from apps.data_center.domain.market_time import (
    cn_market_date_from_observation,
    cn_market_session_close_utc,
)
from apps.simulated_trading.application.rebalance_preview_reference_close import (
    M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    PricePublicationReference,
    ReferenceCloseReadResult,
)
from core.exceptions import AgomTradeProException
from shared.numeric import safe_float

_PRICE_BAR_DATASET_KEY = "equity.price.bar"
_SHA256_CHARACTERS = frozenset("0123456789abcdef")


class PublishedClosePriceReader:
    """Read one exact, fully qualified close from the M1 reference publication."""

    def read(self, *, asset_code: str, cutoff: datetime) -> ReferenceCloseReadResult:
        """Return an exact latest-session close bound to the preview cutoff."""

        if not _canonical_asset_code(asset_code):
            return _blocked("M1_REFERENCE_CLOSE_ROW_INVALID")
        if not _aware(cutoff):
            return _blocked("M1_REFERENCE_PUBLICATION_SCOPE_INVALID")
        try:
            target_session = latest_completed_cn_market_session(cutoff)
            if target_session is None or cn_market_session_close_utc(target_session) > cutoff:
                return _blocked("M1_REFERENCE_CLOSE_CALENDAR_UNAVAILABLE")
            payload = get_published_price_bar_series(
                asset_code,
                publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
                start=target_session,
                end=target_session,
                limit=2,
                knowledge_cutoff=cutoff,
            )
        except (AgomTradeProException, DatabaseError, OSError, RuntimeError, TypeError, ValueError):
            return _blocked("M1_REFERENCE_PUBLICATION_BLOCKED")
        except ArithmeticError:
            return _blocked("M1_REFERENCE_PUBLICATION_SCOPE_INVALID")

        if not isinstance(payload, Mapping):
            return _blocked("M1_REFERENCE_PUBLICATION_SCOPE_INVALID")
        gate, reason = _publication_reference(
            payload,
            asset_code=asset_code,
            target_session=target_session,
            cutoff=cutoff,
        )
        if gate is None:
            return _blocked(reason or "M1_REFERENCE_PUBLICATION_SCOPE_INVALID")
        rows = payload.get("rows")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
            return _blocked("M1_REFERENCE_CLOSE_ROW_INVALID")
        row = rows[0]
        price_result = _market_price_result(
            row,
            asset_code=asset_code,
            target_session=target_session,
            close_at=gate.source_observed_at,
            cutoff=cutoff,
            published_at=gate.published_at,
        )
        if price_result is None:
            return _blocked("M1_REFERENCE_CLOSE_ROW_INVALID")
        try:
            is_current = latest_daily_market_observation_is_current(
                asset_code=asset_code,
                observed_at=target_session,
                now=cutoff,
            )
        except (
            AgomTradeProException,
            DatabaseError,
            OSError,
            PermissionError,
            RuntimeError,
            TypeError,
            ValueError,
            ArithmeticError,
        ):
            return _blocked("M1_REFERENCE_CLOSE_CALENDAR_UNAVAILABLE")
        if not is_current:
            return _blocked("M1_REFERENCE_CLOSE_DATE_NOT_CURRENT")
        return ReferenceCloseReadResult(
            price_result=price_result,
            publication=gate,
            blocked_reason=None,
        )


def _publication_reference(
    payload: Mapping[str, object],
    *,
    asset_code: str,
    target_session: date,
    cutoff: datetime,
) -> tuple[PricePublicationReference | None, str | None]:
    """Validate complete publication scope and source clocks before row use."""

    if (
        payload.get("dataset_key") != _PRICE_BAR_DATASET_KEY
        or payload.get("publication_key") != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        or payload.get("freshness_scope") != "asset"
        or payload.get("asset_code") != asset_code
    ):
        return None, "M1_REFERENCE_PUBLICATION_SCOPE_INVALID"
    if payload.get("must_not_use_for_decision") is not False:
        return None, "M1_REFERENCE_PUBLICATION_BLOCKED"
    blocked_reason = payload.get("blocked_reason")
    if blocked_reason is not None and (type(blocked_reason) is not str or blocked_reason != ""):
        return None, "M1_REFERENCE_PUBLICATION_BLOCKED"
    freshness = payload.get("freshness_status")
    if type(freshness) is not str or freshness not in ("fresh", "latest_completed_session"):
        return None, "M1_REFERENCE_PUBLICATION_BLOCKED"
    if payload.get("publication_outcome") != "success":
        return None, "M1_REFERENCE_PUBLICATION_BLOCKED"

    counts = tuple(
        _nonnegative_int(payload.get(name))
        for name in (
            "coverage_requested_count",
            "coverage_eligible_count",
            "coverage_selected_count",
            "coverage_missing_count",
        )
    )
    requested, eligible, selected, missing = counts
    if (
        requested is None
        or eligible is None
        or selected is None
        or missing != 0
        or requested < 1
        or eligible < 1
        or selected < 1
        or selected > eligible
        or eligible > requested
    ):
        return None, "M1_REFERENCE_PUBLICATION_BLOCKED"

    publication_id = _nonempty_text(payload.get("publication_id"))
    publication_hash = _sha256(payload.get("publication_hash"))
    publication_run_id = _canonical_uuid(payload.get("publication_run_id"))
    policy_identity = _nonempty_text(payload.get("policy_identity"))
    selected_source = _nonempty_text(payload.get("selected_source"))
    observed_at = _aware_datetime(payload.get("observed_at"))
    publication_as_of = _aware_datetime(payload.get("as_of"))
    published_at = _aware_datetime(payload.get("published_at"))
    if (
        publication_id is None
        or publication_hash is None
        or publication_run_id is None
        or policy_identity is None
        or selected_source is None
        or observed_at is None
        or publication_as_of is None
        or published_at is None
    ):
        return None, "M1_REFERENCE_PUBLICATION_SCOPE_INVALID"
    expected_close = cn_market_session_close_utc(target_session)
    if (
        observed_at != expected_close
        or observed_at > publication_as_of
        or publication_as_of > published_at
        or published_at > cutoff
        or publication_as_of > cutoff
        or cn_market_date_from_observation(observed_at) != target_session
    ):
        return None, "M1_REFERENCE_PUBLICATION_SCOPE_INVALID"
    try:
        reference = PricePublicationReference(
            dataset_key=_PRICE_BAR_DATASET_KEY,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            publication_id=publication_id,
            publication_hash=publication_hash,
            publication_run_id=publication_run_id,
            published_at=published_at,
            publication_as_of=publication_as_of,
            knowledge_cutoff=cutoff,
            bar_date=target_session,
            source_observed_at=observed_at,
            freshness_status=freshness,
        )
    except (ArithmeticError, TypeError, ValueError):
        return None, "M1_REFERENCE_PUBLICATION_SCOPE_INVALID"
    return reference, None


def _market_price_result(
    row: Mapping[str, object],
    *,
    asset_code: str,
    target_session: date,
    close_at: datetime,
    cutoff: datetime,
    published_at: datetime,
) -> MarketPriceResult | None:
    """Narrow one public price-bar payload into the existing price contract."""

    row_source = _nonempty_text(row.get("source"))
    if (
        row.get("asset_code") != asset_code
        or row.get("timestamp") != target_session.isoformat()
        or row.get("period") != "1d"
        or row_source is None
    ):
        return None
    raw_price = row.get("close")
    if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
        return None
    price = safe_float(raw_price)
    if price is None or not math.isfinite(price) or price <= 0:
        return None
    fetched_at = _aware_datetime(row.get("fetched_at"))
    if fetched_at is None or fetched_at > cutoff or fetched_at > published_at:
        return None
    try:
        return MarketPriceResult(
            normalized_code=asset_code,
            price=price,
            as_of=target_session,
            source=row_source,
            freshness="close_fallback",
            is_fallback=True,
            observed_at=close_at,
        )
    except (ArithmeticError, TypeError, ValueError):
        return None


def _blocked(reason: str) -> ReferenceCloseReadResult:
    """Return a no-price result carrying one stable failure reason."""

    return ReferenceCloseReadResult(price_result=None, publication=None, blocked_reason=reason)


def _canonical_asset_code(value: object) -> bool:
    """Require an already normalized mainland equity code at this boundary."""

    return (
        type(value) is str
        and value == value.strip().upper()
        and value.endswith((".SH", ".SZ", ".BJ"))
        and 1 <= len(value) <= 16
    )


def _nonempty_text(value: object) -> str | None:
    """Return a bounded nonblank source string."""

    if type(value) is not str or not value.strip() or len(value) > 256:
        return None
    if any(character in "\r\n" for character in value):
        return None
    return value


def _sha256(value: object) -> str | None:
    """Accept only the canonical lowercase plain SHA-256 representation."""

    if type(value) is not str or len(value) != 64:
        return None
    if not set(value) <= _SHA256_CHARACTERS:
        return None
    return value


def _canonical_uuid(value: object) -> str | None:
    """Require a canonical UUID for the publication's source run identity."""

    if type(value) is not str:
        return None
    try:
        parsed = UUID(value)
    except (TypeError, ValueError):
        return None
    return value if str(parsed) == value.lower() else None


def _nonnegative_int(value: object) -> int | None:
    """Reject bool and malformed publication coverage counters."""

    return value if type(value) is int and value >= 0 else None


def _aware_datetime(value: object) -> datetime | None:
    """Parse only aware datetime values from the public query payload."""

    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str and value.strip():
        try:
            parsed = datetime.fromisoformat(value)
        except (OverflowError, TypeError, ValueError):
            return None
    else:
        return None
    return parsed if _aware(parsed) else None


def _aware(value: datetime) -> bool:
    """Return whether a timestamp has a defined UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


__all__: tuple[str, ...] = (
    "M1_REBALANCE_REFERENCE_PUBLICATION_KEY",
    "PublishedClosePriceReader",
)
