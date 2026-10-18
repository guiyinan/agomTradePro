"""Pure JSON contract checks for stored portfolio facts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest import TestCase

from apps.account.application.portfolio_recorded_facts_contracts import (
    RecordedPosition,
    RecordedPositionPage,
    RecordedReadClock,
    RecordedStatistics,
)


class PortfolioRecordedFactsContractTest(TestCase):
    """Keep the presentation contract honest without importing Django models."""

    def test_position_keeps_native_currency_and_zero_or_null_values(self) -> None:
        """Stored native currency and legal zero/null values survive serialization."""

        position = RecordedPosition(
            id=1,
            portfolio=9,
            portfolio_name="组合",
            asset_code="000001.SZ",
            asset_name="示例",
            asset_class="equity",
            shares=0.0,
            avg_cost=Decimal("0"),
            current_price=None,
            market_value=None,
            unrealized_pnl=None,
            unrealized_pnl_pct=None,
            valuation_known=False,
            source="manual",
            source_id=None,
            currency_code=None,
            currency_name=None,
            currency_symbol=None,
            opened_at=None,
            updated_at=None,
        )

        payload = position.to_payload()

        self.assertEqual(payload["shares"], 0.0)
        self.assertIsNone(payload["market_value"])
        self.assertEqual(payload["avg_cost"], "0")
        self.assertFalse(payload["valuation_known"])
        self.assertEqual(payload["valuation_status"], "unknown")
        self.assertIsNone(payload["current_price"])
        self.assertIsNone(payload["currency_code"])
        self.assertIsNone(payload["currency_name"])
        self.assertIsNone(payload["currency_symbol"])

    def test_page_preserves_total_and_continuation(self) -> None:
        """Pagination metadata does not silently discard the total count."""

        position = RecordedPosition(
            id=1,
            portfolio=9,
            portfolio_name="组合",
            asset_code="000001.SZ",
            asset_name="示例",
            asset_class="equity",
            shares=1.0,
            avg_cost=Decimal("1"),
            current_price=Decimal("1"),
            market_value=Decimal("1"),
            unrealized_pnl=Decimal("0"),
            unrealized_pnl_pct=0.0,
            valuation_known=True,
            source="manual",
            source_id=None,
            currency_code="CNY",
            currency_name="人民币",
            currency_symbol="¥",
            opened_at=None,
            updated_at=None,
        )
        page = RecordedPositionPage(
            count=21,
            page=2,
            page_size=20,
            has_next=False,
            items=(position,),
        )

        payload = page.to_payload()

        self.assertEqual(payload["count"], 21)
        self.assertEqual(payload["page"], 2)
        self.assertFalse(payload["has_next"])
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["avg_cost"], "1")

    def test_read_clock_is_explicitly_not_source_time(self) -> None:
        """Read boundaries cannot be mistaken for source observation clocks."""

        timestamp = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
        payload = RecordedReadClock(timestamp, timestamp).to_payload()

        self.assertEqual(payload["read_started_at"], timestamp.isoformat())
        self.assertEqual(payload["clock_kind"], "application_read_boundary")
        self.assertEqual(payload["source_time_status"], "not_provided")

    def test_statistics_discloses_missing_fx_normalization(self) -> None:
        """Statistics retain stored values without claiming one currency basis."""

        statistics = RecordedStatistics(
            total_value=Decimal("1"),
            total_cost=Decimal("1"),
            total_pnl=Decimal("0"),
            total_pnl_pct=0.0,
            position_count=1,
            asset_class_breakdown={"股票": 1.0},
            region_breakdown={"中国境内": 1.0},
            valuation_known=True,
            total_capital_inflow=Decimal("0"),
            total_capital_outflow=Decimal("0"),
            net_capital_flow=Decimal("0"),
        )

        self.assertEqual(
            statistics.to_payload()["currency_status"],
            "stored_values_without_fx_normalization",
        )

    def test_money_strings_preserve_precision_and_zero(self) -> None:
        """The JSON boundary keeps exact Decimal text, including a legal zero."""

        statistics = RecordedStatistics(
            total_value=Decimal("12345678901234567890.123456789"),
            total_cost=Decimal("0"),
            total_pnl=Decimal("-0.000000001"),
            total_pnl_pct=0.0,
            position_count=0,
            asset_class_breakdown={},
            region_breakdown={},
            valuation_known=True,
            total_capital_inflow=Decimal("0"),
            total_capital_outflow=Decimal("0"),
            net_capital_flow=Decimal("0"),
        )

        payload = statistics.to_payload()

        self.assertEqual(payload["total_value"], "12345678901234567890.123456789")
        self.assertEqual(payload["total_cost"], "0")
        self.assertEqual(Decimal(payload["total_pnl"]), Decimal("-0.000000001"))
        self.assertIsInstance(payload["total_pnl"], str)
        self.assertIsInstance(payload["total_value"], str)

    def test_unknown_statistics_keep_cost_and_position_count_but_null_estimate(self) -> None:
        """Unknown valuation does not turn missing market data into zero or a loss."""

        statistics = RecordedStatistics(
            total_value=None,
            total_cost=Decimal("1000"),
            total_pnl=None,
            total_pnl_pct=None,
            position_count=1,
            asset_class_breakdown=None,
            region_breakdown=None,
            valuation_known=False,
            total_capital_inflow=Decimal("0"),
            total_capital_outflow=Decimal("0"),
            net_capital_flow=Decimal("0"),
        )

        payload = statistics.to_payload()

        self.assertIsNone(payload["total_value"])
        self.assertEqual(payload["total_cost"], "1000")
        self.assertIsNone(payload["total_pnl"])
        self.assertIsNone(payload["total_pnl_pct"])
        self.assertIsNone(payload["asset_class_breakdown"])
        self.assertEqual(payload["position_count"], 1)
        self.assertFalse(payload["valuation_known"])
        self.assertEqual(payload["valuation_status"], "unknown")
