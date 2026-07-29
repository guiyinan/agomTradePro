from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.db import OperationalError

from apps.data_center.domain.entities import (
    MacroFact,
    MarketThermometerThresholds,
    MarketThermometerUserOverride,
    ProductionCoverageUniverseConfig,
)
from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.infrastructure import orm_retry
from apps.data_center.infrastructure.a_share_universe_sync import (
    AShareUniverseSyncService,
    JsonFileAshareCodeNameProvider,
)
from apps.data_center.infrastructure.diagnostic_queries import DataCenterDiagnosticRepository
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialFactModel,
    MacroFactModel,
    MarketThermometerSnapshotModel,
    NewsFactModel,
    PriceBarModel,
    ProductionCoverageUniverseConfigModel,
    PublisherCatalogModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.repositories import (
    MacroFactRepository,
    MarketThermometerConfigRepository,
    MarketThermometerSnapshotRepository,
    MarketThermometerUserOverrideRepository,
    NewsRepository,
    ProductionCoverageUniverseConfigRepository,
    PublisherCatalogRepository,
)


def _governed_extra(*, source: str = "akshare") -> dict[str, object]:
    return {
        "source_type": source,
        "original_unit": "%",
        "display_unit": "%",
        "dimension_key": "rate",
        "multiplier_to_storage": 1.0,
        "matched_rule_id": 1,
        "period_type": "D",
    }


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
def test_macro_fact_repository_refreshes_fetched_at_on_existing_fact() -> None:
    """Refreshing an existing observation must advance its ingestion timestamp."""
    old_fetched_at = datetime(2026, 6, 1, tzinfo=UTC)
    refreshed_at = datetime(2026, 7, 19, 15, 30, tzinfo=UTC)
    existing = MacroFactModel.objects.create(
        indicator_code="CN_REFRESH_TEST",
        reporting_period=date(2026, 6, 30),
        value="1.000000",
        unit="%",
        source="akshare",
        revision_number=0,
        quality="valid",
        extra=_governed_extra(),
    )
    MacroFactModel.objects.filter(pk=existing.pk).update(fetched_at=old_fetched_at)

    MacroFactRepository().bulk_upsert(
        [
            MacroFact(
                indicator_code="CN_REFRESH_TEST",
                reporting_period=date(2026, 6, 30),
                value=1.1,
                unit="%",
                source="akshare",
                revision_number=0,
                fetched_at=refreshed_at,
                extra=_governed_extra(),
            )
        ]
    )

    existing.refresh_from_db()
    assert float(existing.value) == pytest.approx(1.1)
    assert existing.fetched_at == refreshed_at


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
                extra=_governed_extra(),
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
                    extra=_governed_extra(),
                )
            ]
        )

    assert attempts == 1


def test_macro_fact_repository_rejects_ungoverned_write(monkeypatch):
    monkeypatch.setattr(
        MacroFactModel.objects,
        "update_or_create",
        lambda **kwargs: (object(), True),
    )

    with pytest.raises(ValueError, match="missing governance metadata"):
        MacroFactRepository().bulk_upsert(
            [
                MacroFact(
                    indicator_code="CN_UNGOVERNED",
                    reporting_period=date(2026, 7, 19),
                    value=1.0,
                    unit="%",
                    source="akshare",
                )
            ]
        )


def test_macro_fact_repository_validates_entire_batch_before_writing(monkeypatch):
    """One invalid fact must prevent earlier facts from being persisted."""

    writes: list[dict] = []
    monkeypatch.setattr(
        MacroFactModel.objects,
        "update_or_create",
        lambda **kwargs: writes.append(kwargs),
    )
    valid = MacroFact(
        indicator_code="CN_VALID_FIRST",
        reporting_period=date(2026, 7, 1),
        value=1.0,
        unit="%",
        source="akshare",
        extra=_governed_extra(),
    )
    invalid = MacroFact(
        indicator_code="CN_INVALID_SECOND",
        reporting_period=date(2026, 7, 1),
        value=2.0,
        unit="%",
        source="akshare",
    )

    with pytest.raises(ValueError, match="missing governance metadata"):
        MacroFactRepository().bulk_upsert([valid, invalid])

    assert writes == []


@pytest.mark.parametrize("limit", [0, -1, True])
@pytest.mark.django_db
def test_macro_fact_repository_rejects_invalid_series_limit(limit):
    """Invalid query limits fail before ORM slicing."""

    with pytest.raises(ValueError, match="limit must be a positive integer"):
        MacroFactRepository().get_series("CN_IMPORT_YOY", limit=limit)


def test_macro_fact_repository_detaches_domain_extra_from_orm_model():
    """Mutable JSON metadata must not alias the ORM model after mapping."""

    model = MacroFactModel(
        indicator_code="CN_EXTRA_COPY",
        reporting_period=date(2026, 7, 1),
        value="1.000000",
        unit="%",
        source="akshare",
        revision_number=0,
        quality="valid",
        extra={"source_type": "akshare"},
    )

    fact = MacroFactRepository._from_model(model)
    fact.extra["source_type"] = "mutated"

    assert model.extra == {"source_type": "akshare"}


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


@pytest.mark.parametrize("limit", [0, -1, True, 1001])
def test_news_repository_rejects_invalid_query_limits(limit):
    with pytest.raises(ValueError, match="limit"):
        NewsRepository().get_recent(limit=limit)


def test_news_repository_rejects_inverted_aggregation_range():
    with pytest.raises(ValueError, match="start cannot be after end"):
        NewsRepository().aggregate_market_daily(
            start=date(2026, 5, 20),
            end=date(2026, 5, 19),
        )


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
def test_production_coverage_universe_config_repository_round_trips_defaults():
    config = ProductionCoverageUniverseConfigRepository().load()

    assert config.universe_id == "active_a_share"
    assert config.asset_type == "stock"
    assert config.exchanges == ["SSE", "SZSE", "BSE"]
    assert config.min_active_asset_count == 4000
    assert ProductionCoverageUniverseConfigModel.objects.count() == 1

    saved = ProductionCoverageUniverseConfigRepository().save(
        ProductionCoverageUniverseConfig(
            universe_id="local_test",
            asset_type="stock",
            exchanges=["SZSE", "SZSE"],
            include_inactive=True,
            min_active_asset_count=1,
            min_star_market_count=0,
            min_chinext_count=1,
            min_bse_count=0,
            description="test",
        )
    )

    assert saved.universe_id == "local_test"
    assert saved.exchanges == ["SZSE"]
    assert saved.include_inactive is True
    assert ProductionCoverageUniverseConfigModel.objects.count() == 1


@pytest.mark.django_db
def test_data_center_diagnostic_repository_uses_configured_universe():
    AssetMasterModel.objects.create(
        code="600000.SH",
        name="浦发银行",
        asset_type="stock",
        exchange="SSE",
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="300750.SZ",
        name="宁德时代",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="920992.BJ",
        name="中科美菱",
        asset_type="stock",
        exchange="BSE",
        is_active=True,
    )
    ProductionCoverageUniverseConfigRepository().save(
        ProductionCoverageUniverseConfig(
            universe_id="chinext_only",
            asset_type="stock",
            exchanges=["SZSE"],
            min_active_asset_count=1,
            min_star_market_count=0,
            min_chinext_count=1,
            min_bse_count=0,
        )
    )

    payload = DataCenterDiagnosticRepository().get_active_stock_fact_coverage_summary()

    assert payload["universe"] == "chinext_only"
    assert payload["asset_count"] == 1
    assert payload["universe_config"]["exchanges"] == ["SZSE"]
    assert payload["universe_quality"]["status"] == "ok"
    assert payload["universe_quality"]["exchange_counts"] == {"SZSE": 1}


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


@pytest.mark.django_db
def test_a_share_universe_sync_loads_rows_from_json_file(tmp_path):
    input_file = tmp_path / "a_share_universe.json"
    input_file.write_text(
        '[{"code": "688111", "name": "金山办公"}, {"code": "920992", "name": "中科美菱"}]',
        encoding="utf-8",
    )

    report = AShareUniverseSyncService(provider=JsonFileAshareCodeNameProvider(input_file)).sync()

    assert report.source == "json_file:a_share_universe.json"
    assert report.active_count == 2
    assert AssetMasterModel.objects.filter(code="688111.SH", exchange="SSE").exists()
    assert AssetMasterModel.objects.filter(code="920992.BJ", exchange="BSE").exists()
