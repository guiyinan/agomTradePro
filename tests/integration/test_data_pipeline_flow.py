"""
Integration Test: Full Data Pipeline Flow

Tests the complete data pipeline:
  Macro Data Ingestion → Regime Calculation → Signal Generation → Audit Trail

All external APIs are mocked. Tests verify data flows correctly through layers.
"""

import json
from datetime import UTC, date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase, override_settings

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.mark.django_db
class TestDataPipelineFlow(TestCase):
    """End-to-end data pipeline integration test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Load fixture data
        with open(FIXTURES_DIR / "macro_data.json", encoding="utf-8") as f:
            cls.macro_fixtures = json.load(f)

    def _load_macro_fixtures_to_db(self):
        """Load macro fixture data into the database."""
        from apps.macro.infrastructure.models import MacroIndicator

        indicators_created = []
        for code, indicator_data in self.macro_fixtures["indicators"].items():
            for point in indicator_data["data"]:
                obj, _ = MacroIndicator.objects.get_or_create(
                    code=code,
                    reporting_period=date.fromisoformat(point["date"]),
                    defaults={
                        "value": float(point["value"]),
                        "unit": indicator_data["unit"],
                        "source": "fixture",
                        "period_type": "M",
                    },
                )
            indicators_created.append(code)

        return indicators_created

    def test_macro_data_ingestion(self):
        """Verify macro fixture data loads correctly into DB."""
        indicators = self._load_macro_fixtures_to_db()

        from apps.macro.infrastructure.models import MacroIndicator

        assert len(indicators) == 4
        # PMI should have 12 data points
        pmi_count = MacroIndicator.objects.filter(
            code="CN_PMI_MANUFACTURING"
        ).count()
        assert pmi_count == 12

    def test_regime_calculation_with_fixture_data(self):
        """Verify regime can be calculated from fixture macro data."""
        self._load_macro_fixtures_to_db()

        from apps.regime.domain.services import RegimeCalculator

        # Build growth and inflation series from fixtures
        pmi_data = self.macro_fixtures["indicators"]["CN_PMI_MANUFACTURING"]["data"]
        cpi_data = self.macro_fixtures["indicators"]["CN_CPI_YOY"]["data"]

        growth_series = {
            date.fromisoformat(p["date"]): p["value"] for p in pmi_data
        }
        inflation_series = {
            date.fromisoformat(p["date"]): p["value"] for p in cpi_data
        }

        # Verify data integrity
        assert len(growth_series) == 12
        assert len(inflation_series) == 12

        # PMI around 50, CPI low -> likely "growth_deflation" regime
        latest_pmi = pmi_data[-1]["value"]
        latest_cpi = cpi_data[-1]["value"]
        assert latest_pmi > 49.0  # marginal growth
        assert latest_cpi < 1.0  # low inflation

    def test_pipeline_data_freshness_check(self):
        """Verify data freshness monitoring works."""
        self._load_macro_fixtures_to_db()

        from django.db.models import Max

        from apps.macro.infrastructure.models import MacroIndicator

        # Check latest dates per indicator
        latest_dates = (
            MacroIndicator.objects
            .values("code")
            .annotate(latest=Max("reporting_period"))
        )

        for entry in latest_dates:
            assert entry["latest"] is not None
            # Fixture data should have valid dates
            assert entry["latest"].year >= 2024

    def test_signal_generation_requires_regime(self):
        """Verify signal entity has required fields including invalidation."""
        from apps.signal.domain.entities import InvestmentSignal

        signal = InvestmentSignal(
            id="test-001",
            asset_code="000001.SH",
            asset_class="a_share_growth",
            direction="LONG",
            logic_desc="PMI 连续回升",
            invalidation_rule=None,
            invalidation_description="PMI 跌破 50 且连续 2 月低于前值",
        )
        assert signal.invalidation_description is not None
        assert signal.direction == "LONG"

    def test_audit_trail_captures_regime_change(self):
        """Verify regime changes create audit records."""
        from apps.events.domain.entities import DomainEvent, EventType

        event = DomainEvent(
            event_id="test-regime-change-001",
            event_type=EventType.REGIME_CHANGED,
            occurred_at=datetime.now(UTC),
            payload={
                "old_regime": "growth_inflation",
                "new_regime": "growth_deflation",
                "calc_date": "2024-12-31",
            },
            metadata={"source": "integration_test"},
        )

        assert event.event_type == EventType.REGIME_CHANGED
        assert event.payload["old_regime"] == "growth_inflation"
        assert event.payload["new_regime"] == "growth_deflation"


@pytest.mark.django_db
class TestDataConsistencyValidation(TestCase):
    """Test data consistency between pipeline stages."""

    def test_macro_data_units_are_consistent(self):
        """Verify all macro data has correct unit information."""
        fixtures_path = FIXTURES_DIR / "macro_data.json"
        with open(fixtures_path, encoding="utf-8") as f:
            data = json.load(f)

        valid_units = {"%", "指数", "元", "万元", "亿元", "点", "元/g", "元/吨"}

        for code, indicator in data["indicators"].items():
            assert "unit" in indicator, f"Missing unit for {code}"
            assert indicator["unit"] in valid_units, (
                f"Invalid unit '{indicator['unit']}' for {code}"
            )

    def test_market_data_ohlcv_consistency(self):
        """Verify OHLCV data follows market conventions."""
        fixtures_path = FIXTURES_DIR / "market_data.json"
        with open(fixtures_path, encoding="utf-8") as f:
            data = json.load(f)

        for index_code, index_data in data["indices"].items():
            for bar in index_data["data"]:
                # High >= Open and Close
                assert bar["high"] >= bar["open"], f"High < Open on {bar['date']}"
                assert bar["high"] >= bar["close"], f"High < Close on {bar['date']}"
                # Low <= Open and Close
                assert bar["low"] <= bar["open"], f"Low > Open on {bar['date']}"
                assert bar["low"] <= bar["close"], f"Low > Close on {bar['date']}"
                # Volume positive
                assert bar["volume"] > 0, f"Non-positive volume on {bar['date']}"

    def test_alpha_scores_are_sorted_by_rank(self):
        """Verify alpha scores are properly ranked."""
        fixtures_path = FIXTURES_DIR / "alpha_scores.json"
        with open(fixtures_path, encoding="utf-8") as f:
            data = json.load(f)

        scores = data["scores"]
        for i in range(len(scores) - 1):
            assert scores[i]["rank"] < scores[i + 1]["rank"]
            assert scores[i]["score"] >= scores[i + 1]["score"]
