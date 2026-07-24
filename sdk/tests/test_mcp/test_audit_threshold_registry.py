from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_audit_threshold_update_previews_before_staff_only_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = []

    class _FakeAuditModule:
        @staticmethod
        def preview_threshold_update(payload):
            calls.append(("preview_threshold_update", dict(payload)))
            return {
                "success": True,
                "preview": {
                    "indicator_code": "CN_PMI",
                    "current": {"level_low": 48.0, "level_high": 52.0},
                    "target": {"level_low": 49.0, "level_high": 51.0},
                    "changed_fields": ["level_low", "level_high"],
                    "writes": ["audit_indicator_threshold_config"],
                },
            }

        @staticmethod
        def update_threshold(payload):
            calls.append(("update_threshold", dict(payload)))
            return {"success": True, "updated": payload}

    class _FakeClient:
        audit = _FakeAuditModule()

    def _log_governed_capability_event(**kwargs):
        audit_events.append(dict(kwargs))
        return "audit-log-1"

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())
    monkeypatch.setattr(
        server_module.CORE_DISPATCHER,
        "_audit_logger",
        SimpleNamespace(log_governed_capability_event=_log_governed_capability_event),
    )
    monkeypatch.setattr(
        server_module.CORE_DISPATCHER,
        "_role_provider",
        lambda: "staff",
    )
    manifest = CapabilityRegistryLoader().build_registry()["audit.update.threshold_levels"]
    assert manifest.required_roles == ("staff",)
    assert manifest.idempotency == "required"
    assert manifest.legacy_tool_names == ("update_audit_threshold",)

    arguments = {
        "indicator_code": "CN_PMI",
        "level_low": 49.0,
        "level_high": 51.0,
        "idempotency_key": "idem-audit-threshold",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="audit.update.threshold_levels",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "indicator_code": "CN_PMI",
        "current": {"level_low": 48.0, "level_high": 52.0},
        "target": {"level_low": 49.0, "level_high": 51.0},
        "changed_fields": ["level_low", "level_high"],
        "writes": ["audit_indicator_threshold_config"],
    }
    assert calls == [
        (
            "preview_threshold_update",
            {"indicator_code": "CN_PMI", "level_low": 49.0, "level_high": 51.0},
        )
    ]

    resumed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )
    assert resumed["status"] == "completed"
    assert calls[1] == (
        "update_threshold",
        {"indicator_code": "CN_PMI", "level_low": 49.0, "level_high": 51.0},
    )

    replay = server_module.CORE_DISPATCHER.call(
        capability_key="audit.update.threshold_levels",
        arguments=arguments,
    )
    assert replay["status"] == "idempotent_replay"
    assert len(calls) == 2
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"
