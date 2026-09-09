"""Model routing must fail closed on stale, conflicting or unverified history."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from apps.data_center.application.model_market_data import ModelMarketDataService, ModelMarketRoute
from apps.data_center.domain.model_market_data import ModelDailyBar
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

    def trade_days(self, *args):
        self.calendar_calls += 1
        return (D1, D2)

    def index_members(self, *args):
        return ("600000.SH",)


def service(primary, backup, *, reference=(), enabled=True, stored=None):
    return ModelMarketDataService(
        (ModelMarketRoute("primary", primary), ModelMarketRoute("backup", backup)),
        enable_failover=enabled,
        tolerance=0.01,
        reference_history=lambda *_: reference,
        store_history=stored.extend if stored is not None else None,
    )


def test_stale_primary_continues_to_consistent_fresh_source_and_stores_raw_values():
    first, second = Source((bar(),)), Source((bar(source="backup"), bar(D2, source="backup")))
    stored = []
    port = service(first, second, stored=stored)
    result = port.stock_history("600000.SH", D1, D2)
    assert result[-1].trade_date == D2
    assert all(row.source == "backup" for row in result)
    assert stored == list(result)
    assert first.calendar_calls == 1
    assert second.calls == 1


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

        def model_market_source(self, **kwargs):
            return self

    first, second = Provider("tushare"), Provider("akshare")
    registry = SimpleNamespace(get_providers=lambda _: [first, second])
    stored = []
    repo = SimpleNamespace(get_bars=lambda *a, **k: [], bulk_upsert=stored.extend)
    config = {
        "status": "active",
        "enable_failover": False,
        "default_source": "akshare",
        "failover_tolerance": 0.01,
    }
    result = build_model_market_service(registry, repo, config).stock_history("600000.SH", D1, D2)
    assert result[-1].source == "akshare"
    assert first.calls == 0
    assert stored[-1].source == "akshare"
    assert stored[-1].close == 10
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
        (ModelMarketRoute("backup", Source((bar(), bar(D2))), requires_reference=True),),
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
