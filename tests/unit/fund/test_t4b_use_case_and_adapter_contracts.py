"""Fund orchestration, persisted adapter, and failover contracts."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from apps.fund.application.use_cases import (
    AnalyzeFundStyleRequest,
    AnalyzeFundStyleUseCase,
    CalculateFundPerformanceRequest,
    CalculateFundPerformanceUseCase,
    RankFundsUseCase,
    ScreenFundsRequest,
    ScreenFundsUseCase,
    SyncFundDataUseCase,
)
from apps.fund.infrastructure.adapters.akshare_fund_adapter import (
    AkShareFundAdapter,
)
from apps.fund.infrastructure.adapters.hybrid_fund_adapter import (
    HybridFundAdapter,
)
from shared.infrastructure.resilience import DataSourceUnavailable, _cache_manager


def _query(rows: list[dict[str, object]]) -> Mock:
    queryset = Mock()
    queryset.filter.return_value = queryset
    queryset.exclude.return_value = queryset
    queryset.values.return_value = queryset
    queryset.order_by.return_value = queryset
    queryset.__iter__ = Mock(return_value=iter(rows))
    return queryset


def test_screen_funds_uses_explicit_custom_criteria_and_missing_name() -> None:
    repository = Mock()
    repository.get_fund_preferences_by_regime.return_value = []
    repository.resolve_research_window.return_value = (
        date(2025, 7, 25),
        date(2026, 7, 25),
    )
    repository.get_persisted_funds_with_performance.return_value = []
    repository.get_fund_info.side_effect = [
        SimpleNamespace(fund_name="Fund A"),
        None,
    ]
    use_case = ScreenFundsUseCase(repository)
    use_case.screener = Mock()
    use_case.screener.screen_by_regime.return_value = ["F1", "F2"]

    result = use_case.execute(
        ScreenFundsRequest(
            regime="Recovery",
            custom_types=["ETF"],
            custom_styles=["value"],
            min_scale=Decimal("100"),
            max_count=2,
        )
    )

    assert result.success is True
    assert result.regime == "Recovery"
    assert result.fund_names == ["Fund A", ""]
    assert result.screening_criteria == {
        "fund_types": ["ETF"],
        "investment_styles": ["value"],
        "min_scale": "100",
    }
    use_case.screener.screen_by_regime.assert_called_once_with(
        all_funds=[],
        preferred_types=["ETF"],
        preferred_styles=["value"],
        min_scale=Decimal("100"),
        max_count=2,
    )


def test_screen_funds_uses_persisted_regime_defaults_and_reports_absence() -> None:
    repository = Mock()
    repository.get_fund_preferences_by_regime.return_value = [
        ("混合型", "成长"),
        ("股票型", "平衡"),
        ("混合型", "价值"),
    ]
    repository.resolve_research_window.return_value = (date.today(), date.today())
    repository.get_persisted_funds_with_performance.return_value = []
    regime_repository = Mock()
    regime_repository.get_latest_snapshot.return_value = SimpleNamespace(dominant_regime="Recovery")

    with patch(
        "apps.fund.application.use_cases.get_regime_repository",
        return_value=regime_repository,
    ):
        result = ScreenFundsUseCase(repository).execute(ScreenFundsRequest())

    assert result.success is True
    assert result.regime == "Recovery"
    assert result.screening_criteria["fund_types"] == ["混合型", "股票型"]
    assert result.screening_criteria["investment_styles"] == ["成长", "平衡", "价值"]
    assert result.screening_criteria["min_scale"] == "0"

    regime_repository.get_latest_snapshot.return_value = None
    with patch(
        "apps.fund.application.use_cases.get_regime_repository",
        return_value=regime_repository,
    ):
        failed = ScreenFundsUseCase(repository).execute(ScreenFundsRequest())
    assert failed.success is False
    assert failed.error == "基金筛选失败，请检查 Regime、筛选偏好和本地业绩数据"


def test_rank_style_and_sync_use_cases_preserve_repository_contracts() -> None:
    repository = Mock()
    repository.resolve_research_window.return_value = (
        date(2025, 1, 1),
        date(2026, 1, 1),
    )
    repository.get_persisted_funds_with_performance.return_value = ["market"]
    repository.get_fund_preferences_by_regime.return_value = [
        ("ETF", ""),
        ("stock", ""),
    ]
    rank = RankFundsUseCase(repository)
    scores = [SimpleNamespace(rank=index) for index in range(3)]
    rank.screener = Mock()
    rank.screener.rank_funds.return_value = scores

    assert rank.execute("Recovery", max_count=2, as_of_date=date(2026, 1, 1)) == scores[:2]
    rank.screener.rank_funds.assert_called_once_with(
        funds_data=["market"],
        regime_weights={"ETF": 1.0, "stock": 1.0},
    )

    info = SimpleNamespace(fund_name="Fund A")
    repository.get_fund_info.return_value = info
    repository.get_fund_holdings.return_value = [SimpleNamespace()]
    repository.get_fund_sector_allocation.return_value = [SimpleNamespace()]
    style = AnalyzeFundStyleUseCase(repository)
    style.style_analyzer = Mock()
    style.style_analyzer.analyze_holding_style.return_value = {"growth": 0.7}
    style.style_analyzer.analyze_sector_concentration.return_value = {"top3": 0.6}

    analyzed = style.execute(AnalyzeFundStyleRequest("F1", report_date=date(2026, 6, 30)))
    assert analyzed.success is True
    assert analyzed.style_weights == {"growth": 0.7}
    assert analyzed.sector_concentration == {"top3": 0.6}

    repository.sync_fund_info_from_tushare.return_value = 4
    repository.sync_fund_nav_from_tushare.return_value = 5
    sync = SyncFundDataUseCase(repository)
    assert sync.sync_fund_list() == {"synced": 4}
    assert sync.sync_fund_nav("F1", "20260101", "20260725") == {"synced": 5}


def test_style_analysis_distinguishes_missing_fund_holdings_and_exception() -> None:
    repository = Mock()
    use_case = AnalyzeFundStyleUseCase(repository)
    repository.get_fund_info.return_value = None
    assert use_case.execute(AnalyzeFundStyleRequest("missing")).error == "基金 MISSING 不存在"

    repository.get_fund_info.return_value = SimpleNamespace(fund_name="Fund A")
    repository.get_fund_holdings.return_value = []
    no_holdings = use_case.execute(AnalyzeFundStyleRequest("F1"))
    assert no_holdings.success is False
    assert no_holdings.fund_name == "Fund A"
    assert "暂无持仓数据" in no_holdings.error

    repository.get_fund_holdings.side_effect = RuntimeError("repository failed")
    failed = use_case.execute(AnalyzeFundStyleRequest("F1"))
    assert failed.success is False
    assert failed.error == "基金风格分析失败，请检查基金与持仓数据"


def test_performance_use_case_validates_data_calculates_and_persists() -> None:
    repository = Mock()
    use_case = CalculateFundPerformanceUseCase(repository)
    request = CalculateFundPerformanceRequest(
        fund_code="F1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 11),
    )
    repository.get_fund_info.return_value = None
    assert use_case.execute(request).error == "基金 F1 不存在"

    repository.get_fund_info.return_value = SimpleNamespace(fund_name="Fund A")
    repository.get_fund_nav.return_value = [SimpleNamespace()]
    assert "净值数据不足" in use_case.execute(request).error

    nav = [
        SimpleNamespace(nav_date=date(2026, 1, 1), daily_return=None),
        SimpleNamespace(nav_date=date(2026, 1, 6), daily_return=0.01),
        SimpleNamespace(nav_date=date(2026, 1, 11), daily_return=0.02),
    ]
    repository.get_fund_nav.return_value = nav
    calculator = Mock()
    calculator.calculate_total_return.return_value = 0.1
    calculator.calculate_annualized_return.return_value = 0.2
    calculator.calculate_volatility.return_value = 0.3
    calculator.calculate_sharpe_ratio.return_value = 0.4
    calculator.calculate_max_drawdown.return_value = 0.05
    use_case.perf_calculator = calculator

    result = use_case.execute(request)

    assert result.success is True
    assert result.performance.total_return == 0.1
    assert result.performance.volatility == 0.3
    assert result.performance.sharpe_ratio == 0.4
    calculator.calculate_annualized_return.assert_called_once_with(0.1, 10)
    calculator.calculate_volatility.assert_called_once_with([0.01, 0.02])
    repository.save_fund_performance.assert_called_once_with(result.performance)

    repository.save_fund_performance.side_effect = RuntimeError("write failed")
    assert use_case.execute(request).error == "基金业绩计算失败，请检查日期范围和净值数据"


def test_persisted_akshare_adapter_maps_fund_list_info_and_scale() -> None:
    list_rows = [
        {
            "fund_code": "F1",
            "fund_name": "Fund A",
            "fund_type": "ETF",
            "investment_style": "index",
            "management_company": "Manager",
            "fund_scale": Decimal("10"),
        }
    ]
    manager = Mock()
    manager.filter.side_effect = [
        _query(list_rows),
        _query([]),
        _query(
            [
                {
                    "fund_code": "F1",
                    "fund_name": "Fund A",
                    "fund_scale": Decimal("10"),
                }
            ]
        ),
    ]
    adapter = AkShareFundAdapter.__new__(AkShareFundAdapter)
    adapter._dc_nav_repo = Mock()

    with patch(
        "apps.fund.infrastructure.adapters.akshare_fund_adapter.FundInfoModel",
        SimpleNamespace(_default_manager=manager),
    ):
        fund_list = adapter.fetch_fund_list_em()
        missing_info = adapter.fetch_fund_info_em("missing")
        scale = adapter.fetch_fund_scale_rank()

    assert fund_list.iloc[0]["代码"] == "F1"
    assert fund_list.iloc[0]["基金类型"] == "ETF"
    assert missing_info.empty
    assert scale.iloc[0]["基金规模"] == Decimal("10")


def test_persisted_akshare_adapter_prefers_facts_and_falls_back_to_models() -> None:
    adapter = AkShareFundAdapter.__new__(AkShareFundAdapter)
    adapter._dc_nav_repo = Mock()
    adapter._dc_nav_repo.get_series.return_value = [
        SimpleNamespace(
            nav_date=date(2026, 7, 25),
            nav=1.2,
            acc_nav=1.3,
            daily_return=0.01,
            source="dc",
        ),
        SimpleNamespace(
            nav_date=date(2026, 7, 24),
            nav=1.1,
            acc_nav=1.2,
            daily_return=0.0,
            source="dc",
        ),
    ]

    facts = adapter.fetch_fund_nav_em("F1")
    assert list(facts["nav_date"]) == [date(2026, 7, 24), date(2026, 7, 25)]

    adapter._dc_nav_repo.get_series.return_value = []
    nav_manager = Mock()
    nav_manager.filter.return_value = _query(
        [
            {
                "nav_date": date(2026, 7, 25),
                "unit_nav": Decimal("1.2"),
                "accum_nav": Decimal("1.3"),
                "daily_return": 0.01,
            }
        ]
    )
    with patch(
        "apps.fund.infrastructure.adapters.akshare_fund_adapter.FundNetValueModel",
        SimpleNamespace(_default_manager=nav_manager),
    ):
        fallback = adapter.fetch_fund_nav_em("F1")
    assert fallback.iloc[0]["unit_nav"] == Decimal("1.2")

    nav_manager.filter.return_value = _query([])
    with patch(
        "apps.fund.infrastructure.adapters.akshare_fund_adapter.FundNetValueModel",
        SimpleNamespace(_default_manager=nav_manager),
    ):
        assert adapter.fetch_fund_nav_em("missing").empty


def test_persisted_akshare_portfolio_sector_and_rank_boundaries() -> None:
    adapter = AkShareFundAdapter.__new__(AkShareFundAdapter)
    adapter._dc_nav_repo = Mock()
    holding_manager = Mock()
    holding_manager.filter.return_value = _query(
        [
            {
                "stock_code": "000001.SZ",
                "stock_name": "Bank",
                "holding_amount": 1,
                "holding_value": Decimal("10"),
                "holding_ratio": 0.2,
                "report_date": date(2026, 3, 31),
            },
            {
                "stock_code": "000002.SZ",
                "stock_name": "Late",
                "holding_amount": 1,
                "holding_value": Decimal("10"),
                "holding_ratio": 0.1,
                "report_date": date(2026, 12, 31),
            },
        ]
    )
    sector_manager = Mock()
    sector_manager.filter.side_effect = [
        _query([]),
        _query(
            [
                {
                    "sector_name": "Bank",
                    "allocation_ratio": 0.4,
                    "report_date": date(2026, 3, 31),
                }
            ]
        ),
    ]

    with (
        patch(
            "apps.fund.infrastructure.adapters.akshare_fund_adapter.FundHoldingModel",
            SimpleNamespace(_default_manager=holding_manager),
        ),
        patch(
            "apps.fund.infrastructure.adapters.akshare_fund_adapter." "FundSectorAllocationModel",
            SimpleNamespace(_default_manager=sector_manager),
        ),
    ):
        holdings = adapter.fetch_fund_portfolio_em("F1", 2026, 2)
        assert adapter.fetch_fund_sector_allocation("F1", 2026, 2).empty
        sectors = adapter.fetch_fund_sector_allocation("F1", 2026, 2)

    assert list(holdings["股票代码"]) == ["000001.SZ"]
    assert sectors.iloc[0]["行业名称"] == "Bank"
    assert adapter.fetch_fund_rank_em("收益率").empty

    with patch.object(
        adapter,
        "fetch_fund_scale_rank",
        return_value=pd.DataFrame([{"基金代码": "F1"}]),
    ):
        assert adapter.fetch_fund_rank_em("规模").iloc[0]["基金代码"] == "F1"


def _raw_fund_list(adapter: HybridFundAdapter) -> pd.DataFrame:
    function = adapter.fetch_fund_list_em
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__
    return function(adapter)


def test_hybrid_adapter_lazy_sources_fallback_and_health_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cache_manager.clear()
    adapter = HybridFundAdapter()
    with pytest.raises(ValueError, match="token"):
        _ = adapter.tushare

    akshare_instance = Mock()
    with patch(
        "apps.fund.infrastructure.adapters.akshare_fund_adapter.AkShareFundAdapter",
        return_value=akshare_instance,
    ):
        assert adapter.akshare is akshare_instance
        assert adapter.akshare is akshare_instance

    tushare_instance = Mock()
    adapter_with_token = HybridFundAdapter(tushare_token="token", tushare_http_url="url")
    with patch(
        "apps.fund.infrastructure.adapters.tushare_fund_adapter.TushareFundAdapter",
        return_value=tushare_instance,
    ) as constructor:
        assert adapter_with_token.tushare is tushare_instance
        constructor.assert_called_once_with(token="token", http_url="url")

    health = Mock()
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.hybrid_fund_adapter._health_manager",
        health,
    )
    health.is_healthy.return_value = True
    adapter_with_token._akshare_adapter = Mock()
    adapter_with_token._akshare_adapter.fetch_fund_list_em.side_effect = RuntimeError(
        "akshare down"
    )
    adapter_with_token._tushare_adapter = Mock()
    adapter_with_token._tushare_adapter.fetch_fund_list.return_value = pd.DataFrame(
        [{"fund_code": "F1"}]
    )

    assert _raw_fund_list(adapter_with_token).iloc[0]["fund_code"] == "F1"
    health.record_failure.assert_any_call("akshare_fund", "RuntimeError")
    health.record_success.assert_called_with("tushare_fund")

    health.is_healthy.return_value = False
    with pytest.raises(DataSourceUnavailable):
        _raw_fund_list(HybridFundAdapter())

    health.get_health_status.side_effect = lambda source: {"source": source}
    assert adapter_with_token.get_health_status() == {
        "akshare_fund": {"source": "akshare_fund"},
        "tushare_fund": {"source": "tushare_fund"},
    }


def test_hybrid_info_and_nav_return_empty_on_unhealthy_or_source_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cache_manager.clear()
    health = Mock()
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.hybrid_fund_adapter._health_manager",
        health,
    )
    adapter = HybridFundAdapter()
    adapter._akshare_adapter = Mock()
    health.is_healthy.return_value = False
    assert adapter.fetch_fund_info_em("000001").empty
    assert adapter.fetch_fund_nav_em("000001").empty

    health.is_healthy.return_value = True
    adapter._akshare_adapter.fetch_fund_info_em.side_effect = RuntimeError("info failed")
    adapter._akshare_adapter.fetch_fund_nav_em.side_effect = RuntimeError("nav failed")
    assert adapter.fetch_fund_info_em("000002").empty
    assert adapter.fetch_fund_nav_em("000002").empty
    health.record_failure.assert_any_call("akshare_fund", "RuntimeError")
