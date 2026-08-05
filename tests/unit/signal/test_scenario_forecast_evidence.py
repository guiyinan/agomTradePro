"""Unit contracts for scenario-bound forecast evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from apps.signal.application.forecast_use_cases import (
    FinalizeForecastOutcomeUseCase,
    ListScenarioForecastOutcomeEvidenceUseCase,
    RecordForecastLedgerEntryUseCase,
)
from apps.signal.domain.forecast_scenario_evidence import (
    ScenarioForecastBinding,
    ScenarioForecastOutcomeEvidence,
    ScenarioProbabilitySource,
)


class _Repository:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.finalized: dict[str, Any] | None = None
        self.listed: dict[str, Any] | None = None
        self.outcomes: tuple[ScenarioForecastOutcomeEvidence, ...] = ()

    def create_entry(self, **kwargs: Any) -> Any:
        self.created = kwargs
        return SimpleNamespace(entry_id="scenario-forecast", status="open")

    def record_evaluation(self, **kwargs: Any) -> Any:
        raise AssertionError("not used")

    def finalize_outcome(self, **kwargs: Any) -> Any:
        self.finalized = kwargs
        return SimpleNamespace(entry_id=kwargs["entry_id"])

    def list_scenario_outcomes(self, **kwargs: Any) -> tuple[ScenarioForecastOutcomeEvidence, ...]:
        self.listed = kwargs
        return self.outcomes


def _entry_payload(revision_id: UUID, set_revision_id: UUID | None) -> dict[str, Any]:
    published_at = datetime(2026, 8, 1, tzinfo=UTC)
    return {
        "entry_id": "scenario-forecast",
        "published_at": published_at,
        "direction": "NEUTRAL",
        "asset_code": "000300.SH",
        "horizon_end": published_at + timedelta(days=30),
        "benchmark_asset": "000300.SH",
        "probability": 0.55,
        "invalidation_rule_version": "rule-v1",
        "decision_snapshot_id": "decision-v1",
        "pit_manifest_id": "manifest-v1",
        "source": "scenario_research",
        "scenario_revision_id": str(revision_id),
        "scenario_set_revision_id": (str(set_revision_id) if set_revision_id is not None else None),
        "subjective_probability": "0.35",
        "subjective_probability_source_version": "committee-2026-08",
    }


def test_binding_keeps_subjective_and_promoted_model_probabilities_separate() -> None:
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=uuid4(),
        scenario_set_revision_id=uuid4(),
        subjective_probability="0.35",
        subjective_probability_source_version="committee-v2",
        model_probability="0.42",
        model_probability_source_version="scenario-model-v4",
        model_promotion_decision_id="promotion-v4",
    )

    assert binding.subjective_probability == Decimal("0.35")
    assert binding.model_probability == Decimal("0.42")
    assert binding.has_model_probability is True
    with pytest.raises(ValueError, match="requires source version and promotion"):
        ScenarioForecastBinding.from_values(
            scenario_revision_id=uuid4(),
            scenario_set_revision_id=None,
            subjective_probability="0.35",
            subjective_probability_source_version="committee-v2",
            model_probability="0.42",
        )


def test_record_use_case_rejects_unknown_scenario_reference_before_persistence() -> None:
    repository = _Repository()
    payload = _entry_payload(uuid4(), uuid4())

    with pytest.raises(ValueError, match="approved Risk Center reference"):
        RecordForecastLedgerEntryUseCase(
            repository,
            scenario_reference_checker=lambda revision_id, set_revision_id: False,
        ).execute(**payload)

    assert repository.created is None


def test_record_use_case_requires_approved_promotion_for_model_probability() -> None:
    repository = _Repository()
    payload = {
        **_entry_payload(uuid4(), uuid4()),
        "model_probability": "0.42",
        "model_probability_source_version": "scenario-model-v4",
        "model_promotion_decision_id": "promotion-v4",
    }

    def valid_reference(revision_id: str, set_revision_id: str | None) -> bool:
        return True

    with pytest.raises(ValueError, match="approved research promotion"):
        RecordForecastLedgerEntryUseCase(
            repository,
            scenario_reference_checker=valid_reference,
            research_promotion_checker=lambda decision_id: False,
        ).execute(**payload)

    assert repository.created is None
    RecordForecastLedgerEntryUseCase(
        repository,
        scenario_reference_checker=valid_reference,
        research_promotion_checker=lambda decision_id: decision_id == "promotion-v4",
    ).execute(**payload)
    assert repository.created is not None
    assert repository.created["probability"] == 0.55
    assert repository.created["subjective_probability"] == Decimal("0.35")
    assert repository.created["model_probability"] == Decimal("0.42")


def test_finalize_and_query_use_cases_keep_scenario_realization_explicit() -> None:
    repository = _Repository()
    revision_id = uuid4()
    set_revision_id = uuid4()
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=revision_id,
        scenario_set_revision_id=set_revision_id,
        subjective_probability="0.35",
        subjective_probability_source_version="committee-v2",
    )
    repository.outcomes = (
        ScenarioForecastOutcomeEvidence(
            entry_id="scenario-forecast",
            binding=binding,
            finalized_at=datetime(2026, 9, 1, tzinfo=UTC),
            scenario_realized=True,
            subjective_brier_score=0.4225,
            model_brier_score=None,
        ),
    )

    FinalizeForecastOutcomeUseCase(repository).execute(
        entry_id="scenario-forecast",
        finalized_at=datetime(2026, 9, 1, tzinfo=UTC),
        outcome_type="expired",
        asset_return=None,
        benchmark_return=None,
        neutral_band=0.01,
        scenario_realized=True,
    )
    result = ListScenarioForecastOutcomeEvidenceUseCase(repository).execute(
        scenario_revision_id=str(revision_id),
        scenario_set_revision_id=str(set_revision_id),
        probability_source="subjective",
    )

    assert repository.finalized is not None
    assert repository.finalized["scenario_realized"] is True
    assert repository.listed == {
        "scenario_revision_id": revision_id,
        "scenario_set_revision_id": set_revision_id,
        "probability_source": ScenarioProbabilitySource.SUBJECTIVE,
    }
    assert result[0].score_for(ScenarioProbabilitySource.SUBJECTIVE) == 0.4225
    assert result[0].score_for(ScenarioProbabilitySource.MODEL_INFERRED) is None


def test_finalize_rejects_non_boolean_scenario_realization() -> None:
    repository = _Repository()

    with pytest.raises(ValueError, match="scenario_realized"):
        FinalizeForecastOutcomeUseCase(repository).execute(
            entry_id="scenario-forecast",
            finalized_at=datetime(2026, 9, 1, tzinfo=UTC),
            outcome_type="expired",
            asset_return=None,
            benchmark_return=None,
            neutral_band=0.01,
            scenario_realized=cast(bool, "yes"),
        )

    assert repository.finalized is None


def test_outcome_evidence_rejects_naive_time_and_invalid_scores() -> None:
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=uuid4(),
        scenario_set_revision_id=None,
        subjective_probability="0.35",
        subjective_probability_source_version="committee-v2",
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        ScenarioForecastOutcomeEvidence(
            entry_id="scenario-forecast",
            binding=binding,
            finalized_at=datetime(2026, 9, 1),
            scenario_realized=True,
            subjective_brier_score=0.4,
            model_brier_score=None,
        )
    with pytest.raises(ValueError, match="within"):
        ScenarioForecastOutcomeEvidence(
            entry_id="scenario-forecast",
            binding=binding,
            finalized_at=datetime(2026, 9, 1, tzinfo=UTC),
            scenario_realized=True,
            subjective_brier_score=1.1,
            model_brier_score=None,
        )
