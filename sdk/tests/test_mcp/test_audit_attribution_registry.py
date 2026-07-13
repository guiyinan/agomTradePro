from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_audit_attribution_report_previews_before_staff_only_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = []

    class _FakeAuditModule:
        @staticmethod
        def preview_report_generation(payload):
            calls.append(("preview_report_generation", dict(payload)))
            return {
                "success": True,
                "preview": {
                    "backtest": {"id": 7, "status": "completed"},
                    "existing_report_count": 1,
                    "external_reads": ["historical_asset_prices"],
                    "writes": [
                        "audit_attribution_report",
                        "audit_loss_analysis_if_applicable",
                        "audit_experience_summary",
                    ],
                    "duplicate_reports_allowed": True,
                    "partial_write_possible": True,
                },
            }

        @staticmethod
        def generate_report(payload):
            calls.append(("generate_report", dict(payload)))
            return {"id": 42, "backtest_id": payload["backtest_id"]}

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
    manifest = CapabilityRegistryLoader().build_registry()["audit.create.attribution_report"]
    assert manifest.required_roles == ("staff",)
    assert manifest.idempotency == "required"
    assert manifest.legacy_tool_names == ("generate_audit_report",)

    arguments = {"backtest_id": 7, "idempotency_key": "idem-audit-report"}
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="audit.create.attribution_report",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "backtest": {"id": 7, "status": "completed"},
        "existing_report_count": 1,
        "external_reads": ["historical_asset_prices"],
        "writes": [
            "audit_attribution_report",
            "audit_loss_analysis_if_applicable",
            "audit_experience_summary",
        ],
        "duplicate_reports_allowed": True,
        "partial_write_possible": True,
    }
    assert calls == [("preview_report_generation", {"backtest_id": 7})]

    resumed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )
    assert resumed["status"] == "completed"
    assert resumed["result"]["id"] == 42
    assert calls[1] == ("generate_report", {"backtest_id": 7})

    replay = server_module.CORE_DISPATCHER.call(
        capability_key="audit.create.attribution_report",
        arguments=arguments,
    )
    assert replay["status"] == "idempotent_replay"
    assert len(calls) == 2
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"
