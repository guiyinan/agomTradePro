"""Governed MCP workflow tests for provider connection probes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_data_center_provider_connection_test_requires_preview_confirmation_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, int]] = []
    audit_events: list[dict] = []

    class _FakeDataCenterModule:
        @staticmethod
        def get_provider(provider_id: int) -> dict:
            calls.append(("get_provider", provider_id))
            return {
                "id": provider_id,
                "name": "tushare-main",
                "source_type": "tushare",
                "is_active": True,
                "priority": 10,
                "has_api_key": True,
                "has_api_secret": False,
            }

        @staticmethod
        def test_provider_connection(provider_id: int) -> dict:
            calls.append(("test_provider_connection", provider_id))
            return {
                "success": True,
                "status": "success",
                "summary": "Tushare probe passed",
                "logs": ["[SUCCESS] parsed one row"],
                "tested_at": "2026-07-13T00:00:00+00:00",
                "api_key": "must-not-escape",
            }

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(data_center=_FakeDataCenterModule()),
    )
    monkeypatch.setattr(
        server_module.CORE_DISPATCHER,
        "_audit_logger",
        SimpleNamespace(
            log_governed_capability_event=lambda **kwargs: audit_events.append(dict(kwargs))
            or "audit-provider-probe"
        ),
    )

    manifest = CapabilityRegistryLoader().build_registry()[
        "data_center.run.provider_connection_test"
    ]
    assert manifest.required_roles == ("staff",)
    assert manifest.idempotency == "required"
    assert manifest.legacy_tool_names == ("test_data_center_provider_connection",)

    arguments = {
        "provider_id": 7,
        "idempotency_key": "idem-provider-connection-test",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.run.provider_connection_test",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview_result = preview_response["preview_result"]
    assert preview_result["preview_only"] is True
    assert preview_result["provider_summary"]["name"] == "tushare-main"
    assert preview_result["side_effects"]["external_provider_call"] is True
    assert preview_result["side_effects"]["provider_health_metadata_write"] is True
    assert preview_result["side_effects"]["market_fact_sync"] is False
    assert calls == [("get_provider", 7)]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert "api_key" not in resume_response["result"]
    assert calls == [("get_provider", 7), ("test_provider_connection", 7)]
    assert audit_events[0]["affected_objects"]["provider_id"] == 7
    assert audit_events[1]["event_type"] == "confirmation_completed"

    replay = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.run.provider_connection_test",
        arguments=arguments,
    )
    assert replay["status"] == "idempotent_replay"
    assert replay["idempotency_reused"] is True
    assert calls == [("get_provider", 7), ("test_provider_connection", 7)]


def test_data_center_provider_connection_preview_rejects_non_positive_id() -> None:
    import agomtradepro_mcp.server as server_module

    response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.run.provider_connection_test",
        arguments={
            "provider_id": 0,
            "idempotency_key": "idem-invalid-provider-connection-test",
        },
    )

    assert response["status"] == "error"
    assert response["error"]["code"] == "capability_preview_failed"
