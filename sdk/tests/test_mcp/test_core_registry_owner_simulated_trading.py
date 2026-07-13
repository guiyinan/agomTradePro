# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_simulated_trading."""

from .core_registry_support import *


def test_simulated_trading_read_fallbacks_normalize_sdk_results(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    def list_accounts(*, account_type=None, active_only=True):
        calls.append(("list_accounts", (account_type, active_only)))
        return [{"account_id": 7, "account_type": "simulated"}]

    def get_account(account_id):
        calls.append(("get_account", account_id))
        return {"account_id": account_id, "account_name": "研究模拟账户"}

    def get_account_positions(account_id):
        calls.append(("get_account_positions", account_id))
        return [{"asset_code": "510300.SH"}]

    def get_account_performance(*, account_id, start_date=None, end_date=None):
        calls.append(
            (
                "get_account_performance",
                (account_id, start_date, end_date),
            )
        )
        return {"returns": {"twr": 0.032}}

    def list_daily_inspections(*, account_id, limit, inspection_date):
        calls.append(
            (
                "list_daily_inspections",
                (account_id, limit, inspection_date),
            )
        )
        return {
            "success": True,
            "count": 1,
            "reports": [{"report_id": 3}],
        }

    client = SimpleNamespace(
        account=SimpleNamespace(
            list_accounts=list_accounts,
            get_account=get_account,
            get_account_positions=get_account_positions,
            get_account_performance=get_account_performance,
        ),
        simulated_trading=SimpleNamespace(
            list_daily_inspections=list_daily_inspections,
        ),
    )
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: client)

    account_list = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_account_list"](
        active_only=True,
        account_type="simulated",
    )
    account_detail = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_account_detail"](7)
    positions = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_account_positions"](7)
    performance = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_account_performance"](
        7,
        start_date="2026-07-01",
        end_date="2026-07-10",
    )
    inspections = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS[
        "simulated_trading_read_daily_inspection_list"
    ](
        7,
        limit=10,
        inspection_date="2026-07-10",
    )

    assert account_list["total_count"] == 1
    assert account_list["query"]["account_type"] == "simulated"
    assert account_detail["account"]["account_name"] == "研究模拟账户"
    assert positions == {
        "account_id": 7,
        "positions": [{"asset_code": "510300.SH"}],
        "total_count": 1,
    }
    assert performance["mode"] == "date_range"
    assert performance["performance"]["returns"]["twr"] == 0.032
    assert inspections["reports"] == [{"report_id": 3}]
    assert inspections["query"]["inspection_date"] == "2026-07-10"
    assert (
        "list_daily_inspections",
        (7, 10, date(2026, 7, 10)),
    ) in calls

    with pytest.raises(ValueError, match="provided together"):
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_account_performance"](
            7,
            start_date="2026-07-01",
        )


def test_trading_submit_simulated_order_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            return {
                "id": account_id,
                "name": "Alpha Sim",
                "status": "active",
                "account_type": "simulated",
                "total_value": 1050000.0,
                "available_cash": 250000.0,
            }

        @staticmethod
        def get_positions(account_id, asset_code=None):
            assert account_id == 7
            assert asset_code == "510300.SH"
            return [
                {
                    "asset_code": "510300.SH",
                    "quantity": 1200,
                    "avg_cost": 3.82,
                }
            ]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_execute_simulated_trade(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "order_id": "order-7001",
            "message": "trade executed",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "execute_simulated_trade",
        fake_execute_simulated_trade,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.submit.simulated_order",
        arguments={
            "account_id": 7,
            "asset_code": "510300.SH",
            "side": "BUY",
            "quantity": 1500,
            "price": 4.05,
            "idempotency_key": "idem-simulated-order",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["account_summary"]["account_name"] == "Alpha Sim"
    assert preview_response["preview_result"]["position_summary"]["current_quantity"] == 1200
    assert preview_response["preview_result"]["trade_summary"]["side"] == "buy"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["order_id"] == "order-7001"
    assert captured_calls[0]["account_id"] == 7
    assert captured_calls[0]["asset_code"] == "510300.SH"
    assert captured_calls[0]["side"] == "buy"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["account_id"] == 7
    assert audit_events[0]["affected_objects"]["asset_code"] == "510300.SH"
    assert audit_events[0]["affected_objects"]["side"] == "BUY"
    assert audit_events[0]["affected_objects"]["quantity"] == 1500
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_trading_close_simulated_position_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            return {
                "id": account_id,
                "name": "Alpha Sim",
                "status": "active",
                "account_type": "simulated",
            }

        @staticmethod
        def get_positions(account_id, asset_code=None):
            assert account_id == 7
            assert asset_code == "510300.SH"
            return [
                {
                    "asset_code": "510300.SH",
                    "quantity": 1200,
                    "avg_cost": 3.82,
                }
            ]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_close_simulated_position(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "order_id": "close-7001",
            "message": "position closed",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "close_simulated_position",
        fake_close_simulated_position,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments={
            "account_id": 7,
            "asset_code": "510300.SH",
            "idempotency_key": "idem-simulated-close",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["account_summary"]["account_name"] == "Alpha Sim"
    assert preview_response["preview_result"]["position_summary"]["current_quantity"] == 1200
    assert preview_response["preview_result"]["target_status"] == "closed"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["order_id"] == "close-7001"
    assert captured_calls[0]["account_id"] == 7
    assert captured_calls[0]["asset_code"] == "510300.SH"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["account_id"] == 7
    assert audit_events[0]["affected_objects"]["asset_code"] == "510300.SH"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_trading_reset_simulated_account_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            return {
                "id": account_id,
                "name": "Alpha Sim",
                "status": "active",
                "account_type": "simulated",
                "initial_capital": 1000000.0,
                "total_value": 1050000.0,
            }

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_reset_simulated_account(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "account_id": kwargs["account_id"],
            "new_initial_capital": kwargs["new_initial_capital"],
            "message": "account reset",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "reset_simulated_account",
        fake_reset_simulated_account,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.reset.simulated_account",
        arguments={
            "account_id": 7,
            "new_initial_capital": 1200000.0,
            "idempotency_key": "idem-simulated-reset",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["account_summary"]["account_name"] == "Alpha Sim"
    assert (
        preview_response["preview_result"]["reset_summary"]["current_initial_capital"] == 1000000.0
    )
    assert preview_response["preview_result"]["reset_summary"]["new_initial_capital"] == 1200000.0
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["account_id"] == 7
    assert resume_response["result"]["new_initial_capital"] == 1200000.0
    assert captured_calls[0]["account_id"] == 7
    assert captured_calls[0]["new_initial_capital"] == 1200000.0
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["account_id"] == 7
    assert audit_events[0]["affected_objects"]["new_initial_capital"] == 1200000.0
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_trading_delete_simulated_account_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            return {
                "id": account_id,
                "name": "Alpha Sim",
                "status": "active",
                "account_type": "simulated",
                "is_active": True,
                "initial_capital": 1000000.0,
                "current_cash": 850000.0,
                "total_value": 1050000.0,
            }

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_delete_simulated_account(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "account_id": kwargs["account_id"],
            "account_name": "Alpha Sim",
            "message": "account deleted",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "delete_simulated_account",
        fake_delete_simulated_account,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.delete.simulated_account",
        arguments={
            "account_id": 7,
            "idempotency_key": "idem-simulated-delete",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["account_summary"]["account_name"] == "Alpha Sim"
    assert preview_response["preview_result"]["target_status"] == "deleted"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["account_id"] == 7
    assert resume_response["result"]["success"] is True
    assert captured_calls[0]["account_id"] == 7
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["account_id"] == 7
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_trading_delete_simulated_account_batch_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            if account_id == 404:
                from agomtradepro.exceptions import NotFoundError

                raise NotFoundError(
                    response={"error": "account not found"},
                )
            return {
                "id": account_id,
                "name": f"Alpha Sim {account_id}",
                "status": "active",
                "account_type": "simulated",
                "is_active": True,
                "initial_capital": 1000000.0,
                "current_cash": 850000.0,
                "total_value": 1050000.0,
            }

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_batch_delete_simulated_accounts(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "requested_count": len(kwargs["account_ids"]),
            "deleted_count": 2,
            "deleted_account_ids": [7, 9],
            "deleted_account_names": ["Alpha Sim 7", "Alpha Sim 9"],
            "failed": [{"account_id": 404, "error": "account not found"}],
            "message": "batch delete completed",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "batch_delete_simulated_accounts",
        fake_batch_delete_simulated_accounts,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.delete.simulated_account_batch",
        arguments={
            "account_ids": [7, 404, 9],
            "idempotency_key": "idem-simulated-batch-delete",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["delete_summary"]["requested_count"] == 3
    assert preview_response["preview_result"]["delete_summary"]["deletable_count"] == 2
    assert preview_response["preview_result"]["delete_summary"]["failed_count"] == 1
    assert preview_response["preview_result"]["partial_failure_risk"] is True
    assert preview_response["preview_result"]["failed"][0]["account_id"] == 404
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["deleted_count"] == 2
    assert resume_response["result"]["success"] is True
    assert captured_calls[0]["account_ids"] == [7, 404, 9]
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["account_count"] == 3
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_trading_create_simulated_account_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def list_accounts(status=None, account_type=None, limit=100):
            return [
                {
                    "id": 2,
                    "name": "Existing Sim",
                    "status": status,
                    "account_type": account_type,
                },
                {
                    "id": 3,
                    "name": "Growth Lab",
                    "status": status,
                    "account_type": account_type,
                },
            ]

        @staticmethod
        def create_account(
            name,
            initial_capital,
            start_date,
            account_type="simulated",
            max_position_pct=20.0,
            stop_loss_pct=10.0,
            commission_rate=0.0003,
            slippage_rate=0.001,
        ):
            captured_calls.append(
                {
                    "name": name,
                    "initial_capital": initial_capital,
                    "start_date": start_date.isoformat() if start_date else None,
                    "account_type": account_type,
                    "max_position_pct": max_position_pct,
                    "stop_loss_pct": stop_loss_pct,
                    "commission_rate": commission_rate,
                    "slippage_rate": slippage_rate,
                }
            )
            return {
                "id": 12,
                "account_name": name,
                "account_type": account_type,
                "initial_capital": initial_capital,
                "message": "account created",
            }

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.create.simulated_account",
        arguments={
            "account_name": "Growth Lab",
            "initial_capital": 250000.0,
            "max_position_pct": 25.0,
            "stop_loss_pct": 8.0,
            "commission_rate": 0.0002,
            "slippage_rate": 0.0008,
            "idempotency_key": "idem-simulated-account-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["create_summary"]["account_name"] == "Growth Lab"
    assert preview_response["preview_result"]["create_summary"]["matching_active_name_count"] == 1
    assert preview_response["preview_result"]["create_summary"]["max_position_pct"] == 25.0
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 12
    assert resume_response["result"]["account_name"] == "Growth Lab"
    assert captured_calls[0]["name"] == "Growth Lab"
    assert captured_calls[0]["start_date"] is None
    assert captured_calls[0]["account_type"] == "simulated"
    assert audit_events[0]["affected_objects"]["account_name"] == "Growth Lab"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_trading_start_simulated_auto_trading_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            return {
                "id": account_id,
                "name": f"Alpha Sim {account_id}",
                "status": "active",
                "account_type": "simulated",
            }

        @staticmethod
        def list_accounts(status=None, account_type=None, limit=100):
            return [
                {
                    "id": 7,
                    "name": "Alpha Sim 7",
                    "status": status,
                    "account_type": account_type,
                }
            ]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_run_simulated_auto_trading(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "trade_date": kwargs["trade_date"],
            "account_ids": kwargs["account_ids"],
            "message": "auto trading started",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "run_simulated_auto_trading",
        fake_run_simulated_auto_trading,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.start.simulated_auto_trading",
        arguments={
            "trade_date": "2026-03-21",
            "account_ids": [7],
            "idempotency_key": "idem-simulated-auto-trading",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["trade_date"] == "2026-03-21"
    assert (
        preview_response["preview_result"]["account_scope_summary"]["requested_account_count"] == 1
    )
    assert (
        preview_response["preview_result"]["account_scope_summary"]["resolved_account_count"] == 1
    )
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["trade_date"] == "2026-03-21"
    assert resume_response["result"]["account_ids"] == [7]
    assert captured_calls[0]["trade_date"] == "2026-03-21"
    assert captured_calls[0]["account_ids"] == [7]
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["trade_date"] == "2026-03-21"
    assert audit_events[0]["affected_objects"]["account_count"] == 1
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_trading_run_simulated_daily_inspection_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            return {
                "id": account_id,
                "name": "Alpha Sim",
                "status": "active",
                "account_type": "simulated",
            }

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_run_simulated_daily_inspection(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "account_id": kwargs["account_id"],
            "inspection_date": kwargs["inspection_date"],
            "message": "inspection completed",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "run_simulated_daily_inspection",
        fake_run_simulated_daily_inspection,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.run.simulated_daily_inspection",
        arguments={
            "account_id": 7,
            "strategy_id": 2,
            "inspection_date": "2026-03-21",
            "auto_create_proposal": True,
            "idempotency_key": "idem-simulated-inspection",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["account_summary"]["account_name"] == "Alpha Sim"
    assert preview_response["preview_result"]["inspection_scope_summary"]["strategy_id"] == 2
    assert (
        preview_response["preview_result"]["inspection_scope_summary"]["auto_create_proposal"]
        is True
    )
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["account_id"] == 7
    assert resume_response["result"]["inspection_date"] == "2026-03-21"
    assert captured_calls[0]["account_id"] == 7
    assert captured_calls[0]["strategy_id"] == 2
    assert captured_calls[0]["inspection_date"] == "2026-03-21"
    assert captured_calls[0]["auto_create_proposal"] is True
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["account_id"] == 7
    assert audit_events[0]["affected_objects"]["strategy_id"] == 2
    assert audit_events[0]["affected_objects"]["inspection_date"] == "2026-03-21"
    assert audit_events[0]["affected_objects"]["auto_create_proposal"] is True
    assert audit_events[1]["event_type"] == "confirmation_completed"
