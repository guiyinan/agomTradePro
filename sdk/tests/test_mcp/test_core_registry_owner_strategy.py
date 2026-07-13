# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_strategy."""

from .core_registry_support import *


def test_strategy_execute_run_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeStrategyModule:
        @staticmethod
        def get_strategy(strategy_id):
            return {
                "id": strategy_id,
                "name": "Momentum Alpha",
                "type": "momentum",
                "status": "active",
                "params": {"lookback": 20, "top_n": 10},
            }

    class _FakeClient:
        strategy = _FakeStrategyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_execute_strategy(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "strategy_id": kwargs["strategy_id"],
            "signals_created": 12,
            "message": "strategy executed",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "execute_strategy",
        fake_execute_strategy,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="strategy.execute.run",
        arguments={
            "strategy_id": 3,
            "as_of_date": "2026-03-21",
            "idempotency_key": "idem-strategy-execute",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["strategy_summary"]["name"] == "Momentum Alpha"
    assert preview_response["preview_result"]["strategy_summary"]["param_count"] == 2
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["strategy_id"] == 3
    assert resume_response["result"]["signals_created"] == 12
    assert captured_calls[0]["strategy_id"] == 3
    assert captured_calls[0]["as_of_date"] == "2026-03-21"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["strategy_id"] == 3
    assert audit_events[0]["affected_objects"]["as_of_date"] == "2026-03-21"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_strategy_bind_portfolio_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    from types import SimpleNamespace

    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeStrategyModule:
        @staticmethod
        def get_strategy(strategy_id):
            return {
                "id": strategy_id,
                "name": "Momentum Alpha",
                "type": "momentum",
                "status": "active",
                "params": {"lookback": 20, "top_n": 10},
            }

    class _FakeAccountModule:
        @staticmethod
        def get_portfolio(portfolio_id):
            return SimpleNamespace(
                id=portfolio_id,
                name="Core Portfolio",
                total_value=2500000.0,
                cash=350000.0,
            )

    class _FakeClient:
        strategy = _FakeStrategyModule()
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_bind_portfolio_strategy(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "portfolio_id": kwargs["portfolio_id"],
            "strategy_id": kwargs["strategy_id"],
            "message": "strategy bound",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "bind_portfolio_strategy",
        fake_bind_portfolio_strategy,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="strategy.bind.portfolio",
        arguments={
            "portfolio_id": 9,
            "strategy_id": 3,
            "idempotency_key": "idem-strategy-bind",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["portfolio_summary"]["name"] == "Core Portfolio"
    assert preview_response["preview_result"]["strategy_summary"]["name"] == "Momentum Alpha"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["portfolio_id"] == 9
    assert resume_response["result"]["strategy_id"] == 3
    assert captured_calls[0]["portfolio_id"] == 9
    assert captured_calls[0]["strategy_id"] == 3
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["portfolio_id"] == 9
    assert audit_events[0]["affected_objects"]["strategy_id"] == 3
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_strategy_unbind_portfolio_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    from types import SimpleNamespace

    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAccountModule:
        @staticmethod
        def get_portfolio(portfolio_id):
            return SimpleNamespace(
                id=portfolio_id,
                name="Core Portfolio",
                total_value=2500000.0,
                cash=350000.0,
            )

    class _FakeClient:
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_unbind_portfolio_strategy(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "portfolio_id": kwargs["portfolio_id"],
            "message": "strategy unbound",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "unbind_portfolio_strategy",
        fake_unbind_portfolio_strategy,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="strategy.unbind.portfolio",
        arguments={
            "portfolio_id": 9,
            "idempotency_key": "idem-strategy-unbind",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["portfolio_summary"]["name"] == "Core Portfolio"
    assert preview_response["preview_result"]["target_status"] == "unbound"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["portfolio_id"] == 9
    assert captured_calls[0]["portfolio_id"] == 9
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["portfolio_id"] == 9
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_strategy_create_position_rule_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeStrategyModule:
        @staticmethod
        def get_strategy(strategy_id):
            return {
                "id": strategy_id,
                "name": "Momentum Alpha",
                "strategy_type": "momentum",
                "is_active": True,
            }

    class _FakeClient:
        strategy = _FakeStrategyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_create_position_rule(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": 31,
            "strategy": kwargs["strategy_id"],
            "name": kwargs["name"],
            "is_active": kwargs["is_active"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_position_rule",
        fake_create_position_rule,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="strategy.create.position_rule",
        arguments={
            "strategy_id": 7,
            "name": "Core Rule",
            "buy_price_expr": "close * 0.99",
            "sell_price_expr": "close * 1.05",
            "stop_loss_expr": "close * 0.95",
            "take_profit_expr": "close * 1.1",
            "position_size_expr": "0.2",
            "variables_schema": [{"name": "close", "type": "number"}],
            "metadata": {"source": "mcp"},
            "idempotency_key": "idem-strategy-create-rule",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["strategy_summary"]["name"] == "Momentum Alpha"
    assert preview_response["preview_result"]["position_rule_summary"]["variable_count"] == 1
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["strategy"] == 7
    assert captured_calls[0]["strategy_id"] == 7
    assert captured_calls[0]["name"] == "Core Rule"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["strategy_id"] == 7
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_strategy_update_position_rule_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeStrategyModule:
        @staticmethod
        def get_position_rule(rule_id):
            return {
                "id": rule_id,
                "strategy": 7,
                "name": "Core Rule",
                "is_active": True,
                "price_precision": 2,
            }

    class _FakeClient:
        strategy = _FakeStrategyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_update_position_rule(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["rule_id"],
            "strategy": 7,
            "name": "Core Rule",
            "is_active": kwargs["updates"]["is_active"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "update_position_rule",
        fake_update_position_rule,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="strategy.update.position_rule",
        arguments={
            "rule_id": 31,
            "updates": {"is_active": False, "price_precision": 4},
            "idempotency_key": "idem-strategy-update-rule",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["position_rule_summary"]["strategy"] == 7
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 2
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 31
    assert captured_calls[0]["rule_id"] == 31
    assert captured_calls[0]["updates"]["is_active"] is False
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["rule_id"] == 31
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_strategy_create_ai_config_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeStrategyModule:
        @staticmethod
        def get_strategy(strategy_id):
            return {
                "id": strategy_id,
                "name": "Momentum Alpha",
                "strategy_type": "momentum",
                "is_active": True,
            }

    class _FakeClient:
        strategy = _FakeStrategyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_create_ai_strategy_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": 41,
            "strategy": kwargs["strategy_id"],
            "approval_mode": kwargs["approval_mode"],
            "confidence_threshold": kwargs["confidence_threshold"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_ai_strategy_config",
        fake_create_ai_strategy_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="strategy.create.ai_config",
        arguments={
            "strategy_id": 7,
            "ai_provider_id": 3,
            "temperature": 0.4,
            "max_tokens": 1500,
            "approval_mode": "conditional",
            "confidence_threshold": 0.75,
            "idempotency_key": "idem-strategy-create-ai-config",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["strategy_summary"]["name"] == "Momentum Alpha"
    assert preview_response["preview_result"]["ai_config_summary"]["ai_provider_id"] == 3
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["strategy"] == 7
    assert captured_calls[0]["strategy_id"] == 7
    assert captured_calls[0]["approval_mode"] == "conditional"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["strategy_id"] == 7
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_strategy_create_strategy_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_create_strategy(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": 52,
            "name": kwargs["name"],
            "strategy_type": kwargs["strategy_type"],
            "is_active": bool(kwargs["params"].get("is_active", True)),
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_strategy",
        fake_create_strategy,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="strategy.create.strategy",
        arguments={
            "name": "Momentum Plus",
            "strategy_type": "momentum",
            "description": "Momentum strategy with tighter stops.",
            "params": {
                "lookback": 20,
                "max_position_pct": 15.0,
                "is_active": True,
            },
            "idempotency_key": "idem-strategy-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["strategy_summary"]["name"] == "Momentum Plus"
    assert preview_response["preview_result"]["strategy_summary"]["param_count"] == 3
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 52
    assert captured_calls[0]["name"] == "Momentum Plus"
    assert captured_calls[0]["strategy_type"] == "momentum"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["name"] == "Momentum Plus"
    assert audit_events[0]["affected_objects"]["strategy_type"] == "momentum"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_strategy_update_ai_config_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeStrategyModule:
        @staticmethod
        def _get(path):
            assert path == "ai-configs/41/"
            return {
                "id": 41,
                "strategy": 7,
                "ai_provider": 3,
                "approval_mode": "conditional",
                "confidence_threshold": 0.75,
            }

    class _FakeClient:
        strategy = _FakeStrategyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_update_ai_strategy_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["config_id"],
            "strategy": 7,
            "approval_mode": kwargs["updates"]["approval_mode"],
            "confidence_threshold": kwargs["updates"]["confidence_threshold"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "update_ai_strategy_config",
        fake_update_ai_strategy_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="strategy.update.ai_config",
        arguments={
            "config_id": 41,
            "updates": {
                "approval_mode": "always",
                "confidence_threshold": 0.9,
            },
            "idempotency_key": "idem-strategy-update-ai-config",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["ai_config_summary"]["strategy"] == 7
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 2
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 41
    assert captured_calls[0]["config_id"] == 41
    assert captured_calls[0]["updates"]["approval_mode"] == "always"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["config_id"] == 41
    assert audit_events[1]["event_type"] == "confirmation_completed"
