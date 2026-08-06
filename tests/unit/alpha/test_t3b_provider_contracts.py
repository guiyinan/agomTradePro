"""T3B Alpha provider contracts for data quality, queues, and model failures."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

from apps.alpha.domain.entities import AlphaResult
from apps.alpha.domain.interfaces import AlphaProviderStatus
from apps.alpha.infrastructure.adapters import qlib_adapter
from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider

TARGET_DATE = date(2026, 7, 24)


class _Values(list[str]):
    def distinct(self) -> _Values:
        return self

    def order_by(self, *args: str) -> _Values:
        return self


class _ValuationQuery(list[SimpleNamespace]):
    def values_list(self, field: str, flat: bool = False) -> _Values:
        assert field == "stock_code"
        assert flat is True
        return _Values([row.stock_code for row in self])

    def order_by(self, *args: str) -> _ValuationQuery:
        return self


class _ValuationManager:
    def __init__(
        self,
        rows: list[SimpleNamespace],
        latest_date: date | None = TARGET_DATE,
    ) -> None:
        self.rows = rows
        self.latest_date = latest_date

    def aggregate(self, **kwargs: object) -> dict[str, date | None]:
        return {"max_date": self.latest_date}

    def filter(self, **kwargs: object) -> _ValuationQuery:
        requested = set(kwargs.get("stock_code__in", []))
        if requested:
            return _ValuationQuery([row for row in self.rows if row.stock_code in requested])
        return _ValuationQuery(self.rows)


class _FinancialQuery(list[SimpleNamespace]):
    def order_by(self, *args: str) -> _FinancialQuery:
        return self

    def first(self) -> SimpleNamespace | None:
        return self[0] if self else None


class _FinancialManager:
    def __init__(self, rows: dict[str, SimpleNamespace]) -> None:
        self.rows = rows

    def filter(self, **kwargs: object) -> _FinancialQuery:
        row = self.rows.get(str(kwargs["stock_code"]))
        return _FinancialQuery([row] if row is not None else [])


def test_simple_universe_selection_uses_config_latest_data_and_safe_failures(
    monkeypatch: pytest.MonkeyPatch,
    settings,
) -> None:
    """Simple provider selects only configured/available stocks and fails closed."""
    available_codes = ["000001.SZ", "600000.SH"]
    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.list_valuation_covered_codes",
        lambda as_of=None: list(available_codes),
    )
    settings.ALPHA_SIMPLE_UNIVERSE_MAP = {
        "configured": ["000001.SZ", "missing.SZ"],
    }
    provider = SimpleAlphaProvider()
    assert provider._get_universe_stocks("configured", TARGET_DATE) == ["000001.SZ"]
    assert provider._get_universe_stocks("all", TARGET_DATE) == [
        "000001.SZ",
        "600000.SH",
    ]

    available_codes.clear()
    assert provider._get_universe_stocks("all", TARGET_DATE) == []

    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.list_valuation_covered_codes",
        lambda as_of=None: (_ for _ in ()).throw(RuntimeError("DB offline")),
    )
    assert provider._get_universe_stocks("all", TARGET_DATE) == []


def test_simple_fundamentals_classify_complete_partial_missing_and_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fundamental reads distinguish usable partial data from missing data."""
    valuations = [
        {"asset_code": "000001.SZ", "pe_ttm": 10.0, "pb": 1.0, "dv_ratio": 0.03},
        {"asset_code": "000002.SZ", "pe_ttm": None, "pb": 2.0, "dv_ratio": None},
        {"asset_code": "000003.SZ", "pe_ttm": None, "pb": None, "dv_ratio": 0.01},
    ]
    financials = {"000001.SZ": [{"period_end": "2026-07-01", "metric_code": "roe", "value": 0.2}]}
    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.get_valuation_facts",
        lambda stock_code, **kwargs: [row for row in valuations if row["asset_code"] == stock_code],
    )
    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.get_financial_facts",
        lambda stock_code, **kwargs: financials.get(stock_code, []),
    )
    provider = SimpleAlphaProvider()
    data, quality = provider._get_fundamental_data(
        ["000001.SZ", "000002.SZ", "000003.SZ"],
        TARGET_DATE,
    )
    assert data["000001.SZ"]["pe"] == 10.0
    assert "000002.SZ" not in data
    assert "000003.SZ" not in data
    assert quality["complete_count"] == 1
    assert quality["partial_count"] == 0
    assert quality["missing_count"] == 2

    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.get_valuation_facts",
        lambda stock_code, **kwargs: (_ for _ in ()).throw(RuntimeError("valuation locked")),
    )
    data, quality = provider._get_fundamental_data(["000001.SZ"], TARGET_DATE)
    assert data == {}
    assert quality["error"] == "获取基本面数据时发生错误: valuation locked"


def test_simple_fundamentals_requests_financial_facts_as_of_trade_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, object]] = []
    financial_rows = [
        {"period_end": TARGET_DATE.isoformat(), "metric_code": "roe", "value": 0.2},
        {"period_end": TARGET_DATE.isoformat(), "metric_code": "roa", "value": 0.1},
        {"period_end": TARGET_DATE.isoformat(), "metric_code": "debt_ratio", "value": 0.4},
        {
            "period_end": TARGET_DATE.isoformat(),
            "metric_code": "revenue_growth",
            "value": 0.1,
        },
        {
            "period_end": TARGET_DATE.isoformat(),
            "metric_code": "net_profit_growth",
            "value": 0.1,
        },
    ]
    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.get_valuation_facts",
        lambda stock_code, **kwargs: [
            {"asset_code": stock_code, "pe_ttm": 10.0, "pb": 1.0, "dv_ratio": 0.03}
        ],
    )

    def _financials(stock_code: str, **kwargs: object) -> list[dict[str, object]]:
        seen.append(kwargs)
        return financial_rows

    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.get_financial_facts",
        _financials,
    )

    data, quality = SimpleAlphaProvider()._get_fundamental_data(["000001.SZ"], TARGET_DATE)

    assert data["000001.SZ"]["roe"] == 0.2
    assert quality["complete_count"] == 1
    assert seen == [{"limit": 100, "as_of": TARGET_DATE}]


def test_simple_quote_fallback_rejects_missing_and_nonpositive_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh quote fallback does not score absent or nonpositive market data."""
    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.get_published_quote_payloads",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "000002.SZ",
                    "snapshot_at": datetime.now(UTC),
                    "current_price": 0,
                    "prev_close": 10,
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "volume": 100,
                }
            ]
        },
    )
    scores, metadata, staleness = SimpleAlphaProvider()._compute_quote_momentum_scores(
        stock_list=["000001.SZ", "000002.SZ"],
        universe_id="portfolio",
        intended_trade_date=TARGET_DATE,
    )
    assert scores == []
    assert metadata["quote_count"] == 1
    assert metadata["price_momentum_count"] == 0
    assert staleness is None


def test_simple_quote_fallback_rejects_rows_when_publication_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked publication cannot be bypassed by non-empty legacy rows."""
    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.simple_adapter.get_published_quote_payloads",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "snapshot_at": datetime.now(UTC),
                    "current_price": 10.5,
                    "prev_close": 10.0,
                    "open": 10.1,
                    "high": 10.8,
                    "low": 9.9,
                    "volume": 1000,
                }
            ],
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_stale",
        },
    )

    scores, metadata, staleness = SimpleAlphaProvider()._compute_quote_momentum_scores(
        stock_list=["000001.SZ"],
        universe_id="portfolio",
        intended_trade_date=TARGET_DATE,
    )

    assert scores == []
    assert metadata["quote_count"] == 0
    assert metadata["price_momentum_count"] == 0
    assert metadata["quote_error"] == "publication_stale"
    assert metadata["must_not_use_for_decision"] is True
    assert staleness is None


def test_simple_factor_exposure_uses_bounded_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factor exposure clamps invalid fundamentals while preserving usable evidence."""
    provider = SimpleAlphaProvider()
    monkeypatch.setattr(
        provider,
        "_get_fundamental_data",
        lambda stocks, day: (
            {
                stocks[0]: {
                    "pe": 0,
                    "pb": 0,
                    "roe": -0.2,
                    "dividend_yield": -0.1,
                }
            },
            {},
        ),
    )
    assert provider.get_factor_exposure("000001.SZ", TARGET_DATE) == {
        "pe_inv": 1.0,
        "pb_inv": 2.0,
        "roe": 0,
        "dividend_yield": 0,
    }


def test_qlib_health_cache_and_model_failures_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Provider health and cache fast paths expose missing artifacts and freshness."""
    provider = QlibAlphaProvider(provider_uri=str(tmp_path), model_path=str(tmp_path))
    monkeypatch.setattr(
        provider,
        "_get_active_model",
        lambda: {"model_path": str(tmp_path / "missing.pkl")},
    )
    assert provider.health_check() is AlphaProviderStatus.UNAVAILABLE
    assert "模型文件不存在" in (provider._last_health_message or "")

    cached = AlphaResult(
        success=True,
        scores=[],
        source="qlib",
        timestamp=TARGET_DATE.isoformat(),
        status="available",
        staleness_days=None,
    )
    monkeypatch.setattr(provider, "_get_from_cache", lambda *args, **kwargs: cached)
    assert provider.get_stock_scores("csi300", TARGET_DATE).staleness_days == 0

    broken_model = tmp_path / "broken.pkl"
    broken_model.write_bytes(b"not-a-pickle")
    assert provider.load_model(str(broken_model)) is False


def test_qlib_queue_trigger_and_inline_failures_release_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue/inline inference failures alert once and always release throttling locks."""
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    monkeypatch.setattr(qlib_adapter.cache, "get", lambda key: None)
    monkeypatch.setattr(provider, "_resolve_live_inference_queue", lambda: "qlib_infer")
    monkeypatch.setattr(
        "apps.alpha.application.tasks.qlib_predict_scores.apply_async",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("queue offline")),
    )
    alerts: list[str] = []
    monkeypatch.setattr(
        provider,
        "_send_inference_failure_alert",
        lambda universe, day, error: alerts.append(error),
    )
    assert provider._trigger_infer_task("csi300", TARGET_DATE, 10) == "failed"
    assert alerts == ["RuntimeError"]

    deleted: list[str] = []
    monkeypatch.setattr(qlib_adapter.cache, "add", lambda *args, **kwargs: True)
    monkeypatch.setattr(qlib_adapter.cache, "delete", lambda key: deleted.append(key))
    monkeypatch.setattr(
        "apps.alpha.application.tasks.qlib_predict_scores.apply",
        lambda **kwargs: SimpleNamespace(
            get=lambda propagate=False: {"outcome": "failed"},
            failed=lambda: True,
        ),
    )
    failed = provider._run_inline_infer_task(
        universe_id="csi300",
        intended_trade_date=TARGET_DATE,
        top_n=10,
    )
    assert failed == {"status": "failed", "error_code": "inline_inference_failed"}

    monkeypatch.setattr(
        "apps.alpha.application.tasks.qlib_predict_scores.apply",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("inline crashed")),
    )
    failed = provider._run_inline_infer_task(
        universe_id="csi300",
        intended_trade_date=TARGET_DATE,
        top_n=10,
    )
    assert failed == {"status": "failed", "error_code": "inline_inference_exception"}
    assert len(deleted) == 2


def test_qlib_alert_and_universe_lookup_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alert persistence and Qlib universe lookup never mask the original degradation."""
    from apps.alpha.infrastructure import models as alpha_models

    created: list[dict[str, object]] = []
    monkeypatch.setattr(
        alpha_models,
        "AlphaAlertModel",
        SimpleNamespace(
            _default_manager=SimpleNamespace(create=lambda **kwargs: created.append(kwargs))
        ),
    )
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    provider._send_inference_failure_alert("csi300", TARGET_DATE, "queue offline")
    assert created[0]["alert_type"] == "inference_failure"

    monkeypatch.setattr(
        alpha_models,
        "AlphaAlertModel",
        SimpleNamespace(
            _default_manager=SimpleNamespace(
                create=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("audit DB offline"))
            )
        ),
    )
    provider._send_inference_failure_alert("csi300", TARGET_DATE, "queue offline")

    data_module = ModuleType("qlib.data")
    data_module.D = SimpleNamespace(
        instruments=lambda market: "instrument-expression",
        list_instruments=lambda **kwargs: ["000001.SZ", "600000.SH"],
    )
    monkeypatch.setitem(sys.modules, "qlib.data", data_module)
    assert provider.get_universe_stocks("csi300") == ["000001.SZ", "600000.SH"]

    data_module.D = SimpleNamespace(
        instruments=lambda market: (_ for _ in ()).throw(RuntimeError("calendar offline"))
    )
    assert provider.get_universe_stocks("csi300") == []


def test_qlib_cache_and_local_calendar_freshness_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache and local-calendar probes return evidence without propagating storage failures."""
    from apps.alpha.infrastructure import models as alpha_models
    from core.integration import runtime_settings

    class _CacheQuery:
        def exists(self) -> bool:
            return True

    monkeypatch.setattr(
        alpha_models,
        "AlphaScoreCacheModel",
        SimpleNamespace(_default_manager=SimpleNamespace(filter=lambda **kwargs: _CacheQuery())),
    )
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    assert provider._has_recent_cache() is True

    monkeypatch.setattr(
        alpha_models,
        "AlphaScoreCacheModel",
        SimpleNamespace(
            _default_manager=SimpleNamespace(
                filter=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("cache DB offline"))
            )
        ),
    )
    assert provider._has_recent_cache() is False

    init_calls: list[dict[str, object]] = []
    qlib_module = ModuleType("qlib")
    qlib_module.init = lambda **kwargs: init_calls.append(kwargs)
    data_module = ModuleType("qlib.data")
    data_module.D = SimpleNamespace(calendar=lambda **kwargs: [pd.Timestamp("2026-07-24")])
    monkeypatch.setitem(sys.modules, "qlib", qlib_module)
    monkeypatch.setitem(sys.modules, "qlib.data", data_module)
    monkeypatch.setattr(
        runtime_settings,
        "get_runtime_qlib_config",
        lambda: {
            "enabled": True,
            "must_not_use_for_decision": False,
            "provider_uri": "local-data",
            "region": "CN",
        },
    )
    assert provider._get_latest_data_date() == TARGET_DATE
    assert init_calls == [{"provider_uri": "local-data", "region": "cn"}]

    monkeypatch.setattr(
        runtime_settings,
        "get_runtime_qlib_config",
        lambda: {
            "enabled": False,
            "must_not_use_for_decision": True,
            "blocked_reason": "runtime_config_snapshot_unavailable",
        },
    )
    init_calls.clear()
    assert provider._get_latest_data_date() is None
    assert init_calls == []

    data_module.D = SimpleNamespace(calendar=lambda **kwargs: [])
    assert provider._get_latest_data_date() is None
    data_module.D = SimpleNamespace(
        calendar=lambda **kwargs: (_ for _ in ()).throw(OSError("calendar corrupt"))
    )
    assert provider._get_latest_data_date() is None


def test_qlib_factor_exposure_handles_empty_and_malformed_feature_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factor reads return an empty mapping for empty or malformed Qlib results."""
    data_module = ModuleType("qlib.data")
    data_module.D = SimpleNamespace(features=lambda **kwargs: pd.DataFrame())
    monkeypatch.setitem(sys.modules, "qlib.data", data_module)
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    assert provider.get_factor_exposure("000001.SZ", TARGET_DATE) == {}

    data_module.D = SimpleNamespace(
        features=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("feature store offline"))
    )
    assert provider.get_factor_exposure("000001.SZ", TARGET_DATE) == {}
