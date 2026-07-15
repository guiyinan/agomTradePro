"""Governed controlled-event-replay capability contracts."""

from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_event_replay_manifest_is_staff_confirmed_and_idempotent() -> None:
    manifest = CapabilityRegistryLoader().build_registry()["events.replay.events"]

    assert manifest.owner_app == "events"
    assert manifest.risk_level == "high"
    assert manifest.required_roles == ("staff",)
    assert manifest.requires_confirmation is True
    assert manifest.idempotency == "required"
    assert manifest.legacy_tool_names == ("replay_events",)
    assert manifest.confirmation_preview_arguments == {"preview_only": True}
    assert manifest.confirmation_commit_arguments == {"preview_only": False}


def test_event_replay_handler_uses_formal_sdk_for_preview_and_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.server as server_module

    calls = []

    class _Events:
        @staticmethod
        def preview_event_replay(payload):
            calls.append(("preview", dict(payload)))
            return {"success": True, "candidate_count": 2}

        @staticmethod
        def commit_event_replay(payload, *, idempotency_key):
            calls.append(("commit", dict(payload), idempotency_key))
            return {"success": True, "outcome": "completed"}

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(events=_Events()),
    )
    monkeypatch.setattr(server_module.CORE_DISPATCHER, "_role_provider", lambda: "staff")
    arguments = {
        "target_key": "events.decision.approved",
        "event_type": "decision_approved",
        "limit": 10,
        "idempotency_key": "replay-mcp-1",
    }

    preview = server_module.CORE_DISPATCHER.call(
        capability_key="events.replay.events",
        arguments=arguments,
    )

    assert preview["status"] == "confirmation_required", preview
    assert calls == [
        (
            "preview",
            {
                "target_key": "events.decision.approved",
                "event_type": "decision_approved",
                "limit": 10,
            },
        )
    ]
    committed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview["confirmation_token"],
        approve=True,
    )
    assert committed["status"] == "completed"
    assert calls[1] == (
        "commit",
        {
            "target_key": "events.decision.approved",
            "event_type": "decision_approved",
            "limit": 10,
        },
        "replay-mcp-1",
    )
