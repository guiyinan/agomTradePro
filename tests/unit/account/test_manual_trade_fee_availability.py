"""Preview-only contracts for fees that are absent from broker imports."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from apps.account.application.manual_trade_sync import ManualTradeImportUseCase


class _Parser:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def parse(self, *, content: bytes, filename: str) -> list[dict[str, Any]]:
        del content, filename
        return self.rows


class _SyncRepository:
    def get_owned_portfolio(self, *, user_id: int, portfolio_id: int) -> object:
        del user_id, portfolio_id
        return object()

    def broker_trade_key_exists(self, broker_trade_key: str) -> bool:
        del broker_trade_key
        return False


class _ExecutionMatcher:
    def record_imported_execution(self, **_kwargs: object) -> dict[str, Any]:
        return {}


def _row(**fee_values: object) -> dict[str, Any]:
    return {
        "traded_at": datetime(2026, 10, 16, 10, 0, tzinfo=UTC),
        "action": "buy",
        "asset_code": "600000.SH",
        "shares": "100",
        "price": "10.50",
        **fee_values,
    }


def _preview(rows: list[dict[str, Any]]) -> Any:
    use_case = ManualTradeImportUseCase(
        sync_repo=_SyncRepository(),
        portfolio_repo=object(),
        parser=_Parser(rows),
        position_service=object(),
        execution_matcher=_ExecutionMatcher(),
    )
    return use_case.preview(
        user_id=7,
        portfolio_id=11,
        broker_name="fixture-broker",
        filename="trades.csv",
        content=b"synthetic fixture only",
    )


def test_preview_distinguishes_missing_blank_zero_positive_and_mixed_fees() -> None:
    result = _preview(
        [
            _row(),
            _row(commission="", stamp_duty=None, transfer_fee="  "),
            _row(commission=0, stamp_duty="0.00", transfer_fee=Decimal("0")),
            _row(commission="1.25", stamp_duty="2", transfer_fee="0.03"),
            _row(commission=None, stamp_duty="0", transfer_fee="0.15"),
        ]
    )

    assert result.valid_rows == 5
    assert result.error_rows == 0
    assert [(row["commission"], row["stamp_duty"], row["transfer_fee"]) for row in result.rows] == [
        (None, None, None),
        (None, None, None),
        ("0", "0.00", "0"),
        ("1.25", "2", "0.03"),
        (None, "0", "0.15"),
    ]


def test_preview_keeps_negative_and_malformed_fee_rejection() -> None:
    result = _preview(
        [
            _row(commission="-1"),
            _row(stamp_duty="not-a-number"),
            _row(transfer_fee="-0.01"),
        ]
    )

    assert result.valid_rows == 0
    assert result.error_rows == 3
    assert [error["row_number"] for error in result.errors] == [2, 3, 4]
