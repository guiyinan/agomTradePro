"""Coverage ratchet for Portfolio domain boundary and tamper branches."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.domain import _optimization_canonical as canonical
from apps.portfolio.domain import canonical_snapshots as snapshots
from apps.portfolio.domain import constrained_optimization as constrained
from apps.portfolio.domain import constrained_optimization_contracts as optimization
from apps.portfolio.domain import governed_input_set as governed_inputs
from apps.portfolio.domain import macro_factor_risk as macro_risk
from apps.portfolio.domain import macro_risk_rolling_contracts as rolling
from apps.portfolio.domain import optimization_lifecycle as lifecycle
from apps.portfolio.domain import optimizer_inputs as optimizer_inputs
from apps.portfolio.domain import r4_rolling_evidence as r4_evidence
from apps.portfolio.domain._optimization_canonical import hash_components
from apps.portfolio.domain.canonical_snapshots import (
    BrokerExecutionEvidence,
    BrokerFillEvidence,
    BrokerOrderEventEvidence,
    CanonicalPosition,
    SnapshotEvidenceKind,
    SnapshotSourceEvidence,
    broker_execution_evidence_hash,
)
from apps.portfolio.domain.constrained_optimization_contracts import (
    AssetCovarianceMatrix,
    AssetOptimizationConstraint,
    AssetOptimizationInput,
    CandidateKind,
    MacroRiskBudget,
    ManualRestriction,
    OptimizationObjective,
    ScenarioLossConstraint,
    SolverConvergenceStatus,
    build_asset_universe_hash,
    build_solver_output,
)
from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind
from apps.portfolio.domain.macro_risk_rolling_contracts import (
    R4MethodBacktestSummary,
    R4MethodWindowMetrics,
    R4RegimeExposureSummary,
    R4RollingExposurePoint,
)
from apps.portfolio.domain.optimizer_inputs import (
    OptimizationEvidenceState,
    OptimizationInputEvidence,
    OptimizationInputKind,
    OptimizationInputRequirement,
    OptimizerInputBundle,
    OptimizerInputContract,
    PromotionReference,
)
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    build_window,
    promotion_attestation,
    rolling_policy,
)
from tests.unit.portfolio.test_constrained_optimization import (
    NOW,
    _policy,
    _problem,
)
from tests.unit.portfolio.test_governed_optimization_inputs import _input_set
from tests.unit.portfolio.test_macro_factor_risk import _allocations as macro_allocations
from tests.unit.portfolio.test_macro_factor_risk import _candidate as macro_candidate
from tests.unit.portfolio.test_macro_factor_risk import _covariance as macro_covariance
from tests.unit.portfolio.test_macro_factor_risk import _exposure as macro_exposure
from tests.unit.portfolio.test_macro_factor_risk import _policy as macro_policy
from tests.unit.portfolio.test_optimization_research_evidence import (
    _promotion as lifecycle_promotion,
)
from tests.unit.portfolio.test_optimization_research_evidence import _result as lifecycle_result

SHA = "a" * 64


def _unsafe_replace(instance, **changes):
    """Forge a nested value so the owning aggregate can verify its own guard."""

    forged = object.__new__(type(instance))
    for field in fields(instance):
        object.__setattr__(
            forged,
            field.name,
            changes.get(field.name, getattr(instance, field.name)),
        )
    return forged


@pytest.mark.parametrize("value", ["", "has space", "x" * 161])
def test_optimization_token_guard_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="bounded token"):
        optimization._require_token(value, "value")


@pytest.mark.parametrize("value", ["", " ", "x" * 513])
def test_optimization_text_guard_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="bounded non-blank text"):
        optimization._require_text(value, "value")


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), 1])
def test_optimization_decimal_guard_rejects_non_finite_values(value: object) -> None:
    with pytest.raises(ValueError, match="finite Decimal"):
        optimization._require_finite(value, "value")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "A" * 64, "0" * 63])
def test_optimization_hash_guard_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        optimization._require_sha256(value, "value")


def test_optimization_clock_guard_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        optimization._require_aware(datetime(2026, 1, 1), "value")


def _asset_input() -> AssetOptimizationInput:
    return AssetOptimizationInput(
        asset_code="asset-a",
        expected_return=Decimal("0.05"),
        minimum_weight=Decimal("0.1"),
        maximum_weight=Decimal("0.8"),
        maximum_trade_weight=Decimal("0.3"),
        transaction_cost_rate=Decimal("0.001"),
        drawdown_loss=Decimal("0.2"),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"minimum_weight": Decimal("0.9")}, "weight bounds"),
        ({"maximum_trade_weight": Decimal("1.1")}, "maximum_trade_weight"),
        ({"transaction_cost_rate": Decimal("-0.1")}, "transaction_cost_rate"),
        ({"drawdown_loss": Decimal("-0.1")}, "drawdown_loss"),
        ({"manual_restriction": "none"}, "manual_restriction"),
    ],
)
def test_asset_input_rejects_each_invalid_boundary(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_asset_input(), **changes)


def _covariance() -> AssetCovarianceMatrix:
    codes = ("asset-a", "asset-b")
    return AssetCovarianceMatrix.create(
        version="cov-v1",
        asset_codes=codes,
        values=((Decimal("1"), Decimal("0")), (Decimal("0"), Decimal("1"))),
        observed_at=NOW,
        valid_until=NOW + timedelta(days=1),
        universe_hash=build_asset_universe_hash(codes),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"valid_until": NOW}, "must follow"),
        ({"asset_codes": ()}, "non-empty and unique"),
        ({"asset_codes": ("asset-a", "asset-a")}, "non-empty and unique"),
        ({"values": ((Decimal("1"),),)}, "must be square"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_covariance_rejects_each_invalid_boundary(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_covariance(), **changes)


def _scenario() -> ScenarioLossConstraint:
    return ScenarioLossConstraint(
        scenario_revision_id="scenario-v1",
        scenario_version="v1",
        asset_codes=("asset-a", "asset-b"),
        loss_rates=(Decimal("0.1"), Decimal("0.2")),
        maximum_portfolio_loss=Decimal("0.3"),
        evidence_hash=SHA,
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"asset_codes": ()}, "non-empty and unique"),
        ({"loss_rates": (Decimal("0.1"),)}, "must align"),
        ({"loss_rates": (Decimal("-0.1"), Decimal("0.2"))}, "cannot be negative"),
        ({"maximum_portfolio_loss": Decimal("1.1")}, "within"),
    ],
)
def test_scenario_constraint_rejects_each_invalid_boundary(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_scenario(), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"expected_return_weight": Decimal("-1")}, "cannot be negative"),
        (
            {"expected_return_weight": Decimal("0"), "variance_penalty": Decimal("0")},
            "requires return or variance",
        ),
    ],
)
def test_objective_rejects_invalid_coefficients(changes: dict[str, object], message: str) -> None:
    objective = OptimizationObjective("objective-v1", Decimal("1"), Decimal("1"), Decimal("1"))
    with pytest.raises(ValueError, match=message):
        replace(objective, **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"valid_until": NOW - timedelta(days=2)}, "must follow"),
        ({"weight_tolerance": Decimal("0")}, "must be positive"),
        ({"solver_minimum_step": Decimal("1")}, "cannot exceed"),
        ({"solver_max_iterations": True}, "positive integer"),
        ({"risk_parity_max_iterations": 0}, "positive integer"),
    ],
)
def test_validation_policy_rejects_invalid_limits(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_policy(), **changes)


def _budget() -> MacroRiskBudget:
    return MacroRiskBudget.create(
        budget_version="budget-v1",
        maximum_factor_variance=Decimal("1"),
        target_contribution_shares=(
            ("growth", Decimal("0.5")),
            ("inflation", Decimal("0.5")),
        ),
        maximum_target_deviation=Decimal("0.2"),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"maximum_factor_variance": Decimal("0")}, "must be positive"),
        ({"maximum_target_deviation": Decimal("2")}, "within"),
        ({"target_contribution_shares": ()}, "non-empty, unique, and ordered"),
        (
            {"target_contribution_shares": (("growth", Decimal("1.1")),)},
            "share must be within",
        ),
        (
            {"target_contribution_shares": (("growth", Decimal("0.4")),)},
            "must sum to one",
        ),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_macro_budget_rejects_invalid_limits(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_budget(), **changes)


def _solver_output():
    return build_solver_output(
        candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
        weights=(Decimal("0.4"), Decimal("0.4")),
        cash_weight=Decimal("0.2"),
        status=SolverConvergenceStatus.LOCAL_STATIONARY,
        iterations=1,
        residual=Decimal("0.001"),
        detail="local solution",
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"iterations": True}, "iterations cannot be negative"),
        ({"iterations": -1}, "iterations cannot be negative"),
        ({"residual": Decimal("-1")}, "residual cannot be negative"),
        ({"declares_global_optimum": True}, "global optimality"),
        ({"cash_weight": None}, "present together"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_solver_output_rejects_invalid_evidence(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_solver_output(), **changes)


def test_problem_private_validators_reject_tampered_values() -> None:
    problem = _problem()
    with pytest.raises(ValueError, match="within"):
        replace(problem, minimum_cash_weight=Decimal("2"), content_hash=problem.content_hash)
    with pytest.raises(ValueError, match="cash requirement"):
        replace(
            problem,
            minimum_cash_weight=Decimal("0.3"),
            target_cash_weight=Decimal("0.2"),
            content_hash=problem.content_hash,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"current_weight": Decimal("2")}, "current_weight"),
        ({"minimum_weight": Decimal("1.1")}, "weight bounds"),
        ({"maximum_trade_weight": Decimal("2")}, "maximum_trade_weight"),
        ({"transaction_cost_rate": Decimal("-1")}, "cost and drawdown"),
        ({"drawdown_loss": Decimal("-1")}, "cost and drawdown"),
        ({"manual_restriction": "none"}, "manual_restriction"),
    ],
)
def test_asset_constraint_validator_rejects_invalid_values(
    changes: dict[str, object], message: str
) -> None:
    constraint = AssetOptimizationConstraint(
        asset_code="asset-a",
        current_weight=Decimal("0.4"),
        expected_return=Decimal("0.1"),
        minimum_weight=Decimal("0"),
        maximum_weight=Decimal("1"),
        maximum_trade_weight=Decimal("1"),
        transaction_cost_rate=Decimal("0"),
        drawdown_loss=Decimal("0.1"),
        manual_restriction=ManualRestriction.NONE,
    )
    with pytest.raises(ValueError, match=message):
        optimization._validate_asset_constraints((replace(constraint, **changes),))


@pytest.mark.parametrize("value", ["", "bad\0value", "x" * 301])
def test_rolling_text_guard_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        rolling._require_text(value, "value")


@pytest.mark.parametrize("value", ["bad", "g" * 64])
def test_rolling_hash_guard_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="sha256"):
        rolling._require_sha256(value, "value")


def test_rolling_primitive_guards_reject_naive_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        rolling._require_aware(datetime(2026, 1, 1), "value")
    with pytest.raises(ValueError, match="finite Decimal"):
        rolling._require_finite(Decimal("NaN"), "value")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"cost_treatment": "gross"}, "cost_treatment"),
        ({"weight_tolerance": Decimal("-1")}, "cannot be negative"),
        ({"maximum_condition_number": Decimal("0.5")}, "at least one"),
        ({"minimum_covariance_coverage_ratio": Decimal("0")}, "within"),
        ({"minimum_regime_windows": True}, "positive integer"),
    ],
)
def test_rolling_policy_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(rolling_policy(), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"evaluation_as_of": datetime(2026, 2, 1, tzinfo=UTC)}, "must precede"),
        ({"selection_as_of": datetime(2026, 2, 1, tzinfo=UTC)}, "follow the validation"),
        ({"selection_as_of": datetime(2026, 2, 12, tzinfo=UTC)}, "precede the OOS"),
        ({"evaluation_as_of": datetime(2026, 2, 12, tzinfo=UTC)}, "cover the OOS"),
        ({"candidates": ()}, "cannot be empty"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_rolling_window_rejects_invalid_boundaries(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(build_window(1), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"windows": (build_window(1),)}, "at least two"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_rolling_study_rejects_invalid_boundaries(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(build_study(), **changes)


def _window_metrics() -> R4MethodWindowMetrics:
    return R4MethodWindowMetrics.create(
        fold_id="fold-1",
        kind=MacroRiskCandidateKind.EQUAL_WEIGHT,
        period_returns=(Decimal("0.01"),),
        gross_return=Decimal("0.01"),
        realized_variance=Decimal("0.01"),
        maximum_drawdown=Decimal("0.1"),
        turnover=Decimal("0.1"),
        expected_cost=Decimal("0.001"),
        cost_semantics_version="gross-v1",
        candidate_report_hash=SHA,
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"period_returns": ()}, "require period returns"),
        ({"period_returns": (Decimal("-1.1"),)}, "below -100"),
        ({"realized_variance": Decimal("-1")}, "risk metrics"),
        ({"maximum_drawdown": Decimal("2")}, "risk metrics"),
        ({"turnover": Decimal("-1")}, "turnover and cost"),
        ({"expected_cost": Decimal("-1")}, "turnover and cost"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_window_metrics_reject_invalid_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_window_metrics(), **changes)


def _exposure_point() -> R4RollingExposurePoint:
    return R4RollingExposurePoint.create(
        fold_id="fold-1",
        regime_code="expansion",
        asset_code="asset-a",
        factor_code="growth",
        beta=Decimal("1"),
        confidence_low=Decimal("0.5"),
        confidence_high=Decimal("1.5"),
        residual_variance=Decimal("0.1"),
        r_squared=Decimal("0.8"),
        stability_score=Decimal("0.9"),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"beta": Decimal("2")}, "outside"),
        ({"residual_variance": Decimal("-1")}, "cannot be negative"),
        ({"r_squared": Decimal("2")}, "within"),
        ({"stability_score": Decimal("2")}, "within"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_exposure_point_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_exposure_point(), **changes)


def _regime_summary() -> R4RegimeExposureSummary:
    return R4RegimeExposureSummary.create(
        regime_code="expansion",
        asset_code="asset-a",
        factor_code="growth",
        window_count=2,
        mean_beta=Decimal("1"),
        minimum_beta=Decimal("0.5"),
        maximum_beta=Decimal("1.5"),
        mean_residual_variance=Decimal("0.1"),
        mean_r_squared=Decimal("0.8"),
        mean_stability_score=Decimal("0.9"),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"window_count": True}, "window_count"),
        ({"mean_beta": Decimal("2")}, "inconsistent"),
        ({"mean_residual_variance": Decimal("-1")}, "cannot be negative"),
        ({"mean_r_squared": Decimal("2")}, "within"),
        ({"mean_stability_score": Decimal("2")}, "within"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_regime_summary_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_regime_summary(), **changes)


def _method_summary() -> R4MethodBacktestSummary:
    return R4MethodBacktestSummary.create(
        kind=MacroRiskCandidateKind.EQUAL_WEIGHT,
        window_count=2,
        compounded_gross_return=Decimal("0.1"),
        realized_variance=Decimal("0.1"),
        maximum_drawdown=Decimal("0.1"),
        total_turnover=Decimal("0.1"),
        total_expected_cost=Decimal("0.01"),
        cost_semantics_version="gross-v1",
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"window_count": 0}, "window_count"),
        ({"realized_variance": Decimal("-1")}, "risk metrics"),
        ({"maximum_drawdown": Decimal("2")}, "risk metrics"),
        ({"total_turnover": Decimal("-1")}, "turnover and cost"),
        ({"total_expected_cost": Decimal("-1")}, "turnover and cost"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_method_summary_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_method_summary(), **changes)


@pytest.mark.parametrize("value", ["", "0" * 63, "G" * 64])
def test_snapshot_hash_guard_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        snapshots._require_sha256(value, "value")


def test_snapshot_primitive_guards_reject_missing_naive_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="required values"):
        snapshots._require_values(a="", b="ok")
    with pytest.raises(ValueError, match="timezone-aware"):
        snapshots._require_aware(datetime(2026, 1, 1), "value")
    with pytest.raises(ValueError, match="must be finite"):
        snapshots._require_finite_decimals(a=Decimal("NaN"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"quantity": Decimal("-1")}, "cannot be negative"),
        ({"available_quantity": Decimal("2")}, "cannot exceed"),
        ({"market_value_base": Decimal("-1")}, "market value"),
    ],
)
def test_canonical_position_rejects_invalid_values(
    changes: dict[str, object], message: str
) -> None:
    position = CanonicalPosition(
        asset_code="asset-a",
        quantity=Decimal("1"),
        available_quantity=Decimal("1"),
        market_value_base=Decimal("1"),
        position_source_ref="position-v1",
        position_observed_at=NOW,
        valuation_source_ref="valuation-v1",
        valuation_observed_at=NOW,
    )
    with pytest.raises(ValueError, match=message):
        replace(position, **changes)


def test_snapshot_source_rejects_ungoverned_owner() -> None:
    with pytest.raises(ValueError, match="owner is not governed"):
        SnapshotSourceEvidence(
            kind=SnapshotEvidenceKind.CASH,
            owner="portfolio",
            evidence_ref="cash-v1",
            version="v1",
            observed_at=NOW,
            content_hash=SHA,
        )


def _order_event() -> BrokerOrderEventEvidence:
    return BrokerOrderEventEvidence("event-1", "submitted", "accepted", NOW)


def _fill() -> BrokerFillEvidence:
    return BrokerFillEvidence("fill-1", Decimal("1"), Decimal("10"), Decimal("0.1"), NOW)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"quantity": Decimal("0")}, "must be positive"),
        ({"price": Decimal("0")}, "must be positive"),
        ({"fee": Decimal("-1")}, "cannot be negative"),
    ],
)
def test_broker_fill_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_fill(), **changes)


def _broker_evidence(*, rejected: bool = False) -> BrokerExecutionEvidence:
    events = (_order_event(),)
    fills = () if rejected else (_fill(),)
    broker_ref = "" if rejected else "broker-order-1"
    rejection_code = "rejected" if rejected else ""
    rejection_reason = "risk guard" if rejected else ""
    observed = NOW + timedelta(minutes=1)
    digest = broker_execution_evidence_hash(
        client_order_ref="client-order-1",
        broker_order_ref=broker_ref,
        order_events=events,
        fills=fills,
        reconciliation_ref="reconciliation-1",
        reconciliation_observed_at=observed,
        rejected=rejected,
        rejection_code=rejection_code,
        rejection_reason=rejection_reason,
    )
    return BrokerExecutionEvidence(
        client_order_ref="client-order-1",
        broker_order_ref=broker_ref,
        order_events=events,
        fills=fills,
        reconciliation_ref="reconciliation-1",
        reconciliation_observed_at=observed,
        source_evidence_hash=digest,
        rejected=rejected,
        rejection_code=rejection_code,
        rejection_reason=rejection_reason,
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"order_events": ()}, "order-event evidence is required"),
        ({"order_events": (_order_event(), _order_event())}, "duplicate broker order-event"),
        ({"fills": (_fill(), _fill())}, "duplicate broker fill"),
        ({"reconciliation_observed_at": NOW - timedelta(days=1)}, "cannot predate"),
        ({"broker_order_ref": ""}, "requires broker_order_ref"),
        ({"rejection_code": "unexpected"}, "cannot contain rejection details"),
        ({"source_evidence_hash": "0" * 64}, "source evidence hash mismatch"),
    ],
)
def test_broker_evidence_rejects_invalid_accepted_inputs(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_broker_evidence(), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"fills": (_fill(),)}, "cannot contain fills"),
        ({"rejection_code": ""}, "requires code and reason"),
        ({"rejection_reason": ""}, "requires code and reason"),
    ],
)
def test_broker_evidence_rejects_invalid_rejected_inputs(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_broker_evidence(rejected=True), **changes)


@pytest.mark.parametrize("value", ["", "x" * 161])
def test_macro_risk_text_guard_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        macro_risk._require_text(value, "value")


def test_macro_risk_primitive_guards_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        macro_risk._require_aware(datetime(2026, 1, 1), "value")
    with pytest.raises(ValueError, match="finite Decimal"):
        macro_risk._require_finite(Decimal("NaN"), "value")
    with pytest.raises(ValueError, match="sha256"):
        macro_risk._require_sha256("bad", "value")


def test_macro_beta_and_asset_exposure_reject_invalid_values() -> None:
    exposure = macro_exposure().exposures[0]
    beta = exposure.betas[0]
    with pytest.raises(ValueError, match="confidence interval"):
        replace(beta, beta=Decimal("2"))
    with pytest.raises(ValueError, match="at least one"):
        replace(exposure, betas=())
    with pytest.raises(ValueError, match="unique per asset"):
        replace(exposure, betas=(beta, beta))
    with pytest.raises(ValueError, match="residual_variance"):
        replace(exposure, residual_variance=Decimal("-1"))
    with pytest.raises(ValueError, match="r_squared"):
        replace(exposure, r_squared=Decimal("2"))
    with pytest.raises(ValueError, match="stability_score"):
        replace(exposure, stability_score=Decimal("2"))


def test_macro_exposure_version_rejects_invalid_values() -> None:
    exposure = macro_exposure()
    with pytest.raises(ValueError, match="valid_until"):
        replace(exposure, valid_until=exposure.observed_at)
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(exposure, exposures=())
    with pytest.raises(ValueError, match="must be unique"):
        replace(exposure, exposures=(exposure.exposures[0], exposure.exposures[0]))
    mismatched = replace(
        exposure.exposures[1],
        betas=(exposure.exposures[1].betas[0],),
    )
    with pytest.raises(ValueError, match="same ordered factor set"):
        replace(exposure, exposures=(exposure.exposures[0], mismatched))


def test_macro_covariance_and_allocation_reject_invalid_values() -> None:
    covariance = macro_covariance()
    with pytest.raises(ValueError, match="valid_until"):
        replace(covariance, valid_until=covariance.observed_at)
    with pytest.raises(ValueError, match="non-empty and unique"):
        replace(covariance, factor_codes=())
    with pytest.raises(ValueError, match="must be square"):
        replace(covariance, values=((Decimal("1"),),))
    allocation = macro_allocations()[0]
    with pytest.raises(ValueError, match="cannot exceed"):
        replace(allocation, minimum_weight=Decimal("2"))
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(allocation, maximum_trade_weight=Decimal("-1"))


def test_macro_candidate_and_policy_reject_invalid_values() -> None:
    candidate = macro_candidate()
    with pytest.raises(ValueError, match="kind is invalid"):
        replace(candidate, kind="equal_weight")
    with pytest.raises(ValueError, match="same PIT manifest"):
        replace(
            candidate,
            covariance_version=replace(candidate.covariance_version, pit_manifest_id="other"),
        )
    with pytest.raises(ValueError, match="expected_cost"):
        replace(candidate, expected_cost=Decimal("-1"))
    future_exposure = replace(
        candidate.exposure_version,
        observed_at=candidate.created_at + timedelta(hours=1),
        valid_until=candidate.created_at + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="observed after creation"):
        replace(candidate, exposure_version=future_exposure)
    with pytest.raises(ValueError, match="non-empty and unique"):
        replace(candidate, allocations=())
    policy = macro_policy()
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(policy, weight_sum_tolerance=Decimal("-1"))
    with pytest.raises(ValueError, match="cannot exceed one"):
        replace(policy, minimum_r_squared=Decimal("2"))


def test_macro_report_rejects_authority_and_hash_tampering() -> None:
    report = macro_risk.evaluate_macro_risk_candidate(
        macro_candidate(), policy=macro_policy(), evaluated_at=NOW
    )
    with pytest.raises(ValueError, match="research_only"):
        replace(report, usage_scope="decision")
    with pytest.raises(ValueError, match="cannot authorize"):
        replace(report, must_not_execute=False)
    with pytest.raises(ValueError, match="evidence_hash"):
        replace(report, evidence_hash="0" * 64)


def test_macro_psd_zero_pivot_paths() -> None:
    assert macro_risk._is_positive_semidefinite(
        ((Decimal("0"), Decimal("0")), (Decimal("0"), Decimal("1"))),
        Decimal("0.0001"),
    )
    assert not macro_risk._is_positive_semidefinite(
        ((Decimal("0"), Decimal("1")), (Decimal("1"), Decimal("1"))),
        Decimal("0.0001"),
    )


def _optimizer_contract() -> OptimizerInputContract:
    return OptimizerInputContract(
        contract_version="contract-v1",
        methodology="method-v1",
        requirements=(
            OptimizationInputRequirement(OptimizationInputKind.EXPECTED_RETURN, "research"),
        ),
        required_promotion_keys=("r3",),
        activated_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
    )


def _optimizer_evidence() -> OptimizationInputEvidence:
    return OptimizationInputEvidence(
        kind=OptimizationInputKind.EXPECTED_RETURN,
        owner="research",
        state=OptimizationEvidenceState.VERIFIED,
        observed_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=1),
        version="v1",
        evidence_ref="evidence-v1",
        content_hash=SHA,
        universe_hash=SHA,
    )


def _optimizer_promotion() -> PromotionReference:
    return PromotionReference(
        "r3", "v1", "decision-v1", NOW - timedelta(days=1), NOW + timedelta(days=1)
    )


def _optimizer_bundle() -> OptimizerInputBundle:
    return OptimizerInputBundle(
        bundle_id="bundle-v1",
        contract_version="contract-v1",
        portfolio_snapshot_id="portfolio-v1",
        decision_snapshot_id="decision-v1",
        universe_hash=SHA,
        evaluated_at=NOW,
        evidence=(_optimizer_evidence(),),
        promotions=(_optimizer_promotion(),),
    )


def test_optimizer_contract_and_evidence_guards() -> None:
    with pytest.raises(ValueError, match="canonical_owner"):
        OptimizationInputRequirement(OptimizationInputKind.EXPECTED_RETURN, "")
    contract = _optimizer_contract()
    with pytest.raises(ValueError, match="version and methodology"):
        replace(contract, contract_version="")
    with pytest.raises(ValueError, match="valid_until"):
        replace(contract, valid_until=contract.activated_at)
    with pytest.raises(ValueError, match="at least one"):
        replace(contract, requirements=())
    with pytest.raises(ValueError, match="duplicate input"):
        replace(contract, requirements=(contract.requirements[0], contract.requirements[0]))
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(contract, required_promotion_keys=("",))
    with pytest.raises(ValueError, match="duplicate promotion"):
        replace(contract, required_promotion_keys=("r3", "r3"))

    evidence = _optimizer_evidence()
    with pytest.raises(ValueError, match="owner is required"):
        replace(evidence, owner="")
    with pytest.raises(ValueError, match="valid_until"):
        replace(evidence, valid_until=evidence.observed_at)
    with pytest.raises(ValueError, match="requires versioned evidence"):
        replace(evidence, version=None)
    with pytest.raises(ValueError, match="requires valid_until"):
        replace(evidence, valid_until=None)
    with pytest.raises(ValueError, match="cannot contain a blocker"):
        replace(evidence, blocking_reason="unexpected")
    with pytest.raises(ValueError, match="requires a blocker"):
        replace(evidence, state=OptimizationEvidenceState.MISSING)


def test_optimizer_promotion_and_bundle_guards() -> None:
    promotion = _optimizer_promotion()
    with pytest.raises(ValueError, match="fields are required"):
        replace(promotion, capability_key="")
    with pytest.raises(ValueError, match="valid_until"):
        replace(promotion, valid_until=promotion.approved_at)
    with pytest.raises(ValueError, match="identifiers are required"):
        replace(_optimizer_bundle(), bundle_id="")
    with pytest.raises(ValueError, match="timezone-aware"):
        optimizer_inputs._require_aware(datetime(2026, 1, 1), "value")


def test_optimizer_bundle_rejects_structural_conflicts() -> None:
    contract = _optimizer_contract()
    bundle = _optimizer_bundle()
    with pytest.raises(ValueError, match="contract version mismatch"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract, bundle=replace(bundle, contract_version="other")
        )
    with pytest.raises(ValueError, match="not active"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract,
            bundle=replace(bundle, evaluated_at=contract.activated_at - timedelta(seconds=1)),
        )
    unexpected = replace(_optimizer_evidence(), kind=OptimizationInputKind.CASH_REQUIREMENT)
    with pytest.raises(ValueError, match="unexpected optimization input"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract, bundle=replace(bundle, evidence=(unexpected,))
        )
    with pytest.raises(ValueError, match="duplicate optimization input"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract,
            bundle=replace(bundle, evidence=(bundle.evidence[0], bundle.evidence[0])),
        )
    wrong_owner = replace(_optimizer_evidence(), owner="portfolio")
    with pytest.raises(ValueError, match="must be owned"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract, bundle=replace(bundle, evidence=(wrong_owner,))
        )
    future = replace(
        _optimizer_evidence(),
        observed_at=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(days=2),
    )
    with pytest.raises(ValueError, match="observed in the future"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract, bundle=replace(bundle, evidence=(future,))
        )


def test_optimizer_promotion_conflict_paths() -> None:
    contract = _optimizer_contract()
    bundle = _optimizer_bundle()
    unexpected = replace(_optimizer_promotion(), capability_key="r4")
    with pytest.raises(ValueError, match="unexpected optimizer promotion"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract, bundle=replace(bundle, promotions=(unexpected,))
        )
    with pytest.raises(ValueError, match="duplicate optimizer promotion"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract,
            bundle=replace(bundle, promotions=(bundle.promotions[0], bundle.promotions[0])),
        )
    future = replace(
        _optimizer_promotion(),
        approved_at=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(days=2),
    )
    with pytest.raises(ValueError, match="approved in the future"):
        optimizer_inputs.evaluate_optimizer_input_bundle(
            contract=contract, bundle=replace(bundle, promotions=(future,))
        )
    expired_contract = replace(contract, valid_until=NOW)
    readiness = optimizer_inputs.evaluate_optimizer_input_bundle(
        contract=expired_contract,
        bundle=replace(bundle, promotions=(), evidence=()),
    )
    assert readiness.can_run_research_preview is False


@pytest.mark.parametrize("value", ["", "bad\0text", "x" * 201])
def test_r4_evidence_text_guard_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        r4_evidence._require_text(value, "value")


def test_r4_evidence_primitive_and_source_guards() -> None:
    with pytest.raises(ValueError, match="sha256"):
        r4_evidence._require_sha256("bad", "value")
    with pytest.raises(ValueError, match="timezone-aware"):
        r4_evidence._require_aware(datetime(2026, 1, 1), "value")
    with pytest.raises(ValueError, match="finite Decimal"):
        r4_evidence._require_finite(Decimal("NaN"), "value")
    with pytest.raises(ValueError, match="non-empty, unique, and ordered"):
        r4_evidence._validate_source_hashes(())


def test_r4_return_value_and_observation_guards() -> None:
    with pytest.raises(ValueError, match="below -100"):
        r4_evidence.R4AssetReturn("asset-a", Decimal("-1.1"))
    observation = build_window(1).return_path.observations[0]
    with pytest.raises(ValueError, match="non-empty, unique, and ordered"):
        replace(observation, asset_returns=())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"owner": "research"}, "owner must be portfolio"),
        ({"asset_codes": ()}, "non-empty, unique, and ordered"),
        ({"values": ((Decimal("1"),),)}, "must be square"),
        ({"condition_number": Decimal("0")}, "at least one"),
        ({"matrix_rank": True}, "matrix_rank"),
        ({"expected_observation_count": True}, "expected_observation_count"),
        ({"missing_observation_count": True}, "missing_observation_count"),
        ({"missing_observation_count": 31}, "cannot exceed"),
        ({"available_at": datetime(2026, 2, 1, tzinfo=UTC)}, "clocks are invalid"),
        ({"content_hash": "0" * 64}, "content_hash mismatch"),
    ],
)
def test_r4_covariance_evidence_guards(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(build_window(1).asset_covariance, **changes)


def test_r4_return_path_evidence_guards() -> None:
    path = build_window(1).return_path
    with pytest.raises(ValueError, match="owner must be portfolio"):
        replace(path, owner="research")
    with pytest.raises(ValueError, match="at least two observations"):
        replace(path, observations=path.observations[:1])
    with pytest.raises(ValueError, match="unique and ordered"):
        replace(path, observations=(path.observations[0], path.observations[0]))
    changed_assets = replace(
        path.observations[1], asset_returns=(path.observations[1].asset_returns[0],)
    )
    with pytest.raises(ValueError, match="asset universe changes"):
        replace(path, observations=(path.observations[0], changed_assets))
    outside = replace(
        path.observations[0],
        period_end=datetime(2020, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="outside the typed window"):
        replace(path, observations=(outside, path.observations[1]))
    with pytest.raises(ValueError, match="before its final return"):
        replace(path, observed_at=path.observations[-1].period_end - timedelta(seconds=1))
    with pytest.raises(ValueError, match="bitemporal clocks are invalid"):
        replace(path, available_at=path.valid_until)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(path, content_hash="0" * 64)


def test_r4_regime_projection_and_promotion_guards() -> None:
    window = build_window(1)
    regime = window.regime_assignment
    with pytest.raises(ValueError, match="owner must be regime"):
        replace(regime, owner="portfolio")
    with pytest.raises(ValueError, match="clocks are invalid"):
        replace(regime, available_at=regime.valid_until)

    projection = window.macro_projection
    with pytest.raises(ValueError, match="owner must be macro_factor"):
        replace(projection, owner="portfolio")
    with pytest.raises(ValueError, match="clocks are invalid"):
        replace(projection, available_at=projection.exposure_version.valid_until)
    with pytest.raises(ValueError, match="artifact version mismatch"):
        replace(projection, factor_artifact_version="other")
    with pytest.raises(ValueError, match="promotion decision mismatch"):
        replace(projection, promotion_decision_id="other")
    with pytest.raises(ValueError, match="source hash mismatch"):
        replace(projection, source_content_hash="0" * 64)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(projection, content_hash="0" * 64)

    promotion = promotion_attestation()
    with pytest.raises(ValueError, match="owner must be research"):
        replace(promotion, owner="portfolio")
    with pytest.raises(ValueError, match="capability mismatch"):
        replace(promotion, capability_key="r4")
    with pytest.raises(ValueError, match="purpose mismatch"):
        replace(promotion, purpose="decision")
    with pytest.raises(ValueError, match="validity is invalid"):
        replace(promotion, valid_until=promotion.approved_at)
    with pytest.raises(ValueError, match="retirement is invalid"):
        replace(promotion, retired_at=promotion.approved_at)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(promotion, content_hash="0" * 64)


def _rebuild_owner_binding(binding, **changes):
    values = {
        "kind": binding.kind,
        "owner": binding.owner,
        "version": binding.version,
        "evidence_ref": binding.evidence_ref,
        "observed_at": binding.observed_at,
        "available_at": binding.available_at,
        "knowledge_as_of": binding.knowledge_as_of,
        "valid_until": binding.valid_until,
        "pit_manifest_id": binding.pit_manifest_id,
        "pit_manifest_hash": binding.pit_manifest_hash,
        "universe_hash": binding.universe_hash,
        "payload_hash": binding.payload_hash,
        "source_content_hashes": binding.source_content_hashes,
    }
    values.update(changes)
    return governed_inputs.build_owner_bound_payload_evidence(**values)


def test_governed_owner_binding_and_promotion_guards() -> None:
    input_set = _input_set()
    binding = input_set.owner_bindings[0]
    with pytest.raises(ValueError, match="availability window"):
        _rebuild_owner_binding(binding, available_at=binding.valid_until)
    with pytest.raises(ValueError, match="source hashes"):
        _rebuild_owner_binding(binding, source_content_hashes=())
    with pytest.raises(ValueError, match="attestation hash mismatch"):
        replace(binding, owner_attestation_hash="0" * 64)

    promotion = input_set.promotions[0]
    with pytest.raises(ValueError, match="valid_until"):
        replace(promotion, valid_until=promotion.approved_at)
    with pytest.raises(ValueError, match="retired_at"):
        replace(promotion, retired_at=promotion.approved_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="attestation hash mismatch"):
        replace(promotion, attestation_hash="0" * 64)


def test_governed_input_set_top_level_guards() -> None:
    input_set = _input_set()
    with pytest.raises(ValueError, match="valid_until"):
        replace(input_set, valid_until=input_set.created_at)
    future_universe = _unsafe_replace(
        input_set.universe,
        available_at=input_set.created_at + timedelta(seconds=1),
        valid_until=input_set.valid_until + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="predate universe availability"):
        replace(input_set, universe=future_universe)
    with pytest.raises(ValueError, match="outlive its universe"):
        replace(input_set, valid_until=input_set.universe.valid_until + timedelta(seconds=1))
    with pytest.raises(ValueError, match="non-executable research"):
        replace(input_set, must_not_execute=False)
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(input_set, content_hash="0" * 64)


def test_governed_payload_and_binding_validator_guards() -> None:
    input_set = _input_set()
    with pytest.raises(ValueError, match="every canonical payload"):
        governed_inputs._validate_payloads(input_set.payloads[:-1], input_set.universe)
    first = input_set.payloads[0]
    wrong_hash = _unsafe_replace(first, universe_hash="0" * 64)
    with pytest.raises(ValueError, match="universe hash mismatch"):
        governed_inputs._validate_payloads(
            (wrong_hash, *input_set.payloads[1:]), input_set.universe
        )
    with pytest.raises(ValueError, match="every owner binding"):
        governed_inputs._validate_bindings(
            input_set.owner_bindings[:-1],
            {item.kind: item for item in input_set.payloads},
            input_set.universe,
            input_set.created_at,
            input_set.valid_until,
        )

    binding = input_set.owner_bindings[0]
    wrong_owner = _rebuild_owner_binding(binding, owner="wrong-owner")
    bindings = (wrong_owner, *input_set.owner_bindings[1:])
    with pytest.raises(ValueError, match="canonical owner mismatch"):
        governed_inputs._validate_bindings(
            bindings,
            {item.kind: item for item in input_set.payloads},
            input_set.universe,
            input_set.created_at,
            input_set.valid_until,
        )
    wrong_payload = _rebuild_owner_binding(binding, payload_hash="0" * 64)
    with pytest.raises(ValueError, match="payload hash mismatch"):
        governed_inputs._validate_bindings(
            (wrong_payload, *input_set.owner_bindings[1:]),
            {item.kind: item for item in input_set.payloads},
            input_set.universe,
            input_set.created_at,
            input_set.valid_until,
        )


def test_governed_promotion_validator_guards() -> None:
    input_set = _input_set()
    with pytest.raises(ValueError, match="exact r3/r4/r5"):
        governed_inputs._validate_promotions(
            input_set.promotions[:-1], input_set.created_at, input_set.valid_until
        )
    promotion = input_set.promotions[0]
    wrong_owner = governed_inputs.ExactPromotionAttestation.create(
        capability_key=promotion.capability_key,
        artifact_id=promotion.artifact_id,
        artifact_version=promotion.artifact_version,
        artifact_content_hash=promotion.artifact_content_hash,
        decision_id=promotion.decision_id,
        decision_content_hash=promotion.decision_content_hash,
        owner="portfolio",
        approved_at=promotion.approved_at,
        valid_until=promotion.valid_until,
    )
    with pytest.raises(ValueError, match="owner must be research"):
        governed_inputs._validate_promotions(
            (wrong_owner, *input_set.promotions[1:]), input_set.created_at, input_set.valid_until
        )


def _lifecycle_root():
    return lifecycle.create_optimization_lifecycle_root(lifecycle_result())


def _lifecycle_owner(event_type=lifecycle.OptimizationLifecycleEventType.RETIRED):
    result = lifecycle_result()
    reasons = ("methodology_retired",)
    return lifecycle.OptimizationLifecycleOwnerAttestation.create(
        attestation_id="owner-attestation-v1",
        owner="portfolio",
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=event_type,
        reason_hash=hash_components("optimization-lifecycle-reasons.v1", *reasons),
        issued_at=NOW + timedelta(hours=2),
    )


def test_lifecycle_owner_attestation_guards() -> None:
    result = lifecycle_result()
    with pytest.raises(ValueError, match="only valid for retirement or rollback"):
        lifecycle.OptimizationLifecycleOwnerAttestation.create(
            attestation_id="owner-attestation-v1",
            owner="portfolio",
            result_id=result.result_id,
            result_hash=result.content_hash,
            event_type=lifecycle.OptimizationLifecycleEventType.RECORDED,
            reason_hash=SHA,
            issued_at=NOW,
        )
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(_lifecycle_owner(), content_hash="0" * 64)


def test_lifecycle_event_contract_guards() -> None:
    root = _lifecycle_root()
    with pytest.raises(ValueError, match="sequence must be positive"):
        replace(root, sequence=True)
    with pytest.raises(ValueError, match="cannot predate"):
        replace(root, recorded_at=root.occurred_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="root evidence is invalid"):
        replace(root, reason_codes=("unexpected",))
    with pytest.raises(ValueError, match="requires previous hash"):
        replace(
            root,
            sequence=2,
            event_type=lifecycle.OptimizationLifecycleEventType.RETIRED,
            reason_codes=("retired",),
        )
    with pytest.raises(ValueError, match="requires reason codes"):
        replace(root, sequence=2, previous_event_hash=SHA)
    with pytest.raises(ValueError, match="requires exact Promotion only"):
        replace(
            root,
            sequence=2,
            event_type=lifecycle.OptimizationLifecycleEventType.PROMOTION_ATTESTED,
            previous_event_hash=SHA,
            reason_codes=("approved",),
        )
    with pytest.raises(ValueError, match="unsupported"):
        replace(
            root,
            sequence=2,
            event_type="unknown",
            previous_event_hash=SHA,
            reason_codes=("unknown",),
        )
    with pytest.raises(ValueError, match="remain research-only"):
        replace(root, must_not_execute=False)
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(root, content_hash="0" * 64)


def test_lifecycle_create_and_chain_guards() -> None:
    result = lifecycle_result()
    root = lifecycle.create_optimization_lifecycle_root(result)
    promotion = lifecycle_promotion(result)
    promoted = lifecycle.create_optimization_lifecycle_event(
        result=result,
        previous_events=(root,),
        event_type=lifecycle.OptimizationLifecycleEventType.PROMOTION_ATTESTED,
        occurred_at=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=1),
        reason_codes=("approved",),
        promotion_attestation=promotion,
    )
    with pytest.raises(ValueError, match="transition is invalid"):
        lifecycle.create_optimization_lifecycle_event(
            result=result,
            previous_events=(root, promoted),
            event_type=lifecycle.OptimizationLifecycleEventType.PROMOTION_ATTESTED,
            occurred_at=NOW + timedelta(hours=2),
            recorded_at=NOW + timedelta(hours=2),
            reason_codes=("again",),
            promotion_attestation=promotion,
        )
    with pytest.raises(ValueError, match="recorded root"):
        lifecycle.derive_optimization_lifecycle_state(())
    with pytest.raises(ValueError, match="discontinuous"):
        lifecycle.derive_optimization_lifecycle_state((_unsafe_replace(root, sequence=2),))
    with pytest.raises(ValueError, match="changes result identity"):
        lifecycle.derive_optimization_lifecycle_state(
            (root, _unsafe_replace(promoted, result_id="other"))
        )
    with pytest.raises(ValueError, match="Promotion transition is invalid"):
        lifecycle.derive_optimization_lifecycle_state(
            (
                root,
                promoted,
                _unsafe_replace(
                    promoted,
                    sequence=3,
                    previous_event_hash=promoted.content_hash,
                ),
            )
        )


def test_optimization_canonical_guards() -> None:
    with pytest.raises(ValueError, match="bounded token"):
        canonical.require_token("bad token", "value")
    with pytest.raises(ValueError, match="bounded non-blank text"):
        canonical.require_text("", "value")
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical.require_aware(datetime(2026, 1, 1), "value")
    with pytest.raises(ValueError, match="finite Decimal"):
        canonical.require_finite(Decimal("NaN"), "value")
    with pytest.raises(ValueError, match="must be positive"):
        canonical.require_positive(Decimal("0"), "value")
    with pytest.raises(ValueError, match="within"):
        canonical.require_unit_interval(Decimal("2"), "value")
    with pytest.raises(ValueError, match="non-negative integer"):
        canonical.require_nonnegative_int(True, "value")
    with pytest.raises(ValueError, match="non-empty, unique, and ordered"):
        canonical.require_ordered_unique((), "value")
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        canonical.require_sha256("bad", "value")
    with pytest.raises(ValueError, match="content hash mismatch"):
        canonical.validate_content_hash("0" * 64, "1" * 64, "value")


def test_constrained_assessment_collects_every_clock_and_covariance_blocker() -> None:
    problem = _problem()
    inactive_policy = _unsafe_replace(
        problem.validation_policy,
        activated_at=NOW + timedelta(days=1),
        valid_until=NOW + timedelta(days=2),
    )
    expired_covariance = _unsafe_replace(
        problem.covariance,
        valid_until=NOW,
    )
    expired_exposure = _unsafe_replace(problem.macro_exposure_version, valid_until=NOW)
    expired_macro_covariance = _unsafe_replace(problem.macro_factor_covariance, valid_until=NOW)
    assessed = constrained.assess_optimization_problem(
        _unsafe_replace(
            problem,
            validation_policy=inactive_policy,
            valid_until=NOW,
            covariance=expired_covariance,
            macro_exposure_version=expired_exposure,
            macro_factor_covariance=expired_macro_covariance,
        ),
        evaluated_at=NOW,
    )
    codes = {item.code for item in assessed.blockers}
    assert constrained.OptimizationBlockerCode.POLICY_INACTIVE in codes
    assert constrained.OptimizationBlockerCode.PROBLEM_EXPIRED in codes
    assert constrained.OptimizationBlockerCode.COVARIANCE_EXPIRED in codes
    assert constrained.OptimizationBlockerCode.MACRO_EVIDENCE_EXPIRED in codes

    with pytest.raises(ValueError, match="before creation"):
        constrained.assess_optimization_problem(
            _unsafe_replace(problem, created_at=NOW + timedelta(seconds=1)),
            evaluated_at=NOW,
        )
    future_covariance = _unsafe_replace(
        problem.covariance,
        observed_at=NOW + timedelta(seconds=1),
        valid_until=NOW + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="observed in the future"):
        constrained.assess_optimization_problem(
            _unsafe_replace(problem, covariance=future_covariance), evaluated_at=NOW
        )


@pytest.mark.parametrize(
    ("field", "values", "code"),
    [
        (
            "macro_factor_covariance",
            ((Decimal("1"), Decimal("2")), (Decimal("0"), Decimal("1"))),
            constrained.OptimizationBlockerCode.MACRO_COVARIANCE_NOT_SYMMETRIC,
        ),
        (
            "macro_factor_covariance",
            ((Decimal("1"), Decimal("2")), (Decimal("2"), Decimal("1"))),
            constrained.OptimizationBlockerCode.MACRO_COVARIANCE_NOT_PSD,
        ),
        (
            "covariance",
            ((Decimal("1"), Decimal("2")), (Decimal("0"), Decimal("1"))),
            constrained.OptimizationBlockerCode.COVARIANCE_NOT_SYMMETRIC,
        ),
        (
            "covariance",
            ((Decimal("1"), Decimal("2")), (Decimal("2"), Decimal("1"))),
            constrained.OptimizationBlockerCode.COVARIANCE_NOT_PSD,
        ),
    ],
)
def test_constrained_assessment_covariance_blockers(field, values, code) -> None:
    problem = _problem()
    matrix = _unsafe_replace(getattr(problem, field), values=values)
    assessment = constrained.assess_optimization_problem(
        _unsafe_replace(problem, **{field: matrix}), evaluated_at=NOW
    )
    assert code in {item.code for item in assessment.blockers}


def test_constrained_assessment_detects_infeasible_bounds() -> None:
    problem = _problem()
    assets = tuple(_unsafe_replace(item, minimum_weight=Decimal("0.6")) for item in problem.assets)
    assessment = constrained.assess_optimization_problem(
        _unsafe_replace(problem, assets=assets), evaluated_at=NOW
    )
    assert constrained.OptimizationBlockerCode.BOUNDS_INFEASIBLE in {
        item.code for item in assessment.blockers
    }


def test_constrained_solver_output_failure_shapes() -> None:
    problem = _problem()
    no_candidate = build_solver_output(
        candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
        weights=None,
        cash_weight=None,
        status=SolverConvergenceStatus.INFEASIBLE,
        iterations=1,
        residual=Decimal("1"),
        detail="no candidate",
    )
    evaluation = constrained.evaluate_solver_output(problem, no_candidate)
    assert constrained.OptimizationBlockerCode.SOLVER_NO_CANDIDATE in {
        item.code for item in evaluation.blockers
    }

    wrong_count = build_solver_output(
        candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
        weights=(Decimal("0.8"),),
        cash_weight=Decimal("0.2"),
        status=SolverConvergenceStatus.ITERATION_LIMIT,
        iterations=1,
        residual=Decimal("1"),
        detail="wrong count",
    )
    evaluation = constrained.evaluate_solver_output(problem, wrong_count)
    codes = {item.code for item in evaluation.blockers}
    assert constrained.OptimizationBlockerCode.SOLVER_NOT_CONVERGED in codes
    assert constrained.OptimizationBlockerCode.WEIGHT_COUNT_MISMATCH in codes


def test_constrained_solver_collects_candidate_budget_blockers() -> None:
    problem = _problem()
    strict_budget = _unsafe_replace(
        problem.macro_risk_budget,
        maximum_factor_variance=Decimal("0.0000001"),
        maximum_target_deviation=Decimal("0"),
    )
    strict = _unsafe_replace(
        problem,
        maximum_turnover=Decimal("0"),
        maximum_transaction_cost=Decimal("0"),
        maximum_drawdown=Decimal("0"),
        macro_risk_budget=strict_budget,
        scenario_losses=(
            _unsafe_replace(
                problem.scenario_losses[0],
                maximum_portfolio_loss=Decimal("0.01"),
            ),
        ),
    )
    output = build_solver_output(
        candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
        weights=(Decimal("0.9"), Decimal("-0.1")),
        cash_weight=Decimal("0.1"),
        status=SolverConvergenceStatus.LOCAL_STATIONARY,
        iterations=1,
        residual=Decimal("0.001"),
        detail="stress candidate",
    )
    evaluation = constrained.evaluate_solver_output(strict, output)
    codes = {item.code for item in evaluation.blockers}
    assert constrained.OptimizationBlockerCode.WEIGHT_SUM_INVALID in codes
    assert constrained.OptimizationBlockerCode.CASH_REQUIREMENT_BREACHED in codes
    assert constrained.OptimizationBlockerCode.POSITION_BOUND_BREACHED in codes
    assert constrained.OptimizationBlockerCode.LIQUIDITY_BREACHED in codes
    assert constrained.OptimizationBlockerCode.TURNOVER_BREACHED in codes
    assert constrained.OptimizationBlockerCode.COST_BUDGET_BREACHED in codes
    assert constrained.OptimizationBlockerCode.SCENARIO_LOSS_BREACHED in codes
    assert constrained.OptimizationBlockerCode.DRAWDOWN_BUDGET_BREACHED in codes
    assert constrained.OptimizationBlockerCode.MACRO_RISK_BUDGET_BREACHED in codes
    assert constrained.OptimizationBlockerCode.MACRO_TARGET_DEVIATION_BREACHED in codes


def test_constrained_psd_and_primitive_guard_edges() -> None:
    assert constrained._is_positive_semidefinite(
        ((Decimal("0"), Decimal("0")), (Decimal("0"), Decimal("1"))),
        Decimal("0.0001"),
    )
    assert not constrained._is_positive_semidefinite(
        ((Decimal("0"), Decimal("1")), (Decimal("1"), Decimal("1"))),
        Decimal("0.0001"),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        constrained._require_aware(datetime(2026, 1, 1), "value")
    with pytest.raises(ValueError, match="finite Decimal"):
        constrained._require_finite(Decimal("NaN"), "value")


def test_constrained_final_four_ratchet_branches() -> None:
    problem = _problem()
    fixed = _unsafe_replace(problem.assets[0], manual_restriction=ManualRestriction.FIXED)
    assert constrained.effective_weight_bounds(fixed) == (
        fixed.current_weight,
        fixed.current_weight,
    )
    no_sell = _unsafe_replace(problem.assets[0], manual_restriction=ManualRestriction.NO_SELL)
    lower, _ = constrained.effective_weight_bounds(no_sell)
    assert lower == no_sell.current_weight
    with pytest.raises(ValueError, match="do not align"):
        constrained.calculate_candidate_metrics(
            problem,
            weights=(Decimal("0.8"),),
            cash_weight=Decimal("0.2"),
        )

    zero_macro = _unsafe_replace(
        problem.macro_factor_covariance,
        values=((Decimal("0"), Decimal("0")), (Decimal("0"), Decimal("0"))),
    )
    zero_problem = _unsafe_replace(problem, macro_factor_covariance=zero_macro)
    output = build_solver_output(
        candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
        weights=(Decimal("0.4"), Decimal("0.4")),
        cash_weight=Decimal("0.2"),
        status=SolverConvergenceStatus.LOCAL_STATIONARY,
        iterations=1,
        residual=Decimal("0.001"),
        detail="zero macro variance",
    )
    evaluation = constrained.evaluate_solver_output(zero_problem, output)
    assert constrained.OptimizationBlockerCode.MACRO_FACTOR_VARIANCE_NON_POSITIVE in {
        item.code for item in evaluation.blockers
    }
