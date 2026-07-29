"""T5 SDK fallback contracts for runtime capability owners."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import agomtradepro
from agomtradepro_mcp.registry.runtime_handlers.owners import (
    account,
    data_center,
    policy,
    risk_center,
    rotation,
    strategy,
)


@pytest.fixture
def sdk_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[MagicMock]:
    """Install one client double for owner fallbacks that import lazily."""
    client = MagicMock()
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: client)
    yield client


def test_strategy_fallback_matrix_delegates_and_normalizes(
    sdk_client: MagicMock,
) -> None:
    """Every strategy fallback must expose stable dictionaries and lists."""
    service = sdk_client.strategy
    service.list_strategies.return_value = [{"id": 1}, "skip"]
    service.get_strategy.return_value = {"id": 1, "name": "quality"}
    service.list_ai_strategy_configs.return_value = [{"id": 2}, "skip"]
    service.get_strategy_ai_config.return_value = {"exists": False}
    service.list_position_rules.return_value = [{"id": 3}, "skip"]
    service.get_strategy_position_rule.return_value = {"id": 3}
    service.evaluate_position_rule.return_value = {"decision": "hold"}
    service.evaluate_strategy_position_management.return_value = {"target": 0.5}
    service.get_strategy_performance.return_value = {"return": 0.1}
    service.get_strategy_signals.return_value = [{"id": 4}]
    service.get_strategy_positions.return_value = [{"asset_code": "A"}]
    for method_name in (
        "execute_strategy",
        "bind_portfolio_strategy",
        "unbind_portfolio_strategy",
        "create_position_rule",
        "update_position_rule",
        "create_strategy",
        "create_ai_strategy_config",
        "update_ai_strategy_config",
    ):
        getattr(service, method_name).return_value = {"success": True}

    assert strategy._fallback_strategy_read_catalog("factor", True, 10)["total_count"] == 1
    assert strategy._fallback_strategy_read_detail(1)["strategy"]["id"] == 1
    assert (
        strategy._fallback_strategy_read_ai_config_catalog(1, "auto", 2, 10)[
            "total_count"
        ]
        == 1
    )
    assert strategy._fallback_strategy_read_ai_config_detail(1)["config"] is None
    assert (
        strategy._fallback_strategy_read_position_rule_catalog(1, True, 10)[
            "total_count"
        ]
        == 1
    )
    assert strategy._fallback_strategy_read_position_rule_detail(1)["rule"]["id"] == 3
    assert strategy._fallback_strategy_compute_position_rule(3, {"price": 10}) == {
        "decision": "hold"
    }
    assert strategy._fallback_strategy_compute_position_management(
        1, {"price": 10}
    ) == {"target": 0.5}
    assert strategy._fallback_strategy_read_performance(
        1, "2026-01-01", "2026-07-25"
    ) == {"return": 0.1}
    assert strategy._fallback_strategy_read_signals(1, "active", 10)["total_count"] == 1
    assert strategy._fallback_strategy_read_positions(1)["total_count"] == 1
    assert strategy._fallback_execute_strategy(1, "2026-07-25")["success"] is True
    assert strategy._fallback_bind_portfolio_strategy(1, 2)["success"] is True
    assert strategy._fallback_unbind_portfolio_strategy(1)["success"] is True
    assert strategy._fallback_create_position_rule(
        1,
        "rule",
        "buy",
        "sell",
        "stop",
        "take",
        "size",
        buy_condition_expr="condition",
        sell_condition_expr="exit",
        description="desc",
        price_precision=4,
        variables_schema=[{"name": "x"}],
        metadata={"source": "test"},
        is_active=False,
    )["success"] is True
    assert strategy._fallback_update_position_rule(3, {"name": "new"})["success"] is True
    assert strategy._fallback_create_strategy(
        "quality", "factor", "desc", {"window": 20}
    )["success"] is True
    assert strategy._fallback_create_ai_strategy_config(
        1,
        prompt_template_id=2,
        chain_config_id=3,
        ai_provider_id=4,
    )["success"] is True
    assert strategy._fallback_update_ai_strategy_config(
        2, {"approval_mode": "manual"}
    )["success"] is True


def test_strategy_fallbacks_reject_invalid_sdk_shapes(sdk_client: MagicMock) -> None:
    """Owner boundaries must reject malformed SDK payloads before dispatch."""
    service = sdk_client.strategy
    invalid_calls = [
        (service.list_strategies, strategy._fallback_strategy_read_catalog, ()),
        (service.get_strategy, strategy._fallback_strategy_read_detail, (1,)),
        (
            service.list_ai_strategy_configs,
            strategy._fallback_strategy_read_ai_config_catalog,
            (),
        ),
        (
            service.get_strategy_ai_config,
            strategy._fallback_strategy_read_ai_config_detail,
            (1,),
        ),
        (
            service.list_position_rules,
            strategy._fallback_strategy_read_position_rule_catalog,
            (),
        ),
        (
            service.get_strategy_position_rule,
            strategy._fallback_strategy_read_position_rule_detail,
            (1,),
        ),
        (
            service.evaluate_position_rule,
            strategy._fallback_strategy_compute_position_rule,
            (1, {}),
        ),
        (
            service.evaluate_strategy_position_management,
            strategy._fallback_strategy_compute_position_management,
            (1, {}),
        ),
        (
            service.get_strategy_performance,
            strategy._fallback_strategy_read_performance,
            (1,),
        ),
        (service.get_strategy_signals, strategy._fallback_strategy_read_signals, (1,)),
        (
            service.get_strategy_positions,
            strategy._fallback_strategy_read_positions,
            (1,),
        ),
    ]
    for method, fallback, arguments in invalid_calls:
        method.return_value = "invalid"
        with pytest.raises(ValueError, match="invalid payload"):
            fallback(*arguments)


def test_data_center_fallback_matrix_builds_complete_payloads(
    sdk_client: MagicMock,
) -> None:
    """Data-center fallbacks must preserve CRUD, query, and sync arguments."""
    service = sdk_client.data_center
    service.get_provider_status.return_value = [{"id": 1}]
    service.list_providers.return_value = [{"id": 1}]
    service.list_indicators.return_value = [{"code": "PMI"}]
    service.list_publishers.return_value = [{"code": "NBS"}]
    service.list_indicator_unit_rules.return_value = [{"id": 7}]
    for method_name in (
        "get_macro_series",
        "get_price_history",
        "get_latest_quotes",
        "get_news",
        "get_publisher",
        "get_indicator",
        "get_indicator_unit_rule",
        "update_publisher",
        "create_publisher",
        "create_indicator",
        "create_indicator_unit_rule",
        "update_indicator_unit_rule",
        "sync_macro",
        "sync_capital_flows",
        "sync_news",
        "update_indicator",
    ):
        getattr(service, method_name).return_value = {"success": True}

    assert data_center._fallback_get_data_center_provider_status()["total_count"] == 1
    assert data_center._fallback_list_data_center_providers()["total_count"] == 1
    assert data_center._fallback_data_center_get_macro_series(
        "PMI", "2026-01-01", "2026-07-25", 10
    )["success"] is True
    assert data_center._fallback_data_center_list_indicators(True)["total_count"] == 1
    assert data_center._fallback_data_center_get_price_history(
        "A", "2026-01-01", "2026-07-25", "1d", "qfq", 10
    )["success"] is True
    assert data_center._fallback_data_center_get_quotes("A", True, 1.5)["success"] is True
    assert data_center._fallback_data_center_get_news("A", 5)["success"] is True
    assert data_center._fallback_data_center_get_publisher("NBS")["success"] is True
    assert data_center._fallback_data_center_list_publishers(True)["total_count"] == 1
    assert data_center._fallback_data_center_get_indicator("PMI")["success"] is True
    assert (
        data_center._fallback_data_center_list_indicator_unit_rules("PMI")[
            "total_count"
        ]
        == 1
    )
    assert data_center._fallback_data_center_get_indicator_unit_rule("PMI", 7)[
        "success"
    ] is True
    assert data_center._fallback_data_center_update_publisher(
        "NBS",
        canonical_name="Statistics",
        publisher_class="government",
        aliases=["NBSC"],
        canonical_name_en="NBS",
        country_code="CN",
        website="https://example.test",
        is_active=False,
        description="updated",
    )["success"] is True
    assert data_center._fallback_data_center_create_publisher(
        "NBS", "Statistics", "government", aliases=["NBSC"]
    )["success"] is True
    assert data_center._fallback_data_center_delete_publisher("NBS") == {
        "success": True,
        "publisher_code": "NBS",
    }
    assert data_center._fallback_data_center_create_indicator(
        "PMI", "采购经理指数", extra={"unit": "index"}
    )["success"] is True
    assert data_center._fallback_data_center_delete_indicator("PMI") == {
        "success": True,
        "indicator_code": "PMI",
    }
    assert data_center._fallback_data_center_create_indicator_unit_rule(
        "PMI", "index", "index", "index", 1.0
    )["success"] is True
    assert data_center._fallback_data_center_delete_indicator_unit_rule("PMI", 7) == {
        "success": True,
        "indicator_code": "PMI",
        "rule_id": 7,
    }
    assert data_center._fallback_data_center_update_indicator_unit_rule(
        "PMI",
        7,
        source_type="api",
        dimension_key="index",
        original_unit="point",
        storage_unit="index",
        display_unit="index",
        multiplier_to_storage=1.0,
        is_active=False,
        priority=10,
        description="updated",
    )["success"] is True
    assert data_center._fallback_data_center_sync_macro(
        1, "PMI", "2026-01-01", "2026-07-25"
    )["success"] is True
    assert data_center._fallback_data_center_sync_capital_flows(1, "A", "10d")[
        "success"
    ] is True
    assert data_center._fallback_data_center_sync_news(1, "A", 10)["success"] is True
    assert data_center._fallback_data_center_update_indicator(
        "PMI",
        name_cn="采购经理指数",
        name_en="PMI",
        description="updated",
        category="growth",
        default_period_type="M",
        is_active=False,
        extra={"unit": "index"},
    )["success"] is True


def test_risk_center_fallback_matrix_delegates_complete_context(
    sdk_client: MagicMock,
) -> None:
    """Risk fallbacks must carry complete pre/post-trade contexts."""
    service = sdk_client.risk_center
    service.get_floor.return_value = {"floor": 0.1}
    service.list_templates.return_value = [{"id": 1}]
    service.get_effective_policy.return_value = {"id": 2}
    service.get_account_policy.return_value = {"id": 3}
    service.list_exceptions.return_value = [{"id": 4}]
    service.check_pre_trade.return_value = {"allowed": True}
    service.check_post_investment.return_value = {"allowed": True}
    service.get_daily_report.return_value = {"id": 5}
    service.list_daily_reports.return_value = [{"id": 5}]

    assert risk_center._fallback_get_risk_floor()["floor"] == 0.1
    assert risk_center._fallback_list_risk_templates()["total_count"] == 1
    assert risk_center._fallback_get_effective_risk_policy(1)["id"] == 2
    assert risk_center._fallback_get_account_risk_policy(1)["id"] == 3
    assert risk_center._fallback_list_risk_exceptions(1)["total_count"] == 1
    assert risk_center._fallback_check_pre_trade_risk(
        1, "A", "buy", 10, 2, 100, 20, 80, 5
    )["allowed"] is True
    assert risk_center._fallback_check_post_investment_risk(
        1,
        100,
        positions=[{"asset_code": "A"}],
        cash_balance=80,
        total_position_value=20,
        daily_pnl_pct=-0.01,
        drawdown_pct=0.02,
    )["allowed"] is True
    assert risk_center._fallback_get_risk_center_daily_report(1, "2026-07-25")[
        "id"
    ] == 5
    assert risk_center._fallback_list_risk_center_daily_reports(
        1,
        "2026-07-25",
        "2026-01-01",
        "2026-07-25",
        10,
    )["total_count"] == 1


def test_account_and_rotation_fallback_matrix(
    sdk_client: MagicMock,
) -> None:
    """Account and rotation read/write fallbacks must normalize boundary payloads."""
    sdk_client.account.get_macro_sizing_config.return_value = {"warning_factor": 0.5}
    sdk_client.account.get_positions.return_value = [
        SimpleNamespace(
            asset_code="A",
            quantity=10,
            avg_cost=2,
            current_price=3,
            market_value=30,
            profit_loss=10,
        )
    ]
    sdk_client.account.get_portfolio_statistics.return_value = {"total": 100}
    sdk_client.account.get_trading_cost_configs.return_value = [
        {"id": 1, "portfolio": 7},
        {"id": 2, "portfolio": 8},
    ]
    sdk_client.account.calculate_trading_cost.return_value = {"total": 1}
    assert account._fallback_get_macro_sizing_config()["warning_factor"] == 0.5
    assert account._fallback_get_positions(7, "A", 10)["total_count"] == 1
    assert account._fallback_get_portfolio_statistics(7)["total"] == 100
    assert account._fallback_get_trading_cost_configs(7)["total_count"] == 1
    assert account._fallback_calculate_trading_cost(1, "sell", 100, True)["total"] == 1

    service = sdk_client.rotation
    service.compare_assets.return_value = {
        "calc_date": "2026-07-25",
        "assets": {"A": {"score": 1}},
    }
    service.list_regimes.return_value = [{"key": "risk_on"}]
    service.list_templates.return_value = [{"key": "balanced"}]
    service.list_account_configs.return_value = [{"id": 1}]
    service.get_account_config.return_value = {"id": 1}
    service.get_account_config_by_account.return_value = {"id": 2}
    service.list_assets.return_value = [{"code": "A"}]
    service.get_asset.return_value = {"code": "A"}
    service.get_latest_signals.return_value = [{"asset_code": "A"}]
    for method_name in (
        "create_account_config",
        "delete_account_config",
        "update_account_config",
        "apply_template_to_account_config",
    ):
        getattr(service, method_name).return_value = {"success": True}

    assert rotation._fallback_rotation_compute_asset_comparison(["A"])["calc_date"] == (
        "2026-07-25"
    )
    assert rotation._fallback_list_rotation_regimes()["total_count"] == 1
    assert rotation._fallback_list_rotation_templates()["total_count"] == 1
    assert rotation._fallback_list_account_rotation_configs()["total_count"] == 1
    assert rotation._fallback_get_account_rotation_config(config_id=1)["id"] == 1
    assert rotation._fallback_get_account_rotation_config(account_id=7)["id"] == 2
    with pytest.raises(ValueError, match="Exactly one"):
        rotation._fallback_get_account_rotation_config()
    assert rotation._fallback_list_rotation_asset_master()["total_count"] == 1
    assert rotation._fallback_get_rotation_asset("A")["code"] == "A"
    assert rotation._fallback_get_latest_rotation_signals()["total_count"] == 1
    assert rotation._fallback_create_account_rotation_config(
        7, "moderate", True, {"risk_on": {"A": 1.0}}
    )["success"] is True
    assert rotation._fallback_delete_account_rotation_config(1)["success"] is True
    assert rotation._fallback_update_account_rotation_config(
        1, {"is_enabled": True}, False
    )["success"] is True
    assert rotation._fallback_apply_rotation_template_to_account_config(
        1, "balanced"
    )["success"] is True


def test_policy_fallback_matrix_formats_workbench_records(
    sdk_client: MagicMock,
) -> None:
    """Policy fallbacks must normalize status, events, workbench rows, and actions."""
    service = sdk_client.policy
    service.get_status.return_value = SimpleNamespace(
        current_gear="P1",
        observed_at=datetime(2026, 7, 25, tzinfo=UTC),
        recent_events=[{"id": 1}],
    )
    service.get_events.return_value = [
        SimpleNamespace(
            id=1,
            event_date=date(2026, 7, 25),
            event_type="rate",
            description="decision",
            gear="P1",
        )
    ]
    service.get_workbench_bootstrap.return_value = {"tabs": ["pending"]}
    service.get_workbench_summary.return_value = SimpleNamespace(
        policy_level="P1",
        policy_level_name="observe",
        gate_level="open",
        gate_level_name="open",
        global_heat=0.5,
        global_sentiment=0.2,
        pending_review_count=1,
        sla_exceeded_count=0,
        today_events_count=1,
    )
    service.get_workbench_event_detail.return_value = {"id": 1}
    item = SimpleNamespace(
        id=1,
        event_date=date(2026, 7, 25),
        event_type="rate",
        level="P1",
        title="decision",
        description="description",
        gate_level="open",
        gate_effective=True,
        audit_status="pending",
        ai_confidence=0.8,
        heat_score=0.5,
        sentiment_score=0.2,
        asset_class="equity",
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    service.get_workbench_items.return_value = SimpleNamespace(
        items=[item],
        total_count=1,
        page=1,
        page_size=20,
    )
    service.get_sentiment_gate_state.return_value = SimpleNamespace(
        gate_level="open",
        global_heat=0.5,
        global_sentiment=0.2,
        max_position_cap=0.8,
        signal_paused=False,
    )
    for method_name in (
        "approve_event",
        "reject_event",
        "rollback_event",
        "override_event",
    ):
        getattr(service, method_name).return_value = {"success": True}

    assert policy._fallback_get_policy_status()["recent_events_count"] == 1
    assert policy._fallback_get_policy_events(
        "2026-01-01", "2026-07-25", 10
    )["total_count"] == 1
    assert policy._fallback_get_workbench_bootstrap()["tabs"] == ["pending"]
    assert policy._fallback_get_workbench_summary()["policy_level"] == "P1"
    assert policy._fallback_get_workbench_event_detail(1)["id"] == 1
    assert policy._fallback_get_workbench_items(
        "pending", "rate", "P1", "open", "decision", 1, 20
    )["items"][0]["created_at"].startswith("2026-07-25")
    assert policy._fallback_get_sentiment_gate_state("equity")["signal_paused"] is False
    assert policy._fallback_approve_workbench_event(1)["success"] is True
    assert policy._fallback_reject_workbench_event(1, "reason")["success"] is True
    assert policy._fallback_rollback_workbench_event(1, "reason")["success"] is True
    assert policy._fallback_override_workbench_event(1, "reason", "P2")[
        "success"
    ] is True
