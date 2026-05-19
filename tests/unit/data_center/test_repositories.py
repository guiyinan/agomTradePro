from datetime import UTC, date, datetime

import pytest
from django.contrib.auth.models import User

from apps.data_center.domain.entities import (
    MarketThermometerThresholds,
    MarketThermometerUserOverride,
)
from apps.data_center.infrastructure.models import (
    MacroFactModel,
    MarketThermometerSnapshotModel,
    NewsFactModel,
    PublisherCatalogModel,
)
from apps.data_center.infrastructure.repositories import (
    MacroFactRepository,
    MarketThermometerConfigRepository,
    MarketThermometerSnapshotRepository,
    MarketThermometerUserOverrideRepository,
    NewsRepository,
    PublisherCatalogRepository,
)


@pytest.mark.django_db
def test_macro_fact_repository_returns_latest_first_series():
    MacroFactModel.objects.create(
        indicator_code="CN_IMPORT_YOY",
        reporting_period=date(2025, 6, 1),
        value="1.200000",
        unit="%",
        source="akshare",
        revision_number=1,
        quality="valid",
        extra={},
    )
    MacroFactModel.objects.create(
        indicator_code="CN_IMPORT_YOY",
        reporting_period=date(2026, 3, 1),
        value="27.800000",
        unit="%",
        source="akshare",
        revision_number=1,
        quality="valid",
        extra={},
    )

    rows = MacroFactRepository().get_series("CN_IMPORT_YOY", limit=10)

    assert [row.reporting_period for row in rows] == [
        date(2026, 3, 1),
        date(2025, 6, 1),
    ]


@pytest.mark.django_db
def test_publisher_catalog_repository_persists_aliases():
    PublisherCatalogModel.objects.create(
        code="TEST_REPO_PUBLISHER",
        canonical_name="测试仓储机构",
        publisher_class="government",
        aliases=["测试别名一", "测试别名二"],
    )

    publisher = PublisherCatalogRepository().get_by_code("TEST_REPO_PUBLISHER")

    assert publisher is not None
    assert publisher.canonical_name == "测试仓储机构"
    assert publisher.aliases == ["测试别名一", "测试别名二"]


@pytest.mark.django_db
def test_market_thermometer_config_repository_loads_default_weights():
    config = MarketThermometerConfigRepository().load()

    assert config.short_window == 5
    assert config.component_weights["turnover"] == 0.25
    assert config.thresholds.overheat_threshold == 75.0


@pytest.mark.django_db
def test_market_thermometer_user_override_repository_round_trip():
    user = User.objects.create_user(username="thermo-user", password="pass1234")
    repo = MarketThermometerUserOverrideRepository()

    saved = repo.save(
        MarketThermometerUserOverride(
            user_id=user.id,
            thresholds=MarketThermometerThresholds(
                warm_threshold=30.0,
                hot_threshold=55.0,
                overheat_threshold=72.0,
                extreme_threshold=88.0,
            ),
        )
    )

    loaded = repo.get_by_user_id(user.id)

    assert saved.thresholds.hot_threshold == 55.0
    assert loaded is not None
    assert loaded.thresholds.extreme_threshold == 88.0


@pytest.mark.django_db
def test_market_thermometer_snapshot_repository_history_reads_latest():
    MarketThermometerSnapshotModel.objects.create(
        observed_at=date(2026, 5, 18),
        score=68.0,
        band="hot",
        components=[],
        trigger_reasons=["成交额抬升"],
        stale_components=[],
        missing_components=[],
        valid_component_count=5,
        data_source="calculated",
        must_not_use_for_decision=False,
        blocked_reason="",
        calculated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )
    MarketThermometerSnapshotModel.objects.create(
        observed_at=date(2026, 5, 19),
        score=79.0,
        band="overheat",
        components=[],
        trigger_reasons=["融资余额抬升"],
        stale_components=[],
        missing_components=[],
        valid_component_count=5,
        data_source="calculated",
        must_not_use_for_decision=False,
        blocked_reason="",
        calculated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )

    repo = MarketThermometerSnapshotRepository()
    latest = repo.get_latest()
    history = repo.list_history(days=10)

    assert latest is not None
    assert latest.observed_at == date(2026, 5, 19)
    assert [item.observed_at for item in history][:2] == [date(2026, 5, 19), date(2026, 5, 18)]


@pytest.mark.django_db
def test_news_repository_aggregate_market_daily_computes_ratio():
    NewsFactModel.objects.create(
        asset_code="",
        title="市场回暖",
        summary="summary",
        url="https://example.com/1",
        published_at=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
        source="akshare",
        external_id="n1",
        sentiment_score=0.6,
    )
    NewsFactModel.objects.create(
        asset_code="",
        title="市场承压",
        summary="summary",
        url="https://example.com/2",
        published_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
        source="akshare",
        external_id="n2",
        sentiment_score=-0.2,
    )

    metrics = NewsRepository().aggregate_market_daily(
        start=date(2026, 5, 19),
        end=date(2026, 5, 19),
    )

    assert len(metrics) == 1
    assert metrics[0].news_count == 2
    assert metrics[0].positive_ratio == 0.5
