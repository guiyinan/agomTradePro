# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_config_center."""

from .core_registry_support import *


def test_config_center_read_manifests_require_staff_role():
    registry = CapabilityRegistryLoader().build_registry()
    capability_keys = {
        "config_center.read.capability_catalog",
        "config_center.read.qlib_runtime",
        "config_center.read.qlib_training_profiles",
        "config_center.read.alpha_universe_catalog",
        "config_center.read.alpha_universe_members",
        "config_center.read.qlib_training_runs",
        "config_center.read.qlib_training_run_detail",
    }

    assert {
        capability_key: registry[capability_key].required_roles
        for capability_key in capability_keys
    } == dict.fromkeys(capability_keys, ("staff",))


def test_config_center_update_runtime_setting_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeConfigCenterModule:
        @staticmethod
        def get_qlib_runtime():
            return {
                "configured": True,
                "enabled": True,
                "provider_uri": "/tmp/qlib/cn_data",
                "region": "CN",
                "model_root": "/tmp/qlib/models",
                "default_universe": "csi300",
                "default_feature_set_id": "v1",
                "default_label_id": "return_5d",
                "train_queue_name": "qlib_train",
                "infer_queue_name": "qlib_infer",
                "allow_auto_activate": False,
                "alpha_fixed_provider": "qlib",
                "alpha_pool_mode": "strict_valuation",
            }

    class _FakeClient:
        config_center = _FakeConfigCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_update_qlib_runtime_config(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "configured": True,
            "enabled": kwargs["enabled"],
            "provider_uri": kwargs["provider_uri"],
            "region": kwargs["region"],
            "default_universe": kwargs["default_universe"],
            "alpha_pool_mode": kwargs["alpha_pool_mode"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "update_qlib_runtime_config",
        fake_update_qlib_runtime_config,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="config_center.update.runtime_setting",
        arguments={
            "enabled": False,
            "provider_uri": "/tmp/qlib/next_cn_data",
            "region": "US",
            "default_universe": "csi500",
            "alpha_pool_mode": "market",
            "idempotency_key": "idem-config-runtime-update",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["runtime_config_summary"]["provider_uri"] == (
        "/tmp/qlib/cn_data"
    )
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 5
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["enabled"] is False
    assert resume_response["result"]["default_universe"] == "csi500"
    assert captured_calls[0]["enabled"] is False
    assert captured_calls[0]["provider_uri"] == "/tmp/qlib/next_cn_data"
    assert captured_calls[0]["region"] == "US"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_config_center_update_data_center_provider_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_provider(provider_id):
            assert provider_id == 7
            return {
                "id": provider_id,
                "name": "Tushare Proxy",
                "source_type": "tushare",
                "priority": 1,
                "is_active": True,
                "http_url": "https://proxy.example.com",
                "api_endpoint": "",
                "description": "primary provider",
                "extra_config": {"timeout": 30, "region": "cn"},
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_update_data_center_provider(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["provider_id"],
            "name": kwargs["name"],
            "priority": kwargs["priority"],
            "is_active": kwargs["is_active"],
            "http_url": kwargs["http_url"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "update_data_center_provider",
        fake_update_data_center_provider,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="config_center.update.data_center_provider",
        arguments={
            "provider_id": 7,
            "name": "Tushare Proxy V2",
            "priority": 2,
            "is_active": False,
            "http_url": "https://proxy-2.example.com",
            "idempotency_key": "idem-config-provider-update",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["provider_summary"]["name"] == "Tushare Proxy"
    assert preview_response["preview_result"]["provider_summary"]["extra_config_keys"] == [
        "region",
        "timeout",
    ]
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 4
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 7
    assert resume_response["result"]["name"] == "Tushare Proxy V2"
    assert captured_calls[0]["provider_id"] == 7
    assert captured_calls[0]["priority"] == 2
    assert captured_calls[0]["is_active"] is False
    assert captured_calls[0]["http_url"] == "https://proxy-2.example.com"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["provider_id"] == 7
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_config_center_create_data_center_provider_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_create_data_center_provider(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": 21,
            "name": kwargs["name"],
            "source_type": kwargs["source_type"],
            "priority": kwargs["priority"],
            "is_active": kwargs["is_active"],
            "http_url": kwargs["http_url"],
            "api_endpoint": kwargs["api_endpoint"],
            "description": kwargs["description"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_data_center_provider",
        fake_create_data_center_provider,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="config_center.create.data_center_provider",
        arguments={
            "name": "tushare-main",
            "source_type": "tushare",
            "priority": 10,
            "is_active": True,
            "http_url": "https://example.invalid/tushare",
            "api_endpoint": "/pro",
            "api_key": "ts-key",
            "api_secret": "ts-secret",
            "extra_config": {"timeout": 10, "region": "cn"},
            "description": "main provider",
            "idempotency_key": "idem-dc-provider-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["create_summary"]["name"] == "tushare-main"
    assert preview_response["preview_result"]["create_summary"]["source_type"] == "tushare"
    assert preview_response["preview_result"]["create_summary"]["has_api_key"] is True
    assert preview_response["preview_result"]["create_summary"]["has_api_secret"] is True
    assert preview_response["preview_result"]["create_summary"]["extra_config_keys"] == [
        "region",
        "timeout",
    ]
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 21
    assert resume_response["result"]["name"] == "tushare-main"
    assert captured_calls[0]["name"] == "tushare-main"
    assert captured_calls[0]["source_type"] == "tushare"
    assert captured_calls[0]["extra_config"] == {"timeout": 10, "region": "cn"}
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["name"] == "tushare-main"
    assert audit_events[1]["event_type"] == "confirmation_completed"
