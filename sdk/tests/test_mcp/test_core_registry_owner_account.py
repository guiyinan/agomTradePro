# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_account."""

from .core_registry_support import *


def test_account_import_positions_capability_runs_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)
    manifest = CapabilityRegistryLoader().build_registry()["account.import.positions"]
    assert manifest.legacy_tool_names == (
        "import_positions_json",
        "import_positions_csv",
    )

    def fake_import_positions_json(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "portfolio_id": kwargs["portfolio_id"],
            "mode": kwargs.get("mode", "upsert"),
            "dry_run": kwargs.get("dry_run", True),
            "summary": {
                "input_rows": len(kwargs["positions"]),
                "valid_rows": len(kwargs["positions"]),
                "create_count": len(kwargs["positions"]),
                "update_count": 0,
                "close_count": 0,
                "error_count": 0,
            },
            "errors": [],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "import_positions_json",
        fake_import_positions_json,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.import.positions",
        arguments={
            "portfolio_id": 101,
            "positions": [{"asset_code": "510300.SH", "shares": 100, "avg_cost": 3.5}],
            "mode": "upsert",
            "idempotency_key": "idem-account-positions",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["dry_run"] is True
    assert captured_calls[0]["dry_run"] is True

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["dry_run"] is False
    assert captured_calls[1]["dry_run"] is False
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[0]["affected_objects"]["position_count"] == 1


def test_account_import_transactions_capability_runs_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)
    manifest = CapabilityRegistryLoader().build_registry()["account.import.transactions"]
    assert manifest.legacy_tool_names == (
        "import_transactions_json",
        "import_transactions_csv",
    )

    def fake_import_transactions_json(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "portfolio_id": kwargs["portfolio_id"],
            "mode": kwargs.get("mode", "append"),
            "dry_run": kwargs.get("dry_run", True),
            "summary": {
                "input_rows": len(kwargs["transactions"]),
                "valid_rows": len(kwargs["transactions"]),
                "delete_count": 0,
                "create_count": len(kwargs["transactions"]),
                "error_count": 0,
            },
            "errors": [],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "import_transactions_json",
        fake_import_transactions_json,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.import.transactions",
        arguments={
            "portfolio_id": 202,
            "transactions": [
                {
                    "asset_code": "510300.SH",
                    "action": "buy",
                    "shares": 100,
                    "price": 3.52,
                    "traded_at": "2026-07-09",
                }
            ],
            "mode": "append",
            "idempotency_key": "idem-account-transactions",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["dry_run"] is True
    assert captured_calls[0]["dry_run"] is True

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["dry_run"] is False
    assert captured_calls[1]["dry_run"] is False
    assert audit_events[0]["affected_objects"]["transaction_count"] == 1


def test_account_import_capital_flows_capability_runs_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)
    manifest = CapabilityRegistryLoader().build_registry()["account.import.capital_flows"]
    assert manifest.legacy_tool_names == (
        "import_capital_flows_json",
        "import_capital_flows_csv",
    )

    def fake_import_capital_flows_json(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "portfolio_id": kwargs["portfolio_id"],
            "mode": kwargs.get("mode", "append"),
            "dry_run": kwargs.get("dry_run", True),
            "summary": {
                "input_rows": len(kwargs["capital_flows"]),
                "valid_rows": len(kwargs["capital_flows"]),
                "delete_count": 0,
                "create_count": len(kwargs["capital_flows"]),
                "error_count": 0,
            },
            "errors": [],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "import_capital_flows_json",
        fake_import_capital_flows_json,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.import.capital_flows",
        arguments={
            "portfolio_id": 303,
            "capital_flows": [
                {
                    "flow_type": "deposit",
                    "amount": 10000,
                    "flow_date": "2026-07-09",
                    "notes": "seed capital",
                }
            ],
            "mode": "append",
            "idempotency_key": "idem-account-capital-flows",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["dry_run"] is True
    assert captured_calls[0]["dry_run"] is True

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["dry_run"] is False
    assert captured_calls[1]["dry_run"] is False
    assert audit_events[0]["affected_objects"]["capital_flow_count"] == 1


def test_account_import_broker_trades_previews_canonical_side_effects_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAccountModule:
        @staticmethod
        def preview_broker_trades(**kwargs):
            calls.append(("preview_broker_trades", dict(kwargs)))
            return {
                "total_rows": 2,
                "valid_rows": 2,
                "duplicate_rows": 1,
                "error_rows": 0,
                "rows": [
                    {"external_trade_id": "trade-1", "duplicate": False},
                    {"external_trade_id": "trade-2", "duplicate": True},
                ],
                "errors": [],
                "imported_rows": 0,
                "skipped_rows": 0,
                "batch_id": None,
            }

        @staticmethod
        def import_broker_trades(**kwargs):
            calls.append(("import_broker_trades", dict(kwargs)))
            return {
                "total_rows": 2,
                "valid_rows": 2,
                "duplicate_rows": 1,
                "error_rows": 0,
                "rows": [],
                "errors": [],
                "imported_rows": 1,
                "skipped_rows": 1,
                "batch_id": 41,
            }

    class _FakeClient:
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["account.import.broker_trades"]
    assert manifest.legacy_tool_names == (
        "preview_broker_trades_csv",
        "import_broker_trades_csv",
        "preview_broker_trades_json",
        "import_broker_trades_json",
    )
    assert manifest.idempotency == "required"
    assert manifest.requires_confirmation is True

    trades = [
        {
            "traded_at": "2026-05-20T10:00:00+08:00",
            "action": "buy",
            "asset_code": "000001.SZ",
            "shares": 100,
            "price": 10,
            "external_trade_id": "trade-1",
        },
        {
            "traded_at": "2026-05-21T10:00:00+08:00",
            "action": "buy",
            "asset_code": "000001.SZ",
            "shares": 50,
            "price": 11,
            "external_trade_id": "trade-2",
        },
    ]
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.import.broker_trades",
        arguments={
            "portfolio_id": 17,
            "broker_name": "demo",
            "trades": trades,
            "idempotency_key": "idem-account-broker-trades",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"]["expected_import_rows"] == 1
    assert preview["summary"]["will_write_import_batch"] is True
    assert preview["summary"]["will_update_unified_positions"] is True
    assert preview["summary"]["will_match_recommendations_and_execution_links"] is True
    assert preview["summary"]["may_partially_commit_valid_rows"] is True
    assert preview["summary"]["will_execute_external_broker_order"] is False
    assert calls == [
        (
            "preview_broker_trades",
            {
                "portfolio_id": 17,
                "trades": trades,
                "broker_name": "demo",
            },
        )
    ]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["imported_rows"] == 1
    assert resume_response["result"]["skipped_rows"] == 1
    assert calls[1] == (
        "import_broker_trades",
        {
            "portfolio_id": 17,
            "trades": trades,
            "broker_name": "demo",
        },
    )
    assert audit_events[0]["affected_objects"]["portfolio_id"] == 17
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]


def test_account_create_position_previews_ledger_effect_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module
    from agomtradepro.types import Position

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAccountModule:
        @staticmethod
        def get_positions(**kwargs):
            calls.append(("get_positions", dict(kwargs)))
            return [
                Position(
                    asset_code="510300.SH",
                    quantity=100.0,
                    avg_cost=3.0,
                    current_price=3.2,
                    market_value=320.0,
                    profit_loss=20.0,
                )
            ]

        @staticmethod
        def create_position(**kwargs):
            calls.append(("create_position", dict(kwargs)))
            return Position(
                asset_code=kwargs["asset_code"],
                quantity=150.0,
                avg_cost=3.2,
                current_price=3.6,
                market_value=540.0,
                profit_loss=60.0,
            )

    class _FakeClient:
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["account.create.position"]
    assert manifest.legacy_tool_names == ("create_position",)
    assert manifest.idempotency == "required"
    assert manifest.requires_confirmation is True

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.create.position",
        arguments={
            "portfolio_id": 7,
            "asset_code": "510300.SH",
            "quantity": 50,
            "price": 3.6,
            "idempotency_key": "idem-account-create-position",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"]["operation"] == "increase"
    assert preview["summary"]["existing_quantity"] == 100.0
    assert preview["summary"]["resulting_quantity"] == 150.0
    assert preview["summary"]["resulting_avg_cost"] == pytest.approx(3.2)
    assert preview["summary"]["will_record_buy_ledger_entry"] is True
    assert preview["summary"]["will_execute_external_broker_order"] is False
    assert calls == [
        (
            "get_positions",
            {
                "portfolio_id": 7,
                "asset_code": "510300.SH",
                "limit": 100,
            },
        )
    ]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"] == {
        "asset_code": "510300.SH",
        "quantity": 150.0,
        "avg_cost": 3.2,
        "current_price": 3.6,
        "market_value": 540.0,
        "profit_loss": 60.0,
    }
    assert calls[1] == (
        "create_position",
        {
            "portfolio_id": 7,
            "asset_code": "510300.SH",
            "quantity": 50.0,
            "price": 3.6,
        },
    )
    assert audit_events[0]["affected_objects"]["portfolio_id"] == 7
    assert audit_events[0]["affected_objects"]["asset_code"] == "510300.SH"
    assert audit_events[0]["affected_objects"]["quantity"] == 50
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]


def test_account_create_unified_account_previews_owner_scope_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAccountModule:
        @staticmethod
        def list_accounts(**kwargs):
            calls.append(("list_accounts", dict(kwargs)))
            return [
                {
                    "account_id": 3,
                    "account_name": "Existing Real",
                    "account_type": "real",
                }
            ]

        @staticmethod
        def create_account(**kwargs):
            calls.append(("create_account", dict(kwargs)))
            return {
                "account_id": 12,
                "account_name": kwargs["name"],
                "account_type": kwargs["account_type"],
                "initial_capital": "250000.00",
                "current_cash": "250000.00",
                "total_value": "250000.00",
                "auto_trading_enabled": False,
                "is_active": True,
            }

    class _FakeClient:
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["account.create.unified_account"]
    assert manifest.legacy_tool_names == ("create_account",)
    assert manifest.input_schema["required"] == [
        "account_name",
        "account_type",
        "initial_capital",
    ]

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.create.unified_account",
        arguments={
            "account_name": "Primary Real",
            "account_type": "real",
            "initial_capital": 250000.0,
            "max_position_pct": 25.0,
            "stop_loss_pct": 8.0,
            "commission_rate": 0.0002,
            "slippage_rate": 0.0008,
            "idempotency_key": "idem-unified-account-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "account_name": "Primary Real",
        "account_type": "real",
        "initial_capital": 250000.0,
        "max_position_pct": 25.0,
        "stop_loss_pct": 8.0,
        "commission_rate": 0.0002,
        "slippage_rate": 0.0008,
        "auto_trading_enabled": False,
        "matching_name_count": 0,
        "will_create_account": True,
        "will_execute_trade": False,
    }
    assert calls == [
        (
            "list_accounts",
            {
                "account_type": "real",
                "active_only": False,
                "limit": 100,
            },
        )
    ]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["account_id"] == 12
    assert calls[1] == (
        "create_account",
        {
            "name": "Primary Real",
            "initial_capital": 250000.0,
            "account_type": "real",
            "max_position_pct": 25.0,
            "stop_loss_pct": 8.0,
            "commission_rate": 0.0002,
            "slippage_rate": 0.0008,
        },
    )
    assert "preview_only" not in calls[1][1]
    assert "idempotency_key" not in calls[1][1]
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_account_create_trading_cost_config_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _Portfolio:
        name = "Core Portfolio"
        total_value = 1_250_000.0
        cash = 180_000.0

    class _FakeAccountModule:
        @staticmethod
        def get_portfolio(portfolio_id):
            assert portfolio_id == 9
            return _Portfolio()

    class _FakeClient:
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_create_trading_cost_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": 61,
            "portfolio": kwargs["portfolio_id"],
            "commission_rate": kwargs["commission_rate"],
            "min_commission": kwargs["min_commission"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_trading_cost_config",
        fake_create_trading_cost_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.create.trading_cost_config",
        arguments={
            "portfolio_id": 9,
            "commission_rate": 0.0002,
            "min_commission": 3.0,
            "idempotency_key": "idem-account-create-cost",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["portfolio_summary"]["name"] == "Core Portfolio"
    assert preview_response["preview_result"]["trading_cost_summary"]["commission_rate"] == 0.0002
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["portfolio"] == 9
    assert captured_calls[0]["portfolio_id"] == 9
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["portfolio_id"] == 9
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_account_create_trading_cost_config_requires_minimum_commission():
    import agomtradepro_mcp.server as server_module

    response = server_module.CORE_DISPATCHER.call(
        capability_key="account.create.trading_cost_config",
        arguments={
            "portfolio_id": 9,
            "idempotency_key": "idem-account-create-cost-missing-minimum",
        },
    )

    assert response["status"] == "error"
    assert response["error"]["code"] == "missing_required_arguments"
    assert response["missing_required"] == ["min_commission"]


def test_account_update_trading_cost_config_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAccountModule:
        @staticmethod
        def get_trading_cost_config(config_id):
            assert config_id == 61
            return {
                "id": config_id,
                "portfolio": 9,
                "commission_rate": 0.00025,
                "min_commission": 5.0,
                "stamp_duty_rate": 0.001,
                "transfer_fee_rate": 0.00002,
                "is_active": True,
            }

    class _FakeClient:
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_update_trading_cost_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["config_id"],
            "portfolio": 9,
            "commission_rate": kwargs["commission_rate"],
            "min_commission": kwargs["min_commission"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "update_trading_cost_config",
        fake_update_trading_cost_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.update.trading_cost_config",
        arguments={
            "config_id": 61,
            "commission_rate": 0.00018,
            "min_commission": 2.5,
            "idempotency_key": "idem-account-update-cost",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["trading_cost_config_summary"]["portfolio"] == 9
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 2
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 61
    assert captured_calls[0]["config_id"] == 61
    assert captured_calls[0]["commission_rate"] == 0.00018
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["config_id"] == 61
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_account_update_macro_sizing_config_capability_previews_before_version_write(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setattr(server_module.CORE_DISPATCHER, "_role_provider", lambda: "staff")
    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAccountModule:
        @staticmethod
        def get_macro_sizing_config():
            return {
                "version": 4,
                "is_active": True,
                "warning_factor": 0.5,
                "market_temperature_hot_factor": 0.9,
                "market_temperature_overheat_factor": 0.75,
                "market_temperature_extreme_factor": 0.35,
                "block_new_position_on_extreme": True,
                "description": "current",
            }

        @staticmethod
        def update_macro_sizing_config(payload, *, partial=True):
            captured_calls.append({"payload": dict(payload), "partial": partial})
            return {
                "version": 5,
                "is_active": True,
                **payload,
            }

    class _FakeClient:
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    with pytest.raises(
        ValueError,
        match="At least one macro sizing config field must be provided",
    ):
        server_module.INTERNAL_GOVERNED_HANDLERS["account_update_macro_sizing_config"](
            preview_only=True
        )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="account.update.macro_sizing_config",
        arguments={
            "market_temperature_hot_factor": 0.82,
            "market_temperature_overheat_factor": 0.68,
            "description": "governed update",
            "idempotency_key": "idem-account-macro-sizing",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["current_config_summary"]["version"] == 4
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 3
    assert preview_response["preview_result"]["update_summary"]["expected_next_version"] == 5
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["version"] == 5
    assert captured_calls == [
        {
            "payload": {
                "market_temperature_hot_factor": 0.82,
                "market_temperature_overheat_factor": 0.68,
                "description": "governed update",
            },
            "partial": True,
        }
    ]
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[1]["event_type"] == "confirmation_completed"
