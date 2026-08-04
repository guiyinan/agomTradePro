from datetime import UTC, datetime

from apps.strategy.infrastructure.providers import (
    DjangoAssetNameResolver,
    DjangoAssetPoolProvider,
    DjangoMacroDataProvider,
    DjangoPortfolioDataProvider,
    DjangoSignalProvider,
)


def test_macro_data_provider_uses_published_data_center_port(monkeypatch):
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.get_macro_indicator_value",
        lambda code: 51.2 if code == "CN_PMI_MANUFACTURING" else None,
    )
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.list_latest_published_macro_values",
        lambda limit: [
            {"indicator_code": "CN_PMI_MANUFACTURING", "value": 51.2},
            {"indicator_code": "CN_CPI_YOY", "value": 0},
        ],
    )

    provider = DjangoMacroDataProvider()

    assert provider.get_indicator("CN_PMI_MANUFACTURING") == 51.2
    assert provider.get_all_indicators() == {
        "CN_PMI_MANUFACTURING": 51.2,
        "CN_CPI_YOY": 0.0,
    }


def test_macro_data_provider_fails_closed_when_publication_port_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.get_macro_indicator_value",
        lambda code: (_ for _ in ()).throw(RuntimeError("publication unavailable")),
    )
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.list_latest_published_macro_values",
        lambda limit: (_ for _ in ()).throw(RuntimeError("publication unavailable")),
    )

    provider = DjangoMacroDataProvider()

    assert provider.get_indicator("CN_PMI_MANUFACTURING") is None
    assert provider.get_all_indicators() == {}


def test_asset_pool_provider_aggregates_application_repository(monkeypatch):
    calls: list[tuple[str, float, int]] = []
    asset_types = ("equity", "fund", "bond", "wealth", "commodity", "index")

    class StubAssetPoolRepository:
        def list_investable_assets(
            self,
            asset_type: str,
            min_score: float,
            limit: int,
        ) -> list[dict]:
            calls.append((asset_type, min_score, limit))
            fixtures = {
                "equity": [
                    {
                        "asset_code": "000001.SZ",
                        "asset_name": "平安银行",
                        "asset_type": "equity",
                        "score": 75.0,
                        "regime_score": 70.0,
                        "policy_score": 68.0,
                    }
                ],
                "fund": [
                    {
                        "asset_code": "510300.OF",
                        "asset_name": "",
                        "asset_type": "fund",
                        "score": 88.5,
                        "regime_score": 82.0,
                        "policy_score": 80.0,
                    }
                ],
                "commodity": [
                    {
                        "asset_code": "AU9999.SGE",
                        "asset_name": "黄金现货",
                        "asset_type": "commodity",
                        "score": 80.0,
                        "regime_score": 78.0,
                        "policy_score": 74.0,
                    }
                ],
            }
            return fixtures.get(asset_type, [])

    monkeypatch.setattr(
        "apps.asset_analysis.application.repository_provider.get_asset_pool_query_repository",
        lambda: StubAssetPoolRepository(),
    )
    monkeypatch.setattr(
        "apps.asset_analysis.application.repository_provider.list_investable_asset_categories",
        lambda: asset_types,
    )

    provider = DjangoAssetPoolProvider()
    result = provider.get_investable_assets(min_score=60.0, limit=2)

    assert calls == [(asset_type, 60.0, 2) for asset_type in asset_types]
    assert result == [
        {
            "asset_code": "510300.OF",
            "asset_name": "510300.OF",
            "total_score": 88.5,
            "regime_score": 82.0,
            "policy_score": 80.0,
            "asset_type": "fund",
            "data_source": "asset_pool",
            "is_fallback": False,
            "actionable": True,
            "execution_block_reason": None,
            "data_quality": {"status": "available", "warnings": []},
        },
        {
            "asset_code": "AU9999.SGE",
            "asset_name": "黄金现货",
            "total_score": 80.0,
            "regime_score": 78.0,
            "policy_score": 74.0,
            "asset_type": "commodity",
            "data_source": "asset_pool",
            "is_fallback": False,
            "actionable": True,
            "execution_block_reason": None,
            "data_quality": {"status": "available", "warnings": []},
        },
    ]


def test_asset_pool_provider_falls_back_to_latest_score_cache(monkeypatch):
    calls: list[tuple[str, float, int, str]] = []
    asset_types = ("equity", "fund")

    class StubAssetPoolRepository:
        def list_investable_assets(
            self,
            *,
            asset_type: str,
            min_score: float,
            limit: int,
        ) -> list[dict]:
            calls.append((asset_type, min_score, limit, "pool"))
            return []

    def fake_list_investable_asset_categories() -> tuple[str, ...]:
        return asset_types

    def fake_list_latest_scored_assets(
        asset_type: str,
        *,
        min_score: float,
        limit: int,
    ) -> list[dict]:
        calls.append((asset_type, min_score, limit, "score"))
        if asset_type == "equity":
            return [
                {
                    "asset_code": "000001.SH",
                    "asset_name": "上证指数",
                    "score": 75.0,
                    "regime_score": 80.0,
                    "policy_score": 70.0,
                    "asset_type": "equity",
                }
            ]
        return [
            {
                "asset_code": "510300.OF",
                "asset_name": "沪深300ETF",
                "score": 68.0,
                "regime_score": 72.0,
                "policy_score": 65.0,
                "asset_type": "fund",
            }
        ]

    monkeypatch.setattr(
        "apps.asset_analysis.application.repository_provider.get_asset_pool_query_repository",
        lambda: StubAssetPoolRepository(),
    )
    monkeypatch.setattr(
        "apps.asset_analysis.application.repository_provider.list_investable_asset_categories",
        fake_list_investable_asset_categories,
    )
    monkeypatch.setattr(
        "apps.asset_analysis.application.repository_provider.list_latest_scored_assets",
        fake_list_latest_scored_assets,
    )

    provider = DjangoAssetPoolProvider()
    result = provider.get_investable_assets(min_score=60.0, limit=5)

    assert result == []
    assert calls == [
        ("equity", 60.0, 5, "pool"),
        ("fund", 60.0, 5, "pool"),
    ]

    calls.clear()
    result = provider.get_investable_assets(min_score=60.0, limit=5, include_degraded=True)

    assert calls == [
        ("equity", 60.0, 5, "pool"),
        ("fund", 60.0, 5, "pool"),
        ("equity", 60.0, 5, "score"),
        ("fund", 60.0, 5, "score"),
    ]
    assert result == [
        {
            "asset_code": "000001.SH",
            "asset_name": "上证指数",
            "total_score": 75.0,
            "regime_score": 80.0,
            "policy_score": 70.0,
            "asset_type": "equity",
            "data_source": "score_cache_fallback",
            "is_fallback": True,
            "actionable": False,
            "execution_block_reason": "degraded_asset_pool_data",
            "data_quality": {
                "status": "degraded",
                "warnings": ["asset_pool_empty_score_cache_fallback"],
            },
        },
        {
            "asset_code": "510300.OF",
            "asset_name": "沪深300ETF",
            "total_score": 68.0,
            "regime_score": 72.0,
            "policy_score": 65.0,
            "asset_type": "fund",
            "data_source": "score_cache_fallback",
            "is_fallback": True,
            "actionable": False,
            "execution_block_reason": "degraded_asset_pool_data",
            "data_quality": {
                "status": "degraded",
                "warnings": ["asset_pool_empty_score_cache_fallback"],
            },
        },
    ]


def test_signal_provider_uses_signal_query_service(monkeypatch):
    created_at = datetime(2026, 4, 27, 1, 2, 3, tzinfo=UTC)

    def fake_list_signal_payloads(
        *,
        status_filter: str = "",
        asset_class: str = "",
        direction: str = "",
        search: str = "",
        limit: int = 50,
    ) -> list[dict]:
        assert status_filter == "approved"
        assert asset_class == ""
        assert direction == ""
        assert search == ""
        assert limit == 100
        return [
            {
                "id": "sig-1",
                "asset_code": "000001.SZ",
                "direction": "LONG",
                "logic_desc": "PMI improving",
                "target_regime": "Recovery",
                "invalidation_description": "PMI falls below 50",
                "created_at": created_at,
            }
        ]

    monkeypatch.setattr(
        "apps.signal.application.query_services.list_investment_signal_payloads",
        fake_list_signal_payloads,
    )

    provider = DjangoSignalProvider()

    assert provider.get_valid_signals() == [
        {
            "signal_id": "sig-1",
            "asset_code": "000001.SZ",
            "direction": "LONG",
            "logic_desc": "PMI improving",
            "target_regime": "Recovery",
            "invalidation_logic": "PMI falls below 50",
            "created_at": created_at.isoformat(),
        }
    ]


def test_asset_name_resolver_delegates_to_asset_analysis_service(monkeypatch):
    def fake_resolve_asset_names(codes: list[str]) -> dict[str, str]:
        assert set(codes) == {"000001.SZ", "510300.OF"}
        return {
            "000001.SZ": "平安银行",
            "510300.OF": "沪深300ETF",
        }

    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        fake_resolve_asset_names,
    )

    resolver = DjangoAssetNameResolver()

    assert resolver.resolve_asset_names(["000001.SZ", "", "510300.OF"]) == {
        "000001.SZ": "平安银行",
        "510300.OF": "沪深300ETF",
    }
    assert resolver.resolve_asset_names([]) == {}


def test_portfolio_data_provider_uses_simulated_trading_facade(monkeypatch):
    expected = object()
    monkeypatch.setattr(
        "apps.strategy.infrastructure.providers.get_simulated_trading_facade",
        lambda: expected,
    )

    provider = DjangoPortfolioDataProvider()

    assert provider._get_facade() is expected
    assert provider._get_facade() is expected
