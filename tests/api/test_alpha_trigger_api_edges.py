from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from apps.alpha_trigger.domain.entities import (
    AlphaCandidate,
    AlphaTrigger,
    CandidateStatus,
    SignalStrength,
    TriggerStatus,
    TriggerType,
)
from apps.alpha_trigger.infrastructure.models import (
    AlphaCandidateModel,
    AlphaTriggerModel,
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    (
        "/alpha-triggers/",
        "/alpha-triggers/create/",
        "/alpha-triggers/invalidation-builder/",
        "/alpha-triggers/performance/",
    ),
)
def test_alpha_trigger_classic_pages_require_login(client, path):
    response = client.get(path)

    assert response.status_code == 302
    assert response.url.startswith("/account/login/")


def _trigger() -> AlphaTrigger:
    return AlphaTrigger(
        trigger_id="trigger-001",
        trigger_type=TriggerType.MOMENTUM_SIGNAL,
        asset_code="600519.SH",
        asset_class="a_share",
        direction="LONG",
        trigger_condition={"signal": "cross_up"},
        invalidation_conditions=[],
        strength=SignalStrength.STRONG,
        confidence=0.82,
        created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
        status=TriggerStatus.ACTIVE,
        thesis="Momentum remains positive.",
    )


def _candidate() -> AlphaCandidate:
    return AlphaCandidate(
        candidate_id="candidate-001",
        trigger_id="trigger-001",
        asset_code="600519.SH",
        asset_class="a_share",
        direction="LONG",
        strength=SignalStrength.STRONG,
        confidence=0.82,
        thesis="Momentum remains positive.",
        time_window_start=date(2026, 7, 10),
        time_window_end=date(2026, 8, 9),
        status=CandidateStatus.ACTIONABLE,
        created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 10, 9, 0, tzinfo=UTC),
        entry_zone={"low": 1450.0, "high": 1500.0},
        exit_zone={"target": 1680.0},
        time_horizon=30,
        expected_return=0.12,
        risk_level="MEDIUM",
    )


@pytest.mark.django_db
def test_alpha_trigger_list_success_contract(authenticated_client):
    trigger = _trigger()
    repository = type(
        "TriggerRepository",
        (),
        {"get_active": lambda self: [trigger]},
    )()

    with patch(
        "apps.alpha_trigger.interface.views.get_alpha_trigger_repository",
        return_value=repository,
    ):
        response = authenticated_client.get("/api/alpha-triggers/triggers/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["results"][0]["trigger_id"] == "trigger-001"
    assert payload["results"][0]["status"] == "active"
    assert payload["results"][0]["custom_data"] == {}


@pytest.mark.django_db
def test_alpha_candidate_list_success_contract(authenticated_client):
    candidate = _candidate()
    repository = type(
        "CandidateRepository",
        (),
        {"get_actionable": lambda self: [candidate]},
    )()

    with patch(
        "apps.alpha_trigger.interface.views.get_alpha_candidate_repository",
        return_value=repository,
    ):
        response = authenticated_client.get("/api/alpha-triggers/candidates/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["results"][0]["candidate_id"] == "candidate-001"
    assert payload["results"][0]["status"] == "ACTIONABLE"
    assert payload["results"][0]["custom_data"] == {}


@pytest.mark.django_db
def test_alpha_candidate_detail_success_contract(authenticated_client):
    candidate = _candidate()
    repository = type(
        "CandidateRepository",
        (),
        {
            "get_by_id": lambda self, candidate_id: (
                candidate if candidate_id == "candidate-001" else None
            )
        },
    )()

    with patch(
        "apps.alpha_trigger.interface.views.get_alpha_candidate_repository",
        return_value=repository,
    ):
        response = authenticated_client.get("/api/alpha-triggers/candidates/candidate-001/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["result"]["candidate_id"] == "candidate-001"
    assert payload["result"]["asset_code"] == "600519.SH"
    assert payload["result"]["custom_data"] == {}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    (
        "days=0",
        "days=366",
        "days=not-an-integer",
        "window_days=30",
    ),
)
def test_alpha_trigger_performance_rejects_invalid_or_unknown_query(
    authenticated_client,
    query,
):
    response = authenticated_client.get(f"/api/alpha-triggers/performance/?{query}")

    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("endpoint", "days"),
    [
        ("/api/alpha-triggers/triggers/statistics/", "not-an-integer"),
        ("/api/alpha-triggers/triggers/statistics/", "0"),
        ("/api/alpha-triggers/triggers/statistics/", "366"),
        ("/api/alpha-triggers/candidates/statistics/", "not-an-integer"),
        ("/api/alpha-triggers/candidates/statistics/", "0"),
        ("/api/alpha-triggers/candidates/statistics/", "366"),
    ],
)
def test_alpha_trigger_statistics_reject_invalid_days(
    authenticated_client,
    endpoint,
    days,
):
    response = authenticated_client.get(endpoint, {"days": days})

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_alpha_trigger_performance_is_pure_read_with_stable_contract(
    authenticated_client,
):
    trigger = AlphaTriggerModel.objects.create(
        trigger_id="trigger-performance-001",
        trigger_type="MOMENTUM_SIGNAL",
        asset_code="600519.SH",
        asset_class="a_share",
        direction="LONG",
        trigger_condition={"signal": "cross_up"},
        confidence=0.82,
        status="ACTIVE",
    )
    AlphaCandidateModel.objects.create(
        candidate_id="candidate-performance-executed",
        trigger_id=trigger.trigger_id,
        asset_code=trigger.asset_code,
        asset_class=trigger.asset_class,
        direction="LONG",
        strength="STRONG",
        confidence=0.82,
        status="EXECUTED",
    )
    AlphaCandidateModel.objects.create(
        candidate_id="candidate-performance-watch",
        trigger_id=trigger.trigger_id,
        asset_code=trigger.asset_code,
        asset_class=trigger.asset_class,
        direction="LONG",
        strength="MODERATE",
        confidence=0.68,
        status="WATCH",
    )
    trigger_before = list(AlphaTriggerModel.objects.order_by("id").values_list("id", "created_at"))
    candidate_before = list(
        AlphaCandidateModel.objects.order_by("id").values_list(
            "id",
            "created_at",
            "updated_at",
        )
    )

    response = authenticated_client.get(
        "/api/alpha-triggers/performance/" "?days=30&trigger_id=trigger-performance-001"
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "data": [
            {
                "trigger_id": "trigger-performance-001",
                "asset_code": "600519.SH",
                "trigger_type": "MOMENTUM_SIGNAL",
                "total_candidates": 2,
                "executed": 1,
                "invalidated": 0,
                "conversion_rate": 50.0,
                "invalidation_rate": 0.0,
            }
        ],
        "summary": {
            "days": 30,
            "trigger_id": "trigger-performance-001",
            "total_triggers": 1,
        },
    }
    assert (
        list(AlphaTriggerModel.objects.order_by("id").values_list("id", "created_at"))
        == trigger_before
    )
    assert (
        list(
            AlphaCandidateModel.objects.order_by("id").values_list(
                "id",
                "created_at",
                "updated_at",
            )
        )
        == candidate_before
    )


@pytest.mark.django_db
def test_alpha_trigger_create_rejects_invalid_confidence(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha-triggers/create/",
        {
            "trigger_type": "MOMENTUM_SIGNAL",
            "asset_code": "600519.SH",
            "asset_class": "a_share_growth",
            "direction": "LONG",
            "trigger_condition": {"signal": "cross_up"},
            "confidence": 1.5,
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "confidence" in payload["error"]


@pytest.mark.django_db
def test_alpha_trigger_check_invalidation_requires_indicator_values(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha-triggers/check-invalidation/",
        {"trigger_id": "trigger-001"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "current_indicator_values" in payload["error"]


@pytest.mark.django_db
def test_alpha_trigger_evaluate_requires_current_data(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha-triggers/evaluate/",
        {"trigger_id": "trigger-001"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "current_data" in payload["error"]


@pytest.mark.django_db
def test_alpha_trigger_update_status_rejects_invalid_status(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha-triggers/candidates/candidate-001/update-status/",
        {"status": "NOT_A_STATUS"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "status" in payload["error"]


@pytest.mark.django_db
def test_alpha_trigger_partial_update_persists_rule_and_recomputes_strength(
    authenticated_client,
):
    AlphaTriggerModel.objects.create(
        trigger_id="trigger-update-001",
        trigger_type="MOMENTUM_SIGNAL",
        asset_code="600519.SH",
        asset_class="a_share",
        direction="LONG",
        trigger_condition={"signal": "cross_up"},
        confidence=0.55,
        status="ACTIVE",
    )

    response = authenticated_client.patch(
        "/api/alpha-triggers/triggers/trigger-update-001/",
        {
            "asset_class": "a_share_consumer",
            "direction": "NEUTRAL",
            "trigger_condition": {"signal": "cooling"},
            "invalidation_conditions": [
                {
                    "condition_type": "threshold_cross",
                    "indicator_code": "CN_PMI_MANUFACTURING",
                    "threshold": 50.0,
                    "direction": "below",
                }
            ],
            "confidence": 0.86,
            "thesis": "Momentum is cooling; wait for confirmation.",
            "related_regime": "Slowdown",
            "related_policy_level": 2,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["result"]["strength"] == "very_strong"
    trigger = AlphaTriggerModel.objects.get(trigger_id="trigger-update-001")
    assert trigger.asset_class == "a_share_consumer"
    assert trigger.direction == "NEUTRAL"
    assert trigger.trigger_condition == {"signal": "cooling"}
    assert trigger.invalidation_conditions[0]["indicator_code"] == "CN_PMI_MANUFACTURING"
    assert trigger.confidence == 0.86
    assert trigger.strength == "VERY_STRONG"
    assert trigger.related_regime == "Slowdown"
    assert trigger.related_policy_level == 2


@pytest.mark.django_db
def test_alpha_trigger_pause_resume_and_cancel_enforce_lifecycle(authenticated_client):
    AlphaTriggerModel.objects.create(
        trigger_id="trigger-lifecycle-001",
        trigger_type="MOMENTUM_SIGNAL",
        asset_code="600519.SH",
        asset_class="a_share",
        direction="LONG",
        trigger_condition={"signal": "cross_up"},
        confidence=0.75,
        status="ACTIVE",
    )

    paused = authenticated_client.post(
        "/api/alpha-triggers/triggers/trigger-lifecycle-001/pause/",
        {},
        format="json",
    )
    invalid_pause = authenticated_client.post(
        "/api/alpha-triggers/triggers/trigger-lifecycle-001/pause/",
        {},
        format="json",
    )
    resumed = authenticated_client.post(
        "/api/alpha-triggers/triggers/trigger-lifecycle-001/resume/",
        {},
        format="json",
    )
    cancelled = authenticated_client.delete(
        "/api/alpha-triggers/triggers/trigger-lifecycle-001/"
    )
    invalid_resume = authenticated_client.post(
        "/api/alpha-triggers/triggers/trigger-lifecycle-001/resume/",
        {},
        format="json",
    )

    assert paused.status_code == 200
    assert paused.json()["result"]["status"] == "paused"
    assert invalid_pause.status_code == 400
    assert resumed.status_code == 200
    assert resumed.json()["result"]["status"] == "active"
    assert cancelled.status_code == 200
    assert cancelled.json()["result"]["status"] == "cancelled"
    assert invalid_resume.status_code == 400
    assert (
        AlphaTriggerModel.objects.get(trigger_id="trigger-lifecycle-001").status
        == "CANCELLED"
    )
