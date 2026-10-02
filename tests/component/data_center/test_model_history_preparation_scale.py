"""Query budget for full-market model-history preparation and cache reads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.application.model_history_preparation import (
    ModelHistoryFetchAuditResult,
    ModelHistoryPreparedFetch,
    ModelHistoryReferenceSnapshot,
)
from apps.data_center.application.model_market_data import ModelMarketDataService, ModelMarketRoute
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.model_market_data import ModelDailyBar
from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    PriceBarModel,
)
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository

TARGET_DATE = date(2026, 9, 18)
FULL_MARKET_ASSET_COUNT = 5001
MAX_PREPARATION_SQL_QUERIES = 2


class _PreparedSource:
    """Stage one prepared response and serve exact-window reads from its private cache."""

    def __init__(self) -> None:
        self.preparation_calls = 0
        self.cache_reads = 0
        self._prepared: dict[tuple[str, date, date], tuple[ModelDailyBar, ...]] = {}
        self._fetches: tuple[ModelHistoryPreparedFetch, ...] = ()

    def prepare_stock_history(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> None:
        self.preparation_calls += 1
        rows = tuple(
            ModelDailyBar(
                asset_code=asset_code,
                trade_date=TARGET_DATE,
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.0,
                volume=10000.0,
                change_percent=0.0,
                adjustment_factor=1.0,
                source="tushare",
            )
            for asset_code in asset_codes
        )
        self._fetches = (
            ModelHistoryPreparedFetch(
                asset_codes=asset_codes,
                start_date=start_date,
                end_date=end_date,
                rows=rows,
                request_details={"provider_fetch_kind": "component_bulk_fixture"},
            ),
        )
        self._prepared = {(row.asset_code, start_date, end_date): (row,) for row in rows}

    def stock_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        self.cache_reads += 1
        return self._prepared.get((asset_code, start_date, end_date), ())

    def has_prepared_model_history(self, asset_code: str, start_date: date, end_date: date) -> bool:
        return (asset_code, start_date, end_date) in self._prepared

    def drain_model_history_prepared_fetches(self) -> tuple[ModelHistoryPreparedFetch, ...]:
        fetches, self._fetches = self._fetches, ()
        return fetches

    def index_history(
        self, _asset_code: str, _start_date: date, _end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        return ()

    def trade_days(self, start_date: date, end_date: date) -> tuple[date, ...]:
        return (TARGET_DATE,) if start_date <= TARGET_DATE <= end_date else ()

    def index_members(self, _index_code: str, _target_date: date) -> tuple[str, ...]:
        return ()


class _AuditWriter:
    """Keep the provider audit boundary in memory while measuring ORM reads."""

    def __init__(self) -> None:
        self.successes = 0
        self.failures = 0

    def record_model_history_fetch_success(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        rows: tuple[ModelDailyBar, ...],
        request_details: Mapping[str, object],
        reference_snapshot: ModelHistoryReferenceSnapshot,
    ) -> ModelHistoryFetchAuditResult:
        self.successes += 1
        reference = RawAuditReference(
            raw_audit_id="raw-audit-5001",
            version="raw-audit-v1",
            content_hash="a" * 64,
            run_id="run-5001",
            ingested_run_id="ingest-5001",
        )
        return ModelHistoryFetchAuditResult(
            provider_name="tushare",
            stored_count=len(rows),
            stored_asset_codes=tuple(sorted({row.asset_code for row in rows})),
            raw_audit_reference=reference,
            source_type="tushare",
        )

    def record_model_history_fetch_failure(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        error: BaseException,
        request_details: Mapping[str, object],
    ) -> RawAuditReference:
        self.failures += 1
        raise AssertionError("the complete fixture must not produce a failed provider audit")


@pytest.mark.django_db
def test_5001_asset_preparation_and_prepared_cache_reads_use_bounded_sql_queries() -> None:
    """Bound SQL across one ORM reference snapshot and all 5,001 cached reads."""

    asset_codes = tuple(f"{index:06d}.SZ" for index in range(1, FULL_MARKET_ASSET_COUNT + 1))
    repository = PriceBarRepository()
    audit = _AuditWriter()
    source = _PreparedSource()

    def reference_snapshot(
        requested_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> ModelHistoryReferenceSnapshot:
        bars = repository.get_bars_for_assets(
            requested_codes,
            start=start_date,
            end=end_date,
            limit=5000,
        )
        return ModelHistoryReferenceSnapshot.from_bars(
            requested_codes,
            start_date,
            end_date,
            bars,
        )

    service = ModelMarketDataService(
        (ModelMarketRoute("tushare", source, source_type="tushare", provider_id=17),),
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda *_args: (),
        reference_history_snapshot=reference_snapshot,
        history_fetch_audit=audit,
    )

    with CaptureQueriesContext(connection) as captured:
        service.prepare_stock_history(asset_codes, TARGET_DATE, TARGET_DATE)
        read_rows = tuple(
            service.stock_history(asset_code, TARGET_DATE, TARGET_DATE)
            for asset_code in asset_codes
        )

    assert len(captured.captured_queries) <= MAX_PREPARATION_SQL_QUERIES, (
        f"model-history preparation used {len(captured.captured_queries)} SQL queries; "
        f"limit is {MAX_PREPARATION_SQL_QUERIES}"
    )
    assert sum(len(rows) for rows in read_rows) == FULL_MARKET_ASSET_COUNT
    assert all(
        rows[0].asset_code == asset_code
        for asset_code, rows in zip(asset_codes, read_rows, strict=True)
    )
    assert source.preparation_calls == 1
    assert source.cache_reads == FULL_MARKET_ASSET_COUNT * 2
    assert audit.successes == 1
    assert audit.failures == 0


@pytest.mark.django_db
def test_bulk_price_reference_lookup_resolves_provider_aliases() -> None:
    """Keep alias resolution and the per-asset limit across a multi-day bulk lookup."""

    asset = AssetMasterModel.objects.create(
        code="000001.SZ", name="Test Asset", asset_type="stock", exchange="SZSE"
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="akshare",
        alias_code="000001.XSHE",
    )
    for asset_code in (asset.code, "600000.SH"):
        for bar_date in (date(2026, 9, 17), TARGET_DATE):
            PriceBarModel.objects.create(
                asset_code=asset_code,
                bar_date=bar_date,
                freq="1d",
                adjustment="none",
                open=10,
                high=11,
                low=9,
                close=10,
                volume=1000,
                source="alias-fixture",
            )

    bars = PriceBarRepository().get_bars_for_assets(
        ("000001.SZ", "000001.XSHE", "600000.SH"),
        start=date(2026, 9, 17),
        end=TARGET_DATE,
        limit=1,
    )

    assert tuple(row.asset_code for row in bars["000001.XSHE"]) == ("000001.SZ",)
    assert tuple(row.bar_date for row in bars["000001.XSHE"]) == (TARGET_DATE,)
    assert tuple(row.asset_code for row in bars["000001.SZ"]) == ("000001.SZ",)
    assert tuple(row.bar_date for row in bars["000001.SZ"]) == (TARGET_DATE,)
    assert tuple(row.asset_code for row in bars["600000.SH"]) == ("600000.SH",)
    assert tuple(row.bar_date for row in bars["600000.SH"]) == (TARGET_DATE,)
