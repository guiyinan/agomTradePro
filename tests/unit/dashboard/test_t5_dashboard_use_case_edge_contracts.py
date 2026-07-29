"""Helper and fallback contracts for dashboard data aggregation."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.dashboard.application import use_cases as use_case_module
from apps.dashboard.application.use_cases import (
    GetDashboardDataUseCase,
    _display_risk_tolerance,
    _normalize_regime_distribution,
    _risk_tolerance_value,
)


def _use_case(
    *,
    overview: object | None = None,
    signal: object | None = None,
) -> GetDashboardDataUseCase:
    use_case = GetDashboardDataUseCase.__new__(GetDashboardDataUseCase)
    use_case.overview_repo = overview or MagicMock()
    use_case.signal_repo = signal or MagicMock()
    return use_case


def _snapshot(
    *,
    invested_ratio: float = 0.7,
    total_return_pct: float = 5.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        total_value=100_000,
        total_return_pct=total_return_pct,
        positions=[1, 2],
        get_invested_ratio=lambda: invested_ratio,
    )


def _match(
    *,
    score: float = 60,
    hostile: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        total_match_score=score,
        hostile_assets=hostile or [],
    )


def _rule(rule_type: str, conditions: dict[str, object], template: str) -> dict[str, object]:
    return {
        "rule_type": rule_type,
        "conditions": conditions,
        "advice_template": template,
    }


def test_risk_and_regime_normalization_helpers() -> None:
    risk = SimpleNamespace(value="moderate")
    assert _display_risk_tolerance(risk) == "稳健型"
    assert _display_risk_tolerance("custom") == "custom"
    assert _risk_tolerance_value(risk) == "moderate"
    assert _normalize_regime_distribution(
        "Recovery",
        {"Recovery": 0.7, "Overheat": 0.3},
    ) == {
        "Recovery": 0.7,
        "Overheat": 0.3,
        "Deflation": 0.0,
        "Stagflation": 0.0,
    }
    assert all(value == 0 for value in _normalize_regime_distribution("Unknown").values())


def test_macro_health_reports_missing_stale_and_healthy_series() -> None:
    today = date.today()
    stale = SimpleNamespace(published_at=None, reporting_period=today - timedelta(days=100))
    fresh = SimpleNamespace(published_at=today, reporting_period=today)
    overview = MagicMock()
    overview.get_growth_series.return_value = [stale] * 3
    overview.get_inflation_series.return_value = []
    use_case = _use_case(overview=overview)

    unhealthy = use_case._assess_macro_data_health("PMI", "CPI", today)
    assert unhealthy["is_healthy"] is False
    assert any("样本不足" in warning for warning in unhealthy["warnings"])
    assert any("陈旧" in warning for warning in unhealthy["warnings"])
    assert "CPI 无可用数据" in unhealthy["warnings"]
    assert use_case._get_staleness_days(stale, today) == 100

    overview.get_growth_series.return_value = [fresh] * 12
    overview.get_inflation_series.return_value = [fresh] * 12
    assert use_case._assess_macro_data_health("PMI", "CPI", today) == {
        "is_healthy": True,
        "warnings": [],
    }


def test_simulated_positions_and_display_helpers() -> None:
    overview = SimpleNamespace(
        get_simulated_positions=lambda _user: [
            {
                "id": 1,
                "asset_code": "600000.SH",
                "asset_name": "浦发银行",
                "asset_class": "equity",
                "shares": 100,
                "avg_cost": 10,
                "current_price": 11,
                "market_value": 1100,
                "unrealized_pnl": 100,
                "unrealized_pnl_pct": 10,
                "opened_at": "2026-01-01",
            }
        ]
    )
    use_case = _use_case(overview=overview)
    positions = use_case._get_simulated_positions(1)
    assert positions[0]["asset_class_display"] == "股票"
    assert positions[0]["region_display"] == "中国"
    overview.get_simulated_positions = lambda _user: []
    assert use_case._get_simulated_positions(1) == []

    for value, label in (
        ("fixed_income", "债券"),
        ("commodity", "商品"),
        ("currency", "外汇"),
        ("cash", "现金"),
        ("fund", "基金"),
        ("derivative", "衍生品"),
        ("other", "其他"),
        ("custom", "custom"),
    ):
        assert use_case._get_asset_class_display(value) == label
    for value, label in (
        ("US", "美国"),
        ("EU", "欧洲"),
        ("JP", "日本"),
        ("EM", "新兴市场"),
        ("GLOBAL", "全球"),
        ("OTHER", "其他"),
        ("XX", "XX"),
    ):
        assert use_case._get_region_display(value) == label


def test_simulated_allocation_groups_and_sorts_values() -> None:
    use_case = _use_case()
    assert use_case._format_simulated_asset_allocation([]) == []
    allocation = use_case._format_simulated_asset_allocation(
        [
            {"asset_class": "fund", "market_value": 20},
            {"asset_class": "equity", "market_value": 70},
            {"asset_class": "equity", "market_value": 10},
        ]
    )
    assert allocation[0]["dimension_value"] == "equity"
    assert allocation[0]["count"] == 2
    assert allocation[0]["percentage"] == 80.0


def test_enhanced_fallback_combo_and_dimension_rules() -> None:
    rules = [
        _rule(
            "regime_policy_combo",
            {"regime": "Recovery", "min_policy_level": 1},
            "{regime}-{policy_level}-{match_score}-{invested_ratio}",
        ),
        _rule(
            "regime_advice",
            {"regime": "Recovery"},
            "{regime}-{growth_direction}-{inflation_direction}",
        ),
        _rule("policy_advice", {"min_policy_level": 0, "max_policy_level": 3}, "{policy_level}"),
    ]
    overview = SimpleNamespace(list_global_investment_rule_payloads=lambda: rules)
    use_case = _use_case(overview=overview)

    insights = use_case._enhanced_fallback_insights(
        "Recovery",
        _snapshot(),
        _match(),
        [],
        "P2",
    )
    assert len(insights) == 3
    assert insights[0].startswith("Recovery-P2")


def test_enhanced_fallback_position_match_hostile_signal_and_risk_rules() -> None:
    rules = [
        _rule(
            "match_position_combo",
            {"max_match_score": 50, "min_invested_ratio": 0.5, "max_invested_ratio": 1},
            "combo-{match_score}-{invested_ratio}",
        ),
        _rule(
            "position_advice",
            {"min_invested_ratio": 0.5, "max_invested_ratio": 1},
            "position-{invested_ratio}-{cash_ratio}",
        ),
        _rule("match_advice", {"min_match_score": 0, "max_match_score": 50}, "match-{match_score}"),
        _rule(
            "signal_advice",
            {"min_signal_count": 1, "has_active_signals": True},
            "signals-{signal_count}",
        ),
        _rule("risk_alert", {"min_return_pct": -10, "max_return_pct": 10}, "risk-{return_pct}"),
    ]
    overview = SimpleNamespace(list_global_investment_rule_payloads=lambda: rules)
    use_case = _use_case(overview=overview)
    insights = use_case._enhanced_fallback_insights(
        "Deflation",
        _snapshot(),
        _match(score=40, hostile=["600000.SH hostile"]),
        [{"asset_code": "000001.SZ"}],
        "P0",
    )
    assert any(item.startswith("combo-") for item in insights)
    assert any("不匹配" in item for item in insights)

    overview.list_global_investment_rule_payloads = lambda: rules[3:]
    insights = use_case._enhanced_fallback_insights(
        "Deflation",
        _snapshot(),
        _match(score=80),
        [{"asset_code": "000001.SZ"}],
        "P0",
    )
    assert "signals-1" in insights
    assert "risk-5" in insights


def test_enhanced_fallback_regime_position_and_static_guarantees() -> None:
    rules = [
        _rule(
            "regime_position_combo",
            {"regime": "Stagflation", "min_invested_ratio": 0, "max_invested_ratio": 0.5},
            "{regime}-{invested_ratio}",
        ),
        _rule("static_advice", {}, "static-one"),
        _rule("static_advice", {}, "static-two"),
    ]
    overview = SimpleNamespace(list_global_investment_rule_payloads=lambda: rules)
    use_case = _use_case(overview=overview)
    insights = use_case._enhanced_fallback_insights(
        "Stagflation",
        _snapshot(invested_ratio=0.3),
        _match(),
        [],
        "invalid",
    )
    assert insights[0].startswith("Stagflation-")
    assert len(insights) >= 2
    assert use_case._policy_to_numeric("invalid") == 0
    assert use_case._select_rule_payloads(rules, "static_advice") == rules[1:]

    overview.list_global_investment_rule_payloads = lambda: []
    assert use_case._fallback_insights(
        "Recovery",
        _snapshot(),
        _match(),
        [],
    ) == ["定期查看持仓与Regime的匹配度，关注市场变化"]


def test_ai_insights_use_provider_then_fallback_on_missing_or_error(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    del settings
    overview = MagicMock()
    overview.get_primary_system_ai_provider_payload.return_value = {"id": 1}
    use_case = _use_case(overview=overview)
    fallback = MagicMock(return_value=["fallback"])
    monkeypatch.setattr(use_case, "_enhanced_fallback_insights", fallback)
    monkeypatch.setattr(
        use_case_module,
        "get_dashboard_ai_insight_client",
        lambda: SimpleNamespace(generate_insights=lambda **_kwargs: ["ai"]),
    )
    monkeypatch.setattr(
        "django.conf.settings.DASHBOARD_SYNC_AI_INSIGHTS_ENABLED",
        True,
        raising=False,
    )

    assert use_case._generate_ai_insights(
        "Recovery",
        _snapshot(),
        _match(hostile=["A"]),
        [{"asset_code": "A", "direction": "BUY"}],
        "P1",
    ) == ["ai"]

    overview.get_primary_system_ai_provider_payload.return_value = None
    assert use_case._generate_ai_insights("Recovery", _snapshot(), _match(), [], "P0") == [
        "fallback"
    ]

    overview.get_primary_system_ai_provider_payload.side_effect = RuntimeError("down")
    assert use_case._generate_ai_insights("Recovery", _snapshot(), _match(), [], "P0") == [
        "fallback"
    ]


def test_latest_macro_values_success_empty_and_errors() -> None:
    overview = MagicMock()
    overview.get_growth_series.return_value = [50.5]
    overview.get_inflation_series.return_value = [2.1]
    use_case = _use_case(overview=overview)
    assert use_case._get_latest_macro_values() == (50.5, 2.1)

    overview.get_growth_series.side_effect = RuntimeError("growth down")
    overview.get_inflation_series.side_effect = RuntimeError("inflation down")
    assert use_case._get_latest_macro_values() == (None, None)


def test_allocation_advice_success_error_and_chart_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.strategy.application.allocation_service import AllocationService

    action = SimpleNamespace(
        asset_code="600000.SH",
        asset_name="浦发银行",
        action="buy",
        amount=123.456,
        reason="rebalance",
        asset_class="equity",
        priority=1,
    )
    advice = SimpleNamespace(
        current_allocation={"equity": 50},
        target_allocation={"equity": 60},
        allocation_diff={"equity": 10},
        trade_actions=[action],
        summary="summary",
        expected_return=0.1,
        expected_volatility=0.2,
        sharpe_ratio=0.5,
        regime="Recovery",
    )
    monkeypatch.setattr(
        AllocationService,
        "calculate_allocation_advice",
        lambda **_kwargs: advice,
    )
    use_case = _use_case()
    profile = SimpleNamespace(risk_tolerance=SimpleNamespace(value="moderate"))
    result = use_case._generate_allocation_advice(
        "Recovery",
        "P2",
        profile,
        100_000,
        [],
    )
    assert result is not None
    assert result["trade_actions"][0]["amount"] == 123.46
    assert result["risk_profile_display"] == "稳健型"
    assert use_case._normalize_policy_level_for_strategy("P3") == "P3"
    assert use_case._normalize_policy_level_for_strategy("unknown") is None

    monkeypatch.setattr(
        AllocationService,
        "calculate_allocation_advice",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert use_case._generate_allocation_advice("Recovery", None, profile, 1, []) is None
    assert use_case._generate_allocation_chart_data(
        [{"dimension_display": "股票", "market_value": 100}]
    ) == {"股票": 100.0}


def test_performance_chart_routes_legacy_user_and_missing_inputs() -> None:
    overview = MagicMock()
    overview.get_portfolio_snapshot_performance_data.return_value = [{"legacy": True}]
    overview.get_simulated_performance_data.return_value = [{"simulated": True}]
    use_case = _use_case(overview=overview)

    assert use_case._generate_performance_chart_data(portfolio_id=3) == [{"legacy": True}]
    assert use_case._generate_performance_chart_data() == []
    assert use_case._generate_performance_chart_data(user_id=1, account_id=2, days=10) == [
        {"simulated": True}
    ]
