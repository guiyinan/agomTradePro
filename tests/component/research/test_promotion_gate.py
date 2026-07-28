from datetime import UTC, date, datetime

import pytest

from apps.backtest.infrastructure.models import BacktestResultModel
from apps.data_center.domain.pit import (
    KnowledgeScope,
    PITDatasetManifest,
    calculate_pit_manifest_hash,
)
from apps.data_center.infrastructure.pit_models import (
    PITDatasetManifestModel,
    PITFactVersionModel,
)
from apps.research.domain.contracts import TrialRegistrationPayload
from apps.research.infrastructure.models import (
    DatasetSplitSpec,
    MetricObservation,
    ResearchExperiment,
)
from apps.research.infrastructure.repositories import ResearchRegistryRepository


def _payload_hash(payload: dict) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _create_verified_manifest() -> None:
    fact = PITFactVersionModel.objects.create(
        dataset="price_bar",
        business_key="000300.SH:2024-12-31",
        effective_at=datetime(2024, 12, 31, tzinfo=UTC),
        available_at=datetime(2024, 12, 31, tzinfo=UTC),
        ingested_at=datetime(2024, 12, 31, tzinfo=UTC),
        source_record_id="benchmark-close",
        content_hash="e" * 64,
        pit_quality="verified",
        payload={"close": "4000"},
    )
    selected_versions = [
        {
            "id": fact.pk,
            "dataset": fact.dataset,
            "business_key": fact.business_key,
            "content_hash": fact.content_hash,
            "payload_hash": _payload_hash(fact.payload),
            "pit_quality": fact.pit_quality,
        }
    ]
    manifest = PITDatasetManifest(
        manifest_id="manifest-verified",
        as_of_time=datetime(2025, 1, 1, tzinfo=UTC),
        knowledge_scope=KnowledgeScope.PUBLIC,
        calendar_version="sse-v1",
        query_spec={"price_bar": {}},
        selected_versions=tuple(selected_versions),
        coverage={"price_bar": 1.0},
        missing=(),
        estimated=(),
        unknown=(),
        manifest_hash="",
    )
    PITDatasetManifestModel.objects.create(
        manifest_id=manifest.manifest_id,
        as_of_time=manifest.as_of_time,
        knowledge_scope=manifest.knowledge_scope.value,
        calendar_version=manifest.calendar_version,
        query_spec=manifest.query_spec,
        selected_versions=selected_versions,
        coverage=manifest.coverage,
        missing=[],
        estimated=[],
        unknown=[],
        manifest_hash=calculate_pit_manifest_hash(manifest),
    )


def _create_verified_backtest(trial_id: str) -> int:
    return BacktestResultModel.objects.create(
        name=trial_id,
        status="completed",
        start_date=date(2023, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital="1000000",
        rebalance_frequency="monthly",
        use_pit_data=True,
        data_manifest_id="manifest-verified",
        trust_status="pit_verified",
        research_trial_id=trial_id,
    ).pk


def _trial_payload(
    trial_id: str,
    family_id: str,
    backtest_id: int,
) -> TrialRegistrationPayload:
    return {
        "experiment_id": "experiment-1",
        "family_id": family_id,
        "planned_trial_count": 2,
        "status": "completed",
        "pit_manifest_id": "manifest-verified",
        "backtest_id": backtest_id,
        "backtest_trust_status": "pit_verified",
        "code_commit": "a" * 40,
        "dependency_lock_hash": "b" * 64,
        "engine_version": "engine-v1",
        "parameters": {"lookback": 20 if trial_id.endswith("1") else 40},
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
                "value": 2.0,
                "sample_count": 504,
                "p_value": 0.001,
                "metadata": {"skewness": 0.0, "excess_kurtosis": 0.0},
            }
        ],
    }


@pytest.mark.django_db
def test_promotion_requires_complete_declared_family_and_records_q_value() -> None:
    ResearchExperiment.objects.create(
        experiment_id="experiment-1",
        question="Does the signal survive out of sample?",
        hypothesis="The signal has positive risk-adjusted return.",
    )
    _create_verified_manifest()
    repository = ResearchRegistryRepository()
    repository.create_trial(
        _trial_payload("trial-1", "family-1", _create_verified_backtest("trial-1")),
        trial_id="trial-1",
        actor_user_id=1,
        actor_is_staff=True,
    )
    repository.create_trial(
        _trial_payload("trial-2", "family-1", _create_verified_backtest("trial-2")),
        trial_id="trial-2",
        actor_user_id=1,
        actor_is_staff=True,
    )

    decision = repository.evaluate_promotion("trial-1", actor_user_id=1, actor_is_staff=True)

    assert decision.decision == "approved"
    assert decision.evidence["actual_trial_count"] == 2
    assert decision.evidence["q_value"] == pytest.approx(0.001)
    assert decision.evidence["deflated_sharpe"] >= 0.95
    assert MetricObservation.objects.get(trial_id="trial-1").q_value == pytest.approx(0.001)


@pytest.mark.django_db
def test_promotion_rejects_unregistered_family_trials() -> None:
    ResearchExperiment.objects.create(
        experiment_id="experiment-1",
        question="Completeness gate",
        hypothesis="All planned trials are registered.",
    )
    _create_verified_manifest()
    repository = ResearchRegistryRepository()
    repository.create_trial(
        _trial_payload("trial-1", "family-1", _create_verified_backtest("trial-1")),
        trial_id="trial-1",
        actor_user_id=1,
        actor_is_staff=True,
    )

    decision = repository.evaluate_promotion("trial-1", actor_user_id=1, actor_is_staff=True)

    assert decision.decision == "rejected"
    assert "family_trial_count_mismatch" in decision.evidence["reasons"]


@pytest.mark.django_db
def test_failed_family_trial_is_retained_without_fabricating_metrics() -> None:
    ResearchExperiment.objects.create(
        experiment_id="experiment-1",
        question="Failed-trial completeness",
        hypothesis="A failed parameter run remains visible in the declared family.",
    )
    _create_verified_manifest()
    repository = ResearchRegistryRepository()
    repository.create_trial(
        _trial_payload("trial-1", "family-1", _create_verified_backtest("trial-1")),
        trial_id="trial-1",
        actor_user_id=1,
        actor_is_staff=True,
    )
    failed = _trial_payload("trial-2", "family-1", _create_verified_backtest("trial-2"))
    failed["status"] = "failed"
    failed["metrics"] = []
    repository.create_trial(
        failed,
        trial_id="trial-2",
        actor_user_id=1,
        actor_is_staff=True,
    )

    decision = repository.evaluate_promotion("trial-1", actor_user_id=1, actor_is_staff=True)

    assert decision.decision == "approved"
    assert decision.evidence["actual_trial_count"] == 2


@pytest.mark.django_db
def test_family_identity_cannot_change_after_registration() -> None:
    ResearchExperiment.objects.create(
        experiment_id="experiment-1",
        question="Family identity",
        hypothesis="The declared family size is immutable.",
    )
    _create_verified_manifest()
    repository = ResearchRegistryRepository()
    repository.create_trial(
        _trial_payload("trial-1", "family-1", _create_verified_backtest("trial-1")),
        trial_id="trial-1",
        actor_user_id=1,
        actor_is_staff=True,
    )
    conflicting = _trial_payload("trial-2", "family-1", _create_verified_backtest("trial-2"))
    conflicting["planned_trial_count"] = 3

    with pytest.raises(ValueError, match="different evidence"):
        repository.create_trial(
            conflicting,
            trial_id="trial-2",
            actor_user_id=1,
            actor_is_staff=True,
        )


@pytest.mark.django_db
def test_promotion_rejects_legacy_trial_with_missing_split_without_crashing() -> None:
    ResearchExperiment.objects.create(
        experiment_id="experiment-1",
        question="Legacy split evidence",
        hypothesis="Missing split evidence prevents promotion.",
    )
    _create_verified_manifest()
    repository = ResearchRegistryRepository()
    repository.create_trial(
        _trial_payload("trial-1", "family-1", _create_verified_backtest("trial-1")),
        trial_id="trial-1",
        actor_user_id=1,
        actor_is_staff=True,
    )
    DatasetSplitSpec._default_manager.filter(trial_id="trial-1").delete()

    decision = repository.evaluate_promotion("trial-1", actor_user_id=1, actor_is_staff=True)

    assert decision.decision == "rejected"
    assert "missing_split_spec" in decision.evidence["reasons"]


@pytest.mark.django_db
def test_promotion_rejects_nonfinite_legacy_metric_without_crashing() -> None:
    ResearchExperiment.objects.create(
        experiment_id="experiment-1",
        question="Legacy metric evidence",
        hypothesis="Nonfinite persisted metrics prevent promotion.",
    )
    _create_verified_manifest()
    repository = ResearchRegistryRepository()
    for trial_id in ("trial-1", "trial-2"):
        repository.create_trial(
            _trial_payload(
                trial_id,
                "family-1",
                _create_verified_backtest(trial_id),
            ),
            trial_id=trial_id,
            actor_user_id=1,
            actor_is_staff=True,
        )
    MetricObservation._default_manager.filter(
        trial_id="trial-1",
        metric_name="sharpe_ratio",
    ).update(value=float("inf"))

    decision = repository.evaluate_promotion("trial-1", actor_user_id=1, actor_is_staff=True)

    assert decision.decision == "rejected"
    assert "nonfinite_metric_evidence" in decision.evidence["reasons"]
