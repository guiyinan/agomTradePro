# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_beta_gate."""

from .core_registry_support import *


def test_beta_gate_batch_evaluation_fallback_uses_formal_sdk_contract(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[dict] = []

    class _FakeBetaGateModule:
        @staticmethod
        def test_gate(payload):
            calls.append(dict(payload))
            return {
                "success": True,
                "config": {
                    "config_id": "aggressive-v1",
                    "risk_profile": "aggressive",
                    "version": 1,
                },
                "query": dict(payload),
                "results": [
                    {
                        "asset_code": payload["asset_codes"][0],
                        "passed": True,
                    }
                ],
                "summary": {
                    "total": len(payload["asset_codes"]),
                    "passed": len(payload["asset_codes"]),
                    "blocked": 0,
                },
            }

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(beta_gate=_FakeBetaGateModule()),
    )

    fallback = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["beta_gate_compute_batch_evaluation"]
    result = fallback(
        asset_codes=[" 000001.SH "],
        asset_class=" equity ",
        current_regime="Recovery",
        regime_confidence=0.6,
        policy_level=0,
        risk_profile="AGGRESSIVE",
    )

    assert calls == [
        {
            "asset_codes": ["000001.SH"],
            "asset_class": "equity",
            "current_regime": "Recovery",
            "regime_confidence": 0.6,
            "policy_level": 0,
            "risk_profile": "aggressive",
        }
    ]
    assert result["config"]["config_id"] == "aggressive-v1"
    assert result["query"] == calls[0]
    assert result["summary"]["passed"] == 1


def test_beta_gate_batch_evaluation_fallback_rejects_duplicate_assets():
    import agomtradepro_mcp.server as server_module

    fallback = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["beta_gate_compute_batch_evaluation"]

    with pytest.raises(ValueError, match="must not contain duplicates"):
        fallback(
            asset_codes=["000001.SH", "000001.SH"],
            asset_class="equity",
            current_regime="Recovery",
            regime_confidence=0.6,
            policy_level=0,
            risk_profile="balanced",
        )


def test_beta_gate_create_config_previews_catalog_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)
    configs = [
        {
            "config_id": "balanced-v1",
            "risk_profile": "balanced",
            "version": 4,
            "is_active": True,
        },
        {
            "config_id": "conservative-v1",
            "risk_profile": "conservative",
            "version": 5,
            "is_active": True,
        },
    ]

    class _FakeBetaGateModule:
        @staticmethod
        def list_configs(*, active_only=True):
            calls.append(("list_configs", active_only))
            return configs

        @staticmethod
        def create_config(payload):
            calls.append(("create_config", dict(payload)))
            return {
                "success": True,
                "result": {
                    "config_id": payload["config_id"],
                    "risk_profile": payload["risk_profile"],
                    "version": 6,
                    "is_active": True,
                },
            }

    class _FakeClient:
        beta_gate = _FakeBetaGateModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["beta_gate.create.config"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("create_beta_gate_config",)
    assert manifest.idempotency == "required"

    arguments = {
        "config_id": " balanced-v2 ",
        "risk_profile": "BALANCED",
        "allowed_regimes": ["Recovery", "Deflation"],
        "min_confidence": 0.6,
        "max_policy_level": 1,
        "veto_on_p3": True,
        "max_total_position": 80.0,
        "max_single_position": 15.0,
        "idempotency_key": "idem-beta-gate-create-config",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="beta_gate.create.config",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "config_id": "balanced-v2",
        "config_id_source": "caller",
        "risk_profile": "balanced",
        "expected_version": 6,
        "replaced_active_config": configs[0],
        "will_create_config": True,
        "will_activate_new_config": True,
        "will_deactivate_same_profile_active_config": True,
        "will_change_existing_decisions": False,
        "will_execute_trade": False,
        "target_constraints": {
            "allowed_regimes": ["Recovery", "Deflation"],
            "min_confidence": 0.6,
            "max_policy_level": 1,
            "veto_on_p3": True,
            "max_total_position": 80.0,
            "max_single_position": 15.0,
        },
    }
    assert calls == [("list_configs", False)]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[1] == (
        "create_config",
        {
            "config_id": "balanced-v2",
            "risk_profile": "balanced",
            "allowed_regimes": ["Recovery", "Deflation"],
            "min_confidence": 0.6,
            "max_policy_level": 1,
            "veto_on_p3": True,
            "max_total_position": 80.0,
            "max_single_position": 15.0,
        },
    )
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_beta_gate_create_config_rejects_duplicate_id_during_preview(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []

    class _FakeBetaGateModule:
        @staticmethod
        def list_configs(*, active_only=True):
            calls.append(("list_configs", active_only))
            return [
                {
                    "config_id": "balanced-v1",
                    "risk_profile": "balanced",
                    "version": 4,
                    "is_active": False,
                }
            ]

        @staticmethod
        def create_config(payload):
            calls.append(("create_config", dict(payload)))
            return payload

    class _FakeClient:
        beta_gate = _FakeBetaGateModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    response = server_module.CORE_DISPATCHER.call(
        capability_key="beta_gate.create.config",
        arguments={
            "config_id": "balanced-v1",
            "risk_profile": "balanced",
            "idempotency_key": "idem-beta-gate-create-config-duplicate",
        },
    )

    assert response["status"] == "error"
    assert "config_id already exists" in response["error"]["message"]
    assert calls == [("list_configs", False)]


def test_beta_gate_rollback_config_previews_activation_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)
    target = {
        "config_id": "balanced-history",
        "risk_profile": "balanced",
        "version": 2,
        "is_active": False,
        "is_expired": False,
        "effective_date": "2026-01-01",
        "expires_at": None,
    }
    current = {
        "config_id": "balanced-current",
        "risk_profile": "balanced",
        "version": 5,
        "is_active": True,
    }

    class _FakeBetaGateModule:
        @staticmethod
        def get_config(config_id):
            calls.append(("get_config", config_id))
            return {"success": True, "result": target}

        @staticmethod
        def list_configs(*, active_only=True):
            calls.append(("list_configs", active_only))
            return [current]

        @staticmethod
        def rollback_config(config_id):
            calls.append(("rollback_config", config_id))
            return {
                "success": True,
                "result": {
                    **target,
                    "is_active": True,
                    "effective_date": "2026-07-12",
                },
            }

    class _FakeClient:
        beta_gate = _FakeBetaGateModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["beta_gate.rollback.config"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("rollback_beta_gate_config",)
    assert manifest.idempotency == "required"

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="beta_gate.rollback.config",
        arguments={
            "config_id": " balanced-history ",
            "idempotency_key": "idem-beta-gate-rollback-config",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["target_config"] == target
    assert preview["current_active_config"] == current
    assert preview["summary"] == {
        "target_config_id": "balanced-history",
        "target_version": 2,
        "risk_profile": "balanced",
        "current_active_config_id": "balanced-current",
        "current_active_version": 5,
        "will_deactivate_current": True,
        "will_activate_target": True,
        "will_create_new_version": False,
        "will_update_effective_date": True,
        "will_change_existing_decisions": False,
        "will_execute_trade": False,
    }
    assert calls == [
        ("get_config", "balanced-history"),
        ("list_configs", True),
    ]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[2] == ("rollback_config", "balanced-history")
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_beta_gate_rollback_config_rejects_expired_target_during_preview(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []

    class _FakeBetaGateModule:
        @staticmethod
        def get_config(config_id):
            calls.append(("get_config", config_id))
            return {
                "success": True,
                "result": {
                    "config_id": config_id,
                    "risk_profile": "balanced",
                    "version": 2,
                    "is_active": False,
                    "is_expired": True,
                },
            }

        @staticmethod
        def list_configs(*, active_only=True):
            calls.append(("list_configs", active_only))
            return []

        @staticmethod
        def rollback_config(config_id):
            calls.append(("rollback_config", config_id))
            return {"config_id": config_id}

    class _FakeClient:
        beta_gate = _FakeBetaGateModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    response = server_module.CORE_DISPATCHER.call(
        capability_key="beta_gate.rollback.config",
        arguments={
            "config_id": "balanced-history",
            "idempotency_key": "idem-beta-gate-rollback-config-expired",
        },
    )

    assert response["status"] == "error"
    assert "config balanced-history is expired" in response["error"]["message"]
    assert calls == [("get_config", "balanced-history")]
