"""Daily-value correction coverage is a read-only, once-only cash overlay."""

from datetime import UTC, date, datetime
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from apps.simulated_trading.application.fee_correction import FeeCorrectionCashPosting
from apps.simulated_trading.domain.fee_correction import FeeCorrectionCashEvent
from apps.simulated_trading.infrastructure.daily_net_value_correction_overlay import (
    overlay_daily_correction_cash,
)
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
    fee_correction_account_prefix_sha256,
)
from core.exceptions import BusinessLogicError


def _events(
    posting_date: date = date(2026, 4, 5),
) -> tuple[FeeCorrectionCashPosting, ...]:
    """Build a valid account prefix whose PK order differs from its revision order."""

    account_id = 41
    predecessor = fee_correction_account_genesis_sha256(account_id)
    postings: list[FeeCorrectionCashPosting] = []
    for revision, event_id, cash_delta, minute in (
        (1, 99, Decimal("-1.00"), 30),
        (2, 2, Decimal("-12.34"), 31),
    ):
        posted_at = datetime(
            posting_date.year,
            posting_date.month,
            posting_date.day,
            8,
            minute,
            tzinfo=UTC,
        )
        request_hash = f"{revision:x}" * 64
        authority_hash = "a" * 64
        prefix_hash = fee_correction_account_prefix_sha256(
            account_id=account_id,
            account_revision=revision,
            predecessor_sha256=predecessor,
            request_payload_sha256=request_hash,
            cash_delta=cash_delta,
            authority_snapshot_sha256=authority_hash,
            posted_at=posted_at,
            posting_date=posting_date,
        )
        postings.append(
            FeeCorrectionCashPosting(
                event=FeeCorrectionCashEvent(
                    event_id=event_id,
                    posting_date=posting_date,
                    posted_at=posted_at,
                    cash_delta=cash_delta,
                ),
                account_revision=revision,
                account_prefix_sha256=prefix_hash,
            )
        )
        predecessor = prefix_hash
    return tuple(postings)


def test_daily_snapshot_before_same_day_correction_gets_cash_and_value_once() -> None:
    event1, event2 = _events()

    result = overlay_daily_correction_cash(
        account_id=41,
        record_date=date(2026, 4, 5),
        cash=Decimal("999.00"),
        total_value=Decimal("1449.00"),
        correction_event_watermark=1,
        correction_event_watermark_sha256=event1.account_prefix_sha256,
        events=(event1, event2),
    )

    assert result.cash == Decimal("986.66")
    assert result.total_value == Decimal("1436.66")
    assert result.correction_coverage_known is True


def test_daily_snapshot_after_same_day_correction_is_not_double_counted() -> None:
    event1, event2 = _events()

    result = overlay_daily_correction_cash(
        account_id=41,
        record_date=date(2026, 4, 5),
        cash=Decimal("986.66"),
        total_value=Decimal("1436.66"),
        correction_event_watermark=2,
        correction_event_watermark_sha256=event2.account_prefix_sha256,
        events=(event1, event2),
    )

    assert result.cash == Decimal("986.66")
    assert result.total_value == Decimal("1436.66")
    assert result.correction_coverage_known is True


def test_correction_is_not_applied_to_a_snapshot_before_its_posting_date() -> None:
    event1, event2 = _events()

    result = overlay_daily_correction_cash(
        account_id=41,
        record_date=date(2026, 4, 4),
        cash=Decimal("1000.00"),
        total_value=Decimal("1450.00"),
        correction_event_watermark=0,
        correction_event_watermark_sha256=fee_correction_account_genesis_sha256(41),
        events=(event1, event2),
    )

    assert result.cash == Decimal("1000.00")
    assert result.total_value == Decimal("1450.00")
    assert result.correction_coverage_known is True


def test_daily_overlay_ignores_hostile_decimal_context() -> None:
    """Historical correction additions use the same full Domain context as replay."""
    event1, event2 = _events()

    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        result = overlay_daily_correction_cash(
            account_id=41,
            record_date=date(2026, 4, 5),
            cash=Decimal("999.00"),
            total_value=Decimal("1449.00"),
            correction_event_watermark=1,
            correction_event_watermark_sha256=event1.account_prefix_sha256,
            events=(event1, event2),
        )
        assert context.prec == 2
        assert context.Emax == 2
        assert context.Emin == -2
        assert context.traps[Inexact]
        assert context.traps[Rounded]

    assert result.cash == Decimal("986.66")
    assert result.total_value == Decimal("1436.66")


def test_legacy_snapshot_with_relevant_event_stays_unmodified_and_unproven() -> None:
    event1, event2 = _events()

    result = overlay_daily_correction_cash(
        account_id=41,
        record_date=date(2026, 4, 5),
        cash=Decimal("1000.00"),
        total_value=Decimal("1450.00"),
        correction_event_watermark=None,
        correction_event_watermark_sha256=None,
        events=(event1, event2),
    )

    assert result.cash == Decimal("1000.00")
    assert result.total_value == Decimal("1450.00")
    assert result.correction_coverage_known is False


def test_legacy_snapshot_without_prior_correction_is_covered_for_that_date() -> None:
    event1, event2 = _events(date(2026, 4, 6))

    result = overlay_daily_correction_cash(
        account_id=41,
        record_date=date(2026, 4, 5),
        cash=Decimal("1000.00"),
        total_value=Decimal("1450.00"),
        correction_event_watermark=None,
        correction_event_watermark_sha256=None,
        events=(event1, event2),
    )

    assert result.cash == Decimal("1000.00")
    assert result.total_value == Decimal("1450.00")
    assert result.correction_coverage_known is True


def test_snapshot_watermark_hash_must_match_its_account_local_revision() -> None:
    event1, event2 = _events()

    with pytest.raises(BusinessLogicError) as error:
        overlay_daily_correction_cash(
            account_id=41,
            record_date=date(2026, 4, 5),
            cash=Decimal("999.00"),
            total_value=Decimal("1449.00"),
            correction_event_watermark=1,
            correction_event_watermark_sha256=event2.account_prefix_sha256,
            events=(event1, event2),
        )

    assert error.value.code == "DAILY_NET_VALUE_CORRECTION_WATERMARK_INVALID"


def test_daily_snapshot_rejects_boolean_watermark() -> None:
    with pytest.raises(BusinessLogicError) as error:
        overlay_daily_correction_cash(
            record_date=date(2026, 4, 5),
            account_id=41,
            cash=Decimal("1000.00"),
            total_value=Decimal("1450.00"),
            correction_event_watermark=True,
            correction_event_watermark_sha256="a" * 64,
            events=(),
        )

    assert error.value.code == "DAILY_NET_VALUE_CORRECTION_INPUT_INVALID"
