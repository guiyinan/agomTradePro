"""
交叉校验模块测试
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.market_data.application.cross_validator import (
    PRICE_ALERT_THRESHOLD_PCT,
    PRICE_TOLERANCE_PCT,
    CrossValidationResult,
    _pct_diff,
    cross_validate_quotes,
    validate_and_select,
)
from apps.market_data.domain.entities import QuoteSnapshot
from apps.market_data.domain.enums import DataCapability


class TestPctDiff:
    def test_both_zero(self):
        assert _pct_diff(Decimal("0"), Decimal("0")) == 0.0

    def test_one_zero(self):
        assert _pct_diff(Decimal("0"), Decimal("10")) == 100.0

    def test_same_value(self):
        assert _pct_diff(Decimal("10"), Decimal("10")) == 0.0

    def test_small_diff(self):
        diff = _pct_diff(Decimal("100"), Decimal("100.5"))
        assert 0 < diff < 1.0

    def test_large_diff(self):
        diff = _pct_diff(Decimal("100"), Decimal("110"))
        assert diff > 5.0


class TestCrossValidateQuotes:
    def _make_snap(self, code: str, price: str, source: str = "src") -> QuoteSnapshot:
        return QuoteSnapshot(
            stock_code=code,
            price=Decimal(price),
            source=source,
        )

    def test_all_match(self):
        primary = [self._make_snap("000001.SZ", "10.00", "p")]
        secondary = [self._make_snap("000001.SZ", "10.05", "s")]
        result = cross_validate_quotes(primary, secondary)
        assert result.is_clean
        assert len(result.matches) == 1

    def test_deviation(self):
        primary = [self._make_snap("000001.SZ", "10.00", "p")]
        secondary = [self._make_snap("000001.SZ", "10.30", "s")]
        result = cross_validate_quotes(primary, secondary)
        assert len(result.deviations) == 1
        assert result.deviations[0]["stock_code"] == "000001.SZ"
        assert not result.is_clean

    def test_alert(self):
        primary = [self._make_snap("000001.SZ", "10.00", "p")]
        secondary = [self._make_snap("000001.SZ", "15.00", "s")]
        result = cross_validate_quotes(primary, secondary)
        assert len(result.alerts) == 1
        assert not result.is_clean

    def test_missing_in_primary(self):
        primary = []
        secondary = [self._make_snap("000001.SZ", "10.00", "s")]
        result = cross_validate_quotes(primary, secondary)
        assert "000001.SZ" in result.missing_in_primary

    def test_missing_in_secondary(self):
        primary = [self._make_snap("000001.SZ", "10.00", "p")]
        secondary = []
        result = cross_validate_quotes(primary, secondary)
        assert "000001.SZ" in result.missing_in_secondary

    def test_multiple_stocks_mixed(self):
        primary = [
            self._make_snap("000001.SZ", "10.00", "p"),
            self._make_snap("000002.SZ", "20.00", "p"),
            self._make_snap("000003.SZ", "30.00", "p"),
        ]
        secondary = [
            self._make_snap("000001.SZ", "10.05", "s"),  # match
            self._make_snap("000002.SZ", "20.80", "s"),  # deviation (~4%)
            self._make_snap("000003.SZ", "40.00", "s"),  # alert (~25%)
        ]
        result = cross_validate_quotes(primary, secondary)
        assert len(result.matches) == 1
        assert len(result.deviations) == 1
        assert len(result.alerts) == 1
        assert result.total_checked == 3

    def test_custom_tolerance(self):
        primary = [self._make_snap("000001.SZ", "10.00", "p")]
        secondary = [self._make_snap("000001.SZ", "10.30", "s")]
        # With high tolerance, should be a match
        result = cross_validate_quotes(primary, secondary, tolerance_pct=5.0)
        assert len(result.matches) == 1

    def test_to_dict(self):
        result = CrossValidationResult()
        result.matches.append("000001.SZ")
        d = result.to_dict()
        assert d["total_checked"] == 1
        assert d["matches"] == 1
        assert d["is_clean"] is True


class TestValidateAndSelect:
    def _make_snap(self, code: str, price: str, source: str) -> QuoteSnapshot:
        return QuoteSnapshot(
            stock_code=code,
            price=Decimal(price),
            source=source,
        )

    def test_no_providers(self):
        registry = MagicMock()
        registry.get_providers.return_value = []
        data, validation = validate_and_select(registry, ["000001.SZ"])
        assert data == []
        assert validation is None

    def test_single_provider_no_validation(self):
        provider = MagicMock()
        provider.get_quote_snapshots.return_value = [
            self._make_snap("000001.SZ", "10.00", "p"),
        ]
        registry = MagicMock()
        registry.get_providers.return_value = [provider]

        data, validation = validate_and_select(registry, ["000001.SZ"])
        assert len(data) == 1
        assert validation is None

    def test_two_providers_with_validation(self):
        primary = MagicMock()
        primary.provider_name.return_value = "primary"
        primary.get_quote_snapshots.return_value = [
            self._make_snap("000001.SZ", "10.00", "primary"),
        ]

        secondary = MagicMock()
        secondary.provider_name.return_value = "secondary"
        secondary.get_quote_snapshots.return_value = [
            self._make_snap("000001.SZ", "10.05", "secondary"),
        ]

        registry = MagicMock()
        registry.get_providers.return_value = [primary, secondary]

        data, validation = validate_and_select(registry, ["000001.SZ"])
        assert len(data) == 1
        assert validation is not None
        assert validation.is_clean

    def test_primary_fails_fallback(self):
        primary = MagicMock()
        primary.provider_name.return_value = "primary"
        primary.get_quote_snapshots.return_value = []

        fallback = MagicMock()
        fallback.provider_name.return_value = "fallback"
        fallback.get_quote_snapshots.return_value = [
            self._make_snap("000001.SZ", "10.00", "fallback"),
        ]

        registry = MagicMock()
        registry.get_providers.return_value = [primary, fallback]

        data, validation = validate_and_select(registry, ["000001.SZ"])
        assert len(data) == 1
        assert data[0].source == "fallback"
        assert validation is None

    def test_secondary_exception_skips_validation(self):
        primary = MagicMock()
        primary.provider_name.return_value = "primary"
        primary.get_quote_snapshots.return_value = [
            self._make_snap("000001.SZ", "10.00", "primary"),
        ]

        secondary = MagicMock()
        secondary.provider_name.return_value = "secondary"
        secondary.get_quote_snapshots.side_effect = Exception("network error")

        registry = MagicMock()
        registry.get_providers.return_value = [primary, secondary]

        data, validation = validate_and_select(registry, ["000001.SZ"])
        assert len(data) == 1
        assert validation is None
