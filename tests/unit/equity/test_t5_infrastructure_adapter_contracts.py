"""Offline branch contracts for equity infrastructure adapters."""

from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.equity.infrastructure import adapters as adapter_module
from apps.equity.infrastructure.adapters import (
    MarketDataRepositoryAdapter,
    RegimeRepositoryAdapter,
    StockPoolRepositoryAdapter,
    TushareStockAdapter,
)


def _tushare_adapter(repository: object | None = None) -> TushareStockAdapter:
    adapter = TushareStockAdapter.__new__(TushareStockAdapter)
    adapter._dc_price_repo = repository or MagicMock()
    return adapter


def _market_adapter(repository: object | None = None) -> MarketDataRepositoryAdapter:
    adapter = MarketDataRepositoryAdapter.__new__(MarketDataRepositoryAdapter)
    adapter._bar_repo = repository or MagicMock()
    adapter._default_index_code = "000300.SH"
    return adapter


def _stock_pool_adapter() -> StockPoolRepositoryAdapter:
    adapter = StockPoolRepositoryAdapter.__new__(StockPoolRepositoryAdapter)
    adapter._cache = MagicMock()
    adapter._cache_key_prefix = "equity:stock_pool"
    return adapter


def _price_bar(code: str = "600000.SH", close: float = 10.0) -> PriceBar:
    return PriceBar(
        asset_code=code,
        bar_date=date(2026, 7, 1),
        open=close,
        high=close,
        low=close,
        close=close,
        freq="1d",
        adjustment=PriceAdjustment.NONE,
        source="test",
    )


def test_runtime_benchmark_and_adapter_initializers_use_composition_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_service = SimpleNamespace(get_runtime_benchmark_code=lambda _key, _default: None)
    price_repo = MagicMock()
    regime_repo = MagicMock()
    monkeypatch.setattr(
        adapter_module,
        "get_account_config_summary_service",
        lambda: config_service,
    )
    monkeypatch.setattr(adapter_module, "get_price_bar_repository", lambda: price_repo)
    monkeypatch.setattr(
        "apps.regime.application.repository_provider.get_regime_repository",
        lambda: regime_repo,
    )

    assert adapter_module.get_runtime_benchmark_code("key", "fallback") == "fallback"
    assert TushareStockAdapter()._dc_price_repo is price_repo
    assert MarketDataRepositoryAdapter()._bar_repo is price_repo
    assert RegimeRepositoryAdapter()._regime_repo is regime_repo


def test_stock_list_handles_empty_and_normalizes_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MagicMock()
    manager.filter.return_value.values.return_value = []
    fake_model = SimpleNamespace(_default_manager=manager)
    monkeypatch.setattr(adapter_module, "StockInfoModel", fake_model)
    adapter = _tushare_adapter()
    assert adapter.fetch_stock_list().empty

    manager.filter.return_value.values.return_value = [
        {
            "stock_code": "600000.SH",
            "name": "浦发银行",
            "sector": None,
            "market": "SH",
            "list_date": "1999-11-10",
        }
    ]
    frame = adapter.fetch_stock_list()

    assert frame.loc[0, "symbol"] == "600000"
    assert frame.loc[0, "area"] == ""
    assert frame.loc[0, "industry"] == ""
    assert isinstance(frame.loc[0, "list_date"], pd.Timestamp)


def test_daily_data_prefers_data_center_and_calculates_returns() -> None:
    repository = MagicMock()
    repository.get_bars.return_value = [
        _price_bar(close=11.0),
        PriceBar(
            asset_code="600000.SH",
            bar_date=date(2026, 6, 30),
            open=10.0,
            high=10.0,
            low=10.0,
            close=10.0,
            freq="1d",
            adjustment=PriceAdjustment.NONE,
            source="test",
        ),
    ]
    adapter = _tushare_adapter(repository)

    frame = adapter.fetch_daily_data("600000", date(2026, 6, 30), datetime(2026, 7, 1))

    assert frame["close"].tolist() == [10.0, 11.0]
    assert frame["pct_chg"].tolist() == [0.0, 10.0]
    repository.get_bars.assert_called_once_with(
        "600000.SH",
        start=date(2026, 6, 30),
        end=date(2026, 7, 1),
        limit=5000,
    )


def test_daily_data_falls_back_to_equity_models_and_handles_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    repository.get_bars.return_value = []
    query = MagicMock()
    manager = MagicMock()
    manager.filter.return_value.order_by.return_value = query
    monkeypatch.setattr(
        adapter_module,
        "StockDailyModel",
        SimpleNamespace(_default_manager=manager),
    )
    adapter = _tushare_adapter(repository)

    query.__iter__.return_value = iter([])
    assert adapter.fetch_daily_data("000001", "2026-07-01", "2026-07-02").empty

    query.__iter__.return_value = iter(
        [
            SimpleNamespace(
                stock_code="000001.SZ",
                trade_date=date(2026, 7, 1),
                open=10,
                high=11,
                low=9,
                close=10,
                volume=100,
                amount=1000,
            ),
            SimpleNamespace(
                stock_code="000001.SZ",
                trade_date=date(2026, 7, 2),
                open=10,
                high=12,
                low=10,
                close=11,
                volume=200,
                amount=2000,
            ),
        ]
    )
    frame = adapter.fetch_daily_data("000001", "2026-07-01", "2026-07-02")
    assert frame["change"].iloc[1] == 1


def test_stock_info_uses_exact_then_symbol_fallback_and_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_query = MagicMock()
    fallback_query = MagicMock()
    manager = MagicMock()
    manager.filter.side_effect = [exact_query, fallback_query, exact_query]
    exact_query.values.return_value.first.side_effect = [None, None]
    fallback_query.values.return_value.first.return_value = {
        "stock_code": "600000.SH",
        "name": "浦发银行",
        "sector": "银行",
        "market": "SH",
        "list_date": "1999-11-10",
    }
    monkeypatch.setattr(
        adapter_module,
        "StockInfoModel",
        SimpleNamespace(_default_manager=manager),
    )
    adapter = _tushare_adapter()

    info = adapter.fetch_stock_info("600000")
    assert info["ts_code"] == "600000.SH"
    assert info["industry"] == "银行"
    assert adapter.fetch_stock_info("XYZ") == {}


def test_stock_and_date_normalization_covers_all_branches() -> None:
    adapter = _tushare_adapter()
    assert adapter._normalize_stock_code(" 600000.sh ") == "600000.SH"
    assert adapter._normalize_stock_code("600000") == "600000.SH"
    assert adapter._normalize_stock_code("000001") == "000001.SZ"
    assert adapter._normalize_stock_code("300001") == "300001.SZ"
    assert adapter._normalize_stock_code("830001") == "830001.BJ"
    assert adapter._normalize_stock_code("XYZ") == "XYZ"
    assert adapter._normalize_date(datetime(2026, 7, 1, 12)) == "20260701"
    assert adapter._normalize_date(date(2026, 7, 1)) == "20260701"
    assert adapter._normalize_date("2026-07-01") == "20260701"
    with pytest.raises(ValueError, match="无效日期格式"):
        adapter._normalize_date("not-a-date")


def test_regime_adapter_delegates_repository_calls() -> None:
    repository = MagicMock()
    repository.get_snapshots_in_range.return_value = iter(["first", "second"])
    repository.get_snapshot_by_date.return_value = "snapshot"
    adapter = RegimeRepositoryAdapter.__new__(RegimeRepositoryAdapter)
    adapter._regime_repo = repository

    assert adapter.get_snapshots_in_range(date(2026, 1, 1), date(2026, 1, 2)) == [
        "first",
        "second",
    ]
    assert adapter.get_snapshot_by_date(date(2026, 1, 1)) == "snapshot"


def test_market_symbol_and_dataframe_normalization_contracts() -> None:
    assert MarketDataRepositoryAdapter._to_akshare_symbol("000300.SH") == "sh000300"
    assert MarketDataRepositoryAdapter._to_akshare_symbol("399001.SZ") == "sz399001"
    assert MarketDataRepositoryAdapter._to_akshare_symbol("UNKNOWN") is None
    assert MarketDataRepositoryAdapter._to_raw_index_code("000300.SH") == "000300"
    assert MarketDataRepositoryAdapter._extract_index_points(pd.DataFrame()) == []
    assert (
        MarketDataRepositoryAdapter._extract_index_points(pd.DataFrame({"date": ["2026-01-01"]}))
        == []
    )

    frame = pd.DataFrame(
        {
            "日期": ["2026-01-02", "bad", "2026-01-01", "2026-01-01"],
            "收盘价": [102, 100, -1, 101],
        }
    )
    assert MarketDataRepositoryAdapter._extract_index_points(frame) == [
        (date(2026, 1, 1), 101.0),
        (date(2026, 1, 2), 102.0),
    ]


def test_market_local_load_persistence_and_empty_persistence() -> None:
    repository = MagicMock()
    repository.get_bars.return_value = [
        _price_bar(close=0),
        _price_bar(close=12),
    ]
    adapter = _market_adapter(repository)

    assert adapter._load_local_index_points(
        "000300.SH",
        date(2026, 1, 1),
        date(2026, 1, 2),
    ) == [(date(2026, 7, 1), 12.0)]

    adapter._persist_index_points("000300.SH", [], "source")
    repository.bulk_upsert.assert_not_called()
    adapter._persist_index_points(
        "000300.SH",
        [(date(2026, 1, 1), 100.0)],
        "source",
    )
    persisted = repository.bulk_upsert.call_args.args[0]
    assert persisted[0].asset_code == "000300.SH"
    assert persisted[0].adjustment is PriceAdjustment.NONE


def test_remote_index_load_skips_errors_and_empty_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(
        stock_zh_index_daily_em=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("down")),
        stock_zh_index_daily=lambda **_kwargs: pd.DataFrame({"date": [], "close": []}),
        stock_zh_index_daily_tx=lambda **_kwargs: pd.DataFrame(
            {"date": ["2025-12-31"], "close": [100]}
        ),
        index_zh_a_hist=lambda **_kwargs: pd.DataFrame({"x": [1]}),
    )
    monkeypatch.setattr(adapter_module, "get_akshare_module", lambda: provider)
    adapter = _market_adapter()
    persist = MagicMock()
    monkeypatch.setattr(adapter, "_persist_index_points", persist)

    assert (
        adapter._load_remote_index_points(
            "000300.SH",
            date(2026, 1, 1),
            date(2026, 1, 2),
        )
        == []
    )
    persist.assert_not_called()


def test_index_returns_hydration_controls_and_exception_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _market_adapter()
    monkeypatch.setattr(
        adapter,
        "_load_local_index_points",
        lambda *_args: [(date(2026, 1, 1), 0.0), (date(2026, 1, 2), 100.0)],
    )
    remote = MagicMock()
    monkeypatch.setattr(adapter, "_load_remote_index_points", remote)

    assert (
        adapter.get_index_daily_returns(
            "000300.SH",
            date(2026, 1, 1),
            date(2026, 1, 2),
            hydrate=False,
        )
        == {}
    )
    remote.assert_not_called()

    monkeypatch.setattr(
        adapter,
        "_load_local_index_points",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    assert adapter.get_index_daily_returns(
        "000300.SH",
        date(2026, 1, 1),
        date(2026, 1, 2),
    ) == {}


def test_stock_pool_cache_paths_and_save_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.core.cache import cache

    adapter = _stock_pool_adapter()
    monkeypatch.setattr(cache, "get", lambda _key: [" 600000.SH ", 42, ""])
    load_db = MagicMock(return_value=["db"])
    monkeypatch.setattr(adapter, "_load_pool_from_db", load_db)
    assert adapter.get_current_pool() == ["600000.SH"]
    load_db.assert_not_called()

    monkeypatch.setattr(cache, "get", lambda _key: [])
    assert adapter.get_current_pool() == ["db"]

    set_mock = MagicMock()
    monkeypatch.setattr(cache, "set", set_mock)
    save_db = MagicMock()
    monkeypatch.setattr(adapter, "_save_pool_to_db", save_db)
    adapter.save_pool(["600000.SH"], "recovery", date(2026, 7, 1))

    metadata = json.loads(set_mock.call_args_list[1].args[1])
    assert metadata["regime"] == "recovery"
    assert metadata["count"] == 1
    save_db.assert_called_once()


def test_stock_pool_latest_info_cache_and_database_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.core.cache import cache

    adapter = _stock_pool_adapter()
    monkeypatch.setattr(cache, "get", lambda _key: b'{"regime":"growth","count":2}')
    assert adapter.get_latest_pool_info() == {"regime": "growth", "count": 2}

    fallback = MagicMock(return_value={"regime": "db"})
    monkeypatch.setattr(adapter, "_load_pool_meta_from_db", fallback)
    monkeypatch.setattr(cache, "get", lambda _key: ["not-json"])
    assert adapter.get_latest_pool_info() == {"regime": "db"}


def test_stock_pool_database_helpers_cover_success_empty_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.equity.infrastructure import models

    adapter = _stock_pool_adapter()
    latest = SimpleNamespace(
        stock_codes=["600000.SH"],
        regime="growth",
        as_of_date=date(2026, 7, 1),
        created_at=datetime(2026, 7, 2, 1),
    )
    manager = MagicMock()
    manager.filter.return_value.order_by.return_value.first.side_effect = [latest, None, latest, None]
    monkeypatch.setattr(models, "StockPoolSnapshot", SimpleNamespace(objects=manager))

    assert adapter._load_pool_from_db() == ["600000.SH"]
    assert adapter._load_pool_from_db() == []
    adapter._save_pool_to_db(["600000.SH"], "growth", date(2026, 7, 1))
    manager.filter.return_value.update.assert_called_once_with(is_active=False)
    manager.create.assert_called_once()
    assert adapter._load_pool_meta_from_db() == {
        "regime": "growth",
        "as_of_date": "2026-07-01",
        "count": 1,
        "updated_at": "2026-07-02",
    }
    assert adapter._load_pool_meta_from_db() is None

    failing = MagicMock()
    failing.filter.side_effect = RuntimeError("db down")
    monkeypatch.setattr(models, "StockPoolSnapshot", SimpleNamespace(objects=failing))
    assert adapter._load_pool_from_db() == []
    adapter._save_pool_to_db([], "growth", date(2026, 7, 1))
    assert adapter._load_pool_meta_from_db() is None


def test_stock_code_list_normalization_rejects_invalid_values() -> None:
    assert StockPoolRepositoryAdapter._normalize_stock_codes(None) == []
    assert StockPoolRepositoryAdapter._normalize_stock_codes([" A ", "", 1, "B"]) == ["A", "B"]
