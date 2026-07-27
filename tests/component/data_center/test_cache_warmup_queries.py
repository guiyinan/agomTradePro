"""Canonical macro cache-warmup query regression tests."""

from datetime import date

import pytest

from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.infrastructure.cache_warmup_queries import (
    MacroFactCacheWarmupRepository,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel


def _create_fact(
    *,
    code: str,
    reporting_period: date,
    value: float,
    source: str,
    quality: str = "valid",
) -> None:
    MacroFactModel.objects.create(
        indicator_code=code,
        reporting_period=reporting_period,
        value=value,
        unit="%",
        source=source,
        quality=quality,
        extra={"source_type": source},
    )


@pytest.mark.django_db
def test_macro_cache_warmup_batches_queries_and_applies_canonical_selection(
    django_assert_num_queries,
) -> None:
    """Warmup uses three bulk queries while preserving governed source selection."""

    IndicatorCatalogModel.objects.create(
        code="CACHE_A",
        name_cn="缓存 A",
        name_en="Cache A",
        category="test",
        default_period_type="M",
        default_unit="%",
        extra={"governance_sync_source_type": "tushare"},
    )
    _create_fact(
        code="CACHE_A",
        reporting_period=date(2026, 6, 1),
        value=1.0,
        source="tushare",
    )
    _create_fact(
        code="CACHE_A",
        reporting_period=date(2026, 7, 1),
        value=99.0,
        source="akshare",
    )
    _create_fact(
        code="CACHE_A",
        reporting_period=date(2026, 7, 1),
        value=2.0,
        source="tushare",
        quality="stale",
    )
    _create_fact(
        code="CACHE_B",
        reporting_period=date(2026, 7, 1),
        value=7.0,
        source="akshare",
    )
    _create_fact(
        code="CACHE_C",
        reporting_period=date(2026, 7, 1),
        value=1.0,
        source="akshare",
    )
    _create_fact(
        code="CACHE_C",
        reporting_period=date(2026, 7, 1),
        value=3.0,
        source="tushare",
    )

    with django_assert_num_queries(3):
        facts = MacroFactCacheWarmupRepository().list_latest_by_indicator(limit=3)

    assert [(fact.indicator_code, fact.source, fact.value) for fact in facts] == [
        ("CACHE_A", "tushare", 2.0),
        ("CACHE_B", "akshare", 7.0),
    ]
    assert facts[0].quality is DataQualityStatus.STALE


@pytest.mark.parametrize("limit", [True, "5", 1.5])
@pytest.mark.django_db
def test_macro_cache_warmup_rejects_non_integer_limit(
    limit: object,
    django_assert_num_queries,
) -> None:
    """Dynamic limit values fail before the warmup touches the database."""

    with django_assert_num_queries(0), pytest.raises(ValueError, match="limit must be an integer"):
        MacroFactCacheWarmupRepository().list_latest_by_indicator(limit=limit)


@pytest.mark.parametrize("limit", [0, -1])
@pytest.mark.django_db
def test_macro_cache_warmup_nonpositive_limit_is_a_query_free_noop(
    limit: int,
    django_assert_num_queries,
) -> None:
    """An explicitly empty warmup remains a query-free no-op."""

    with django_assert_num_queries(0):
        assert MacroFactCacheWarmupRepository().list_latest_by_indicator(limit=limit) == []
