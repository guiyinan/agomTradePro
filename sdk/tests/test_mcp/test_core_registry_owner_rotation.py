# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_rotation."""

from .core_registry_support import *


def test_rotation_config_detail_fallback_normalizes_found_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[str] = []

    class _Rotation:
        def get_all_configs(self):
            calls.append("get_all_configs")
            return [
                {
                    "id": 3,
                    "name": "动量轮动策略",
                    "strategy_type": "momentum",
                },
                {
                    "id": 4,
                    "name": "风险平价策略",
                    "strategy_type": "risk_parity",
                },
            ]

    class _Client:
        rotation = _Rotation()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["rotation_read_config_detail"](
        "动量轮动策略"
    ) == {
        "success": True,
        "config": {
            "id": 3,
            "name": "动量轮动策略",
            "strategy_type": "momentum",
        },
        "available_configs": ["动量轮动策略", "风险平价策略"],
        "error": None,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["rotation_read_config_detail"](
        "不存在"
    ) == {
        "success": False,
        "config": None,
        "available_configs": ["动量轮动策略", "风险平价策略"],
        "error": "Rotation config not found: 不存在",
    }
    assert calls == ["get_all_configs", "get_all_configs"]


def test_rotation_create_account_config_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAccountModule:
        @staticmethod
        def get_account(account_id):
            return {
                "id": account_id,
                "account_name": "Growth Account",
                "account_type": "simulated",
                "status": "active",
            }

    class _FakeClient:
        account = _FakeAccountModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_create_account_rotation_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "account": kwargs["account_id"],
            "risk_tolerance": kwargs["risk_tolerance"],
            "is_enabled": kwargs["is_enabled"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_account_rotation_config",
        fake_create_account_rotation_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.create.account_config",
        arguments={
            "account_id": 11,
            "risk_tolerance": "aggressive",
            "is_enabled": True,
            "regime_allocations": {"reflation": {"equity": 0.7, "gold": 0.3}},
            "idempotency_key": "idem-rotation-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["account_summary"]["account_name"] == "Growth Account"
    assert preview_response["preview_result"]["rotation_config_summary"]["regime_count"] == 1
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["account"] == 11
    assert resume_response["result"]["risk_tolerance"] == "aggressive"
    assert captured_calls[0]["account_id"] == 11
    assert captured_calls[0]["risk_tolerance"] == "aggressive"
    assert captured_calls[0]["is_enabled"] is True
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["account_id"] == 11
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_rotation_delete_account_config_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRotationModule:
        @staticmethod
        def get_account_config(config_id):
            return {
                "id": config_id,
                "account": 17,
                "account_name": "Rotation Account",
                "account_type": "simulated",
                "risk_tolerance": "moderate",
                "is_enabled": True,
                "regime_allocations": {"reflation": {"equity": 0.6, "gold": 0.4}},
            }

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_delete_account_rotation_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "config_id": kwargs["config_id"],
            "deleted": True,
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "delete_account_rotation_config",
        fake_delete_account_rotation_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.delete.account_config",
        arguments={
            "config_id": 23,
            "idempotency_key": "idem-rotation-delete",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert (
        preview_response["preview_result"]["account_rotation_config_summary"]["account_name"]
        == "Rotation Account"
    )
    assert (
        preview_response["preview_result"]["account_rotation_config_summary"]["regime_count"] == 1
    )
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["config_id"] == 23
    assert captured_calls[0]["config_id"] == 23
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["config_id"] == 23
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_rotation_update_account_config_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRotationModule:
        @staticmethod
        def get_account_config(config_id):
            return {
                "id": config_id,
                "account": 17,
                "account_name": "Rotation Account",
                "account_type": "simulated",
                "risk_tolerance": "moderate",
                "is_enabled": True,
                "regime_allocations": {"reflation": {"equity": 0.6, "gold": 0.4}},
            }

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_update_account_rotation_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "id": kwargs["config_id"],
            "risk_tolerance": kwargs["payload"]["risk_tolerance"],
            "is_enabled": kwargs["payload"]["is_enabled"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "update_account_rotation_config",
        fake_update_account_rotation_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.update.account_config",
        arguments={
            "config_id": 23,
            "payload": {
                "risk_tolerance": "aggressive",
                "is_enabled": False,
            },
            "partial": True,
            "idempotency_key": "idem-rotation-update",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["update_summary"]["partial"] is True
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 2
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 23
    assert captured_calls[0]["config_id"] == 23
    assert captured_calls[0]["partial"] is True
    assert captured_calls[0]["payload"]["risk_tolerance"] == "aggressive"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["config_id"] == 23
    assert audit_events[0]["affected_objects"]["partial"] is True
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_rotation_apply_template_account_config_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRotationModule:
        @staticmethod
        def get_account_config(config_id):
            return {
                "id": config_id,
                "account": 17,
                "account_name": "Rotation Account",
                "account_type": "simulated",
                "risk_tolerance": "moderate",
                "is_enabled": True,
                "regime_allocations": {"reflation": {"equity": 0.6, "gold": 0.4}},
            }

        @staticmethod
        def list_templates():
            return [
                {
                    "key": "aggressive",
                    "label": "Aggressive",
                    "risk_tolerance": "aggressive",
                }
            ]

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_apply_rotation_template_to_account_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "id": kwargs["config_id"],
            "risk_tolerance": "aggressive",
            "is_enabled": True,
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "apply_rotation_template_to_account_config",
        fake_apply_rotation_template_to_account_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.apply_template.account_config",
        arguments={
            "config_id": 23,
            "template_key": "aggressive",
            "idempotency_key": "idem-rotation-apply-template",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["template_summary"]["template_found"] is True
    assert preview_response["preview_result"]["template_summary"]["template_key"] == "aggressive"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 23
    assert captured_calls[0]["config_id"] == 23
    assert captured_calls[0]["template_key"] == "aggressive"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["config_id"] == 23
    assert audit_events[0]["affected_objects"]["template_key"] == "aggressive"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_rotation_create_asset_previews_global_code_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module
    from agomtradepro import NotFoundError

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRotationModule:
        @staticmethod
        def get_asset(asset_code):
            calls.append(("get_asset", asset_code))
            raise NotFoundError()

        @staticmethod
        def create_asset(payload):
            calls.append(("create_asset", dict(payload)))
            return {"id": 17, **payload}

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["rotation.create.asset"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("create_rotation_asset",)
    assert manifest.idempotency == "required"

    arguments = {
        "code": " 510300 ",
        "name": " 沪深300ETF ",
        "category": "EQUITY",
        "description": " 宽基指数资产 ",
        "underlying_index": " 000300.SH ",
        "currency": "cny",
        "is_active": True,
        "idempotency_key": "idem-rotation-create-asset",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.create.asset",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["operation"] == "create"
    assert preview["summary"] == {
        "code": "510300",
        "name": "沪深300ETF",
        "category": "equity",
        "description": "宽基指数资产",
        "underlying_index": "000300.SH",
        "currency": "CNY",
        "is_active": True,
        "global_catalog": True,
        "existing_code_count": 0,
        "will_create_asset": True,
        "will_execute_trade": False,
    }
    assert calls == [("get_asset", "510300")]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[1] == (
        "create_asset",
        {
            "code": "510300",
            "name": "沪深300ETF",
            "category": "equity",
            "description": "宽基指数资产",
            "underlying_index": "000300.SH",
            "currency": "CNY",
            "is_active": True,
        },
    )
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_rotation_create_asset_rejects_inactive_duplicate_during_preview(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []

    class _FakeRotationModule:
        @staticmethod
        def get_asset(asset_code):
            calls.append(("get_asset", asset_code))
            return {
                "id": 17,
                "code": asset_code,
                "name": "旧资产",
                "category": "equity",
                "is_active": False,
            }

        @staticmethod
        def create_asset(payload):
            calls.append(("create_asset", dict(payload)))
            return payload

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.create.asset",
        arguments={
            "code": "510300",
            "name": "沪深300ETF",
            "category": "equity",
            "idempotency_key": "idem-rotation-create-asset-duplicate",
        },
    )

    assert response["status"] == "error"
    assert "already exists (inactive)" in response["error"]["message"]
    assert calls == [("get_asset", "510300")]


def test_rotation_update_asset_previews_changes_before_partial_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRotationModule:
        @staticmethod
        def get_asset(asset_code):
            calls.append(("get_asset", asset_code))
            return {
                "id": 17,
                "code": asset_code,
                "name": "旧名称",
                "category": "equity",
                "description": "",
                "underlying_index": "",
                "currency": "CNY",
                "is_active": False,
            }

        @staticmethod
        def update_asset(asset_code, payload, partial=False):
            calls.append(("update_asset", asset_code, dict(payload), partial))
            return {
                "id": 17,
                "code": asset_code,
                **payload,
            }

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["rotation.update.asset"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("update_rotation_asset",)
    assert manifest.idempotency == "required"
    assert "partial" not in manifest.input_schema["properties"]

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.update.asset",
        arguments={
            "asset_code": " 510300 ",
            "name": " 沪深300ETF ",
            "underlying_index": " 000300.SH ",
            "currency": "cny",
            "is_active": True,
            "idempotency_key": "idem-rotation-update-asset",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["operation"] == "update"
    assert preview["requested_updates"] == {
        "name": "沪深300ETF",
        "underlying_index": "000300.SH",
        "currency": "CNY",
        "is_active": True,
    }
    assert preview["summary"] == {
        "asset_code": "510300",
        "global_catalog": True,
        "changed_field_count": 3,
        "changed_fields": ["is_active", "name", "underlying_index"],
        "current_is_active": False,
        "target_is_active": True,
        "will_reactivate": True,
        "will_deactivate": False,
        "will_execute_trade": False,
    }
    assert calls == [("get_asset", "510300")]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[1] == (
        "update_asset",
        "510300",
        {
            "name": "沪深300ETF",
            "underlying_index": "000300.SH",
            "currency": "CNY",
            "is_active": True,
        },
        True,
    )
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_rotation_update_asset_rejects_no_effective_change_during_preview(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []

    class _FakeRotationModule:
        @staticmethod
        def get_asset(asset_code):
            calls.append(("get_asset", asset_code))
            return {
                "id": 17,
                "code": asset_code,
                "name": "沪深300ETF",
                "category": "equity",
                "currency": "CNY",
                "is_active": True,
            }

        @staticmethod
        def update_asset(asset_code, payload, partial=False):
            calls.append(("update_asset", asset_code, dict(payload), partial))
            return payload

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.update.asset",
        arguments={
            "asset_code": "510300",
            "name": "沪深300ETF",
            "currency": "CNY",
            "idempotency_key": "idem-rotation-update-asset-no-change",
        },
    )

    assert response["status"] == "error"
    assert "no effective changes" in response["error"]["message"]
    assert calls == [("get_asset", "510300")]


def test_rotation_delete_asset_previews_soft_delete_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRotationModule:
        @staticmethod
        def get_asset(asset_code):
            calls.append(("get_asset", asset_code))
            return {
                "id": 17,
                "code": asset_code,
                "name": "沪深300ETF",
                "category": "equity",
                "currency": "CNY",
                "is_active": True,
            }

        @staticmethod
        def delete_asset(asset_code):
            calls.append(("delete_asset", asset_code))
            return {
                "status": "soft_deleted",
                "code": asset_code,
                "is_active": False,
            }

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["rotation.delete.asset"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("delete_rotation_asset",)
    assert manifest.idempotency == "required"
    assert "hard" not in manifest.input_schema["properties"]

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.delete.asset",
        arguments={
            "asset_code": " 510300 ",
            "idempotency_key": "idem-rotation-delete-asset",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["operation"] == "soft_delete"
    assert preview["summary"] == {
        "asset_code": "510300",
        "asset_name": "沪深300ETF",
        "category": "equity",
        "global_catalog": True,
        "current_is_active": True,
        "target_is_active": False,
        "will_soft_delete": True,
        "will_physically_delete": False,
        "will_fetch_prices": False,
        "will_generate_signal": False,
        "will_execute_trade": False,
    }
    assert calls == [("get_asset", "510300")]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[1] == ("delete_asset", "510300")
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_rotation_delete_asset_rejects_inactive_target_during_preview(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []

    class _FakeRotationModule:
        @staticmethod
        def get_asset(asset_code):
            calls.append(("get_asset", asset_code))
            return {
                "id": 17,
                "code": asset_code,
                "name": "沪深300ETF",
                "category": "equity",
                "is_active": False,
            }

        @staticmethod
        def delete_asset(asset_code):
            calls.append(("delete_asset", asset_code))
            return {"code": asset_code}

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.delete.asset",
        arguments={
            "asset_code": "510300",
            "idempotency_key": "idem-rotation-delete-asset-inactive",
        },
    )

    assert response["status"] == "error"
    assert "already inactive" in response["error"]["message"]
    assert calls == [("get_asset", "510300")]


def test_rotation_import_default_assets_uses_canonical_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRotationModule:
        @staticmethod
        def preview_default_asset_import():
            calls.append(("preview_default_asset_import", {}))
            return {
                "created": 15,
                "reactivated": 1,
                "updated": 1,
                "unchanged": 1,
                "existing": 2,
                "total_defaults": 18,
                "items": [
                    {
                        "code": "510300",
                        "action": "reactivate",
                        "changed_fields": ["is_active", "name"],
                    }
                ],
            }

        @staticmethod
        def import_default_assets():
            calls.append(("import_default_assets", {}))
            return {
                "created": 15,
                "reactivated": 1,
                "updated": 1,
                "unchanged": 1,
                "existing": 2,
                "total_defaults": 18,
            }

    class _FakeClient:
        rotation = _FakeRotationModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["rotation.import.default_assets"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("import_default_rotation_assets",)
    assert manifest.idempotency == "required"

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="rotation.import.default_assets",
        arguments={
            "idempotency_key": "idem-rotation-import-default-assets",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["operation"] == "import_defaults"
    assert preview["summary"] == {
        "global_catalog": True,
        "created": 15,
        "reactivated": 1,
        "updated": 1,
        "unchanged": 1,
        "existing": 2,
        "total_defaults": 18,
        "will_physically_delete": False,
        "will_fetch_prices": False,
        "will_generate_signal": False,
        "will_execute_trade": False,
    }
    assert calls == [("preview_default_asset_import", {})]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[1] == ("import_default_assets", {})
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"
