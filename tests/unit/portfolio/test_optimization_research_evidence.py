"""Domain invariants for governed R8 result and lifecycle evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.application.governed_optimization import (
    AppendGovernedOptimizationLifecycleEventUseCase,
)
from apps.portfolio.domain._optimization_canonical import hash_components
from apps.portfolio.domain.constrained_optimization import (
    CandidateEvaluation,
    CandidateMetrics,
    OptimizationBlocker,
    OptimizationBlockerCode,
)
from apps.portfolio.domain.constrained_optimization_contracts import (
    CandidateKind,
    SolverConvergenceStatus,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleOwnerAttestation,
    OptimizationResearchLifecycleEvent,
    create_optimization_lifecycle_event,
    create_optimization_lifecycle_root,
    derive_optimization_lifecycle_state,
    optimization_lifecycle_event_hash_values,
)
from apps.portfolio.domain.optimization_research_result import (
    GovernedCandidateEvidence,
    GovernedOptimizationResearchResult,
    GovernedOptimizationResultStatus,
    governed_result_hash_values,
)

NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)
LATER = NOW + timedelta(days=30)


def _decimal(value: str, *, scaled: bool) -> Decimal:
    return Decimal(f"{value}0" if scaled else value)


def _evaluation(
    kind: CandidateKind,
    objective: str,
    *,
    scaled: bool = False,
    eligible: bool = True,
    weights: tuple[Decimal, ...] | None = None,
    cash_weight: Decimal | None = None,
) -> CandidateEvaluation:
    metrics = CandidateMetrics(
        expected_return=_decimal("0.08", scaled=scaled),
        variance=_decimal("0.02", scaled=scaled),
        transaction_cost=_decimal("0.001", scaled=scaled),
        turnover=_decimal("0.2", scaled=scaled),
        drawdown_estimate=_decimal("0.12", scaled=scaled),
        scenario_losses=(("scenario-r8", _decimal("0.1", scaled=scaled)),),
        macro_factor_variance=_decimal("0.02", scaled=scaled),
        macro_contribution_shares=(
            ("growth", _decimal("0.6", scaled=scaled)),
            ("inflation", _decimal("0.4", scaled=scaled)),
        ),
        macro_max_target_deviation=_decimal("0.1", scaled=scaled),
        objective_value=_decimal(objective, scaled=scaled),
    )
    blockers = (
        ()
        if eligible
        else (
            OptimizationBlocker(
                code=OptimizationBlockerCode.CASH_REQUIREMENT_BREACHED,
                detail="current configuration breaches the governed cash requirement",
            ),
        )
    )
    return CandidateEvaluation(
        candidate_kind=kind,
        eligible_for_comparison=eligible,
        weights=(
            weights
            if weights is not None
            else (
                _decimal("0.4", scaled=scaled),
                _decimal("0.5", scaled=scaled),
            )
        ),
        cash_weight=(cash_weight if cash_weight is not None else _decimal("0.1", scaled=scaled)),
        solver_status=SolverConvergenceStatus.BASELINE,
        solver_iterations=0,
        solver_residual=_decimal("0.0", scaled=scaled),
        solver_detail="sealed deterministic evidence",
        metrics=metrics,
        blockers=blockers,
        evidence_hash=hash_components("candidate-source.v1", kind.value),
    )


def _all_evaluations(
    *,
    current_eligible: bool = True,
) -> tuple[CandidateEvaluation, ...]:
    return (
        _evaluation(
            CandidateKind.CURRENT_CONFIGURATION,
            "0.01",
            eligible=current_eligible,
        ),
        _evaluation(CandidateKind.EQUAL_WEIGHT, "0.04"),
        _evaluation(CandidateKind.ASSET_RISK_PARITY, "0.03"),
        _evaluation(CandidateKind.DETERMINISTIC_SEARCH, "0.02"),
    )


def _result(
    *,
    current_eligible: bool = True,
    run_version: str = "run.v1",
) -> GovernedOptimizationResearchResult:
    return GovernedOptimizationResearchResult.create(
        run_key="governed-r8-run",
        run_version=run_version,
        assembly_hash="1" * 64,
        problem_id="problem:r8:v1",
        problem_hash="2" * 64,
        input_set_id="input-set:r8:v1",
        input_set_hash="3" * 64,
        candidate_evaluations=_all_evaluations(current_eligible=current_eligible),
        problem_blockers=(),
        evaluated_at=NOW,
        valid_until=LATER,
    )


def _promotion(
    result: GovernedOptimizationResearchResult,
    *,
    owner: str = "research",
    approved_at: datetime = NOW + timedelta(hours=1),
) -> ExactPromotionAttestation:
    return ExactPromotionAttestation.create(
        capability_key="r8",
        artifact_id=result.result_id,
        artifact_version=result.result_version,
        artifact_content_hash=result.content_hash,
        decision_id="promotion:r8:v1",
        decision_content_hash="4" * 64,
        owner=owner,
        approved_at=approved_at,
        valid_until=LATER,
    )


class _ExactPromotionProvider:
    def __init__(self, promotions: tuple[ExactPromotionAttestation, ...]) -> None:
        self._records = {(item.capability_key, item.decision_id): item for item in promotions}

    def get_exact(
        self,
        *,
        capability_key: str,
        decision_id: str,
        evaluated_at: datetime,
    ) -> ExactPromotionAttestation | None:
        del evaluated_at
        return self._records.get((capability_key, decision_id))


class _ExactOwnerAuthorizationProvider:
    def __init__(
        self,
        attestations: tuple[OptimizationLifecycleOwnerAttestation, ...],
    ) -> None:
        self._records = {item.attestation_id: item for item in attestations}

    def get_exact(
        self,
        *,
        attestation_id: str,
        result_id: str,
        result_hash: str,
        event_type: OptimizationLifecycleEventType,
        evaluated_at: datetime,
    ) -> OptimizationLifecycleOwnerAttestation | None:
        del evaluated_at
        candidate = self._records.get(attestation_id)
        if candidate is None or (
            candidate.result_id != result_id
            or candidate.result_hash != result_hash
            or candidate.event_type is not event_type
        ):
            return None
        return candidate


class _LifecycleRepository:
    def __init__(self) -> None:
        self.appended: list[OptimizationResearchLifecycleEvent] = []

    def append_lifecycle_event(
        self,
        event: OptimizationResearchLifecycleEvent,
    ) -> OptimizationResearchLifecycleEvent:
        self.appended.append(event)
        return event


def test_current_configuration_participates_in_selection_and_completeness() -> None:
    completed = _result()

    assert completed.status is GovernedOptimizationResultStatus.COMPLETED
    assert completed.selected_candidate is CandidateKind.CURRENT_CONFIGURATION

    blocked = _result(current_eligible=False)

    assert blocked.status is GovernedOptimizationResultStatus.BLOCKED
    assert blocked.selected_candidate is None


def test_rehashed_status_and_selection_tampering_still_fail_restore() -> None:
    result = _result()
    blocked_hash = governed_result_hash_values(
        result_version=result.result_version,
        run_key=result.run_key,
        run_version=result.run_version,
        assembly_hash=result.assembly_hash,
        problem_id=result.problem_id,
        problem_hash=result.problem_hash,
        input_set_id=result.input_set_id,
        input_set_hash=result.input_set_hash,
        status=GovernedOptimizationResultStatus.BLOCKED,
        candidates=result.candidates,
        selected_candidate=None,
        problem_blockers=result.problem_blockers,
        evaluated_at=result.evaluated_at,
        valid_until=result.valid_until,
    )
    with pytest.raises(ValueError, match="status does not match"):
        replace(
            result,
            status=GovernedOptimizationResultStatus.BLOCKED,
            selected_candidate=None,
            content_hash=blocked_hash,
        )

    wrong_selection = CandidateKind.EQUAL_WEIGHT
    selection_hash = governed_result_hash_values(
        result_version=result.result_version,
        run_key=result.run_key,
        run_version=result.run_version,
        assembly_hash=result.assembly_hash,
        problem_id=result.problem_id,
        problem_hash=result.problem_hash,
        input_set_id=result.input_set_id,
        input_set_hash=result.input_set_hash,
        status=result.status,
        candidates=result.candidates,
        selected_candidate=wrong_selection,
        problem_blockers=result.problem_blockers,
        evaluated_at=result.evaluated_at,
        valid_until=result.valid_until,
    )
    with pytest.raises(ValueError, match="selected candidate does not match"):
        replace(
            result,
            selected_candidate=wrong_selection,
            content_hash=selection_hash,
        )


def test_candidate_hash_is_decimal_scale_independent_and_weights_are_conserved() -> None:
    canonical = GovernedCandidateEvidence.from_evaluation(
        _evaluation(CandidateKind.CURRENT_CONFIGURATION, "0.01")
    )
    scaled = GovernedCandidateEvidence.from_evaluation(
        _evaluation(CandidateKind.CURRENT_CONFIGURATION, "0.01", scaled=True)
    )

    assert canonical.content_hash == scaled.content_hash

    with pytest.raises(ValueError, match="weights do not sum to one"):
        GovernedCandidateEvidence.from_evaluation(
            _evaluation(
                CandidateKind.CURRENT_CONFIGURATION,
                "0.01",
                weights=(Decimal("0.4"), Decimal("0.4")),
                cash_weight=Decimal("0.1"),
            )
        )


def test_lifecycle_requires_canonical_owners_and_matching_result_chain() -> None:
    result = _result()
    root = create_optimization_lifecycle_root(result)

    with pytest.raises(ValueError, match="owner must be portfolio"):
        OptimizationLifecycleOwnerAttestation.create(
            attestation_id="owner-attestation:r8:retire:v1",
            owner="portfolio-governance-owner",
            result_id=result.result_id,
            result_hash=result.content_hash,
            event_type=OptimizationLifecycleEventType.RETIRED,
            reason_hash=hash_components(
                "optimization-lifecycle-reasons.v1",
                "methodology_retired",
            ),
            issued_at=NOW + timedelta(hours=2),
        )

    with pytest.raises(ValueError, match="Promotion attestation does not match"):
        create_optimization_lifecycle_event(
            result=result,
            previous_events=(root,),
            event_type=OptimizationLifecycleEventType.PROMOTION_ATTESTED,
            occurred_at=NOW + timedelta(hours=1),
            recorded_at=NOW + timedelta(hours=1),
            reason_codes=("research_promotion_approved",),
            promotion_attestation=_promotion(result, owner="portfolio"),
        )

    different_result = _result(run_version="run.v2")
    with pytest.raises(ValueError, match="result identity does not match"):
        create_optimization_lifecycle_event(
            result=different_result,
            previous_events=(root,),
            event_type=OptimizationLifecycleEventType.PROMOTION_ATTESTED,
            occurred_at=NOW + timedelta(hours=1),
            recorded_at=NOW + timedelta(hours=1),
            reason_codes=("research_promotion_approved",),
            promotion_attestation=_promotion(different_result),
        )


def test_lifecycle_clocks_are_monotonic_on_create_and_restored_chains() -> None:
    result = _result()
    root = create_optimization_lifecycle_root(result)
    with pytest.raises(ValueError, match="occurred_at cannot move backwards"):
        create_optimization_lifecycle_event(
            result=result,
            previous_events=(root,),
            event_type=OptimizationLifecycleEventType.PROMOTION_ATTESTED,
            occurred_at=NOW - timedelta(minutes=1),
            recorded_at=NOW,
            reason_codes=("research_promotion_approved",),
            promotion_attestation=_promotion(
                result,
                approved_at=NOW - timedelta(hours=1),
            ),
        )

    promoted = create_optimization_lifecycle_event(
        result=result,
        previous_events=(root,),
        event_type=OptimizationLifecycleEventType.PROMOTION_ATTESTED,
        occurred_at=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=3),
        reason_codes=("research_promotion_approved",),
        promotion_attestation=_promotion(result),
    )
    reasons = ("methodology_retired",)
    owner = OptimizationLifecycleOwnerAttestation.create(
        attestation_id="owner-attestation:r8:retire:v1",
        owner="portfolio",
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=OptimizationLifecycleEventType.RETIRED,
        reason_hash=hash_components("optimization-lifecycle-reasons.v1", *reasons),
        issued_at=NOW + timedelta(hours=2),
    )
    with pytest.raises(ValueError, match="recorded_at cannot move backwards"):
        create_optimization_lifecycle_event(
            result=result,
            previous_events=(root, promoted),
            event_type=OptimizationLifecycleEventType.RETIRED,
            occurred_at=NOW + timedelta(hours=2),
            recorded_at=NOW + timedelta(hours=2),
            reason_codes=reasons,
            owner_attestation=owner,
        )

    digest = optimization_lifecycle_event_hash_values(
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=OptimizationLifecycleEventType.RETIRED,
        sequence=3,
        occurred_at=NOW + timedelta(hours=2),
        recorded_at=NOW + timedelta(hours=2),
        reason_codes=reasons,
        previous_event_hash=promoted.content_hash,
        promotion_attestation=None,
        owner_attestation=owner,
    )
    restored_regression = OptimizationResearchLifecycleEvent(
        event_id=f"optimization_lifecycle_event:{digest[:24]}",
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=OptimizationLifecycleEventType.RETIRED,
        sequence=3,
        occurred_at=NOW + timedelta(hours=2),
        recorded_at=NOW + timedelta(hours=2),
        reason_codes=reasons,
        previous_event_hash=promoted.content_hash,
        promotion_attestation=None,
        owner_attestation=owner,
        content_hash=digest,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )
    with pytest.raises(ValueError, match="recorded_at moves backwards"):
        derive_optimization_lifecycle_state((root, promoted, restored_regression))


def test_lifecycle_application_requires_exact_authoritative_providers() -> None:
    result = _result()
    root = create_optimization_lifecycle_root(result)
    promotion = _promotion(result)
    reasons = ("methodology_retired",)
    owner = OptimizationLifecycleOwnerAttestation.create(
        attestation_id="owner-attestation:r8:retire:authorized",
        owner="portfolio",
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=OptimizationLifecycleEventType.RETIRED,
        reason_hash=hash_components("optimization-lifecycle-reasons.v1", *reasons),
        issued_at=NOW + timedelta(hours=2),
    )
    repository = _LifecycleRepository()
    use_case = AppendGovernedOptimizationLifecycleEventUseCase(
        promotion_provider=_ExactPromotionProvider((promotion,)),
        owner_authorization_provider=_ExactOwnerAuthorizationProvider((owner,)),
        repository=repository,
    )

    promoted = use_case.execute(
        result=result,
        previous_events=(root,),
        event_type=OptimizationLifecycleEventType.PROMOTION_ATTESTED,
        occurred_at=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=1),
        reason_codes=("research_promotion_approved",),
        promotion_attestation=promotion,
    )
    retired = use_case.execute(
        result=result,
        previous_events=(root,),
        event_type=OptimizationLifecycleEventType.RETIRED,
        occurred_at=NOW + timedelta(hours=2),
        recorded_at=NOW + timedelta(hours=2),
        reason_codes=reasons,
        owner_attestation=owner,
    )
    assert repository.appended == [promoted, retired]

    fabricated_promotion = ExactPromotionAttestation.create(
        capability_key="r8",
        artifact_id=result.result_id,
        artifact_version=result.result_version,
        artifact_content_hash=result.content_hash,
        decision_id="promotion:r8:fabricated",
        decision_content_hash="5" * 64,
        owner="research",
        approved_at=NOW + timedelta(hours=1),
        valid_until=LATER,
    )
    with pytest.raises(ValueError, match="Promotion authorization is not authoritative"):
        use_case.execute(
            result=result,
            previous_events=(root,),
            event_type=OptimizationLifecycleEventType.PROMOTION_ATTESTED,
            occurred_at=NOW + timedelta(hours=1),
            recorded_at=NOW + timedelta(hours=1),
            reason_codes=("research_promotion_approved",),
            promotion_attestation=fabricated_promotion,
        )

    fabricated_owner = OptimizationLifecycleOwnerAttestation.create(
        attestation_id="owner-attestation:r8:retire:fabricated",
        owner="portfolio",
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=OptimizationLifecycleEventType.RETIRED,
        reason_hash=hash_components("optimization-lifecycle-reasons.v1", *reasons),
        issued_at=NOW + timedelta(hours=2),
    )
    with pytest.raises(ValueError, match="lifecycle authorization is not authoritative"):
        use_case.execute(
            result=result,
            previous_events=(root,),
            event_type=OptimizationLifecycleEventType.RETIRED,
            occurred_at=NOW + timedelta(hours=2),
            recorded_at=NOW + timedelta(hours=2),
            reason_codes=reasons,
            owner_attestation=fabricated_owner,
        )
