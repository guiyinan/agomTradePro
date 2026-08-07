"""No-data contract tests for exact R3 monitoring and governed reads."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.macro_factor.application.governed_read import (
    R3GovernedReadBlockerCode,
    R3GovernedReadStatus,
    ReadGovernedR3Output,
    ReadGovernedR3OutputCommand,
)
from apps.macro_factor.domain.governed_read import (
    R3ExperimentTrialEvidence,
    R3MonitoringEvidence,
    R3MonitoringMetricObservation,
    R3PromotionDecisionEvidence,
    R3PromotionOutcome,
    R3RegimeObservationEvidence,
    R3RegimeSegmentReport,
    artifact_selection_started_at,
    build_regime_segment_report,
    r3_trial_family_content_hash,
)
from apps.macro_factor.domain.lifecycle import MacroFactorLifecycleEvent
from apps.macro_factor.domain.reproducible_runner import (
    DatedMacroFactorOutput,
    ReproducibleMacroFactorRunArtifact,
    build_reproducible_run,
)
from tests.unit.macro_factor.factories import complete_manifest
from tests.unit.macro_factor.runner_factories import (
    external_runner_artifact,
    runner_dataset,
    runner_spec,
)


class _Ledger:
    def __init__(
        self,
        artifact: ReproducibleMacroFactorRunArtifact,
        outputs: tuple[DatedMacroFactorOutput, ...],
        events: tuple[MacroFactorLifecycleEvent, ...],
    ) -> None:
        self.artifact = artifact
        self.outputs = outputs
        self.events = events

    def get_artifact(self, artifact_id: str) -> ReproducibleMacroFactorRunArtifact | None:
        return self.artifact if artifact_id == self.artifact.artifact_id else None

    def list_outputs(self, artifact_id: str) -> tuple[DatedMacroFactorOutput, ...]:
        return self.outputs if artifact_id == self.artifact.artifact_id else ()

    def list_lifecycle_events(
        self,
        artifact_id: str,
    ) -> tuple[MacroFactorLifecycleEvent, ...]:
        return self.events if artifact_id == self.artifact.artifact_id else ()


class _RegimeProvider:
    def __init__(self, report: R3RegimeSegmentReport | None) -> None:
        self.report = report
        self.calls: list[tuple[str, str, datetime]] = []

    def get_report(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> R3RegimeSegmentReport | None:
        self.calls.append((artifact_id, expected_artifact_hash, as_of))
        return self.report


class _TrialProvider:
    def __init__(self, trial: R3ExperimentTrialEvidence | None) -> None:
        self.trial = trial
        self.calls: list[tuple[str, str, datetime]] = []

    def get_trial(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> R3ExperimentTrialEvidence | None:
        self.calls.append((artifact_id, expected_artifact_hash, as_of))
        return self.trial


class _PromotionProvider:
    def __init__(self, decision: R3PromotionDecisionEvidence | None) -> None:
        self.decision = decision
        self.calls: list[tuple[str, str, datetime]] = []

    def get_decision(
        self,
        *,
        trial_id: str,
        expected_trial_hash: str,
        as_of: datetime,
    ) -> R3PromotionDecisionEvidence | None:
        self.calls.append((trial_id, expected_trial_hash, as_of))
        return self.decision


class _MonitoringProvider:
    def __init__(self, evidence: R3MonitoringEvidence | None) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, str, datetime]] = []

    def get_monitoring(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> R3MonitoringEvidence | None:
        self.calls.append((artifact_id, expected_artifact_hash, as_of))
        return self.evidence


@dataclass(frozen=True)
class _Case:
    ledger: _Ledger
    report: R3RegimeSegmentReport
    trial: R3ExperimentTrialEvidence
    decision: R3PromotionDecisionEvidence
    monitoring: R3MonitoringEvidence
    command: ReadGovernedR3OutputCommand


def _regime_observations(
    artifact: ReproducibleMacroFactorRunArtifact,
) -> tuple[R3RegimeObservationEvidence, ...]:
    return (
        R3RegimeObservationEvidence(
            owner="regime",
            artifact_id=artifact.artifact_id,
            artifact_hash=artifact.content_hash,
            fold_id="wf-1",
            row_id="pit-row-6",
            observation_at=datetime(2020, 2, 5, tzinfo=UTC),
            actual_available_at=datetime(2020, 3, 1, tzinfo=UTC),
            actual_value=Decimal("6"),
            actual_fact_id="growth-actual-2020-02",
            actual_fact_hash="6" * 64,
            predicted_value=Decimal("5.5"),
            regime_code="growth",
            regime_version="regime-growth-v1",
            regime_content_hash="7" * 64,
            regime_effective_at=datetime(2019, 12, 1, tzinfo=UTC),
            regime_available_at=datetime(2020, 2, 10, tzinfo=UTC),
        ),
        R3RegimeObservationEvidence(
            owner="regime",
            artifact_id=artifact.artifact_id,
            artifact_hash=artifact.content_hash,
            fold_id="wf-2",
            row_id="pit-row-7",
            observation_at=datetime(2021, 2, 5, tzinfo=UTC),
            actual_available_at=datetime(2021, 3, 1, tzinfo=UTC),
            actual_value=Decimal("7"),
            actual_fact_id="growth-actual-2021-02",
            actual_fact_hash="8" * 64,
            predicted_value=Decimal("6.5"),
            regime_code="slowdown",
            regime_version="regime-slowdown-v1",
            regime_content_hash="9" * 64,
            regime_effective_at=datetime(2020, 12, 1, tzinfo=UTC),
            regime_available_at=datetime(2021, 2, 10, tzinfo=UTC),
        ),
    )


def _monitoring_observations(
    first_value: Decimal = Decimal("0.20"),
    second_value: Decimal = Decimal("0.18"),
) -> tuple[R3MonitoringMetricObservation, ...]:
    return (
        R3MonitoringMetricObservation(
            metric_name="out_of_sample.r_squared",
            observation_window="rolling-12m",
            observed_at=datetime(2026, 5, 31, tzinfo=UTC),
            available_at=datetime(2026, 6, 1, tzinfo=UTC),
            value=first_value,
            source_fact_id="monitor-oos-r2-2026-05",
            source_fact_hash="a" * 64,
        ),
        R3MonitoringMetricObservation(
            metric_name="out_of_sample.r_squared",
            observation_window="rolling-12m",
            observed_at=datetime(2026, 6, 30, tzinfo=UTC),
            available_at=datetime(2026, 7, 2, 11, tzinfo=UTC),
            value=second_value,
            source_fact_id="monitor-oos-r2-2026-06",
            source_fact_hash="b" * 64,
        ),
    )


def _case() -> _Case:
    external = external_runner_artifact()
    bundle = build_reproducible_run(
        runner_spec(),
        runner_dataset(),
        complete_manifest(),
        external,
    )
    artifact = bundle.artifact
    report = build_regime_segment_report(
        artifact,
        _regime_observations(artifact),
        evaluated_at=datetime(2026, 7, 2, 12, tzinfo=UTC),
    )
    family_registered_at = datetime(2014, 12, 1, tzinfo=UTC)
    family_trial_ids = ("trial-growth-1", "trial-growth-2")
    trial = R3ExperimentTrialEvidence(
        owner="research",
        capability="macro_factor_r3",
        purpose="oos_promotion_trial",
        trial_id="trial-growth-1",
        trial_version="trial-growth-v1",
        family_id="growth-nowcast-family",
        family_version="growth-family-v1",
        family_content_hash=r3_trial_family_content_hash(
            family_id="growth-nowcast-family",
            family_version="growth-family-v1",
            family_trial_ids=family_trial_ids,
            registered_at=family_registered_at,
        ),
        family_trial_ids=family_trial_ids,
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        source_result_hash=artifact.source_result_hash,
        external_artifact_hash=artifact.external_artifact_hash,
        pit_manifest_id=artifact.pit_manifest_id,
        pit_manifest_hash=artifact.pit_manifest_hash,
        dataset_hash=artifact.dataset_hash,
        split_contract_hash=artifact.split_contract_hash,
        plan_hash=artifact.plan_hash,
        regime_report_hash=report.content_hash,
        minimum_regime_count=2,
        registered_at=family_registered_at,
        selection_started_at=artifact_selection_started_at(artifact),
        evaluated_at=datetime(2026, 7, 3, 9, tzinfo=UTC),
        valid_until=datetime(2026, 7, 9, tzinfo=UTC),
    )
    decision = R3PromotionDecisionEvidence.create(
        decision_id="promotion-growth-1",
        decision_version="promotion-v1",
        trial_id=trial.trial_id,
        trial_hash=trial.content_hash,
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        regime_report_hash=report.content_hash,
        outcome=R3PromotionOutcome.APPROVED,
        authorization_id="research-owner-authorization-1",
        decided_at=datetime(2026, 7, 3, 10, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 3, 11, tzinfo=UTC),
        valid_until=datetime(2026, 7, 9, tzinfo=UTC),
    )
    monitoring = R3MonitoringEvidence(
        owner_ref=external.result.retirement_policy.owner_ref,
        evidence_id="monitor-growth-2026-07",
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        source_result_hash=artifact.source_result_hash,
        policy=external.result.retirement_policy,
        evaluated_at=datetime(2026, 7, 4, tzinfo=UTC),
        valid_until=datetime(2026, 7, 8, tzinfo=UTC),
        observations=_monitoring_observations(),
    )
    output = bundle.outputs[0]
    return _Case(
        ledger=_Ledger(artifact, bundle.outputs, bundle.lifecycle_events),
        report=report,
        trial=trial,
        decision=decision,
        monitoring=monitoring,
        command=ReadGovernedR3OutputCommand(
            artifact_id=artifact.artifact_id,
            expected_artifact_hash=artifact.content_hash,
            output_id=output.output_id,
            expected_output_hash=output.content_hash,
            as_of=datetime(2026, 7, 5, tzinfo=UTC),
        ),
    )


def _execute(
    case: _Case,
    *,
    report: R3RegimeSegmentReport | None = None,
    trial: R3ExperimentTrialEvidence | None = None,
    decision: R3PromotionDecisionEvidence | None = None,
    monitoring: R3MonitoringEvidence | None = None,
    use_default_report: bool = True,
    use_default_trial: bool = True,
    use_default_decision: bool = True,
    use_default_monitoring: bool = True,
):
    regime_provider = _RegimeProvider(case.report if use_default_report else report)
    trial_provider = _TrialProvider(case.trial if use_default_trial else trial)
    promotion_provider = _PromotionProvider(case.decision if use_default_decision else decision)
    monitoring_provider = _MonitoringProvider(
        case.monitoring if use_default_monitoring else monitoring
    )
    assessment = ReadGovernedR3Output(
        ledger=case.ledger,
        regime_provider=regime_provider,
        trial_provider=trial_provider,
        promotion_provider=promotion_provider,
        monitoring_provider=monitoring_provider,
    ).execute(case.command)
    return assessment, regime_provider, trial_provider, promotion_provider, monitoring_provider


def test_complete_exact_projection_remains_research_only_and_not_current() -> None:
    case = _case()

    assessment, regime, trial, promotion, monitoring = _execute(case)

    assert assessment.status is R3GovernedReadStatus.EVIDENCE_COMPLETE
    assert assessment.blocker_codes == ()
    assert assessment.projection is not None
    assert assessment.projection.valid_until == case.monitoring.valid_until
    assert assessment.projection.research_only is True
    assert assessment.projection.publishes_current is False
    assert assessment.projection.decision_authorized is False
    assert assessment.projection.execution_authorized is False
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_execute is True
    expected_call = (
        case.ledger.artifact.artifact_id,
        case.ledger.artifact.content_hash,
        case.command.as_of,
    )
    assert regime.calls == [expected_call]
    assert trial.calls == [expected_call]
    assert promotion.calls == [(case.trial.trial_id, case.trial.content_hash, case.command.as_of)]
    assert monitoring.calls == [expected_call]


def test_regime_report_recalculates_complete_oos_coverage_and_metrics() -> None:
    case = _case()

    assert tuple(item.regime_code for item in case.report.segments) == ("growth", "slowdown")
    assert tuple(item.metrics.sample_count for item in case.report.segments) == (1, 1)
    assert tuple(item.metrics.mean_absolute_error for item in case.report.segments) == (
        Decimal("0.5"),
        Decimal("0.5"),
    )
    with pytest.raises(ValueError, match="exactly cover"):
        build_regime_segment_report(
            case.ledger.artifact,
            case.report.observations[:1],
            evaluated_at=case.report.evaluated_at,
        )
    changed_prediction = replace(case.report.observations[0], predicted_value=Decimal("99"))
    with pytest.raises(ValueError, match="changed an OOS prediction"):
        build_regime_segment_report(
            case.ledger.artifact,
            (changed_prediction, case.report.observations[1]),
            evaluated_at=case.report.evaluated_at,
        )


def test_tampered_regime_report_blocks_before_trial_lookup() -> None:
    case = _case()
    changed = replace(case.report.observations[0], actual_value=Decimal("60"))
    tampered = replace(case.report, observations=(changed, case.report.observations[1]))

    assessment, _, trial, promotion, monitoring = _execute(
        case,
        report=tampered,
        use_default_report=False,
    )

    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.REGIME_REPORT_INVALID,)
    assert trial.calls == []
    assert promotion.calls == []
    assert monitoring.calls == []


def test_exact_trial_and_promotion_substitution_fail_closed() -> None:
    case = _case()
    with pytest.raises(ValueError, match="family hash"):
        replace(case.trial, family_content_hash="0" * 64)
    with pytest.raises(ValueError, match="authorization hash"):
        replace(case.decision, authorization_hash="0" * 64)

    wrong_trial = replace(case.trial, regime_report_hash="e" * 64)
    assessment, *_ = _execute(case, trial=wrong_trial, use_default_trial=False)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.TRIAL_INVALID,)

    rejected = R3PromotionDecisionEvidence.create(
        decision_id=case.decision.decision_id,
        decision_version=case.decision.decision_version,
        trial_id=case.decision.trial_id,
        trial_hash=case.decision.trial_hash,
        artifact_id=case.decision.artifact_id,
        artifact_hash=case.decision.artifact_hash,
        regime_report_hash=case.decision.regime_report_hash,
        outcome=R3PromotionOutcome.REJECTED,
        authorization_id=case.decision.authorization_id,
        decided_at=case.decision.decided_at,
        recorded_at=case.decision.recorded_at,
        valid_until=case.decision.valid_until,
    )
    assessment, *_ = _execute(case, decision=rejected, use_default_decision=False)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.PROMOTION_NOT_APPROVED,)

    wrong_decision = R3PromotionDecisionEvidence.create(
        decision_id=case.decision.decision_id,
        decision_version=case.decision.decision_version,
        trial_id=case.decision.trial_id,
        trial_hash=case.decision.trial_hash,
        artifact_id=case.decision.artifact_id,
        artifact_hash="f" * 64,
        regime_report_hash=case.decision.regime_report_hash,
        outcome=case.decision.outcome,
        authorization_id=case.decision.authorization_id,
        decided_at=case.decision.decided_at,
        recorded_at=case.decision.recorded_at,
        valid_until=case.decision.valid_until,
    )
    assessment, *_ = _execute(case, decision=wrong_decision, use_default_decision=False)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.PROMOTION_INVALID,)


def test_missing_owner_evidence_never_defaults_to_success() -> None:
    case = _case()

    assessment, *_ = _execute(case, use_default_report=False)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.REGIME_REPORT_MISSING,)

    assessment, *_ = _execute(case, use_default_trial=False)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.TRIAL_MISSING,)

    assessment, *_ = _execute(case, use_default_decision=False)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.PROMOTION_MISSING,)

    assessment, *_ = _execute(case, use_default_monitoring=False)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.MONITORING_MISSING,)


def test_monitoring_is_recalculated_from_policy_owner_facts() -> None:
    case = _case()
    incomplete = replace(case.monitoring, observations=case.monitoring.observations[:1])
    assessment, *_ = _execute(
        case,
        monitoring=incomplete,
        use_default_monitoring=False,
    )
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.MONITORING_INCOMPLETE,)

    breached = replace(
        case.monitoring, observations=_monitoring_observations(Decimal("0.01"), Decimal("0.02"))
    )
    assessment, *_ = _execute(case, monitoring=breached, use_default_monitoring=False)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.RETIREMENT_REVIEW_REQUIRED,)


def test_stale_output_blocks_before_any_external_owner_lookup() -> None:
    case = _case()
    stale_command = replace(
        case.command,
        as_of=case.ledger.outputs[0].valid_until,
    )
    stale_case = replace(case, command=stale_command)

    assessment, regime, trial, promotion, monitoring = _execute(stale_case)

    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.OUTPUT_INACTIVE,)
    assert regime.calls == []
    assert trial.calls == []
    assert promotion.calls == []
    assert monitoring.calls == []


def test_future_artifact_and_expired_promotion_are_pit_blocked() -> None:
    case = _case()
    future_case = replace(
        case,
        command=replace(
            case.command,
            as_of=case.ledger.artifact.produced_at - timedelta(seconds=1),
        ),
    )
    assessment, regime, *_ = _execute(future_case)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.ARTIFACT_FUTURE,)
    assert regime.calls == []

    extended_trial = replace(
        case.trial,
        valid_until=datetime(2026, 7, 10, tzinfo=UTC),
    )
    expired_decision = R3PromotionDecisionEvidence.create(
        decision_id=case.decision.decision_id,
        decision_version=case.decision.decision_version,
        trial_id=extended_trial.trial_id,
        trial_hash=extended_trial.content_hash,
        artifact_id=case.decision.artifact_id,
        artifact_hash=case.decision.artifact_hash,
        regime_report_hash=case.decision.regime_report_hash,
        outcome=R3PromotionOutcome.APPROVED,
        authorization_id=case.decision.authorization_id,
        decided_at=case.decision.decided_at,
        recorded_at=case.decision.recorded_at,
        valid_until=datetime(2026, 7, 6, tzinfo=UTC),
    )
    expired_case = replace(
        case,
        trial=extended_trial,
        decision=expired_decision,
        command=replace(case.command, as_of=datetime(2026, 7, 7, tzinfo=UTC)),
    )
    assessment, *_ = _execute(expired_case)
    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.PROMOTION_INACTIVE,)


def test_monitoring_rejects_future_owner_knowledge_at_construction() -> None:
    case = _case()
    future_observation = replace(
        case.monitoring.observations[1],
        available_at=case.monitoring.evaluated_at + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="future knowledge"):
        replace(
            case.monitoring,
            observations=(case.monitoring.observations[0], future_observation),
        )


def test_governed_read_requires_exact_hash_identities() -> None:
    case = _case()
    wrong_hash = replace(case.command, expected_output_hash="0" * 64)
    assessment = ReadGovernedR3Output(
        ledger=case.ledger,
        regime_provider=_RegimeProvider(case.report),
        trial_provider=_TrialProvider(case.trial),
        promotion_provider=_PromotionProvider(case.decision),
        monitoring_provider=_MonitoringProvider(case.monitoring),
    ).execute(wrong_hash)

    assert assessment.blocker_codes == (R3GovernedReadBlockerCode.OUTPUT_MISMATCH,)
    with pytest.raises(ValueError, match="sha256"):
        replace(case.command, artifact_id="latest")
