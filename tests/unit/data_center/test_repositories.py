from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.db import OperationalError

from apps.data_center.domain.entities import (
    MacroFact,
    MarketThermometerThresholds,
    MarketThermometerUserOverride,
)
from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.infrastructure import orm_retry
from apps.data_center.infrastructure.a_share_universe_sync import (
    AShareUniverseSyncService,
)
from apps.data_center.infrastructure.diagnostic_queries import DataCenterDiagnosticRepository
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialFactModel,
    MacroFactModel,
    MarketThermometerSnapshotModel,
    NewsFactModel,
    PriceBarModel,
    PublisherCatalogModel,
    ValuationFactModel,
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


def test_macro_fact_repository_retries_transient_sqlite_lock(monkeypatch):
    attempts: list[dict] = []
    sleeps: list[float] = []
    closed_connections: list[bool] = []

    def fake_update_or_create(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise OperationalError("database is locked")
        return object(), True

    monkeypatch.setattr(MacroFactModel.objects, "update_or_create", fake_update_or_create)
    monkeypatch.setattr(orm_retry.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        orm_retry,
        "close_old_connections",
        lambda: closed_connections.append(True),
    )

    stored = MacroFactRepository().bulk_upsert(
        [
            MacroFact(
                indicator_code="CN_TEST_LOCK",
                reporting_period=date(2026, 6, 30),
                value=1.23,
                unit="%",
                source="akshare",
                quality=DataQualityStatus.VALID,
            )
        ]
    )

    assert stored == 1
    assert len(attempts) == 2
    assert sleeps == [orm_retry.SQLITE_LOCK_RETRY_DELAYS_SECONDS[0]]
    assert closed_connections == [True]


def test_macro_fact_repository_does_not_retry_non_lock_operational_error(monkeypatch):
    attempts = 0

    def fake_update_or_create(**kwargs):
        nonlocal attempts
        attempts += 1
        raise OperationalError("no such table: data_center_macro_fact")

    monkeypatch.setattr(MacroFactModel.objects, "update_or_create", fake_update_or_create)

    with pytest.raises(OperationalError, match="no such table"):
        MacroFactRepository().bulk_upsert(
            [
                MacroFact(
                    indicator_code="CN_TEST_NO_TABLE",
                    reporting_period=date(2026, 6, 30),
                    value=1.23,
                    unit="%",
                    source="akshare",
                    quality=DataQualityStatus.VALID,
                )
            ]
        )

    assert attempts == 1


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
    latest_day = date.today()
    previous_day = latest_day - timedelta(days=1)
    MarketThermometerSnapshotModel.objects.create(
        observed_at=previous_day,
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
        calculated_at=datetime(
            previous_day.year,
            previous_day.month,
            previous_day.day,
            tzinfo=UTC,
        ),
    )
    MarketThermometerSnapshotModel.objects.create(
        observed_at=latest_day,
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
        calculated_at=datetime(
            latest_day.year,
            latest_day.month,
            latest_day.day,
            tzinfo=UTC,
        ),
    )

    repo = MarketThermometerSnapshotRepository()
    latest = repo.get_latest()
    history = repo.list_history(days=10)

    assert latest is not None
    assert latest.observed_at == latest_day
    assert [item.observed_at for item in history][:2] == [latest_day, previous_day]


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


@pytest.mark.django_db
def test_data_center_diagnostic_repository_summarizes_active_stock_fact_coverage():
    AssetMasterModel.objects.create(
        code="600000.SH",
        name="浦发银行",
        asset_type="stock",
        exchange="SSE",
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="510300.SH",
        name="沪深300ETF",
        asset_type="etf",
        exchange="SSE",
        is_active=True,
    )
    PriceBarModel.objects.create(
        asset_code="600000.SH",
        bar_date=date(2026, 7, 3),
        freq="1d",
        adjustment="none",
        open="1",
        high="1",
        low="1",
        close="1",
        source="test",
    )
    ValuationFactModel.objects.create(
        asset_code="600000.SH",
        val_date=date(2026, 7, 3),
        pe_ttm="10",
        source="test",
    )
    FinancialFactModel.objects.create(
        asset_code="600000.SH",
        period_end=date(2026, 3, 31),
        period_type="quarterly",
        metric_code="revenue",
        value="100",
        source="test",
    )

    payload = DataCenterDiagnosticRepository().get_active_stock_fact_coverage_summary()

    assert payload["status"] == "incomplete"
    assert payload["asset_count"] == 2
    assert payload["universe_quality"]["status"] == "incomplete"
    assert "active_a_share_universe_too_narrow" in payload["universe_quality"]["issues"]
    assert payload["domains"]["price"] == {
        "covered_count": 1,
        "missing_count": 1,
        "latest_date": "2026-07-03",
        "status": "incomplete",
    }
    assert payload["domains"]["valuation"]["covered_count"] == 1
    assert payload["domains"]["financial"]["latest_date"] == "2026-03-31"


@pytest.mark.django_db
def test_a_share_universe_sync_upserts_current_market_boards():
    class FakeProvider:
        source_name = "fake_akshare"

        def load_code_names(self):
            return [
                {"code": "000001", "name": "平安银行"},
                {"code": "300750", "name": "宁德时代"},
                {"code": "688111", "name": "金山办公"},
                {"code": "920992", "name": "中科美菱"},
                {"code": "000004", "name": "国华退"},
            ]

    report = AShareUniverseSyncService(provider=FakeProvider()).sync()

    assert report.active_count == 4
    assert report.skipped_count == 1
    assert AssetMasterModel.objects.filter(code="000001.SZ", exchange="SZSE").exists()
    assert AssetMasterModel.objects.filter(code="300750.SZ", exchange="SZSE").exists()
    assert AssetMasterModel.objects.filter(code="688111.SH", exchange="SSE").exists()
    assert AssetMasterModel.objects.filter(code="920992.BJ", exchange="BSE").exists()
    assert not AssetMasterModel.objects.filter(code="000004.SZ").exists()
