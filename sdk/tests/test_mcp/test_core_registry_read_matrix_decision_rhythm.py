# ruff: noqa: F403, F405
"""Core-only read matrix for decision_rhythm."""

from .core_registry_support import *


@pytest.mark.parametrize(
    (
        "capability_key",
        "executor_ref",
        "legacy_tool_names",
        "arguments",
        "payload",
        "expected",
    ),
    [
        (
            "decision.read.advisor_sheet",
            "decision_read_advisor_sheet",
            ("get_auto_advisor_decision_sheet",),
            {"account_id": 135},
            {
                "account": {"account_id": "135", "account_name": "Primary"},
                "baseline": "existing_positions",
                "generated_at": "2026-07-11T09:30:00+08:00",
                "today_conclusion": "REVIEW",
                "data_health": {"status": "ok"},
                "holdings": [{"asset_code": "000001.SZ"}],
                "allocation": [{"asset_class": "equity"}],
                "order_summary": {"total": 1},
                "order_intents": [{"side": "REDUCE"}],
                "execution_plan": {"requires_human_confirmation": True},
                "blockers": [],
                "next_actions": [{"key": "review"}],
                "source": "core-only-fallback",
            },
            "existing_positions",
        ),
        (
            "decision_rhythm.read.quota_list",
            "list_decision_quotas",
            ("list_decision_quotas",),
            {},
            {
                "quotas": [
                    {
                        "quota_id": "quota-weekly",
                        "period": "weekly",
                        "remaining_decisions": 3,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "quota-weekly",
        ),
        (
            "decision_rhythm.read.request_list",
            "list_decision_requests",
            ("list_decision_requests",),
            {},
            {
                "requests": [
                    {
                        "request_id": "request-001",
                        "asset_code": "600519.SH",
                        "priority": "high",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "request-001",
        ),
        (
            "decision_rhythm.read.request_detail",
            "get_decision_request",
            ("get_decision_request",),
            {"request_id": "request-001"},
            {
                "request_id": "request-001",
                "asset_code": "600519.SH",
                "priority": "high",
                "execution_status": "PENDING",
                "source": "core-only-fallback",
            },
            "600519.SH",
        ),
        (
            "decision_rhythm.read.summary",
            "get_decision_rhythm_summary",
            ("get_decision_rhythm_summary",),
            {},
            {
                "quota_status": {"weekly": "available"},
                "pending_requests": 2,
                "source": "core-only-fallback",
            },
            "pending_requests",
        ),
        (
            "decision.read.recommendation_list",
            "decision_workflow_list_recommendations",
            ("decision_workflow_list_recommendations",),
            {
                "account_id": "acct-1",
                "user_action": "ADOPTED",
                "page": 1,
                "page_size": 20,
            },
            {
                "recommendations": [
                    {
                        "recommendation_id": "rec-001",
                        "account_id": "acct-1",
                        "security_code": "600519.SH",
                    }
                ],
                "total_count": 1,
                "page": 1,
                "page_size": 20,
                "source": "core-only-fallback",
            },
            "rec-001",
        ),
        (
            "decision.read.transition_plan_detail",
            "decision_workflow_get_transition_plan",
            ("decision_workflow_get_transition_plan",),
            {"plan_id": "plan-001"},
            {
                "plan_id": "plan-001",
                "account_id": "acct-1",
                "status": "READY_FOR_APPROVAL",
                "orders": [{"security_code": "600519.SH"}],
                "source": "core-only-fallback",
            },
            "READY_FOR_APPROVAL",
        ),
    ],
)
def test_agom_capability_call_reads_data_family_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    executor_ref,
    legacy_tool_names,
    arguments,
    payload,
    expected,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        executor_ref,
        lambda **kwargs: payload,
    )
    assert all(legacy_tool_names)

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": capability_key,
                "arguments": arguments,
            },
        )
    )

    rendered = str(result)
    assert capability_key in rendered
    assert expected in rendered
    assert "core-only-fallback" in rendered
