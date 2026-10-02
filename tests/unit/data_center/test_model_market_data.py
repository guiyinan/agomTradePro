"""Model routing must fail closed on stale, conflicting or unverified history."""

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from apps.data_center.application.model_market_data import ModelMarketDataService, ModelMarketRoute
from apps.data_center.domain.model_market_data import ModelDailyBar, TradingCalendarEvidence
from apps.data_center.infrastructure.akshare_model_market_source import AkshareModelMarketSource
from core.exceptions import DataFetchError, TushareError

D1, D2 = date(2026, 9, 7), date(2026, 9, 8)


def bar(day=D1, *, source="primary", close=10.0, factor=2.0):
    return ModelDailyBar("600000.SH", day, close, close, close, close, 1200.0, 0.0, factor, source)


class Source:
    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.calls, self.calendar_calls = rows, error, 0, 0

    def stock_history(self, *args):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows

    index_history = stock_history

    def trade_days(self, start_date, end_date):
        self.calendar_calls += 1
        return tuple(day for day in (D1, D2) if start_date <= day <= end_date)

    def trading_calendar_evidence(self, start_date, end_date):
        return TradingCalendarEvidence(
            coverage_start=start_date,
            coverage_end=end_date,
            open_sessions=(D1, D2),
            source="primary-fixture",
            observed_at=datetime.now(UTC),
        )

    def index_members(self, *args):
        return ("600000.SH",)


def service(
    primary,
    backup,
    *,
    reference=(),
    enabled=True,
    stored=None,
    primary_source_type="tushare",
    backup_source_type="akshare",
):
    return ModelMarketDataService(
        (
            ModelMarketRoute("primary display label", primary, source_type=primary_source_type),
            ModelMarketRoute("backup display label", backup, source_type=backup_source_type),
        ),
        enable_failover=enabled,
        tolerance=0.01,
        reference_history=lambda *_: reference,
    )


def test_calendar_evidence_binds_requested_coverage_and_provider_source():
    evidence = service(Source(), Source()).trading_calendar_evidence(D1, D2)

    assert evidence.coverage_start == D1
    assert evidence.coverage_end == D2
    assert evidence.open_sessions == (D1, D2)
    assert evidence.source == "primary-fixture"
    assert evidence.observed_at.tzinfo is not None


def test_calendar_evidence_fails_over_to_akshare_complete_series():
    class RejectedCalendar(Source):
        def trading_calendar_evidence(self, start_date, end_date):
            raise DataFetchError(
                "primary calendar invalid", code="MODEL_MARKET_CALENDAR_SCHEMA_INVALID"
            )

    class AkshareCalendarClient:
        def tool_trade_date_hist_sina(self):
            return pd.DataFrame({"trade_date": [date(2026, 9, 6), D1, D2, date(2026, 9, 9)]})

    backup = AkshareModelMarketSource(
        AkshareCalendarClient(), source="akshare-calendar", tolerance=0.01
    )

    evidence = service(RejectedCalendar(), backup).trading_calendar_evidence(D1, D2)

    assert evidence.open_sessions == (D1, D2)
    assert evidence.source == "akshare-calendar"


def test_stale_primary_continues_to_consistent_fresh_source_without_read_side_writes():
    first, second = Source((bar(),)), Source((bar(source="backup"), bar(D2, source="backup")))
    stored = []
    port = service(first, second, stored=stored)
    result = port.stock_history("600000.SH", D1, D2)
    assert result[-1].trade_date == D2
    assert all(row.source == "backup" for row in result)
    assert stored == []
    assert first.calendar_calls == 1
    assert second.calls == 1


def test_repeated_stock_history_reads_never_write_facts_or_create_fetch_audits():
    class AuditWriter:
        calls = 0

        def record_model_history_fetch_success(self, **kwargs):
            self.calls += 1
            raise AssertionError("ordinary history reads must not create audits")

        def record_model_history_fetch_failure(self, **kwargs):
            self.calls += 1
            raise AssertionError("ordinary history reads must not create audits")

    source = Source((bar(), bar(D2)))
    stored = []
    audit = AuditWriter()
    port = ModelMarketDataService(
        (ModelMarketRoute("primary", source, source_type="tushare"),),
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda *_: (),
        history_fetch_audit=audit,
    )

    assert port.stock_history("600000.SH", D1, D2) == (bar(), bar(D2))
    assert port.stock_history("600000.SH", D1, D2) == (bar(), bar(D2))

    assert source.calls == 2
    assert audit.calls == 0
    assert stored == []


@pytest.mark.parametrize(
    "reason, rows",
    [
        (
            "MODEL_MARKET_SOURCE_CONFLICT",
            (bar(source="backup", close=11), bar(D2, source="backup")),
        ),
        ("MODEL_MARKET_UNVERIFIED_FAILOVER", (bar(D2, source="backup"),)),
        ("MODEL_MARKET_INVALID", (bar(source="backup"), bar(D2, source="backup", factor=None))),
    ],
)
def test_bad_failover_never_writes(reason, rows):
    stored = []
    with pytest.raises(DataFetchError) as caught:
        service(Source((bar(),)), Source(rows), stored=stored).stock_history("600000.SH", D1, D2)
    assert caught.value.code == reason
    assert stored == []


def test_disabled_failover_does_not_call_backup():
    backup = Source((bar(), bar(D2)))
    with pytest.raises(DataFetchError, match="stale"):
        service(Source((bar(),)), backup, enabled=False).stock_history("600000.SH", D1, D2)
    assert backup.calls == 0


def test_quota_disables_route_for_rest_of_build_and_requires_overlap():
    first = Source(error=TushareError("quota", code="TUSHARE_DAILY_QUOTA_EXHAUSTED"))
    second = Source((bar(), bar(D2)))
    port = service(first, second, reference=(bar(),))
    port.stock_history("600000.SH", D1, D2)
    port.stock_history("600000.SH", D1, D2)
    assert first.calls == 1
    assert second.calls == 2


def test_all_stale_sources_block_without_advancing_source_date():
    with pytest.raises(DataFetchError) as caught:
        service(Source((bar(),)), Source((bar(),))).stock_history("600000.SH", D1, D2)
    assert caught.value.code == "MODEL_MARKET_STALE"


def test_verified_full_day_suspension_remains_read_only_without_advancing_observation():
    class Suspended(Source):
        def suspended_days(self, *args):
            return (D2,)

    stored = []
    with pytest.raises(DataFetchError) as caught:
        service(Source(), Suspended((bar(),)), reference=(bar(),), stored=stored).stock_history(
            "600000.SH", D1, D2
        )
    assert caught.value.code == "MODEL_MARKET_SUSPENDED"
    assert caught.value.details["last_observed_date"] == D1.isoformat()
    assert caught.value.details["suspended_through"] == D2.isoformat()
    assert caught.value.details["source"] == "akshare"
    assert stored == []


def test_empty_target_day_with_complete_suspension_evidence_is_suspended():
    class Suspended(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            assert asset_code == "600000.SH"
            assert start_date == end_date == D2
            return (D2,)

    with pytest.raises(DataFetchError) as caught:
        service(Suspended(), Source()).stock_history("600000.SH", D2, D2)

    assert caught.value.code == "MODEL_MARKET_SUSPENDED"
    assert caught.value.details["asset_code"] == "600000.SH"
    assert caught.value.details["suspended_through"] == D2.isoformat()
    assert caught.value.details["source"] == "tushare"


def test_empty_multi_session_history_requires_suspension_evidence_for_every_open_day():
    class LastDaySuspended(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            assert start_date == D1
            assert end_date == D2
            return (D2,)

    with pytest.raises(DataFetchError) as caught:
        service(LastDaySuspended(), Source()).stock_history("600000.SH", D1, D2)

    assert caught.value.code == "MODEL_MARKET_UNAVAILABLE"


def test_empty_multi_session_history_is_suspended_when_all_open_days_are_confirmed():
    class FullySuspended(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            assert start_date == D1
            assert end_date == D2
            return (D1, D2)

    with pytest.raises(DataFetchError) as caught:
        service(FullySuspended(), Source()).stock_history("600000.SH", D1, D2)

    assert caught.value.code == "MODEL_MARKET_SUSPENDED"
    assert caught.value.details["suspended_through"] == D2.isoformat()


@pytest.mark.parametrize("evidence", [(), (D1,)])
def test_empty_target_day_without_complete_suspension_evidence_is_unavailable(evidence):
    class PossiblySuspended(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            return evidence

    with pytest.raises(DataFetchError) as caught:
        service(PossiblySuspended(), Source()).stock_history("600000.SH", D2, D2)

    assert caught.value.code == "MODEL_MARKET_UNAVAILABLE"


def test_empty_target_day_suspension_lookup_failure_remains_fail_closed():
    class FailedSuspensionLookup(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            raise DataFetchError(
                "suspension evidence unavailable", code="MODEL_MARKET_SUSPENSION_UNAVAILABLE"
            )

    port = ModelMarketDataService(
        (ModelMarketRoute("primary", FailedSuspensionLookup(), source_type="tushare"),),
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda *_: (),
    )
    with pytest.raises(DataFetchError) as caught:
        port.stock_history("600000.SH", D2, D2)

    assert caught.value.code == "MODEL_MARKET_SUSPENSION_UNAVAILABLE"


def test_empty_target_day_suspension_does_not_hide_backup_conflict():
    class Suspended(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            return (D2,)

    conflict = DataFetchError("backup source conflicted", code="MODEL_MARKET_SOURCE_CONFLICT")
    with pytest.raises(DataFetchError) as caught:
        service(Suspended(), Source(error=conflict)).stock_history("600000.SH", D2, D2)

    assert caught.value.code == "MODEL_MARKET_SOURCE_CONFLICT"


def test_empty_full_interval_suspension_does_not_hide_stale_backup_history():
    class FullySuspended(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            assert asset_code == "600000.SH"
            assert start_date == D1
            assert end_date == D2
            return (D1, D2)

    with pytest.raises(DataFetchError) as caught:
        service(FullySuspended(), Source((bar(),))).stock_history("600000.SH", D1, D2)

    assert caught.value.code == "MODEL_MARKET_STALE"


def test_empty_full_interval_suspension_conflicting_with_persisted_history_fails_closed():
    class FullySuspended(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            return (D1, D2)

    with pytest.raises(DataFetchError) as caught:
        service(FullySuspended(), Source(), reference=(bar(),)).stock_history("600000.SH", D1, D2)

    assert caught.value.code == "MODEL_MARKET_SOURCE_CONFLICT"


def test_persisted_suspension_conflict_is_not_hidden_by_fresh_fallback():
    class FullySuspended(Source):
        def suspended_days(self, asset_code, start_date, end_date):
            return (D1, D2)

    fresh = Source((bar(source="backup"), bar(D2, source="backup")))
    with pytest.raises(DataFetchError) as caught:
        service(FullySuspended(), fresh, reference=(bar(),)).stock_history("600000.SH", D1, D2)

    assert caught.value.code == "MODEL_MARKET_SOURCE_CONFLICT"


def test_empty_nontrading_target_is_not_classified_as_suspended():
    class Suspended(Source):
        def suspended_days(self, *args):
            raise AssertionError("suspension evidence is only requested for a trading day")

    with pytest.raises(DataFetchError) as caught:
        service(Suspended(), Source()).stock_history(
            "600000.SH", date(2026, 9, 6), date(2026, 9, 6)
        )

    assert caught.value.code == "MODEL_MARKET_UNAVAILABLE"


@pytest.mark.parametrize("evidence", [(), (D1,)])
def test_incomplete_suspension_evidence_remains_stale(evidence):
    class Suspended(Source):
        def suspended_days(self, *args):
            return evidence

    with pytest.raises(DataFetchError) as caught:
        service(Source(), Suspended((bar(),)), reference=(bar(),)).stock_history(
            "600000.SH", D1, D2
        )
    assert caught.value.code == "MODEL_MARKET_STALE"


def test_confirmed_suspension_survives_backup_quota_failure():
    class Suspended(Source):
        def suspended_days(self, *args):
            return (D2,)

    backup = Source(error=TushareError("quota", code="TUSHARE_DAILY_QUOTA_EXHAUSTED"))
    with pytest.raises(DataFetchError) as caught:
        service(Suspended((bar(),)), backup).stock_history("600000.SH", D1, D2)
    assert caught.value.code == "MODEL_MARKET_SUSPENDED"
    assert caught.value.details["last_observed_date"] == D1.isoformat()


def test_suspension_does_not_hide_price_conflict_or_stop_fresh_failover():
    class Suspended(Source):
        def suspended_days(self, *args):
            return (D2,)

    with pytest.raises(DataFetchError) as caught:
        service(Source(), Suspended((bar(close=11),)), reference=(bar(),)).stock_history(
            "600000.SH", D1, D2
        )
    assert caught.value.code == "MODEL_MARKET_SOURCE_CONFLICT"
    fresh = Source((bar(), bar(D2)))
    assert (
        service(Suspended((bar(),)), fresh).stock_history("600000.SH", D1, D2)[-1].trade_date == D2
    )


def test_tushare_suspension_normalization_rejects_intraday_other_assets_and_resumption():
    from apps.data_center.infrastructure.tushare_model_market_source import TushareModelMarketSource

    class Client:
        def suspend_d(self, **kwargs):
            return pd.DataFrame(
                [
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260908",
                        "suspend_type": "S",
                        "suspend_timing": None,
                    },
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260907",
                        "suspend_type": "S",
                        "suspend_timing": "09:30-10:00",
                    },
                    {
                        "ts_code": "600001.SH",
                        "trade_date": "20260907",
                        "suspend_type": "S",
                        "suspend_timing": None,
                    },
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260907",
                        "suspend_type": "R",
                        "suspend_timing": None,
                    },
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "invalid",
                        "suspend_type": "S",
                        "suspend_timing": None,
                    },
                ]
            )

    assert TushareModelMarketSource(Client()).suspended_days("600000.SH", D1, D2) == (D2,)


def test_factor_absolute_scale_can_differ_but_relative_adjustments_must_match():
    port = service(Source(), Source())
    port._check_consistency((bar(), bar(D2, factor=4)), (bar(factor=20), bar(D2, factor=40)))
    with pytest.raises(DataFetchError, match="adjustments disagree"):
        port._check_consistency((bar(), bar(D2, factor=4)), (bar(factor=20), bar(D2, factor=30)))


def test_akshare_prices_stay_raw_and_volume_is_shares():
    class Client:
        def stock_zh_a_hist(self, *, adjust, **kwargs):
            scale = 2 if adjust == "hfq" else 1
            return pd.DataFrame(
                [
                    {
                        "日期": D1,
                        "开盘": 10 * scale,
                        "最高": 12 * scale,
                        "最低": 9 * scale,
                        "收盘": 11 * scale,
                        "成交量": 12,
                        "涨跌幅": 1,
                        "成交额": 13200,
                    }
                ]
            )

    result = AkshareModelMarketSource(Client(), source="ak-route", tolerance=0.01).stock_history(
        "600000.SH", D1, D2
    )
    assert result[0].close == 11
    assert result[0].adjustment_factor == 2
    assert result[0].volume == 1200
    assert result[0].amount == 13200
    assert result[0].trade_date == D1


def test_model_consumers_cannot_obtain_vendor_sdks_or_choose_market_sources():
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "apps/alpha/infrastructure/qlib_builder.py",
        "apps/alpha/management/commands/build_qlib_data.py",
        "apps/equity/infrastructure/adapters.py",
        "apps/equity/infrastructure/market_data_repository.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        for forbidden in (
            "get_tushare_client",
            "get_akshare_module",
            "fetch_tushare_historical_prices",
            "fetch_akshare_eastmoney_historical_prices",
            "self._pro.",
            "TUSHARE_TOKEN",
        ):
            assert forbidden not in text, (relative, forbidden)


def test_wiring_honors_configured_default_and_disabled_failover():
    from types import SimpleNamespace

    from apps.data_center.infrastructure.model_market_wiring import build_model_market_service
    from core.exceptions import ConfigurationError

    class Provider(Source):
        def __init__(self, name):
            super().__init__((bar(source=name), bar(D2, source=name)))
            self.name = name

        def provider_name(self):
            return self.name

        def provider_source(self):
            return self.name

        def provider_id(self):
            return 1 if self.name == "tushare" else 2

        def model_market_source(self, **kwargs):
            return self

    first, second = Provider("tushare"), Provider("akshare")
    registry = SimpleNamespace(get_providers=lambda _: [first, second])
    stored = []
    repo = SimpleNamespace(get_bars=lambda *a, **k: [], bulk_upsert=stored.extend)
    audit_calls = []

    class AuditWriter:
        def record_model_history_fetch_success(self, **kwargs):
            audit_calls.append("success")
            raise AssertionError("ordinary history reads must not create audits")

        def record_model_history_fetch_failure(self, **kwargs):
            audit_calls.append("failure")
            raise AssertionError("ordinary history reads must not create audits")

    config = {
        "status": "active",
        "enable_failover": False,
        "default_source": "akshare",
        "failover_tolerance": 0.01,
    }
    result_port = build_model_market_service(
        registry, repo, config, history_fetch_audit=AuditWriter()
    )
    result = result_port.stock_history("600000.SH", D1, D2)
    result_port.stock_history("600000.SH", D1, D2)
    assert result[-1].source == "akshare"
    assert first.calls == 0
    assert stored == []
    assert audit_calls == []
    registry.get_providers = lambda _: [first]
    with pytest.raises(ConfigurationError, match="No configured"):
        build_model_market_service(registry, repo, config)


def test_akshare_rejects_nonmultiplicative_adjusted_ohlc():
    class Client:
        def stock_zh_a_hist(self, *, adjust, **kwargs):
            return pd.DataFrame(
                [
                    {
                        "日期": D1,
                        "开盘": 30 if adjust else 10,
                        "最高": 30 if adjust else 12,
                        "最低": 18 if adjust else 9,
                        "收盘": 22 if adjust else 11,
                        "成交量": 12,
                        "涨跌幅": 1,
                    }
                ]
            )

    with pytest.raises(DataFetchError, match="not multiplicative"):
        AkshareModelMarketSource(Client(), source="ak", tolerance=0.01).stock_history(
            "600000.SH", D1, D2
        )


def test_circuit_filtered_backup_still_requires_consistency_evidence():
    port = ModelMarketDataService(
        (
            ModelMarketRoute(
                "backup",
                Source((bar(), bar(D2))),
                source_type="akshare",
                requires_reference=True,
            ),
        ),
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda *_: (),
    )
    with pytest.raises(DataFetchError) as caught:
        port.stock_history("600000.SH", D1, D2)
    assert caught.value.code == "MODEL_MARKET_UNVERIFIED_FAILOVER"


def test_new_primary_cannot_overwrite_conflicting_history_from_previous_source():
    port = service(
        Source((bar(close=11), bar(D2, close=11))),
        Source(),
        reference=(bar(source="previous-route"),),
    )
    with pytest.raises(DataFetchError) as caught:
        port.stock_history("600000.SH", D1, D2)
    assert caught.value.code == "MODEL_MARKET_SOURCE_CONFLICT"


def test_sdk_escape_inventory_cannot_grow_beyond_documented_remaining_contracts():
    import ast

    root = Path(__file__).resolve().parents[3]
    remaining = {
        "apps/alpha/infrastructure/adapters/etf_adapter.py",
        "apps/fund/infrastructure/adapters/tushare_fund_adapter.py",
        "apps/realtime/infrastructure/repositories.py",
        "apps/equity/infrastructure/intraday_repository.py",
        "apps/sector/infrastructure/adapters/akshare_sector_adapter.py",
    }
    sdk_factories = {
        "get_tushare_client",
        "get_akshare_module",
        "get_akshare_module_port",
        "get_akshare_eastmoney_gateway_port",
        "fetch_tushare_historical_prices",
        "fetch_akshare_eastmoney_historical_prices",
    }
    violations = set()
    for path in (root / "apps").rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("apps/data_center/") or "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("apps.data_center")
                and any(alias.name in sdk_factories for alias in node.names)
            ):
                violations.add(relative)
    assert violations <= remaining, sorted(violations - remaining)
