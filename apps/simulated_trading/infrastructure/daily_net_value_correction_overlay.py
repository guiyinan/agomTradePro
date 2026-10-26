"""Correction cash overlay for immutable daily net-value snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.simulated_trading.application.fee_correction import FeeCorrectionCashPosting
from apps.simulated_trading.domain.fee_correction import (
    require_exact_ledger_money,
    sum_signed_ledger_money,
)
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
)
from core.exceptions import BusinessLogicError


@dataclass(frozen=True, slots=True)
class DailyCorrectionOverlay:
    """Read-time cash/value projection and correction-coverage status."""

    cash: Decimal
    total_value: Decimal
    correction_coverage_known: bool


def overlay_daily_correction_cash(
    *,
    account_id: int,
    record_date: date,
    cash: Decimal,
    total_value: Decimal,
    correction_event_watermark: int | None,
    correction_event_watermark_sha256: str | None,
    events: Sequence[FeeCorrectionCashPosting],
) -> DailyCorrectionOverlay:
    """Apply relevant post-snapshot correction events without mutating the row."""

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(record_date) is not date
        or type(cash) is not Decimal
        or not cash.is_finite()
        or type(total_value) is not Decimal
        or not total_value.is_finite()
        or (
            correction_event_watermark is not None
            and (type(correction_event_watermark) is not int or correction_event_watermark < 0)
        )
        or (correction_event_watermark is None and correction_event_watermark_sha256 is not None)
        or (
            correction_event_watermark is not None
            and (
                type(correction_event_watermark_sha256) is not str
                or len(correction_event_watermark_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in correction_event_watermark_sha256
                )
            )
        )
    ):
        raise BusinessLogicError(
            "日净值费用更正覆盖输入无效",
            code="DAILY_NET_VALUE_CORRECTION_INPUT_INVALID",
        )
    if any(type(event) is not FeeCorrectionCashPosting for event in events):
        raise BusinessLogicError(
            "日净值费用更正事件类型无效",
            code="DAILY_NET_VALUE_CORRECTION_INPUT_INVALID",
        )
    relevant_events = tuple(event for event in events if event.posting_date <= record_date)
    try:
        require_exact_ledger_money(cash, "daily_snapshot.cash")
        require_exact_ledger_money(total_value, "daily_snapshot.total_value")
    except (ArithmeticError, TypeError, ValueError) as error:
        raise BusinessLogicError(
            "日净值现金或资产值不满足精确账本金额",
            code="DAILY_NET_VALUE_CORRECTION_INPUT_INVALID",
        ) from error
    if correction_event_watermark is not None:
        if correction_event_watermark == 0:
            expected_head_hash = fee_correction_account_genesis_sha256(account_id)
        else:
            captured_head = next(
                (
                    event
                    for event in relevant_events
                    if event.account_revision == correction_event_watermark
                ),
                None,
            )
            if captured_head is None:
                raise BusinessLogicError(
                    "日净值快照引用的费用更正前缀不存在",
                    code="DAILY_NET_VALUE_CORRECTION_WATERMARK_INVALID",
                )
            expected_head_hash = captured_head.account_prefix_sha256
        if correction_event_watermark_sha256 != expected_head_hash:
            raise BusinessLogicError(
                "日净值快照费用更正前缀摘要不匹配",
                code="DAILY_NET_VALUE_CORRECTION_WATERMARK_INVALID",
            )
    if correction_event_watermark is None:
        return DailyCorrectionOverlay(
            cash=cash,
            total_value=total_value,
            correction_coverage_known=not relevant_events,
        )

    pending_events = tuple(
        event for event in relevant_events if event.account_revision > correction_event_watermark
    )
    try:
        cash_delta = sum_signed_ledger_money(
            tuple(event.cash_delta for event in pending_events),
            "daily_snapshot.correction_cash_delta",
        )
        projected_cash = sum_signed_ledger_money(
            (cash, cash_delta),
            "daily_snapshot.projected_cash",
        )
        projected_total = sum_signed_ledger_money(
            (total_value, cash_delta),
            "daily_snapshot.projected_total_value",
        )
        require_exact_ledger_money(projected_cash, "daily_snapshot.projected_cash")
        require_exact_ledger_money(projected_total, "daily_snapshot.projected_total_value")
    except (ArithmeticError, TypeError, ValueError) as error:
        raise BusinessLogicError(
            "日净值费用更正现金投影超出账本范围",
            code="DAILY_NET_VALUE_CORRECTION_OVERLAY_INVALID",
        ) from error
    return DailyCorrectionOverlay(
        cash=projected_cash,
        total_value=projected_total,
        correction_coverage_known=True,
    )


__all__ = ["DailyCorrectionOverlay", "overlay_daily_correction_cash"]
