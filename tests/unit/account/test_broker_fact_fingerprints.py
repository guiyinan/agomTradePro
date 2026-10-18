"""Semantic binding for broker source files, execution economics, and preview scope."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest

from apps.account.domain.broker_trade_reconciliation_fingerprints import (
    BrokerFactIdentity,
    broker_fact_set_fingerprint,
    canonical_float,
)


def _fact() -> BrokerFactIdentity:
    """Build one exact execution identity with mixed known and unknown costs."""
    return BrokerFactIdentity(
        broker_trade_key="1" * 64,
        action="sell",
        asset_code="000001.SZ",
        shares=Decimal("40"),
        price=Decimal("11.2500"),
        commission=Decimal("1.23"),
        stamp_duty=None,
        transfer_fee=Decimal("0.07"),
        traded_at=datetime(2020, 5, 20, 2, 11, 12, tzinfo=UTC),
    )


def _fingerprint(facts: tuple[BrokerFactIdentity, ...], **scope: object) -> str:
    """Create a fingerprint for one owner, portfolio, and exact source file."""
    arguments = {
        "owner_user_id": 7,
        "portfolio_id": 11,
        "source_file_sha256": "a" * 64,
        **scope,
    }
    return broker_fact_set_fingerprint(facts=facts, **arguments)


@pytest.mark.parametrize(
    "scope_change",
    [
        {"owner_user_id": 8},
        {"portfolio_id": 12},
        {"source_file_sha256": "b" * 64},
    ],
    ids=["owner", "portfolio", "source-file-bytes"],
)
def test_preview_is_bound_to_exact_owner_portfolio_and_file(
    scope_change: dict[str, object],
) -> None:
    """A valid preview for a different source or owner is not reusable."""
    assert _fingerprint((_fact(),)) != _fingerprint((_fact(),), **scope_change)


@pytest.mark.parametrize(
    "economic_change",
    [
        {"broker_trade_key": "2" * 64},
        {"action": "buy"},
        {"asset_code": "000002.SZ"},
        {"shares": Decimal("41")},
        {"price": Decimal("11.26")},
        {"commission": Decimal("1.24")},
        {"stamp_duty": Decimal("0")},
        {"transfer_fee": None},
        {"traded_at": datetime(2020, 5, 20, 2, 11, 13, tzinfo=UTC)},
    ],
    ids=[
        "key",
        "side",
        "security",
        "shares",
        "price",
        "commission",
        "known-zero",
        "unknown-fee",
        "source-time",
    ],
)
def test_same_stable_key_does_not_hide_changed_execution_economics(
    economic_change: dict[str, object],
) -> None:
    """A broker identifier alone cannot attest to all immutable execution fields."""
    assert _fingerprint((_fact(),)) != _fingerprint((replace(_fact(), **economic_change),))


def test_equal_decimals_and_equivalent_aware_instants_are_not_false_conflicts() -> None:
    """Database decimal scale and equivalent timezone offsets preserve identity."""
    original = _fact()
    equivalent = replace(
        original,
        shares=Decimal("40.000000"),
        price=Decimal("11.25"),
        commission=Decimal("1.2300"),
        traded_at=original.traded_at.astimezone(timezone(timedelta(hours=8))),
    )
    assert _fingerprint((original,)) == _fingerprint((equivalent,))


def test_fact_set_fingerprint_is_stable_under_row_order_changes() -> None:
    """Exact source bytes remain independently bound while fact order is canonical."""
    first = _fact()
    second = replace(first, broker_trade_key="2" * 64, shares=Decimal("50"))
    assert _fingerprint((first, second)) == _fingerprint((second, first))


def test_duplicate_stable_keys_are_rejected_before_digest_creation() -> None:
    """Caller must explicitly resolve repeated keys before declaring one fact set."""
    with pytest.raises(ValueError):
        _fingerprint((_fact(), replace(_fact(), shares=Decimal("50"))))


@pytest.mark.parametrize(
    "invalid_value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_nonfinite_economics_cannot_produce_a_valid_preview(invalid_value: Decimal) -> None:
    """A nonfinite source value cannot turn into a stable confirmation basis."""
    with pytest.raises(ValueError):
        _fingerprint((replace(_fact(), shares=invalid_value),))


def test_source_execution_time_must_be_aware() -> None:
    """The digest cannot guess which instant a timezone-less clock represents."""
    with pytest.raises(ValueError):
        _fingerprint((replace(_fact(), traded_at=datetime(2020, 5, 20, 10, 11, 12)),))


@pytest.mark.parametrize(
    "scope_change",
    [
        {"owner_user_id": True},
        {"owner_user_id": 0},
        {"portfolio_id": False},
        {"portfolio_id": -1},
        {"source_file_sha256": "A" * 64},
        {"source_file_sha256": "not-a-digest"},
    ],
    ids=[
        "boolean-owner",
        "zero-owner",
        "boolean-portfolio",
        "negative-portfolio",
        "uppercase-digest",
        "malformed-digest",
    ],
)
def test_invalid_fact_scope_cannot_produce_a_preview_fingerprint(
    scope_change: dict[str, object],
) -> None:
    """A source preview is rejected unless every owner, portfolio, and digest is exact."""
    with pytest.raises(ValueError):
        _fingerprint((_fact(),), **scope_change)


@pytest.mark.parametrize(
    "economic_change",
    [
        {"broker_trade_key": ""},
        {"broker_trade_key": None},
        {"action": "hold"},
        {"asset_code": ""},
        {"asset_code": None},
    ],
    ids=["empty-key", "nonstring-key", "unsupported-action", "empty-asset", "nonstring-asset"],
)
def test_fact_identity_requires_a_key_action_and_asset(
    economic_change: dict[str, object],
) -> None:
    """Incomplete source rows are rejected instead of being assigned a synthetic identity."""
    with pytest.raises(ValueError):
        _fingerprint((replace(_fact(), **economic_change),))


def test_fact_set_rejects_an_untyped_row_before_digest_creation() -> None:
    """The fingerprint boundary does not accept arbitrary objects as normalized facts."""
    from typing import cast

    with pytest.raises(ValueError, match="BrokerFactIdentity"):
        _fingerprint((cast(BrokerFactIdentity, object()),))


@pytest.mark.parametrize(
    "economic_change",
    [
        {"shares": Decimal("0")},
        {"price": Decimal("-1")},
        {"commission": Decimal("-0.01")},
        {"shares": 40},
    ],
    ids=["zero-shares", "negative-price", "negative-fee", "nondecimal-shares"],
)
def test_invalid_decimal_economics_are_rejected(
    economic_change: dict[str, object],
) -> None:
    """Shares and price must be positive while a fee must be a nonnegative Decimal."""
    with pytest.raises(ValueError):
        _fingerprint((replace(_fact(), **economic_change),))


@pytest.mark.parametrize(
    "value",
    [True, float("nan"), float("inf"), "12.50"],
    ids=["boolean", "nan", "infinity", "text"],
)
def test_balance_snapshot_rejects_boolean_nonfinite_and_non_numeric_values(value: object) -> None:
    """Snapshot fingerprints never coerce booleans, nonfinite values, or text into money."""
    from typing import cast

    with pytest.raises(ValueError, match="finite number"):
        canonical_float(cast(float | None, value), field_name="total_shares")


def test_balance_snapshot_float_conversion_preserves_null_and_finite_values() -> None:
    """Known finite values have a canonical decimal form and missing values remain null."""
    assert canonical_float(None, field_name="available_quantity") is None
    assert canonical_float(12.5, field_name="total_shares") == "12.5"


def test_source_execution_time_rejects_text_instead_of_guessing_a_timezone() -> None:
    """A timestamp string must be parsed and validated before fingerprinting."""
    with pytest.raises(ValueError, match="timezone-aware"):
        _fingerprint((replace(_fact(), traded_at=cast(datetime, "2026-10-19T10:00:00")),))
