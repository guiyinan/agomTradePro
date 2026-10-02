"""Bulk transport must retain source, date, unit and failover checks."""

from collections.abc import Mapping
from datetime import date

import pandas as pd
import pytest

from apps.data_center.application.market_publication_refresh import (
    refresh_market_price_inputs,
)
from apps.data_center.application.model_market_data import (
    ModelHistoryFetchAuditResult,
    ModelHistoryPreparedFetch,
    ModelHistoryRawAuditBinding,
    ModelHistoryReferenceSnapshot,
    ModelMarketDataService,
    ModelMarketRoute,
)
from apps.data_center.domain.entities import PriceBar, RawAuditReference
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.model_market_data import ModelDailyBar
from apps.data_center.infrastructure.tushare_model_market_source import TushareModelMarketSource
from core.exceptions import DataFetchError

DAY = date(2026, 9, 18)
CODES = ("000006.SZ", "000007.SZ")


class AuditRecorder:
    """Capture the canonical sync-use-case boundary without external services."""

    def __init__(self, source_types_by_provider: Mapping[int, str] | None = None) -> None:
        self.successes: list[tuple[int, tuple[str, ...], tuple[ModelDailyBar, ...]]] = []
        self.snapshots: list[ModelHistoryReferenceSnapshot] = []
        self.failures: list[tuple[int, tuple[str, ...], BaseException]] = []
        self.source_types_by_provider = source_types_by_provider or {
            17: "configured_vendor",
            29: "backup",
        }

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
        self.successes.append((provider_id, asset_codes, rows))
        self.snapshots.append(reference_snapshot)
        sequence = len(self.successes)
        source_type = self.source_types_by_provider.get(provider_id)
        if source_type is None:
            raise AssertionError("audit fixture lacks the configured provider source type")
        reference = RawAuditReference(
            raw_audit_id=f"raw-{sequence}",
            version="raw-audit-v1",
            content_hash=f"{sequence:064x}",
            run_id=f"run-{sequence}",
            ingested_run_id=f"ingest-{sequence}",
        )
        return ModelHistoryFetchAuditResult(
            provider_name=rows[0].source if rows else "configured_vendor",
            stored_count=len(rows),
            stored_asset_codes=tuple(sorted({row.asset_code for row in rows})),
            raw_audit_reference=reference,
            source_type=source_type,
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
        self.failures.append((provider_id, asset_codes, error))
        sequence = len(self.failures)
        return RawAuditReference(
            raw_audit_id=f"failure-{sequence}",
            version="raw-audit-v1",
            content_hash=f"{sequence:064x}",
            run_id=f"failure-run-{sequence}",
            ingested_run_id=f"failure-ingest-{sequence}",
        )


class Client:
    def __init__(self):
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "trade_date": "20260918",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "vol": 100,
                    "pct_chg": 0,
                    "amount": 50,
                }
                for code in kwargs["ts_code"].split(",")
            ]
        )

    def adj_factor(self, **kwargs):
        self.calls.append(("factor", kwargs))
        return pd.DataFrame(
            [
                {"ts_code": code, "trade_date": "20260918", "adj_factor": 2}
                for code in kwargs["ts_code"].split(",")
            ]
        )

    def trade_cal(self, **kwargs):
        return pd.DataFrame([{"cal_date": "20260918"}])


def _reference_snapshot(
    asset_codes: tuple[str, ...],
    start_date: date,
    end_date: date,
    references: Mapping[str, tuple[ModelDailyBar, ...]] | None = None,
) -> ModelHistoryReferenceSnapshot:
    """Build an immutable PriceBar snapshot from known prior provider observations."""

    rows = {
        code: tuple(
            PriceBar(
                asset_code=row.asset_code,
                bar_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                amount=row.amount,
                source=row.source,
                adjustment=PriceAdjustment.NONE,
            )
            for row in (references or {}).get(code, ())
        )
        for code in asset_codes
    }
    return ModelHistoryReferenceSnapshot.from_bars(asset_codes, start_date, end_date, rows)


def _service(
    routes: tuple[ModelMarketRoute, ...],
    audit: AuditRecorder,
    *,
    references: Mapping[str, tuple[ModelDailyBar, ...]] | None = None,
    per_asset_limit: int | None = None,
) -> ModelMarketDataService:
    """Build an audited service with one pre-provider batched reference snapshot."""

    return ModelMarketDataService(
        routes,
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda code, _start, _end: (references or {}).get(code, ()),
        reference_history_snapshot=lambda codes, start, end: _reference_snapshot(
            codes, start, end, references
        ),
        history_fetch_audit=audit,
        max_per_asset_preparation_assets=per_asset_limit,
    )


def test_prepared_multi_symbol_history_reduces_requests_and_preserves_units():
    client = Client()
    source = TushareModelMarketSource(client, source="configured_vendor")
    source.prepare_stock_history(CODES, DAY, DAY)
    for code in CODES:
        rows = source.stock_history(code, DAY, DAY)
        assert len(rows) == 1
        assert rows[0].asset_code == code
        assert rows[0].trade_date == DAY
        assert rows[0].volume == 10000
        assert rows[0].amount == 50000
        assert rows[0].adjustment_factor == 2
        assert rows[0].source == "configured_vendor"
    assert len(client.calls) == 2
    assert client.calls[0][1]["ts_code"] == ",".join(CODES)


def test_explicit_batch_preparation_reuses_one_audit_and_read_cache_has_no_side_effects():
    client = Client()
    audit = AuditRecorder()
    source = TushareModelMarketSource(
        client,
        source="configured_vendor",
        provider_id=17,
        history_fetch_audit=audit,
    )
    port = _service(
        (
            ModelMarketRoute(
                "configured_vendor", source, source_type="configured_vendor", provider_id=17
            ),
        ),
        audit,
    )

    port.prepare_stock_history(CODES, DAY, DAY)
    first = port.stock_history(CODES[0], DAY, DAY)
    second = port.stock_history(CODES[1], DAY, DAY)

    assert len(audit.successes) == 1
    assert audit.successes[0][0:2] == (17, CODES)
    assert len(audit.successes[0][2]) == 2
    references = port.model_history_audit_references((*first, *second))
    assert len(references) == 1
    reference = references[0]
    assert first[0].asset_code == CODES[0]
    assert second[0].asset_code == CODES[1]
    assert len(client.calls) == 2
    assert port.model_history_audit_bindings((*first, *second)) == (
        ModelHistoryRawAuditBinding(reference, "configured_vendor"),
    )
    assert port.take_model_history_audit_references() == (reference,)
    assert port.take_model_history_audit_bindings() == ()
    assert audit.failures == []


def test_partial_batch_audits_only_returned_members_and_caches_the_exact_empty_member():
    class MissingMember(Client):
        def daily(self, **kwargs):
            return super().daily(**kwargs).iloc[:1]

    audit = AuditRecorder()
    client = MissingMember()
    source = TushareModelMarketSource(
        client,
        source="configured_vendor",
        provider_id=17,
        history_fetch_audit=audit,
    )
    port = _service(
        (
            ModelMarketRoute(
                "configured_vendor", source, source_type="configured_vendor", provider_id=17
            ),
        ),
        audit,
        per_asset_limit=2,
    )
    port.prepare_stock_history(CODES, DAY, DAY)

    assert len(audit.successes) == 1
    assert audit.successes[0][1] == CODES
    assert tuple(row.asset_code for row in audit.successes[0][2]) == (CODES[0],)
    assert source.has_prepared_model_history(CODES[0], DAY, DAY)
    assert source.has_prepared_model_history(CODES[1], DAY, DAY)
    with pytest.raises(DataFetchError):
        port.stock_history(CODES[1], DAY, DAY)
    assert source.stock_history(CODES[1], DAY, DAY) == ()
    assert port.model_history_audit_references(port.stock_history(CODES[0], DAY, DAY)) == (
        RawAuditReference(
            raw_audit_id="raw-1",
            version="raw-audit-v1",
            content_hash=f"{1:064x}",
            run_id="run-1",
            ingested_run_id="ingest-1",
        ),
    )
    assert len(client.calls) == 2


def test_provider_fetch_failure_retains_its_own_failed_audit():
    class Broken(Client):
        def daily(self, **kwargs):
            raise RuntimeError("provider unavailable")

    audit = AuditRecorder()
    source = TushareModelMarketSource(
        Broken(),
        source="configured_vendor",
        provider_id=17,
        history_fetch_audit=audit,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        source.prepare_stock_history(CODES, DAY, DAY)

    assert audit.successes == []
    assert len(audit.failures) == 1
    assert audit.failures[0][0:2] == (17, CODES)
    assert source.drain_model_history_prepared_fetches() == ()


def test_failed_primary_batch_fails_over_with_separate_audits_and_success_refs_only():
    class Broken(Client):
        def daily(self, **kwargs):
            raise DataFetchError("primary unavailable", code="EGRESS_PROVIDER_UNAVAILABLE")

    class Backup:
        def stock_history(self, asset_code, start_date, end_date):
            return (
                ModelDailyBar(
                    asset_code=asset_code,
                    trade_date=DAY,
                    open=10.0,
                    high=11.0,
                    low=9.0,
                    close=10.0,
                    volume=10000.0,
                    change_percent=0.0,
                    adjustment_factor=2.0,
                    source="backup",
                ),
            )

        def fetch_stock_history(self, asset_code, start_date, end_date):
            return ModelHistoryPreparedFetch(
                asset_codes=(asset_code,),
                start_date=start_date,
                end_date=end_date,
                rows=self.stock_history(asset_code, start_date, end_date),
                request_details={"provider_fetch_kind": "backup_asset_fetch"},
            )

        def index_history(self, asset_code, start_date, end_date):
            return ()

        def trade_days(self, start_date, end_date):
            return (DAY,) if start_date <= DAY <= end_date else ()

        def index_members(self, index_code, target_date):
            return ()

    audit = AuditRecorder()
    primary = TushareModelMarketSource(
        Broken(),
        source="primary",
        provider_id=17,
        history_fetch_audit=audit,
    )
    previous_rows = {
        code: (
            ModelDailyBar(
                asset_code=code,
                trade_date=DAY,
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.0,
                volume=10000.0,
                change_percent=0.0,
                adjustment_factor=2.0,
                source="previous",
            ),
        )
        for code in CODES
    }
    port = _service(
        (
            ModelMarketRoute("primary", primary, source_type="tushare", provider_id=17),
            ModelMarketRoute(
                "backup", Backup(), source_type="akshare", requires_reference=True, provider_id=29
            ),
        ),
        audit,
        references=previous_rows,
        per_asset_limit=2,
    )

    port.prepare_stock_history(CODES, DAY, DAY)
    rows = tuple(row for code in CODES for row in port.stock_history(code, DAY, DAY))
    references = port.take_model_history_audit_references()

    assert len(audit.failures) == 1
    assert audit.failures[0][0:2] == (17, CODES)
    assert len(audit.successes) == len(CODES)
    assert all(provider_id == 29 for provider_id, _codes, _rows in audit.successes)
    assert {row.source for row in rows} == {"backup"}
    assert len(references) == len(CODES)
    assert all(not reference.raw_audit_id.startswith("failure-") for reference in references)


def test_failover_default_requires_reference_before_fallback_facts_or_success_audit():
    from types import SimpleNamespace

    from apps.data_center.infrastructure.model_market_wiring import build_model_market_service

    class Broken(Client):
        def daily(self, **kwargs):
            raise RuntimeError("primary unavailable")

    class Provider:
        def __init__(self, name, source, provider_id, client):
            self.name = name
            self.source = source
            self.identity = provider_id
            self.client = client

        def provider_name(self):
            return self.name

        def provider_source(self):
            return self.source

        def provider_id(self):
            return self.identity

        def model_market_source(self, *, tolerance, history_fetch_audit=None):
            return TushareModelMarketSource(
                self.client,
                source=self.source,
                provider_id=self.identity,
                history_fetch_audit=history_fetch_audit,
            )

    audit = AuditRecorder()
    providers = (
        Provider("primary", "akshare", 17, Broken()),
        Provider("fallback", "tushare", 29, Client()),
    )
    registry = SimpleNamespace(get_providers=lambda _capability: list(providers))

    class EmptyReferenceRepository:
        def get_bars_for_assets(self, asset_codes, *, start, end, limit):
            return dict.fromkeys(asset_codes, ())

    service = build_model_market_service(
        registry,
        EmptyReferenceRepository(),
        {
            "status": "active",
            "enable_failover": True,
            "default_source": "failover",
            "failover_tolerance": 0.01,
        },
        history_fetch_audit=audit,
    )

    service.prepare_stock_history((CODES[0],), DAY, DAY)
    with pytest.raises(DataFetchError) as caught:
        service.stock_history(CODES[0], DAY, DAY)

    assert caught.value.code == "MODEL_MARKET_UNVERIFIED_FAILOVER"
    assert audit.successes == []
    assert len(audit.failures) == 2


def test_empty_session_raw_audit_is_request_scoped_and_transported_to_full_market_result():
    class EmptySuspendedClient(Client):
        def __init__(self) -> None:
            super().__init__()
            self.suspension_calls = 0

        def daily(self, **kwargs):
            self.calls.append(("daily", kwargs))
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "pct_chg",
                    "amount",
                ]
            )

        def adj_factor(self, **kwargs):
            self.calls.append(("factor", kwargs))
            return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])

        def trade_cal(self, **kwargs):
            self.calls.append(("calendar", kwargs))
            return pd.DataFrame([{"cal_date": "20260918", "is_open": "1"}])

        def suspend_d(self, **kwargs):
            self.suspension_calls += 1
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "trade_date": "20260918",
                        "suspend_type": "S",
                        "suspend_timing": None,
                    }
                ]
            )

    asset_codes = tuple(f"{index:06d}.SZ" for index in range(1, 202))
    client = EmptySuspendedClient()
    audit = AuditRecorder({17: "tushare"})
    source = TushareModelMarketSource(
        client,
        source="tushare",
        provider_id=17,
        history_fetch_audit=audit,
    )
    service = _service(
        (ModelMarketRoute("tushare", source, source_type="tushare", provider_id=17),), audit
    )
    expected_reference = RawAuditReference(
        raw_audit_id="raw-1",
        version="raw-audit-v1",
        content_hash=f"{1:064x}",
        run_id="run-1",
        ingested_run_id="ingest-1",
    )

    result = refresh_market_price_inputs(service, list(asset_codes), DAY)

    assert result.suspended_codes == asset_codes
    assert result.raw_audit_references == (expected_reference,)
    assert tuple(binding.source_type for binding in result.raw_audit_bindings) == ("tushare",)
    assert len(audit.successes) == 1
    assert audit.successes[0][2] == ()
    assert audit.failures == []
    assert len([call for call in client.calls if call[0] == "daily"]) == 1
    assert len([call for call in client.calls if call[0] == "factor"]) == 1
    assert client.suspension_calls == len(asset_codes)


def test_unadvertised_cache_route_fails_closed_without_fabricating_lineage():
    class UnboundCache:
        def prepare_stock_history(self, asset_codes, start_date, end_date):
            return None

        def has_prepared_model_history(self, asset_code, start_date, end_date):
            return True

        def prepared_model_history_audit_reference(
            self, asset_code, trade_date, start_date, end_date
        ):
            return None

        def drain_model_history_preparation_audit_references(self):
            return ()

        def stock_history(self, asset_code, start_date, end_date):
            return (
                ModelDailyBar(
                    asset_code=asset_code,
                    trade_date=DAY,
                    open=10.0,
                    high=11.0,
                    low=9.0,
                    close=10.0,
                    volume=10000.0,
                    change_percent=0.0,
                    adjustment_factor=2.0,
                    source="cache",
                ),
            )

        def index_history(self, asset_code, start_date, end_date):
            return ()

        def trade_days(self, start_date, end_date):
            return (DAY,)

        def index_members(self, index_code, target_date):
            return ()

    audit = AuditRecorder()
    port = _service(
        (ModelMarketRoute("cache", UnboundCache(), source_type="tushare", provider_id=17),),
        audit,
    )

    with pytest.raises(DataFetchError) as caught:
        port.prepare_stock_history((CODES[0],), DAY, DAY)

    assert caught.value.code == "MODEL_MARKET_BULK_PREPARATION_REQUIRED"
    assert audit.successes == []
    assert audit.failures == []


def test_preparation_is_exact_window_and_does_not_reuse_a_previous_request():
    client = Client()
    source = TushareModelMarketSource(client)
    source.prepare_stock_history(CODES, DAY, DAY)
    source.stock_history(CODES[0], date(2026, 9, 17), DAY)
    assert len(client.calls) == 4


def test_prepared_data_still_runs_cross_source_consistency_and_remains_read_only():
    client = Client()
    audit = AuditRecorder()
    source = TushareModelMarketSource(
        client,
        source="vendor",
        provider_id=17,
        history_fetch_audit=audit,
    )
    port = _service(
        (
            ModelMarketRoute(
                "vendor",
                source,
                source_type="configured_vendor",
                requires_reference=True,
                provider_id=17,
            ),
        ),
        audit,
    )
    port.prepare_stock_history(CODES, DAY, DAY)
    with pytest.raises(DataFetchError) as error:
        port.stock_history(CODES[0], DAY, DAY)
    assert error.value.code == "MODEL_MARKET_UNVERIFIED_FAILOVER"
    assert audit.successes == []
    assert len(audit.failures) == 1


def test_preparation_batches_bound_calendar_day_rows():
    client = Client()
    source = TushareModelMarketSource(client)
    codes = tuple(f"{code:06}.SZ" for code in range(1, 26))
    source.prepare_stock_history(codes, date(2025, 8, 14), DAY)
    assert len(client.calls) == 6
    assert all(len(params["ts_code"].split(",")) <= 11 for _, params in client.calls)


def test_missing_batch_member_caches_verified_empty_without_second_provider_request():
    class Missing(Client):
        def daily(self, **kwargs):
            frame = super().daily(**kwargs)
            return frame.iloc[:1]

    client = Missing()
    source = TushareModelMarketSource(client)
    source.prepare_stock_history(CODES, DAY, DAY)
    assert source.stock_history(CODES[1], DAY, DAY) == ()
    assert source.stock_history(CODES[1], DAY, DAY) == ()
    assert len(client.calls) == 2


def test_wide_scope_prefetches_by_session_and_retains_exact_stock_windows():
    codes = tuple(f"{code:06}.SZ" for code in range(1, 202))

    class MarketClient(Client):
        def daily(self, **kwargs):
            assert kwargs == {"trade_date": "20260918"}
            return super().daily(ts_code=",".join(codes))

        def adj_factor(self, **kwargs):
            assert kwargs == {"trade_date": "20260918"}
            return super().adj_factor(ts_code=",".join(codes))

    client = MarketClient()
    source = TushareModelMarketSource(client)
    source.prepare_stock_history(codes, DAY, DAY)
    assert len(client.calls) == 2
    assert all(source.stock_history(code, DAY, DAY)[0].asset_code == code for code in codes)
    assert len(client.calls) == 2


def test_truncated_session_prefetch_fails_closed_without_partial_cache_or_per_asset_fallback():
    class Truncated(Client):
        def daily(self, **kwargs):
            if "trade_date" in kwargs:
                return pd.concat([super().daily(ts_code=CODES[0])] * 6000)
            return super().daily(**kwargs)

        def adj_factor(self, **kwargs):
            return super().adj_factor(ts_code=kwargs.get("ts_code", CODES[0]))

    client = Truncated()
    source = TushareModelMarketSource(client)
    codes = tuple(f"{code:06}.SZ" for code in range(1, 202))
    with pytest.raises(DataFetchError) as caught:
        source.prepare_stock_history(codes, DAY, DAY)
    assert caught.value.code == "MODEL_MARKET_SESSION_INCOMPLETE"
    assert source._prepared == {}
    assert source.drain_model_history_prepared_fetches() == ()
    assert len(client.calls) == 2


def test_default_large_scope_with_akshare_primary_fails_closed_before_any_provider_or_audit_io():
    class PerAssetOnly:
        def __init__(self) -> None:
            self.fetch_count = 0

        def fetch_stock_history(self, asset_code, start_date, end_date):
            self.fetch_count += 1
            raise AssertionError("bulk capability gate must run before provider requests")

        def stock_history(self, asset_code, start_date, end_date):
            raise AssertionError("bulk capability gate must run before provider requests")

        def index_history(self, asset_code, start_date, end_date):
            return ()

        def trade_days(self, start_date, end_date):
            return (DAY,)

        def index_members(self, index_code, target_date):
            return ()

    codes = tuple(f"{value:06d}.SZ" for value in range(1, 5002))
    audit = AuditRecorder()
    akshare = PerAssetOnly()
    tushare_client = Client()
    tushare = TushareModelMarketSource(
        tushare_client,
        provider_id=29,
        history_fetch_audit=audit,
    )
    snapshot_calls = 0

    def capture_snapshot(
        requested: tuple[str, ...], start: date, end: date
    ) -> ModelHistoryReferenceSnapshot:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return _reference_snapshot(requested, start, end)

    service = ModelMarketDataService(
        (
            ModelMarketRoute("akshare-primary", akshare, source_type="akshare", provider_id=17),
            ModelMarketRoute("tushare-secondary", tushare, source_type="tushare", provider_id=29),
        ),
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda *_: (),
        reference_history_snapshot=capture_snapshot,
        history_fetch_audit=audit,
    )

    with pytest.raises(DataFetchError) as caught:
        service.prepare_stock_history(codes, DAY, DAY)

    assert caught.value.code == "MODEL_MARKET_BULK_PREPARATION_REQUIRED"
    assert caught.value.details["requested_count"] == 5001
    assert snapshot_calls == 0
    assert akshare.fetch_count == 0
    assert tushare_client.calls == []
    assert audit.successes == []
    assert audit.failures == []
    assert "000001.SZ" not in str(caught.value.details)


def test_explicit_small_scope_uses_the_route_audited_per_asset_fetch_contract():
    class PerAssetOnly:
        def __init__(self) -> None:
            self.fetches: list[str] = []

        def fetch_stock_history(self, asset_code, start_date, end_date):
            self.fetches.append(asset_code)
            row = ModelDailyBar(
                asset_code=asset_code,
                trade_date=DAY,
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.0,
                volume=100.0,
                change_percent=0.0,
                adjustment_factor=2.0,
                source="akshare",
            )
            return ModelHistoryPreparedFetch(
                asset_codes=(asset_code,),
                start_date=start_date,
                end_date=end_date,
                rows=(row,),
                request_details={"provider_fetch_kind": "akshare_test_asset_fetch"},
            )

        def stock_history(self, asset_code, start_date, end_date):
            raise AssertionError("explicit preparation must use the typed fetch envelope")

        def index_history(self, asset_code, start_date, end_date):
            return ()

        def trade_days(self, start_date, end_date):
            return (DAY,)

        def index_members(self, index_code, target_date):
            return ()

    audit = AuditRecorder()
    provider = PerAssetOnly()
    service = _service(
        (ModelMarketRoute("akshare", provider, source_type="akshare", provider_id=17),),
        audit,
        per_asset_limit=2,
    )

    service.prepare_stock_history(CODES, DAY, DAY)
    rows = tuple(row for code in CODES for row in service.stock_history(code, DAY, DAY))

    assert provider.fetches == list(CODES)
    assert len(audit.successes) == 2
    assert [asset_codes for _provider_id, asset_codes, _rows in audit.successes] == [
        (CODES[0],),
        (CODES[1],),
    ]
    assert {row.asset_code for row in rows} == set(CODES)
    assert len(service.take_model_history_audit_references()) == 2


def test_empty_provider_batch_is_audited_once_and_suspension_error_is_reused():
    class EmptySuspendedClient(Client):
        def __init__(self) -> None:
            super().__init__()
            self.suspension_calls = 0

        def daily(self, **kwargs):
            self.calls.append(("daily", kwargs))
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "pct_chg",
                    "amount",
                ]
            )

        def adj_factor(self, **kwargs):
            self.calls.append(("factor", kwargs))
            return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])

        def trade_cal(self, **kwargs):
            self.calls.append(("calendar", kwargs))
            return pd.DataFrame([{"cal_date": "20260918"}])

        def suspend_d(self, **kwargs):
            self.suspension_calls += 1
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "trade_date": "20260918",
                        "suspend_type": "S",
                        "suspend_timing": None,
                    }
                ]
            )

    client = EmptySuspendedClient()
    audit = AuditRecorder()
    source = TushareModelMarketSource(
        client,
        source="tushare",
        provider_id=17,
        history_fetch_audit=audit,
    )
    service = _service(
        (ModelMarketRoute("tushare", source, source_type="tushare", provider_id=17),), audit
    )

    service.prepare_stock_history((CODES[0],), DAY, DAY)
    with pytest.raises(DataFetchError) as first:
        service.stock_history(CODES[0], DAY, DAY)
    calls_after_first = tuple(client.calls)
    with pytest.raises(DataFetchError) as second:
        service.stock_history(CODES[0], DAY, DAY)

    assert first.value.code == second.value.code == "MODEL_MARKET_SUSPENDED"
    assert len(audit.successes) == 1
    assert audit.successes[0][2] == ()
    assert audit.failures == []
    assert tuple(client.calls) == calls_after_first
    assert client.suspension_calls == 1
    assert service.take_model_history_audit_references() == (
        RawAuditReference(
            raw_audit_id="raw-1",
            version="raw-audit-v1",
            content_hash=f"{1:064x}",
            run_id="run-1",
            ingested_run_id="ingest-1",
        ),
    )


def test_generic_stock_history_read_never_writes_audit_even_when_provider_is_configured():
    client = Client()
    audit = AuditRecorder()
    source = TushareModelMarketSource(
        client,
        source="tushare",
        provider_id=17,
        history_fetch_audit=audit,
    )
    service = _service(
        (ModelMarketRoute("tushare", source, source_type="tushare", provider_id=17),), audit
    )

    assert service.stock_history(CODES[0], DAY, DAY)
    assert service.stock_history(CODES[0], DAY, DAY)

    assert len(client.calls) == 4
    assert audit.successes == []
    assert audit.failures == []
