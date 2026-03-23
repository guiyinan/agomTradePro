"""
Unit tests for Macro Domain Entities.

Pure Domain layer tests using only Python standard library.
"""

from datetime import date

import pytest

from apps.macro.domain.entities import MacroIndicator


class TestMacroIndicator:
    """Tests for MacroIndicator value object"""

    def test_create_macro_indicator_basic(self):
        """Test creating a basic MacroIndicator"""
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1)
        )

        assert indicator.code == "CN_PMI"
        assert indicator.value == 50.1
        assert indicator.observed_at == date(2024, 1, 1)
        assert indicator.published_at is None
        assert indicator.source == "unknown"

    def test_create_macro_indicator_with_all_fields(self):
        """Test creating MacroIndicator with all fields"""
        indicator = MacroIndicator(
            code="CN_CPI",
            value=2.1,
            reporting_period=date(2024, 1, 1),
            published_at=date(2024, 1, 10),
            source="NBS"
        )

        assert indicator.code == "CN_CPI"
        assert indicator.value == 2.1
        assert indicator.observed_at == date(2024, 1, 1)
        assert indicator.published_at == date(2024, 1, 10)
        assert indicator.source == "NBS"

    def test_macro_indicator_frozen(self):
        """Test that MacroIndicator is frozen (immutable)"""
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1)
        )

        # Should raise FrozenInstanceError when trying to modify
        with pytest.raises(Exception):  # FrozenInstanceError
            indicator.value = 51.0

    def test_macro_indicator_equality(self):
        """Test MacroIndicator equality"""
        indicator1 = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1)
        )
        indicator2 = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1)
        )
        indicator3 = MacroIndicator(
            code="CN_PMI",
            value=50.2,  # Different value
            reporting_period=date(2024, 1, 1)
        )

        assert indicator1 == indicator2
        assert indicator1 != indicator3

    def test_macro_indicator_hash(self):
        """Test MacroIndicator is hashable"""
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1)
        )

        # Should be able to create a set with it
        indicators = {indicator}
        assert len(indicators) == 1

    def test_macro_indicator_negative_value(self):
        """Test MacroIndicator with negative value"""
        indicator = MacroIndicator(
            code="CN_GROWTH_RATE",
            value=-2.5,
            reporting_period=date(2024, 1, 1)
        )

        assert indicator.value == -2.5

    def test_macro_indicator_zero_value(self):
        """Test MacroIndicator with zero value"""
        indicator = MacroIndicator(
            code="CN_SOME_INDICATOR",
            value=0.0,
            reporting_period=date(2024, 1, 1)
        )

        assert indicator.value == 0.0

    def test_macro_indicator_default_source(self):
        """Test default source is 'unknown'"""
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1)
        )

        assert indicator.source == "unknown"

    def test_macro_indicator_custom_source(self):
        """Test custom source"""
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1),
            source="Tushare"
        )

        assert indicator.source == "Tushare"

    def test_macro_indicator_with_publication_lag(self):
        """Test indicator with publication lag"""
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1),
            published_at=date(2024, 2, 1),  # Published 1 month later
            source="NBS"
        )

        assert indicator.observed_at == date(2024, 1, 1)
        assert indicator.published_at == date(2024, 2, 1)

    def test_macro_indicator_future_observed_date(self):
        """Test indicator with future observed date"""
        future_date = date(2025, 12, 31)
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=future_date
        )

        assert indicator.observed_at == future_date

    def test_macro_indicator_code_types(self):
        """Test various indicator code formats"""
        codes = [
            "CN_PMI",
            "CN_CPI_YOY",
            "CN_M2_MOM",
            "SHIBOR_1W",
            "000001.SH"
        ]

        for code in codes:
            indicator = MacroIndicator(
                code=code,
                value=50.0,
                reporting_period=date(2024, 1, 1)
            )
            assert indicator.code == code

    def test_macro_indicator_precision(self):
        """Test indicator value with high precision"""
        indicator = MacroIndicator(
            code="CN_CPI",
            value=2.123456789,
            reporting_period=date(2024, 1, 1)
        )

        assert indicator.value == pytest.approx(2.123456789)

    def test_macro_indicator_repr(self):
        """Test MacroIndicator string representation"""
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1)
        )

        repr_str = repr(indicator)
        assert "MacroIndicator" in repr_str
        assert "CN_PMI" in repr_str


class TestMacroIndicatorEdgeCases:
    """Edge case tests for MacroIndicator"""

    def test_very_large_value(self):
        """Test with very large value"""
        indicator = MacroIndicator(
            code="CN_M2",
            value=1e15,  # Very large number (like money supply)
            reporting_period=date(2024, 1, 1)
        )

        assert indicator.value == 1e15

    def test_very_small_value(self):
        """Test with very small value"""
        indicator = MacroIndicator(
            code="CN_RATE",
            value=1e-6,
            reporting_period=date(2024, 1, 1)
        )

        assert indicator.value == 1e-6

    def test_empty_code(self):
        """Test with empty code (should still work)"""
        indicator = MacroIndicator(
            code="",
            value=50.1,
            reporting_period=date(2024, 1, 1)
        )

        assert indicator.code == ""

    def test_minimal_date(self):
        """Test with minimal date"""
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(1970, 1, 1)
        )

        assert indicator.observed_at == date(1970, 1, 1)

    def test_copy_with_modification(self):
        """Test that we need to create new instance for modification"""
        original = MacroIndicator(
            code="CN_PMI",
            value=50.1,
            reporting_period=date(2024, 1, 1),
            source="NBS"
        )

        # To "modify", we need to create a new instance
        modified = MacroIndicator(
            code=original.code,
            value=51.0,  # Changed value
            reporting_period=original.reporting_period,
            published_at=original.published_at,
            source=original.source
        )

        assert original.value == 50.1  # Original unchanged
        assert modified.value == 51.0
        assert original is not modified
