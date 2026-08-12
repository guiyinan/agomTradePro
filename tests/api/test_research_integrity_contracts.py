from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.infrastructure.pit_models import PITFactVersionModel
from apps.portfolio.infrastructure.policy_models import PortfolioPlanningPolicyModel
from apps.prompt.infrastructure.eval_models import (
    PromptEvalCase,
    PromptEvalDataset,
    PromptVersion,
)
from apps.prompt.infrastructure.models import PromptTemplateORM
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


def _assert_json(response, status_code: int) -> dict:  # type: ignore[no-untyped-def]
    assert response.status_code == status_code
    assert response.headers["Content-Type"].startswith("application/json")
    return response.json()


@pytest.mark.django_db
def test_pit_manifest_and_decision_snapshot_api_contract(authenticated_client) -> None:
    now = datetime(2025, 3, 1, tzinfo=UTC)
    PITFactVersionModel.objects.create(
        dataset="regime_state",
        business_key="global",
        effective_at=now - timedelta(days=1),
        available_at=now - timedelta(hours=1),
        ingested_at=now - timedelta(minutes=30),
        revision_number=0,
        source_record_id="regime-1",
        content_hash="f" * 64,
        pit_quality="verified",
        payload={"dominant_regime": "recovery"},
    )
    manifest_payload = _assert_json(
        authenticated_client.post(
            "/api/data-center/pit-manifests/",
            data={
                "as_of_time": now.isoformat(),
                "knowledge_scope": "public",
                "calendar_version": "sse-2025-v1",
                "query_spec": {"regime_state": {"business_key": "global"}},
                "required_keys": {"regime_state": ["global"]},
            },
            content_type="application/json",
        ),
        201,
    )
    assert manifest_payload["is_verified"] is True

    components = {
        name: {
            "version": "v1",
            "event_id": f"evt-{name}",
            "as_of_time": (now - timedelta(minutes=1)).isoformat(),
        }
        for name in ("regime", "policy", "risk", "beta_gate", "decision_rhythm")
    }
    snapshot_payload = _assert_json(
        authenticated_client.post(
            "/api/decision-rhythm/input-snapshots/",
            data={
                "as_of_time": now.isoformat(),
                "pit_manifest_id": manifest_payload["manifest_id"],
                "components": components,
                "portfolio_snapshot_id": "holdings-v1",
                "config_version": "config-v1",
                "strategy_version": "strategy-v1",
                "prompt_version": "prompt-v1",
            },
            content_type="application/json",
        ),
        201,
    )
    assert len(snapshot_payload["state_hash"]) == 64
    detail = _assert_json(
        authenticated_client.get(
            f"/api/decision-rhythm/input-snapshots/{snapshot_payload['snapshot_id']}/"
        ),
        200,
    )
    assert detail["state_hash"] == snapshot_payload["state_hash"]


@pytest.mark.django_db
def test_portfolio_plan_is_idempotent_and_snapshot_bound(authenticated_client, auth_user) -> None:
    now = datetime.now(UTC)
    account = SimulatedAccountModel.objects.create(
        user=auth_user,
        account_name="portfolio-contract",
        account_type="simulated",
        initial_capital="10000.00",
        current_cash="10000.00",
        total_value="10000.00",
    )
    PortfolioPlanningPolicyModel.objects.create(
        policy_id="api-policy-v1",
        version="a-share-policy-v1",
        status="active",
        buy_lot_size=100,
        fee_rate="0.001",
        slippage_rate="0.001",
        min_rebalance_value="0",
        max_asset_weight="0.8",
        max_volume_participation="0.2",
    )
    request = {
        "idempotency_key": "portfolio-contract-1",
        "account_id": str(account.id),
        "portfolio_snapshot_id": "holdings-1",
        "as_of_time": now.isoformat(),
        "cash": "10000.00",
        "current_positions": {},
        "target_portfolio_id": "target-1",
        "decision_snapshot_id": "decision-1",
        "target_positions": [{"asset_code": "000001.SZ", "target_weight": "0.5"}],
        "target_cash_weight": "0.5",
        "strategy_version": "strategy-v1",
        "prices": {"000001.SZ": "10.00"},
        "market_facts": {
            "000001.SZ": {
                "volume": 100000,
                "suspended": False,
                "limit_up": False,
                "limit_down": False,
            }
        },
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }
    first = _assert_json(
        authenticated_client.post(
            "/api/portfolio/transition-plans/", request, content_type="application/json"
        ),
        201,
    )
    repeated = _assert_json(
        authenticated_client.post(
            "/api/portfolio/transition-plans/", request, content_type="application/json"
        ),
        201,
    )
    assert first["plan_id"] == repeated["plan_id"]
    conflicting = _assert_json(
        authenticated_client.post(
            "/api/portfolio/transition-plans/",
            {**request, "cash": "12000.00"},
            content_type="application/json",
        ),
        400,
    )
    assert conflicting["code"] == "API_ERROR"
    mismatch = _assert_json(
        authenticated_client.post(
            f"/api/portfolio/transition-plans/{first['plan_id']}/approve/",
            {"decision_snapshot_id": "decision-changed"},
            content_type="application/json",
        ),
        400,
    )
    assert mismatch["code"] == "VALIDATION_ERROR"
    approved = _assert_json(
        authenticated_client.post(
            f"/api/portfolio/transition-plans/{first['plan_id']}/approve/",
            {"decision_snapshot_id": "decision-1"},
            content_type="application/json",
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    blocked_handoff = _assert_json(
        authenticated_client.post(
            f"/api/portfolio/transition-plans/{first['plan_id']}/submit/",
            {},
            content_type="application/json",
        ),
        400,
    )
    assert "Evidence is integrated" in str(blocked_handoff)


@pytest.mark.django_db
def test_portfolio_transition_plan_rejects_foreign_account(authenticated_client) -> None:
    from django.contrib.auth import get_user_model

    other_user = get_user_model().objects.create_user(
        username="portfolio-other", password="testpass123"
    )
    account = SimulatedAccountModel.objects.create(
        user=other_user,
        account_name="foreign-portfolio",
        account_type="simulated",
        initial_capital="10000.00",
        current_cash="10000.00",
        total_value="10000.00",
    )
    now = datetime.now(UTC)
    response = authenticated_client.post(
        "/api/portfolio/transition-plans/",
        {
            "idempotency_key": "foreign-plan",
            "account_id": str(account.id),
            "portfolio_snapshot_id": "foreign-holdings",
            "as_of_time": now.isoformat(),
            "cash": "10000.00",
            "current_positions": {},
            "target_portfolio_id": "foreign-target",
            "decision_snapshot_id": "foreign-decision",
            "target_positions": [],
            "target_cash_weight": "1",
            "strategy_version": "strategy-v1",
            "prices": {},
            "market_facts": {},
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        },
        content_type="application/json",
    )

    assert response.status_code == 403
    assert "无权" in response.json()["detail"]


@pytest.mark.django_db
def test_prompt_evaluation_and_activation_api_contract(authenticated_client) -> None:
    template = PromptTemplateORM.objects.create(
        name="api-eval-template",
        category="analysis",
        template_content="{{ input }}",
    )
    PromptVersion.objects.create(
        version_id="api-prompt-v1",
        template=template,
        version="1",
        content="{{ input }}",
        content_hash="1" * 64,
        status="candidate",
    )
    dataset = PromptEvalDataset.objects.create(
        dataset_id="api-dataset-v1",
        name="api-contracts",
        version="1",
        content_hash="2" * 64,
    )
    PromptEvalCase.objects.create(case_id="api-case-1", dataset=dataset)
    base = {
        "version_id": "api-prompt-v1",
        "dataset_id": "api-dataset-v1",
        "provider": "fixed-provider",
        "model": "fixed-model",
        "temperature": 0,
        "max_cost": "1.0",
        "max_tokens": 1000,
        "max_cases": 10,
        "assertion_results": [
            {
                "case_id": "api-case-1",
                "assertion_type": "schema",
                "passed": True,
                "critical": True,
                "tokens": 10,
                "cost": "0.01",
            }
        ],
    }
    for evaluation_type in ("offline", "online"):
        payload = {**base, "evaluation_type": evaluation_type}
        result = _assert_json(
            authenticated_client.post(
                "/api/prompts/evaluations/", payload, content_type="application/json"
            ),
            201,
        )
        assert result["status"] == "completed"
    activated = _assert_json(
        authenticated_client.post("/api/prompts/versions/api-prompt-v1/activate/", {}),
        200,
    )
    assert activated["decision"] == "approved"


@pytest.mark.django_db
def test_forecast_ledger_and_scoreboard_api_contract(authenticated_client) -> None:
    published_at = datetime(2025, 4, 1, tzinfo=UTC)
    entry = _assert_json(
        authenticated_client.post(
            "/api/signal/forecast-ledger/",
            {
                "entry_id": "api-forecast-v1",
                "published_at": published_at.isoformat(),
                "direction": "LONG",
                "asset_code": "000001.SZ",
                "horizon_end": (published_at + timedelta(days=30)).isoformat(),
                "benchmark_asset": "000300.SH",
                "probability": 0.8,
                "invalidation_rule_version": "rule-v1",
                "decision_snapshot_id": "decision-v1",
                "pit_manifest_id": "manifest-v1",
                "strategy_version": "strategy-v1",
                "source": "strategy",
            },
            content_type="application/json",
        ),
        201,
    )
    evaluation_payload = {
        "checked_at": (published_at + timedelta(days=1)).isoformat(),
        "data_version_ids": [1],
        "conditions": [{"name": "price_floor", "triggered": False}],
    }
    first = _assert_json(
        authenticated_client.post(
            f"/api/signal/forecast-ledger/{entry['entry_id']}/evaluations/",
            evaluation_payload,
            content_type="application/json",
        ),
        201,
    )
    repeated = _assert_json(
        authenticated_client.post(
            f"/api/signal/forecast-ledger/{entry['entry_id']}/evaluations/",
            evaluation_payload,
            content_type="application/json",
        ),
        201,
    )
    assert repeated["evaluation_id"] == first["evaluation_id"]
    _assert_json(
        authenticated_client.post(
            f"/api/signal/forecast-ledger/{entry['entry_id']}/outcome/",
            {
                "finalized_at": (published_at + timedelta(days=30)).isoformat(),
                "outcome_type": "expired",
                "asset_return": 0.1,
                "benchmark_return": 0.04,
                "neutral_band": 0.01,
                "evidence": {"price_version_ids": [2, 3]},
            },
            content_type="application/json",
        ),
        201,
    )
    scoreboard = _assert_json(
        authenticated_client.get("/api/audit/forecast-scoreboard/?group_by=source"), 200
    )
    assert scoreboard["results"][0]["hit_rate"] == 1.0
    missing = _assert_json(
        authenticated_client.post(
            "/api/signal/forecast-ledger/does-not-exist/evaluations/",
            evaluation_payload,
            content_type="application/json",
        ),
        404,
    )
    assert missing["detail"] == "Forecast entry not found."


@pytest.mark.django_db
def test_new_write_endpoints_require_authentication(client) -> None:
    for path in (
        "/api/data-center/pit-manifests/",
        "/api/decision-rhythm/input-snapshots/",
        "/api/portfolio/transition-plans/",
        "/api/research/experiments/",
        "/api/prompts/evaluations/",
        "/api/signal/forecast-ledger/",
    ):
        response = client.post(path, data={}, content_type="application/json")
        assert response.status_code in {401, 403}
        assert response.headers["Content-Type"].startswith("application/json")
