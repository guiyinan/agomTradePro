# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_alpha_trigger."""

from .core_registry_support import *


def test_alpha_trigger_update_candidate_status_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAlphaTriggerModule:
        @staticmethod
        def get_candidate(candidate_id):
            assert candidate_id == "cand-001"
            return {
                "candidate_id": candidate_id,
                "asset_code": "000001.SH",
                "asset_class": "a_share_equity",
                "direction": "LONG",
                "status": "CANDIDATE",
                "confidence": 0.82,
                "created_at": "2026-07-09T10:00:00Z",
                "expires_at": "2026-07-16T10:00:00Z",
            }

    class _FakeClient:
        alpha_trigger = _FakeAlphaTriggerModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_update_alpha_candidate_status(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "candidate_id": kwargs["candidate_id"],
            "asset_code": "000001.SH",
            "status": kwargs["status"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "update_alpha_candidate_status",
        fake_update_alpha_candidate_status,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="alpha_trigger.update.candidate_status",
        arguments={
            "candidate_id": "cand-001",
            "status": "ACTIONABLE",
            "idempotency_key": "idem-alpha-candidate-status",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["candidate_summary"]["status"] == "CANDIDATE"
    assert preview_response["preview_result"]["target_status"] == "ACTIONABLE"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["candidate_id"] == "cand-001"
    assert resume_response["result"]["status"] == "ACTIONABLE"
    assert captured_calls[0]["candidate_id"] == "cand-001"
    assert captured_calls[0]["status"] == "ACTIONABLE"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["candidate_id"] == "cand-001"
    assert audit_events[1]["event_type"] == "confirmation_completed"
