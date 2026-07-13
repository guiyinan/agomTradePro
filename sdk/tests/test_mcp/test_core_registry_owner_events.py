# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_events."""

from .core_registry_support import *


def test_events_core_only_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _Events:
        def query(self, payload):
            calls.append(("query", payload))
            return {"success": True, "events": []}

        def metrics(self):
            calls.append(("metrics", None))
            return {"success": True, "metrics": {}}

        def status(self):
            calls.append(("status", None))
            return {"success": True, "is_running": True}

    class _Client:
        events = _Events()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["query_events"](
        event_type="regime_changed",
        correlation_id="corr-1",
        limit=10,
    ) == {"success": True, "events": []}
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_event_metrics"]() == {
        "success": True,
        "metrics": {},
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_event_bus_status"]() == {
        "success": True,
        "is_running": True,
    }
    assert calls == [
        (
            "query",
            {
                "limit": 10,
                "event_type": "regime_changed",
                "correlation_id": "corr-1",
            },
        ),
        ("metrics", None),
        ("status", None),
    ]


def test_events_publish_event_capability_previews_side_effects_before_staff_only_publish(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(
        monkeypatch,
        server_module.CORE_DISPATCHER,
    )

    class _FakeEventsModule:
        @staticmethod
        def publish_event(**kwargs):
            captured_calls.append(kwargs)
            return {
                "success": True,
                "event_id": kwargs["event_id"],
                "published_at": kwargs["occurred_at"],
                "subscribers_notified": 2,
            }

    class _FakeClient:
        events = _FakeEventsModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["events.publish.event"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("publish_event",)
    assert manifest.idempotency == "required"
    assert manifest.audit_tags == ("events:publish", "mcp:write")

    arguments = {
        "event_type": "regime_changed",
        "payload": {
            "old_regime": "Recovery",
            "new_regime": "Overheat",
        },
        "metadata": {"source": "governed-test"},
        "occurred_at": "2026-07-12T12:00:00Z",
        "correlation_id": "correlation-governed-001",
        "causation_id": "causation-governed-001",
        "idempotency_key": "idem-events-publish-001",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="events.publish.event",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["event_summary"] == {
        "event_id": "idem-events-publish-001",
        "event_type": "regime_changed",
        "occurred_at": "2026-07-12T12:00:00+00:00",
        "payload_keys": ["new_regime", "old_regime"],
        "metadata_keys": ["source"],
        "correlation_id": "correlation-governed-001",
        "causation_id": "causation-governed-001",
    }
    assert preview_response["preview_result"]["side_effects"] == {
        "persists_stored_event": True,
        "notifies_subscribers_synchronously": True,
        "subscriber_side_effect_scope": "subscriber_defined_cross_module_writes",
        "duplicate_event_id_blocked": True,
    }
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["event_id"] == "idem-events-publish-001"
    assert captured_calls == [
        {
            "event_type": "regime_changed",
            "payload": {
                "old_regime": "Recovery",
                "new_regime": "Overheat",
            },
            "metadata": {"source": "governed-test"},
            "occurred_at": "2026-07-12T12:00:00+00:00",
            "event_id": "idem-events-publish-001",
            "correlation_id": "correlation-governed-001",
            "causation_id": "causation-governed-001",
        }
    ]

    replay_response = server_module.CORE_DISPATCHER.call(
        capability_key="events.publish.event",
        arguments=arguments,
    )

    assert replay_response["status"] == "idempotent_replay"
    assert replay_response["result"] == resume_response["result"]
    assert replay_response["idempotency_reused"] is True
    assert len(captured_calls) == 1
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[1]["event_type"] == "confirmation_completed"
    assert audit_events[2]["event_type"] == "idempotent_replay"
