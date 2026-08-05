"""SDK contracts for governed scenario research."""

from unittest.mock import MagicMock, call

from agomtradepro.modules.risk_center import RiskCenterModule


def test_scenario_sdk_uses_canonical_preview_and_write_endpoints() -> None:
    client = MagicMock()
    client.get.side_effect = [
        {"success": True, "data": []},
        {"success": True, "data": {"scenario_key": "tail-risk"}},
        {"success": True, "data": {"set_key": "macro"}},
        {"success": True, "data": {"dimensions": []}},
    ]
    client.post.side_effect = [{"success": True, "data": {}}] * 10
    module = RiskCenterModule(client)

    module.list_scenarios()
    module.get_scenario("tail-risk")
    module.get_active_scenario_set()
    module.validate_scenario_revision({"scenario_key": "tail-risk"})
    module.preview_scenario_revision({"scenario_key": "tail-risk"})
    module.propose_scenario_revision({"scenario_key": "tail-risk"})
    module.activate_scenario_revision({"proposal_id": "proposal-1"})
    module.rollback_scenario_revision({"proposal_id": "proposal-2"})
    module.retire_scenario("tail-risk", {"proposal_id": "proposal-3"})
    module.preview_scenario_matrix({"scenario_set_revision_id": "set-v2"})
    module.get_market_state_evidence()
    module.build_decision_scorecard({"asset_code": "000300.SH"})
    module.generate_strategy_brief({"scenario_set_revision_id": "set-v2"})

    assert client.get.call_args_list == [
        call(
            "/api/risk-center/stress-scenarios/",
            params={"include_inactive": "false"},
        ),
        call("/api/risk-center/stress-scenarios/tail-risk/", params=None),
        call(
            "/api/risk-center/stress-scenario-sets/active/",
            params={"environment": "production", "purpose": "portfolio_stress"},
        ),
        call("/api/risk-center/research/market-state/", params=None),
    ]
    assert client.post.call_args_list == [
        call(
            "/api/risk-center/stress-scenarios/validate-revision/",
            data=None,
            json={"scenario_key": "tail-risk"},
        ),
        call(
            "/api/risk-center/stress-scenarios/preview-revision/",
            data=None,
            json={"scenario_key": "tail-risk"},
        ),
        call(
            "/api/risk-center/stress-scenarios/propose-revision/",
            data=None,
            json={"scenario_key": "tail-risk"},
        ),
        call(
            "/api/risk-center/stress-scenario-sets/activate/",
            data=None,
            json={"proposal_id": "proposal-1"},
        ),
        call(
            "/api/risk-center/stress-scenario-sets/rollback/",
            data=None,
            json={"proposal_id": "proposal-2"},
        ),
        call(
            "/api/risk-center/stress-scenarios/tail-risk/retire/",
            data=None,
            json={"proposal_id": "proposal-3"},
        ),
        call(
            "/api/risk-center/stress-scenario-sets/impact-preview/",
            data=None,
            json={"scenario_set_revision_id": "set-v2"},
        ),
        call(
            "/api/risk-center/research/decision-scorecard/",
            data=None,
            json={"asset_code": "000300.SH"},
        ),
        call(
            "/api/risk-center/research/strategy-brief/",
            data=None,
            json={"scenario_set_revision_id": "set-v2"},
        ),
    ]


def test_scenario_sdk_exposes_action_preview_and_human_review_endpoints() -> None:
    client = MagicMock()
    client.post.side_effect = [
        {"success": True, "data": {"preview_id": "preview-1"}},
        {"success": True, "data": {"status": "approved"}},
        {"success": True, "data": {"status": "rejected"}},
    ]
    module = RiskCenterModule(client)

    module.preview_scenario_action(
        "activate",
        {
            "payload": {},
            "scenario_set_revision_id": "set-v2",
            "environment": "production",
            "purpose": "portfolio_stress",
            "change_reason": "promote reviewed scenarios",
            "correlation_id": "corr-1",
        },
    )
    module.approve_scenario_proposal(
        7,
        {"reason": "reviewed", "correlation_id": "corr-2"},
    )
    module.reject_scenario_proposal(
        8,
        {"reason": "evidence incomplete", "correlation_id": "corr-3"},
    )

    assert client.post.call_args_list == [
        call(
            "/api/risk-center/stress-scenarios/preview-revision/",
            data=None,
            json={
                "operation": "activate",
                "payload": {},
                "scenario_set_revision_id": "set-v2",
                "environment": "production",
                "purpose": "portfolio_stress",
                "change_reason": "promote reviewed scenarios",
                "correlation_id": "corr-1",
            },
        ),
        call(
            "/api/risk-center/stress-scenario-proposals/7/approve/",
            data=None,
            json={"reason": "reviewed", "correlation_id": "corr-2"},
        ),
        call(
            "/api/risk-center/stress-scenario-proposals/8/reject/",
            data=None,
            json={"reason": "evidence incomplete", "correlation_id": "corr-3"},
        ),
    ]
