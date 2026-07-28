from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.research.application.use_cases import EvaluatePromotion, RunTrial
from apps.research.domain.contracts import TrialRegistrationPayload


@dataclass
class _TrialView:
    trial_id: str
    experiment_id: str
    family_id: str
    status: str
    parameter_hash: str = "hash"
    pit_manifest_id: str = "manifest-1"


@dataclass
class _ExperimentView:
    experiment_id: str
    question: str
    hypothesis: str
    status: str = "draft"


@dataclass
class _DecisionView:
    decision_id: str
    trial_id: str
    decision: str
    evidence: dict[str, object]
    decided_at: datetime


class _FakeResearchRegistry:
    def __init__(self) -> None:
        self.created_payload: TrialRegistrationPayload | None = None
        self.created_trial_id: str | None = None
        self.actor_user_id: int | None = None
        self.actor_is_staff: bool | None = None
        self.create_trial_calls = 0
        self.evaluate_calls = 0

    def create_experiment(
        self,
        *,
        experiment_id: str,
        question: str,
        hypothesis: str,
        owner_id: int | None,
    ) -> _ExperimentView:
        return _ExperimentView(experiment_id, question, hypothesis)

    def create_trial(
        self,
        payload: TrialRegistrationPayload,
        *,
        trial_id: str,
        actor_user_id: int,
        actor_is_staff: bool,
    ) -> _TrialView:
        self.create_trial_calls += 1
        self.created_payload = deepcopy(payload)
        self.created_trial_id = trial_id
        self.actor_user_id = actor_user_id
        self.actor_is_staff = actor_is_staff
        return _TrialView(
            trial_id=trial_id,
            experiment_id=payload["experiment_id"],
            family_id=payload["family_id"],
            status=payload["status"],
            pit_manifest_id=payload["pit_manifest_id"],
        )

    def evaluate_promotion(
        self,
        trial_id: str,
        *,
        actor_user_id: int,
        actor_is_staff: bool,
    ) -> _DecisionView:
        self.evaluate_calls += 1
        self.actor_user_id = actor_user_id
        self.actor_is_staff = actor_is_staff
        return _DecisionView(
            decision_id="decision-1",
            trial_id=trial_id,
            decision="rejected",
            evidence={},
            decided_at=datetime(2026, 7, 28, tzinfo=UTC),
        )


def _trial_payload() -> dict[str, object]:
    return {
        "experiment_id": "experiment-1",
        "family_id": "family-1",
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
                "p_value": 0.02,
                "metadata": {"skewness": 0.0},
            }
        ],
    }


def test_run_trial_detaches_payload_and_passes_exact_actor_context() -> None:
    repository = _FakeResearchRegistry()
    payload = _trial_payload()
    original = deepcopy(payload)

    trial = RunTrial(repository).execute(
        payload,
        actor_user_id=42,
        actor_is_staff=True,
    )

    assert payload == original
    assert repository.created_payload == original
    assert repository.created_payload is not payload
    assert repository.created_trial_id == trial.trial_id
    assert repository.created_trial_id is not None
    assert len(repository.created_trial_id) == 32
    assert repository.actor_user_id == 42
    assert repository.actor_is_staff is True


@pytest.mark.parametrize("actor_user_id", [0, -1, True])
def test_run_trial_rejects_invalid_actor_before_repository_call(
    actor_user_id: object,
) -> None:
    repository = _FakeResearchRegistry()

    with pytest.raises(ValueError, match="actor_user_id"):
        RunTrial(repository).execute(
            _trial_payload(),
            actor_user_id=cast(int, actor_user_id),
        )

    assert repository.create_trial_calls == 0


def test_evaluate_promotion_rejects_non_boolean_staff_flag_before_repository_call() -> None:
    repository = _FakeResearchRegistry()

    with pytest.raises(ValueError, match="actor_is_staff"):
        EvaluatePromotion(repository).execute(
            "trial-1",
            actor_user_id=1,
            actor_is_staff=cast(bool, 1),
        )

    assert repository.evaluate_calls == 0


@pytest.mark.parametrize("field", ["experiment_id", "split_spec", "metrics"])
def test_run_trial_rejects_missing_governed_fields(field: str) -> None:
    repository = _FakeResearchRegistry()
    payload = _trial_payload()
    del payload[field]

    with pytest.raises(ValueError, match="missing fields"):
        RunTrial(repository).execute(payload, actor_user_id=1)

    assert repository.create_trial_calls == 0


def test_run_trial_rejects_unknown_fields_without_mutating_input() -> None:
    repository = _FakeResearchRegistry()
    payload = _trial_payload()
    payload["trial_id"] = "caller-controlled"
    original = deepcopy(payload)

    with pytest.raises(ValueError, match="unknown fields"):
        RunTrial(repository).execute(payload, actor_user_id=1)

    assert payload == original
    assert repository.create_trial_calls == 0
