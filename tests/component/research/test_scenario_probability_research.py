"""Component contract for the R7 research packet application boundary."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.research.application.scenario_probability_research import (
    BuildScenarioProbabilityResearchPacketUseCase,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ResearchEvidenceStatus,
    ScenarioInvalidationEvidence,
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_evidence import (
    HistoricalAnalogyStudyEvidence,
    ScenarioPathStudyEvidence,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
SET_REVISION = UUID("00000000-0000-0000-0000-000000000100")
REVISION_A = UUID("00000000-0000-0000-0000-000000000001")
REVISION_B = UUID("00000000-0000-0000-0000-000000000002")


def _scope() -> ScenarioResearchScope:
    return ScenarioResearchScope.create(
        scope_version="scenario-scope.v1",
        scenario_set_revision_id=SET_REVISION,
        scenario_revision_ids=(REVISION_A, REVISION_B),
        forecast_horizon=timedelta(days=10),
        censoring_rule_version="scenario-censoring.v1",
        path_horizon_periods=2,
        path_initial_state_revision_ids=(REVISION_A, REVISION_B),
    )


def _policy() -> ScenarioProbabilityResearchPolicy:
    return ScenarioProbabilityResearchPolicy.create(
        policy_version="scenario-calibration-policy.v1",
        activated_at=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        sample_window_start=NOW - timedelta(days=30),
        sample_window_end=NOW,
        forecast_horizon=timedelta(days=10),
        censoring_lag=timedelta(days=7),
        censoring_rule_version="scenario-censoring.v1",
        minimum_forecasts_per_revision=2,
        minimum_resolved_outcomes_per_revision=2,
        minimum_outcome_coverage=Decimal("0.80"),
        minimum_binary_class_observations=1,
        minimum_multiclass_groups=2,
        minimum_multiclass_class_observations=1,
        maximum_outcome_evidence_age=timedelta(days=365),
        calibration_bin_edges=(Decimal("0"), Decimal("0.5"), Decimal("1")),
        probability_sum_tolerance=Decimal("0.000001"),
        minimum_historical_analogies=2,
        minimum_path_probability_observations=10,
        path_horizon_periods=2,
        require_all_path_initial_states=True,
        maximum_research_evidence_age=timedelta(days=90),
        invalidation_review_delay=timedelta(days=1),
        approved_by="research-owner",
    )


def _open_observations() -> tuple[ForecastLedgerOutcomeObservation, ...]:
    published_at = NOW - timedelta(days=5)
    invalidation = ScenarioInvalidationEvidence.create(
        evidence_version="scenario-invalidation.v1",
        scenario_revision_id=REVISION_A,
        scenario_set_revision_id=SET_REVISION,
        invalidated_at=NOW - timedelta(hours=1),
        invalidation_rule_version="scenario-rule.v3",
        pit_manifest_id="pit-invalidation-v1",
        evidence_refs=("evidence://scenario-invalidated",),
    )

    def observation(
        revision_id: UUID,
        probability: str,
        invalidation_evidence: ScenarioInvalidationEvidence | None,
    ) -> ForecastLedgerOutcomeObservation:
        binding = ScenarioForecastBinding.from_values(
            scenario_revision_id=revision_id,
            scenario_set_revision_id=SET_REVISION,
            subjective_probability=probability,
            subjective_probability_source_version="committee-v1",
        )
        return ForecastLedgerOutcomeObservation.create(
            observation_version="ledger-observation.v1",
            entry_id=f"open-{revision_id}",
            forecast_group_id="open-group",
            binding=binding,
            pit_manifest_id="pit-open-group",
            pit_manifest_version="pit-manifest.v1",
            pit_manifest_hash=hashlib.sha256(b"pit-open-group").hexdigest(),
            censoring_rule_version="scenario-censoring.v1",
            published_at=published_at,
            horizon_end=published_at + timedelta(days=10),
            scenario_realized=None,
            outcome_recorded_at=None,
            outcome_evidence_valid_until=None,
            invalidation=invalidation_evidence,
        )

    return (
        observation(REVISION_A, "0.40", invalidation),
        observation(REVISION_B, "0.60", None),
    )


class _PolicyProvider:
    calls: list[tuple[ScenarioResearchScope, datetime]] = []

    def get_active(
        self,
        *,
        scope: ScenarioResearchScope,
        evaluated_at: datetime,
    ) -> ScenarioProbabilityResearchPolicy:
        self.calls.append((scope, evaluated_at))
        return _policy()


class _ForecastProvider:
    calls: list[tuple[ScenarioResearchScope, datetime, datetime, datetime]] = []

    def list_for_scope(
        self,
        *,
        scope: ScenarioResearchScope,
        window_start: datetime,
        window_end: datetime,
        evaluated_at: datetime,
    ) -> tuple[ForecastLedgerOutcomeObservation, ...]:
        self.calls.append((scope, window_start, window_end, evaluated_at))
        return _open_observations()


class _AnalogyProvider:
    def get_for_scope(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> HistoricalAnalogyStudyEvidence | None:
        assert scope == _scope()
        assert as_of == NOW
        return None


class _PathProvider:
    def get_for_scope(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> ScenarioPathStudyEvidence | None:
        assert scope == _scope()
        assert as_of == NOW
        return None


def test_empty_outcome_packet_is_safe_and_emits_only_internal_review_intent() -> None:
    policy_provider = _PolicyProvider()
    forecast_provider = _ForecastProvider()
    packet = BuildScenarioProbabilityResearchPacketUseCase(
        policy_provider=policy_provider,
        forecast_evidence_provider=forecast_provider,
        historical_analogy_provider=_AnalogyProvider(),
        path_evidence_provider=_PathProvider(),
    ).execute(scope=_scope(), evaluated_at=NOW)

    assert packet.calibration.subjective.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert packet.calibration.subjective.revision_metrics == ()
    assert packet.calibration.model_inferred.revision_metrics == ()
    assert packet.historical_analogy.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert packet.path_research.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert len(packet.review_reminder_intents) == 1
    assert packet.review_reminder_intents[0].dispatch_requested is False
    assert packet.trains_probability_model is False
    assert packet.dispatches_reminders is False
    assert packet.research_only is True
    assert packet.must_not_use_for_decision is True
    assert len(packet.content_hash) == 64
    assert policy_provider.calls == [(_scope(), NOW)]
    assert forecast_provider.calls == [
        (
            _scope(),
            _policy().sample_window_start,
            _policy().sample_window_end,
            NOW,
        )
    ]
