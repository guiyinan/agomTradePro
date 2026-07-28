from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.research.infrastructure.models import (
    DatasetSplitSpec,
    ExperimentTrial,
    MetricObservation,
    MultipleTestFamily,
    PromotionDecision,
    ResearchExperiment,
)


def _trial_payload(
    experiment_id: str,
    *,
    family_id: str = "family-1",
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "family_id": family_id,
        "planned_trial_count": 1,
        "status": "completed",
        "pit_manifest_id": "manifest-1",
        "backtest_id": None,
        "backtest_trust_status": "exploratory",
        "code_commit": "a" * 40,
        "dependency_lock_hash": "b" * 64,
        "engine_version": "engine-v1",
        "parameters": {"lookback": 20},
        "random_seed": 7,
        "benchmark_spec": {"asset": "000300.SH"},
        "cost_spec": {"bps": 10},
        "slippage_spec": {"bps": 5},
        "universe_spec": {"manifest": "csi300-v1"},
        "split_spec": {
            "training_window": {"start": "2018-01-01", "end": "2021-12-31"},
            "validation_window": {"start": "2022-01-01", "end": "2022-12-31"},
            "out_of_sample_window": {"start": "2023-01-01", "end": "2024-12-31"},
            "walk_forward_windows": [{"train": "2018-2022", "test": "2023"}],
            "embargo_days": 5,
        },
        "metrics": [
            {
                "metric_name": "sharpe_ratio",
                "value": 1.2,
                "sample_count": 504,
                "confidence_interval_low": 1.0,
                "confidence_interval_high": 1.4,
                "p_value": 0.02,
                "metadata": {"skewness": 0.0, "excess_kurtosis": 0.0},
            }
        ],
    }


def _assert_json_response(response: Any, expected_status: int) -> dict[str, Any]:
    assert response.status_code == expected_status
    assert response.headers["Content-Type"].startswith("application/json")
    return response.json()


@pytest.mark.django_db
def test_owner_can_register_trial_with_complete_evidence(
    api_client: APIClient,
    auth_user: Any,
) -> None:
    api_client.force_authenticate(user=auth_user)
    experiment = _assert_json_response(
        api_client.post(
            "/api/research/experiments/",
            {
                "question": "Does the signal survive out of sample?",
                "hypothesis": "The signal retains positive risk-adjusted returns.",
            },
            format="json",
        ),
        201,
    )

    trial = _assert_json_response(
        api_client.post(
            "/api/research/trials/",
            _trial_payload(experiment["experiment_id"]),
            format="json",
        ),
        201,
    )

    assert ResearchExperiment.objects.get(pk=experiment["experiment_id"]).owner_id == auth_user.pk
    assert ExperimentTrial.objects.filter(pk=trial["trial_id"]).exists()
    assert DatasetSplitSpec.objects.filter(trial_id=trial["trial_id"]).exists()
    assert MetricObservation.objects.filter(trial_id=trial["trial_id"]).count() == 1


@pytest.mark.django_db
def test_other_user_cannot_register_trial_for_owned_experiment(
    api_client: APIClient,
    auth_user: Any,
) -> None:
    other_user = get_user_model().objects.create_user(username="research-other")
    experiment = ResearchExperiment.objects.create(
        experiment_id="owned-experiment",
        question="Owner boundary",
        hypothesis="Only the owner can append immutable evidence.",
        owner=auth_user,
    )
    api_client.force_authenticate(user=other_user)

    _assert_json_response(
        api_client.post(
            "/api/research/trials/",
            _trial_payload(experiment.experiment_id),
            format="json",
        ),
        403,
    )

    assert ExperimentTrial.objects.count() == 0
    assert MultipleTestFamily.objects.count() == 0
    assert DatasetSplitSpec.objects.count() == 0
    assert MetricObservation.objects.count() == 0


@pytest.mark.django_db
def test_other_user_cannot_evaluate_or_mutate_owned_trial(
    api_client: APIClient,
    auth_user: Any,
) -> None:
    other_user = get_user_model().objects.create_user(username="research-evaluator")
    experiment = ResearchExperiment.objects.create(
        experiment_id="promotion-owned-experiment",
        question="Promotion boundary",
        hypothesis="Only an authorized actor can trigger state changes.",
        owner=auth_user,
    )
    api_client.force_authenticate(user=auth_user)
    trial = _assert_json_response(
        api_client.post(
            "/api/research/trials/",
            _trial_payload(experiment.experiment_id, family_id="promotion-family"),
            format="json",
        ),
        201,
    )
    api_client.force_authenticate(user=other_user)

    _assert_json_response(
        api_client.post(f"/api/research/trials/{trial['trial_id']}/promotion/"),
        403,
    )

    assert PromotionDecision.objects.count() == 0
    assert ExperimentTrial.objects.get(pk=trial["trial_id"]).status == "completed"


@pytest.mark.django_db
@pytest.mark.parametrize("owner_kind", ["other", "system"])
def test_staff_can_operate_on_owned_or_system_research(
    api_client: APIClient,
    auth_user: Any,
    owner_kind: str,
) -> None:
    staff_user = get_user_model().objects.create_user(
        username=f"research-staff-{owner_kind}",
        is_staff=True,
    )
    experiment = ResearchExperiment.objects.create(
        experiment_id=f"staff-{owner_kind}-experiment",
        question="Staff operations",
        hypothesis="Staff may maintain governed research evidence.",
        owner=auth_user if owner_kind == "other" else None,
    )
    api_client.force_authenticate(user=staff_user)

    trial = _assert_json_response(
        api_client.post(
            "/api/research/trials/",
            _trial_payload(
                experiment.experiment_id,
                family_id=f"staff-{owner_kind}-family",
            ),
            format="json",
        ),
        201,
    )
    decision = _assert_json_response(
        api_client.post(f"/api/research/trials/{trial['trial_id']}/promotion/"),
        200,
    )

    assert decision["trial_id"] == trial["trial_id"]
    assert decision["decision"] == "rejected"


@pytest.mark.django_db
def test_missing_research_records_return_not_found(
    api_client: APIClient,
    auth_user: Any,
) -> None:
    api_client.force_authenticate(user=auth_user)

    _assert_json_response(
        api_client.post(
            "/api/research/trials/",
            _trial_payload("missing-experiment"),
            format="json",
        ),
        404,
    )
    _assert_json_response(
        api_client.post("/api/research/trials/missing-trial/promotion/"),
        404,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("nested_target", ["top", "split", "metric"])
def test_trial_api_rejects_unknown_fields(
    api_client: APIClient,
    auth_user: Any,
    nested_target: str,
) -> None:
    experiment = ResearchExperiment.objects.create(
        experiment_id=f"unknown-{nested_target}",
        question="Strict evidence",
        hypothesis="Unknown evidence is rejected.",
        owner=auth_user,
    )
    payload = _trial_payload(experiment.experiment_id)
    if nested_target == "top":
        payload["unexpected"] = True
    elif nested_target == "split":
        payload["split_spec"]["unexpected"] = True
    else:
        payload["metrics"][0]["unexpected"] = True
    api_client.force_authenticate(user=auth_user)

    _assert_json_response(
        api_client.post("/api/research/trials/", payload, format="json"),
        400,
    )

    assert ExperimentTrial.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("value", float("nan")),
        ("value", float("inf")),
        ("p_value", 1.1),
        ("confidence_interval_low", 2.0),
    ],
)
def test_trial_api_rejects_invalid_metric_evidence(
    api_client: APIClient,
    auth_user: Any,
    field: str,
    value: float,
) -> None:
    experiment = ResearchExperiment.objects.create(
        experiment_id=f"bad-metric-{field}-{str(value).replace('.', '-')}",
        question="Finite evidence",
        hypothesis="Malformed metrics never reach persistence.",
        owner=auth_user,
    )
    payload = _trial_payload(experiment.experiment_id)
    payload["metrics"][0][field] = value
    api_client.force_authenticate(user=auth_user)

    if math.isfinite(value):
        response = api_client.post("/api/research/trials/", payload, format="json")
    else:
        response = api_client.post(
            "/api/research/trials/",
            json.dumps(payload),
            content_type="application/json",
        )
    _assert_json_response(response, 400)

    assert ExperimentTrial.objects.count() == 0


@pytest.mark.django_db
def test_trial_api_rejects_duplicate_metrics_and_oversized_json(
    api_client: APIClient,
    auth_user: Any,
) -> None:
    experiment = ResearchExperiment.objects.create(
        experiment_id="bounded-evidence",
        question="Bounded evidence",
        hypothesis="Duplicate and oversized evidence is rejected.",
        owner=auth_user,
    )
    api_client.force_authenticate(user=auth_user)
    duplicate = _trial_payload(experiment.experiment_id)
    duplicate["metrics"].append(deepcopy(duplicate["metrics"][0]))
    _assert_json_response(
        api_client.post("/api/research/trials/", duplicate, format="json"),
        400,
    )

    oversized = _trial_payload(experiment.experiment_id)
    for field in (
        "parameters",
        "benchmark_spec",
        "cost_spec",
        "slippage_spec",
        "universe_spec",
    ):
        oversized[field] = {"payload": "x" * 60_000}
    _assert_json_response(
        api_client.post("/api/research/trials/", oversized, format="json"),
        400,
    )

    assert ExperimentTrial.objects.count() == 0
