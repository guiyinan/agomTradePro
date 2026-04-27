from datetime import datetime, timezone

from apps.strategy.infrastructure.providers import (
    DjangoAssetNameResolver,
    DjangoAssetPoolProvider,
    DjangoMacroDataProvider,
    DjangoSignalProvider,
)


def test_macro_data_provider_uses_indicator_service(monkeypatch):
    class StubIndicatorService:
        @classmethod
        def get_indicator_by_code(cls, code: str) -> dict | None:
            assert code == "CN_PMI_MANUFACTURING"
            return {"latest_value": "51.2"}

        @classmethod
        def get_available_indicators(cls, include_stats: bool = True) -> list[dict]:
            assert include_stats is False
            return [
                {"code": "CN_PMI_MANUFACTURING", "latest_value": "51.2"},
                {"code": "CN_CPI_YOY", "latest_value": 0},
                {"code": "CN_M2", "latest_value": None},
            ]

    monkeypatch.setattr(
        "apps.macro.application.indicator_service.IndicatorService",
        StubIndicatorService,
    )

    provider = DjangoMacroDataProvider()

    assert provider.get_indicator("CN_PMI_MANUFACTURING") == 51.2
    assert provider.get_all_indicators() == {
        "CN_PMI_MANUFACTURING": 51.2,
        "CN_CPI_YOY": 0.0,
    }


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
        },
        {
            "asset_code": "AU9999.SGE",
            "asset_name": "黄金现货",
            "total_score": 80.0,
            "regime_score": 78.0,
            "policy_score": 74.0,
            "asset_type": "commodity",
        },
    ]


def test_signal_provider_uses_signal_query_service(monkeypatch):
    created_at = datetime(2026, 4, 27, 1, 2, 3, tzinfo=timezone.utc)

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
