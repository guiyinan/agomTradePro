# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_policy."""

from .core_registry_support import *


def test_agom_capability_call_reads_policy_workbench_bootstrap_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_workbench_bootstrap",
        lambda **kwargs: {
            "summary": {"policy_level": "P2"},
            "default_list": [{"id": 1, "title": "Liquidity Support Bulletin"}],
            "filter_options": {"levels": ["P1", "P2"]},
            "trend": {"pending_review_count": [1, 2, 3]},
            "fetch_status": {"latest_error": None},
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "policy.read.workbench.bootstrap",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "policy.read.workbench.bootstrap" in rendered
    assert "Liquidity Support Bulletin" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_policy_workbench_event_detail_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_workbench_event_detail",
        lambda **kwargs: {
            "id": kwargs["event_id"],
            "title": "Detailed Event",
            "audit_status": "manual_approved",
            "rss_source_name": "Detail Feed",
            "effective_by_name": "operator",
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "policy.read.workbench.event_detail",
                "arguments": {"event_id": 123},
            },
        )
    )

    rendered = str(result)
    assert "policy.read.workbench.event_detail" in rendered
    assert "Detailed Event" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_policy_workbench_items_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_workbench_items",
        lambda **kwargs: {
            "items": [
                {
                    "id": 11,
                    "title": "Pending Liquidity Event",
                    "audit_status": "pending_review",
                }
            ],
            "total_count": 1,
            "page": kwargs.get("page", 1),
            "page_size": kwargs.get("page_size", 20),
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "policy.read.workbench.items",
                "arguments": {"tab": "pending", "page": 1, "page_size": 10},
            },
        )
    )

    rendered = str(result)
    assert "policy.read.workbench.items" in rendered
    assert "Pending Liquidity Event" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_policy_workbench_summary_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_workbench_summary",
        lambda **kwargs: {
            "policy_level": "P2",
            "policy_level_name": "Moderate Support",
            "gate_level": "G1",
            "gate_level_name": "Open",
            "global_heat": 0.67,
            "global_sentiment": 0.58,
            "pending_review_count": 3,
            "sla_exceeded_count": 1,
            "today_events_count": 6,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "policy.read.workbench.summary",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "policy.read.workbench.summary" in rendered
    assert "Moderate Support" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_policy_sentiment_gate_state_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_sentiment_gate_state",
        lambda **kwargs: {
            "asset_class": kwargs.get("asset_class", "all"),
            "gate_level": "L2",
            "global_heat": 0.81,
            "global_sentiment": 0.64,
            "max_position_cap": 0.35,
            "signal_paused": False,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "policy.read.sentiment_gate.state",
                "arguments": {"asset_class": "equity"},
            },
        )
    )

    rendered = str(result)
    assert "policy.read.sentiment_gate.state" in rendered
    assert "L2" in rendered
    assert "core-only-fallback" in rendered


def test_policy_approve_workbench_event_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakePolicyModule:
        @staticmethod
        def get_workbench_event_detail(event_id):
            return {
                "id": event_id,
                "title": "Liquidity Support Bulletin",
                "event_date": "2026-07-10",
                "level": "P2",
                "event_type": "policy",
                "audit_status": "pending_review",
                "source_type": "rss",
                "source_name": "Policy Feed",
            }

    class _FakeClient:
        policy = _FakePolicyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_approve_workbench_event(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "event_id": kwargs["event_id"],
            "message": "event approved",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "approve_workbench_event",
        fake_approve_workbench_event,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="policy.approve.workbench_event",
        arguments={
            "event_id": 17,
            "idempotency_key": "idem-policy-approve",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert (
        preview_response["preview_result"]["event_summary"]["title"] == "Liquidity Support Bulletin"
    )
    assert preview_response["preview_result"]["event_summary"]["audit_status"] == "pending_review"
    assert preview_response["preview_result"]["target_status"] == "manual_approved"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert resume_response["result"]["event_id"] == 17
    assert captured_calls[0]["event_id"] == 17
    assert audit_events[0]["affected_objects"]["event_id"] == 17
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_policy_reject_workbench_event_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakePolicyModule:
        @staticmethod
        def get_workbench_event_detail(event_id):
            return {
                "id": event_id,
                "title": "Liquidity Support Bulletin",
                "event_date": "2026-07-10",
                "level": "P2",
                "event_type": "policy",
                "audit_status": "pending_review",
                "source_type": "rss",
                "source_name": "Policy Feed",
            }

    class _FakeClient:
        policy = _FakePolicyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_reject_workbench_event(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "event_id": kwargs["event_id"],
            "message": "event rejected",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "reject_workbench_event",
        fake_reject_workbench_event,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="policy.reject.workbench_event",
        arguments={
            "event_id": 18,
            "reason": "Evidence is incomplete",
            "idempotency_key": "idem-policy-reject",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert (
        preview_response["preview_result"]["event_summary"]["title"] == "Liquidity Support Bulletin"
    )
    assert preview_response["preview_result"]["event_summary"]["audit_status"] == "pending_review"
    assert preview_response["preview_result"]["reason"] == "Evidence is incomplete"
    assert preview_response["preview_result"]["target_status"] == "rejected"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert resume_response["result"]["event_id"] == 18
    assert captured_calls[0]["event_id"] == 18
    assert captured_calls[0]["reason"] == "Evidence is incomplete"
    assert audit_events[0]["affected_objects"]["event_id"] == 18
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_policy_rollback_workbench_event_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakePolicyModule:
        @staticmethod
        def get_workbench_event_detail(event_id):
            return {
                "id": event_id,
                "title": "Liquidity Support Bulletin",
                "event_date": "2026-07-10",
                "level": "P2",
                "event_type": "policy",
                "audit_status": "manual_approved",
                "gate_effective": True,
                "effective_at": "2026-07-10T08:00:00+00:00",
                "source_type": "rss",
                "source_name": "Policy Feed",
            }

    class _FakeClient:
        policy = _FakePolicyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_rollback_workbench_event(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "event_id": kwargs["event_id"],
            "message": "event rolled back",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "rollback_workbench_event",
        fake_rollback_workbench_event,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="policy.rollback.workbench_event",
        arguments={
            "event_id": 19,
            "reason": "Policy basis changed",
            "idempotency_key": "idem-policy-rollback",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert (
        preview_response["preview_result"]["event_summary"]["title"] == "Liquidity Support Bulletin"
    )
    assert preview_response["preview_result"]["event_summary"]["audit_status"] == "manual_approved"
    assert preview_response["preview_result"]["event_summary"]["gate_effective"] is True
    assert preview_response["preview_result"]["reason"] == "Policy basis changed"
    assert preview_response["preview_result"]["target_status"] == "rolled_back"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert resume_response["result"]["event_id"] == 19
    assert captured_calls[0]["event_id"] == 19
    assert captured_calls[0]["reason"] == "Policy basis changed"
    assert audit_events[0]["affected_objects"]["event_id"] == 19
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_policy_override_workbench_event_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakePolicyModule:
        @staticmethod
        def get_workbench_event_detail(event_id):
            return {
                "id": event_id,
                "title": "Liquidity Support Bulletin",
                "event_date": "2026-07-10",
                "level": "P2",
                "event_type": "policy",
                "audit_status": "pending_review",
                "gate_effective": False,
                "effective_at": None,
                "source_type": "rss",
                "source_name": "Policy Feed",
            }

    class _FakeClient:
        policy = _FakePolicyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_override_workbench_event(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "event_id": kwargs["event_id"],
            "message": "event overridden",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "override_workbench_event",
        fake_override_workbench_event,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="policy.override.workbench_event",
        arguments={
            "event_id": 20,
            "reason": "Manual override due to exceptional context",
            "new_level": "P1",
            "idempotency_key": "idem-policy-override",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["event_summary"]["level"] == "P2"
    assert preview_response["preview_result"]["override_summary"]["requested_level"] == "P1"
    assert preview_response["preview_result"]["override_summary"]["level_changed"] is True
    assert (
        preview_response["preview_result"]["reason"] == "Manual override due to exceptional context"
    )
    assert preview_response["preview_result"]["target_status"] == "overridden"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert resume_response["result"]["event_id"] == 20
    assert captured_calls[0]["event_id"] == 20
    assert captured_calls[0]["new_level"] == "P1"
    assert audit_events[0]["affected_objects"]["event_id"] == 20
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_policy_create_event_capability_previews_same_day_before_staff_only_create(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(
        monkeypatch,
        server_module.CORE_DISPATCHER,
    )

    class _FakePolicyModule:
        @staticmethod
        def get_events(*, start_date=None, end_date=None, limit=100):
            assert start_date == date(2026, 7, 11)
            assert end_date == date(2026, 7, 11)
            assert limit == 100
            return [
                SimpleNamespace(
                    id=19,
                    event_date=date(2026, 7, 11),
                    gear="neutral",
                    description="Existing same-day policy context.",
                )
            ]

        @staticmethod
        def create_event(
            event_date,
            event_type,
            description,
            gear,
            *,
            level=None,
            title=None,
            evidence_url=None,
        ):
            captured_calls.append(
                {
                    "event_date": event_date,
                    "event_type": event_type,
                    "description": description,
                    "gear": gear,
                    "level": level,
                    "title": title,
                    "evidence_url": evidence_url,
                }
            )
            return SimpleNamespace(id=82)

    class _FakeClient:
        policy = _FakePolicyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["policy.create.event"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("create_policy_event",)

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="policy.create.event",
        arguments={
            "event_date": "2026-07-11",
            "level": "P2",
            "title": "Governed liquidity support",
            "description": "Targeted liquidity support was announced with sufficient detail.",
            "evidence_url": "https://example.com/policy/governed",
            "idempotency_key": "idem-policy-event-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["summary"] == {
        "event_date": "2026-07-11",
        "level": "P2",
        "existing_event_count": 1,
    }
    assert preview_response["preview_result"]["event_summary"]["may_trigger_alert"] is True
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["event"]["id"] == 82
    assert captured_calls == [
        {
            "event_date": date(2026, 7, 11),
            "event_type": "Governed liquidity support",
            "description": "Targeted liquidity support was announced with sufficient detail.",
            "gear": "stimulus",
            "level": "P2",
            "title": "Governed liquidity support",
            "evidence_url": "https://example.com/policy/governed",
        }
    ]
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_policy_rss_fetch_capability_previews_sources_before_staff_only_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(
        monkeypatch,
        server_module.CORE_DISPATCHER,
    )

    class _FakePolicyModule:
        @staticmethod
        def get_rss_source(source_id):
            calls.append(("get_rss_source", {"source_id": source_id}))
            return {
                "id": source_id,
                "name": "Central Bank Feed",
                "category": "central_bank",
                "is_active": True,
                "extract_content": True,
                "parser_type": "feedparser",
                "rsshub_enabled": False,
                "last_fetch_at": "2026-07-11T08:00:00Z",
                "last_fetch_status": "success",
            }

        @staticmethod
        def trigger_fetch(source_id=None, force_refetch=False):
            calls.append(
                (
                    "trigger_fetch",
                    {
                        "source_id": source_id,
                        "force_refetch": force_refetch,
                    },
                )
            )
            return {
                "success": True,
                "mode": "single",
                "sources_processed": 1,
                "total_items": 4,
                "new_policy_events": 2,
                "errors": [],
                "details": [],
            }

    class _FakeClient:
        policy = _FakePolicyModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["policy.start.rss_fetch"]
    assert manifest.required_roles == ("staff",)
    assert manifest.idempotency == "required"
    assert manifest.legacy_tool_names == ("trigger_rss_fetch",)

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="policy.start.rss_fetch",
        arguments={
            "source_id": 3,
            "force_refetch": True,
            "idempotency_key": "idem-policy-rss-fetch",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "mode": "single",
        "source_count": 1,
        "source_ids": [3],
        "force_refetch": True,
        "external_network_io": True,
        "may_invoke_ai": True,
        "may_send_alerts": True,
        "partial_success_possible": True,
        "writes": [
            "raw_policy_logs",
            "policy_events",
            "rss_fetch_logs",
            "rss_source_last_fetch_status",
        ],
    }
    assert calls == [("get_rss_source", {"source_id": 3})]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["new_policy_events"] == 2
    assert calls[1] == (
        "trigger_fetch",
        {"source_id": 3, "force_refetch": True},
    )

    replay = server_module.CORE_DISPATCHER.call(
        capability_key="policy.start.rss_fetch",
        arguments={
            "source_id": 3,
            "force_refetch": True,
            "idempotency_key": "idem-policy-rss-fetch",
        },
    )
    assert replay["status"] == "idempotent_replay"
    assert len(calls) == 2
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"
