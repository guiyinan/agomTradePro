"""Tests for canonical macro-fact governance normalization."""

from datetime import date

import pytest

from apps.data_center.application.macro_fact_governance import MacroFactGovernanceNormalizer
from apps.data_center.domain.entities import IndicatorCatalog, IndicatorUnitRule, MacroFact


class _CatalogRepo:
    def __init__(self, catalog: IndicatorCatalog | None) -> None:
        self._catalog = catalog

    def get_by_code(self, code: str) -> IndicatorCatalog | None:
        if self._catalog is not None and self._catalog.code == code:
            return self._catalog
        return None


class _RuleRepo:
    def __init__(self, rule: IndicatorUnitRule | None) -> None:
        self._rule = rule

    def resolve_active_rule(self, indicator_code, *, source_type="", original_unit=None):
        if self._rule is None or self._rule.indicator_code != indicator_code:
            return None
        if original_unit is not None and self._rule.original_unit != original_unit:
            return None
        return self._rule


def _catalog() -> IndicatorCatalog:
    return IndicatorCatalog(
        code="CN_TEST_CURRENCY",
        name_cn="测试货币指标",
        default_unit="元",
        default_period_type="M",
        is_active=True,
    )


def _rule(*, original_unit: str = "亿元", multiplier: float = 100_000_000.0):
    return IndicatorUnitRule(
        id=7,
        indicator_code="CN_TEST_CURRENCY",
        source_type="akshare",
        dimension_key="currency",
        original_unit=original_unit,
        storage_unit="元",
        display_unit="亿元",
        multiplier_to_storage=multiplier,
        priority=10,
    )


def test_normalizer_converts_raw_value_and_populates_complete_metadata():
    normalizer = MacroFactGovernanceNormalizer(_CatalogRepo(_catalog()), _RuleRepo(_rule()))

    fact = normalizer.normalize(
        MacroFact(
            indicator_code="CN_TEST_CURRENCY",
            reporting_period=date(2026, 5, 31),
            published_at=date(2026, 6, 10),
            value=1.5,
            unit="亿元",
            source="provider-label",
        ),
        source_type="akshare",
        provider_name="AKShare Public",
    )

    assert fact.value == 150_000_000.0
    assert fact.unit == "元"
    assert fact.source == "akshare"
    assert fact.extra == {
        "source_type": "akshare",
        "provider_name": "AKShare Public",
        "original_unit": "亿元",
        "display_unit": "亿元",
        "dimension_key": "currency",
        "multiplier_to_storage": 100_000_000.0,
        "matched_rule_id": 7,
        "period_type": "M",
        "publication_lag_days": 10,
    }


def test_normalizer_does_not_convert_an_already_canonical_value_again():
    normalizer = MacroFactGovernanceNormalizer(_CatalogRepo(_catalog()), _RuleRepo(_rule()))

    fact = normalizer.normalize(
        MacroFact(
            indicator_code="CN_TEST_CURRENCY",
            reporting_period=date(2026, 5, 31),
            value=150_000_000.0,
            unit="元",
            source="akshare",
            extra={"original_unit": "亿元"},
        )
    )

    assert fact.value == 150_000_000.0
    assert fact.unit == "元"


def test_normalizer_rejects_missing_catalog_or_rule():
    fact = MacroFact(
        indicator_code="CN_TEST_CURRENCY",
        reporting_period=date(2026, 5, 31),
        value=1.0,
        unit="亿元",
        source="akshare",
    )

    with pytest.raises(ValueError, match="catalog missing"):
        MacroFactGovernanceNormalizer(_CatalogRepo(None), _RuleRepo(_rule())).normalize(fact)
    with pytest.raises(ValueError, match="unit rule missing"):
        MacroFactGovernanceNormalizer(_CatalogRepo(_catalog()), _RuleRepo(None)).normalize(fact)
