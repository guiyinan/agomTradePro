"""Truthfulness and direct-call invariants for Fund application services."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.fund.application import interface_services
from apps.fund.application.services import FundMultiDimScorer
from apps.fund.application.use_cases import (
    CalculateFundPerformanceRequest,
    CalculateFundPerformanceUseCase,
    ScreenFundsRequest,
    ScreenFundsUseCase,
)
from apps.fund.domain.entities import FundInfo, FundNetValue


class FundRepositoryStub:
    """Small repository double covering the Fund application protocol."""

    def __init__(self) -> None:
        self.preferences: list[tuple[str, str]] = []
        self.saved_performance: object | None = None
        self.persisted_query_count = 0
        self.nav_rows: list[FundNetValue] = []

    def get_fund_preferences_by_regime(self, regime: str) -> list[tuple[str, str]]:
        return self.preferences

    def resolve_research_window(
        self, *, requested_end_date: date, lookback_days: int = 365
    ) -> tuple[date, date]:
        return date(2026, 1, 1), date(2026, 12, 31)

    def get_persisted_funds_with_performance(
        self, start_date: date, end_date: date
    ) -> list[tuple[object, object, list[object]]]:
        self.persisted_query_count += 1
        return []

    def get_fund_info(self, fund_code: str) -> FundInfo | None:
        return FundInfo(
            fund_code=fund_code,
            fund_name="测试基金",
            fund_type="股票型",
        )

    def get_fund_holdings(self, fund_code: str, report_date: date | None = None) -> list[object]:
        return []

    def get_fund_sector_allocation(
        self, fund_code: str, report_date: date | None = None
    ) -> list[object]:
        return []

    def get_fund_nav(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundNetValue]:
        return self.nav_rows

    def save_fund_performance(self, performance: object) -> None:
        self.saved_performance = performance

    def sync_fund_info_from_tushare(self) -> int:
        return 0

    def sync_fund_nav_from_tushare(self, fund_code: str, start_date: str, end_date: str) -> int:
        return 0


def test_dashboard_does_not_fabricate_missing_macro_state(monkeypatch) -> None:
    """Missing Policy and Sentiment must remain visibly unavailable."""

    monkeypatch.setattr(interface_services, "resolve_current_regime", lambda **_: None)
    monkeypatch.setattr(
        interface_services,
        "get_current_policy_repository",
        lambda: SimpleNamespace(get_current_policy_level=lambda: None),
    )
    monkeypatch.setattr(
        interface_services,
        "get_sentiment_index_repository",
        lambda: SimpleNamespace(get_latest=lambda: None),
    )
    monkeypatch.setattr(
        interface_services,
        "get_signal_repository",
        lambda: SimpleNamespace(get_active_signals=lambda: []),
    )

    context = interface_services.build_dashboard_context()

    assert context["current_regime"] == "Unknown"
    assert context["regime_confidence"] == "N/A"
    assert context["current_policy"] == "Unknown"
    assert context["policy_display"] == "未配置"
    assert context["sentiment_index"] == "N/A"
    assert context["sentiment_level"] == "未知"


def test_screening_fails_closed_without_database_preferences() -> None:
    """No hard-coded fund types or styles may replace missing configuration."""

    repository = FundRepositoryStub()
    response = ScreenFundsUseCase(repository).execute(ScreenFundsRequest(regime="Recovery"))

    assert response.success is False
    assert response.screening_criteria == {}
    assert repository.persisted_query_count == 0


def test_screening_uses_configured_type_and_style_pairs() -> None:
    """Both fund type and style come from the persisted preference rows."""

    repository = FundRepositoryStub()
    repository.preferences = [
        ("股票型", "成长"),
        ("混合型", "平衡"),
    ]
    use_case = ScreenFundsUseCase(repository)
    use_case.screener.screen_by_regime = Mock(return_value=["000001"])

    response = use_case.execute(ScreenFundsRequest(regime="Recovery"))

    assert response.success is True
    call = use_case.screener.screen_by_regime.call_args.kwargs
    assert call["preferred_types"] == ["股票型", "混合型"]
    assert call["preferred_styles"] == ["成长", "平衡"]


def test_performance_persists_actual_nav_window_not_requested_window() -> None:
    """A partial NAV series must not be labeled as covering unavailable dates."""

    repository = FundRepositoryStub()
    repository.nav_rows = [
        FundNetValue(
            fund_code="000001",
            nav_date=date(2026, 2, 1),
            unit_nav=Decimal("1.00"),
            accum_nav=Decimal("1.00"),
            daily_return=0.0,
        ),
        FundNetValue(
            fund_code="000001",
            nav_date=date(2026, 2, 2),
            unit_nav=Decimal("1.01"),
            accum_nav=Decimal("1.01"),
            daily_return=1.0,
        ),
        FundNetValue(
            fund_code="000001",
            nav_date=date(2026, 2, 3),
            unit_nav=Decimal("1.02"),
            accum_nav=Decimal("1.02"),
            daily_return=0.99,
        ),
    ]

    response = CalculateFundPerformanceUseCase(repository).execute(
        CalculateFundPerformanceRequest(
            fund_code="000001.OF",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
        )
    )

    assert response.success is True
    assert response.performance is not None
    assert response.performance.fund_code == "000001"
    assert response.performance.start_date == date(2026, 2, 1)
    assert response.performance.end_date == date(2026, 2, 3)
    assert repository.saved_performance == response.performance


def test_multidim_direct_call_requires_explicit_macro_context() -> None:
    """Internal callers cannot fall back to fabricated Recovery/P0/neutral state."""

    with pytest.raises(ValueError, match="required"):
        interface_services.screen_funds_multidim(
            filters={},
            context_data={},
            max_count=10,
        )


def test_multidim_empty_result_has_stable_shape() -> None:
    """No-match screening publishes count zero instead of causing a view KeyError."""

    repository = SimpleNamespace(get_assets_by_filter=lambda **_: [])
    result = FundMultiDimScorer(repository).screen_funds(
        filters={},
        context=ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.0,
            active_signals=[],
        ),
        max_count=10,
    )

    assert result == {
        "success": False,
        "count": 0,
        "message": "未找到符合条件的基金",
        "funds": [],
    }
