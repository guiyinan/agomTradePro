"""Pure evaluation service for rolling R4 macro-risk research."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from apps.portfolio.domain.macro_factor_risk import (
    MacroRiskCandidateInput,
    MacroRiskCandidateKind,
    MacroRiskCandidateReport,
    evaluate_macro_risk_candidate,
)
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation

from .macro_risk_rolling_contracts import (
    R4MethodBacktestSummary,
    R4MethodWindowMetrics,
    R4RegimeExposureSummary,
    R4RollingBlocker,
    R4RollingBlockerCode,
    R4RollingExposurePoint,
    R4RollingResearchArtifact,
    R4RollingStudyInput,
    R4RollingWindowInput,
)

_REQUIRED_METHODS = frozenset(
    (
        MacroRiskCandidateKind.EQUAL_WEIGHT,
        MacroRiskCandidateKind.ASSET_RISK_PARITY,
        MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,
    )
)


def evaluate_r4_rolling_study(
    study: R4RollingStudyInput,
    *,
    promotion_attestation: ExactR3PromotionAttestation,
    evaluated_at: datetime,
) -> R4RollingResearchArtifact:
    """Evaluate exact rolling windows without publication or execution authority."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    blockers: list[R4RollingBlocker] = []
    metrics: list[R4MethodWindowMetrics] = []
    exposure_points: list[R4RollingExposurePoint] = []
    _validate_r3_promotion(study, promotion_attestation, evaluated_at, blockers)

    for window in study.windows:
        candidates = _candidate_family(window, blockers)
        if candidates is None:
            continue
        _validate_shared_inputs(window, candidates, blockers)
        _validate_window_clocks(window, evaluated_at, blockers)
        _validate_equal_weight(
            window,
            candidates[MacroRiskCandidateKind.EQUAL_WEIGHT],
            study,
            blockers,
        )
        _validate_asset_risk_parity(
            window,
            candidates[MacroRiskCandidateKind.ASSET_RISK_PARITY],
            study,
            blockers,
        )
        reports = _candidate_reports(window, candidates, study, blockers)
        for kind in sorted(_REQUIRED_METHODS, key=lambda value: value.value):
            result = _window_metrics(
                window,
                candidates[kind],
                reports[kind],
                study,
                blockers,
            )
            if result is not None:
                metrics.append(result)
        exposure_points.extend(
            _exposure_points(
                window,
                candidates[MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY],
            )
        )

    regime_summaries = _regime_summaries(exposure_points)
    blockers.extend(_regime_sample_blockers(study, regime_summaries))
    ordered_blockers = tuple(
        sorted(
            blockers,
            key=lambda value: (value.code.value, value.fold_id or "", value.detail),
        )
    )
    return R4RollingResearchArtifact.create(
        study=study,
        promotion_attestation=promotion_attestation,
        window_metrics=tuple(sorted(metrics, key=lambda value: (value.fold_id, value.kind.value))),
        exposure_points=tuple(
            sorted(
                exposure_points,
                key=lambda value: (value.fold_id, value.asset_code, value.factor_code),
            )
        ),
        regime_summaries=regime_summaries,
        method_summaries=_method_summaries(study, metrics),
        blockers=ordered_blockers,
        evaluated_at=evaluated_at,
    )


def _validate_r3_promotion(
    study: R4RollingStudyInput,
    attestation: ExactR3PromotionAttestation,
    evaluated_at: datetime,
    blockers: list[R4RollingBlocker],
) -> None:
    projections = tuple(item.macro_projection for item in study.windows)
    first = projections[0]
    projection_identity_matches = all(
        item.factor_artifact_id == first.factor_artifact_id
        and item.factor_artifact_version == first.factor_artifact_version
        and item.factor_artifact_content_hash == first.factor_artifact_content_hash
        and item.promotion_decision_id == first.promotion_decision_id
        and item.promotion_decision_version == first.promotion_decision_version
        and item.promotion_decision_content_hash == first.promotion_decision_content_hash
        for item in projections[1:]
    )
    attestation_matches = (
        attestation.artifact_id == first.factor_artifact_id
        and attestation.artifact_version == first.factor_artifact_version
        and attestation.artifact_content_hash == first.factor_artifact_content_hash
        and attestation.decision_id == first.promotion_decision_id
        and attestation.decision_version == first.promotion_decision_version
        and attestation.decision_content_hash == first.promotion_decision_content_hash
        and attestation.is_active_at(evaluated_at)
        and all(attestation.approved_at <= item.selection_as_of for item in study.windows)
    )
    if not projection_identity_matches or not attestation_matches:
        blockers.append(
            R4RollingBlocker(
                code=R4RollingBlockerCode.R3_PROMOTION_INVALID,
                detail="R3 promotion is missing, inactive, or not bound to the exact factor artifact",
            )
        )


def _candidate_family(
    window: R4RollingWindowInput,
    blockers: list[R4RollingBlocker],
) -> dict[MacroRiskCandidateKind, MacroRiskCandidateInput] | None:
    by_kind = {item.kind: item for item in window.candidates}
    if len(by_kind) != len(window.candidates) or frozenset(by_kind) != _REQUIRED_METHODS:
        blockers.append(
            _block(
                R4RollingBlockerCode.METHOD_FAMILY_INCOMPLETE,
                "each fold requires exactly one candidate for every R4 method",
                window,
            )
        )
        return None
    return by_kind


def _allocation_contract(
    candidate: MacroRiskCandidateInput,
) -> tuple[tuple[str, Decimal, Decimal, Decimal, Decimal], ...]:
    return tuple(
        (
            item.asset_code,
            item.current_weight,
            item.minimum_weight,
            item.maximum_weight,
            item.maximum_trade_weight,
        )
        for item in sorted(candidate.allocations, key=lambda value: value.asset_code)
    )


def _validate_shared_inputs(
    window: R4RollingWindowInput,
    candidates: dict[MacroRiskCandidateKind, MacroRiskCandidateInput],
    blockers: list[R4RollingBlocker],
) -> None:
    ordered = tuple(candidates[kind] for kind in sorted(_REQUIRED_METHODS, key=lambda x: x.value))
    first = ordered[0]
    if any(
        candidate.canonical_portfolio_snapshot_id != first.canonical_portfolio_snapshot_id
        or candidate.exposure_version != first.exposure_version
        or candidate.covariance_version != first.covariance_version
        or candidate.cost_model_version != first.cost_model_version
        or candidate.constraint_version != first.constraint_version
        or candidate.created_at != first.created_at
        or _allocation_contract(candidate) != _allocation_contract(first)
        for candidate in ordered[1:]
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.METHOD_INPUT_MISMATCH,
                "methods do not share exact snapshot, formation, cost, and constraint inputs",
                window,
            )
        )
    allocation_assets = tuple(
        item.asset_code for item in sorted(first.allocations, key=lambda value: value.asset_code)
    )
    covariance_assets = window.asset_covariance.asset_codes
    path_assets = tuple(
        item.asset_code for item in window.return_path.observations[0].asset_returns
    )
    exposure_assets = tuple(sorted(item.asset_code for item in first.exposure_version.exposures))
    if not allocation_assets == covariance_assets == path_assets == exposure_assets:
        blockers.append(
            _block(
                R4RollingBlockerCode.METHOD_INPUT_MISMATCH,
                "allocation, exposure, covariance, and OOS universes differ",
                window,
            )
        )
    if (
        window.asset_covariance.universe_id != window.return_path.universe_id
        or window.asset_covariance.universe_hash != window.return_path.universe_hash
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.METHOD_INPUT_MISMATCH,
                "formation covariance and OOS path do not share the exact PIT universe",
                window,
            )
        )


def _validate_window_clocks(
    window: R4RollingWindowInput,
    evaluated_at: datetime,
    blockers: list[R4RollingBlocker],
) -> None:
    selection = window.selection_as_of
    projection = window.macro_projection
    formation_invalid = (
        any(item.created_at != selection for item in window.candidates)
        or projection.available_at > selection
        or projection.knowledge_as_of > selection
        or projection.exposure_version.observed_at > selection
        or projection.exposure_version.valid_until <= selection
        or window.candidates[0].covariance_version.observed_at > selection
        or window.candidates[0].covariance_version.valid_until <= selection
        or window.asset_covariance.available_at > selection
        or window.asset_covariance.knowledge_as_of > selection
        or window.asset_covariance.valid_until <= selection
    )
    if formation_invalid:
        blockers.append(
            _block(
                R4RollingBlockerCode.FORMATION_EVIDENCE_INVALID,
                "formation evidence was late, expired, or used a different cutoff",
                window,
            )
        )
    regime = window.regime_assignment
    if (
        regime.effective_at > selection
        or regime.available_at > selection
        or regime.knowledge_as_of > selection
        or regime.valid_until <= selection
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.REGIME_EVIDENCE_INVALID,
                "Regime-owner evidence was not known and valid at formation",
                window,
            )
        )
    returns = window.return_path
    if (
        returns.available_at <= selection
        or returns.available_at > window.evaluation_as_of
        or returns.knowledge_as_of > window.evaluation_as_of
        or returns.valid_until <= window.evaluation_as_of
        or evaluated_at < window.evaluation_as_of
        or any(
            item.period_end <= selection or item.period_end > window.evaluation_as_of
            for item in returns.observations
        )
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.RETURN_PATH_INVALID,
                "OOS returns violated selection or evaluation knowledge time",
                window,
            )
        )


def _validate_equal_weight(
    window: R4RollingWindowInput,
    candidate: MacroRiskCandidateInput,
    study: R4RollingStudyInput,
    blockers: list[R4RollingBlocker],
) -> None:
    target = Decimal("1") / Decimal(len(candidate.allocations))
    if any(
        abs(item.candidate_weight - target) > study.rolling_policy.weight_tolerance
        for item in candidate.allocations
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.EQUAL_WEIGHT_MISMATCH,
                "equal-weight baseline cannot be recomputed from the exact universe",
                window,
            )
        )


def _validate_asset_risk_parity(
    window: R4RollingWindowInput,
    candidate: MacroRiskCandidateInput,
    study: R4RollingStudyInput,
    blockers: list[R4RollingBlocker],
) -> None:
    matrix = window.asset_covariance.values
    if not _is_symmetric(matrix, study.rolling_policy.covariance_symmetry_tolerance) or not (
        _is_positive_semidefinite(matrix, study.rolling_policy.covariance_psd_tolerance)
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.ASSET_COVARIANCE_INVALID,
                "asset covariance is not symmetric positive semidefinite",
                window,
            )
        )
        return
    if (
        window.asset_covariance.condition_number > study.rolling_policy.maximum_condition_number
        or window.asset_covariance.matrix_rank < len(window.asset_covariance.asset_codes)
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.ASSET_COVARIANCE_ILL_CONDITIONED,
                "asset covariance exceeds the condition limit or is rank deficient",
                window,
            )
        )
        return
    observed_count = (
        window.asset_covariance.expected_observation_count
        - window.asset_covariance.missing_observation_count
    )
    coverage_ratio = Decimal(observed_count) / Decimal(
        window.asset_covariance.expected_observation_count
    )
    if coverage_ratio < study.rolling_policy.minimum_covariance_coverage_ratio:
        blockers.append(
            _block(
                R4RollingBlockerCode.ASSET_COVARIANCE_MISSING_COVERAGE,
                "asset covariance missing observations exceed the versioned policy limit",
                window,
            )
        )
        return
    weights_by_asset = {item.asset_code: item.candidate_weight for item in candidate.allocations}
    if set(weights_by_asset) != set(window.asset_covariance.asset_codes):
        blockers.append(
            _block(
                R4RollingBlockerCode.ASSET_RISK_PARITY_MISMATCH,
                "asset-risk-parity weights do not cover the covariance universe",
                window,
            )
        )
        return
    weights = tuple(weights_by_asset[code] for code in window.asset_covariance.asset_codes)
    marginal = _matrix_vector(matrix, weights)
    contributions = tuple(
        weight * marginal_value for weight, marginal_value in zip(weights, marginal, strict=True)
    )
    total = sum(contributions, Decimal("0"))
    if total <= study.rolling_policy.covariance_psd_tolerance or any(
        value < 0 for value in contributions
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.ASSET_RISK_PARITY_MISMATCH,
                "asset-risk-parity contributions are non-positive",
                window,
            )
        )
        return
    target = Decimal("1") / Decimal(len(contributions))
    if any(
        abs(value / total - target) > study.rolling_policy.asset_risk_parity_tolerance
        for value in contributions
    ):
        blockers.append(
            _block(
                R4RollingBlockerCode.ASSET_RISK_PARITY_MISMATCH,
                "asset-risk-parity contribution target was missed",
                window,
            )
        )


def _candidate_reports(
    window: R4RollingWindowInput,
    candidates: dict[MacroRiskCandidateKind, MacroRiskCandidateInput],
    study: R4RollingStudyInput,
    blockers: list[R4RollingBlocker],
) -> dict[MacroRiskCandidateKind, MacroRiskCandidateReport]:
    reports = {
        kind: evaluate_macro_risk_candidate(
            candidate,
            policy=study.candidate_policy,
            evaluated_at=window.selection_as_of,
        )
        for kind, candidate in candidates.items()
    }
    for kind, report in reports.items():
        if not report.eligible_for_research_comparison:
            codes = ",".join(item.code.value for item in report.blockers)
            blockers.append(
                _block(
                    R4RollingBlockerCode.CANDIDATE_INELIGIBLE,
                    f"{kind.value} candidate failed exact validation: {codes}",
                    window,
                )
            )
    return reports


def _window_metrics(
    window: R4RollingWindowInput,
    candidate: MacroRiskCandidateInput,
    report: MacroRiskCandidateReport,
    study: R4RollingStudyInput,
    blockers: list[R4RollingBlocker],
) -> R4MethodWindowMetrics | None:
    weights = {item.asset_code: item.candidate_weight for item in candidate.allocations}
    path_assets = tuple(
        item.asset_code for item in window.return_path.observations[0].asset_returns
    )
    if set(weights) != set(path_assets):
        blockers.append(
            _block(
                R4RollingBlockerCode.RETURN_PATH_INVALID,
                f"{candidate.kind.value} weights do not match the OOS universe",
                window,
            )
        )
        return None
    period_returns = tuple(
        sum(
            (weights[item.asset_code] * item.value for item in observation.asset_returns),
            Decimal("0"),
        )
        for observation in window.return_path.observations
    )
    if any(value < -1 for value in period_returns):
        blockers.append(
            _block(
                R4RollingBlockerCode.RETURN_PATH_INVALID,
                f"{candidate.kind.value} produced an impossible OOS loss",
                window,
            )
        )
        return None
    gross_return, maximum_drawdown = _path_metrics(period_returns)
    return R4MethodWindowMetrics.create(
        fold_id=window.fold.fold_id,
        kind=candidate.kind,
        period_returns=period_returns,
        gross_return=gross_return,
        realized_variance=_realized_variance(period_returns),
        maximum_drawdown=maximum_drawdown,
        turnover=report.turnover,
        expected_cost=candidate.expected_cost,
        cost_semantics_version=study.rolling_policy.cost_semantics_version,
        candidate_report_hash=report.evidence_hash,
    )


def _exposure_points(
    window: R4RollingWindowInput,
    candidate: MacroRiskCandidateInput,
) -> tuple[R4RollingExposurePoint, ...]:
    return tuple(
        R4RollingExposurePoint.create(
            fold_id=window.fold.fold_id,
            regime_code=window.regime_assignment.regime_code,
            asset_code=exposure.asset_code,
            factor_code=beta.factor_code,
            beta=beta.beta,
            confidence_low=beta.confidence_low,
            confidence_high=beta.confidence_high,
            residual_variance=exposure.residual_variance,
            r_squared=exposure.r_squared,
            stability_score=exposure.stability_score,
        )
        for exposure in candidate.exposure_version.exposures
        for beta in exposure.betas
    )


def _regime_summaries(
    points: Iterable[R4RollingExposurePoint],
) -> tuple[R4RegimeExposureSummary, ...]:
    groups: dict[tuple[str, str, str], list[R4RollingExposurePoint]] = {}
    for point in points:
        groups.setdefault((point.regime_code, point.asset_code, point.factor_code), []).append(
            point
        )
    summaries: list[R4RegimeExposureSummary] = []
    for (regime_code, asset_code, factor_code), values in sorted(groups.items()):
        count = len(values)
        divisor = Decimal(count)
        betas = tuple(item.beta for item in values)
        summaries.append(
            R4RegimeExposureSummary.create(
                regime_code=regime_code,
                asset_code=asset_code,
                factor_code=factor_code,
                window_count=count,
                mean_beta=sum(betas, Decimal("0")) / divisor,
                minimum_beta=min(betas),
                maximum_beta=max(betas),
                mean_residual_variance=(
                    sum((item.residual_variance for item in values), Decimal("0")) / divisor
                ),
                mean_r_squared=(sum((item.r_squared for item in values), Decimal("0")) / divisor),
                mean_stability_score=(
                    sum((item.stability_score for item in values), Decimal("0")) / divisor
                ),
            )
        )
    return tuple(summaries)


def _regime_sample_blockers(
    study: R4RollingStudyInput,
    summaries: tuple[R4RegimeExposureSummary, ...],
) -> tuple[R4RollingBlocker, ...]:
    return tuple(
        R4RollingBlocker(
            code=R4RollingBlockerCode.REGIME_SAMPLE_INSUFFICIENT,
            detail=(
                f"regime={item.regime_code} asset={item.asset_code} "
                f"factor={item.factor_code} has {item.window_count} windows"
            ),
        )
        for item in summaries
        if item.window_count < study.rolling_policy.minimum_regime_windows
    )


def _method_summaries(
    study: R4RollingStudyInput,
    metrics: list[R4MethodWindowMetrics],
) -> tuple[R4MethodBacktestSummary, ...]:
    grouped: dict[MacroRiskCandidateKind, list[R4MethodWindowMetrics]] = {}
    for item in metrics:
        grouped.setdefault(item.kind, []).append(item)
    summaries: list[R4MethodBacktestSummary] = []
    for kind, values in sorted(grouped.items(), key=lambda item: item[0].value):
        period_returns = tuple(value for item in values for value in item.period_returns)
        gross_return, maximum_drawdown = _path_metrics(period_returns)
        summaries.append(
            R4MethodBacktestSummary.create(
                kind=kind,
                window_count=len(values),
                compounded_gross_return=gross_return,
                realized_variance=_realized_variance(period_returns),
                maximum_drawdown=maximum_drawdown,
                total_turnover=sum((item.turnover for item in values), Decimal("0")),
                total_expected_cost=sum(
                    (item.expected_cost for item in values),
                    Decimal("0"),
                ),
                cost_semantics_version=study.rolling_policy.cost_semantics_version,
            )
        )
    return tuple(summaries)


def _realized_variance(values: tuple[Decimal, ...]) -> Decimal:
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    return sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))


def _path_metrics(values: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    nav = Decimal("1")
    peak = Decimal("1")
    maximum_drawdown = Decimal("0")
    for value in values:
        nav *= Decimal("1") + value
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, (peak - nav) / peak)
    return nav - Decimal("1"), maximum_drawdown


def _is_symmetric(
    matrix: tuple[tuple[Decimal, ...], ...],
    tolerance: Decimal,
) -> bool:
    return all(
        abs(matrix[row][column] - matrix[column][row]) <= tolerance
        for row in range(len(matrix))
        for column in range(row + 1, len(matrix))
    )


def _is_positive_semidefinite(
    matrix: tuple[tuple[Decimal, ...], ...],
    tolerance: Decimal,
) -> bool:
    size = len(matrix)
    lower = [[Decimal("0") for _ in range(size)] for _ in range(size)]
    diagonal = [Decimal("0") for _ in range(size)]
    for row in range(size):
        diagonal[row] = matrix[row][row] - sum(
            lower[row][index] * lower[row][index] * diagonal[index] for index in range(row)
        )
        if diagonal[row] < -tolerance:
            return False
        if abs(diagonal[row]) <= tolerance:
            diagonal[row] = Decimal("0")
        for below in range(row + 1, size):
            numerator = matrix[below][row] - sum(
                lower[below][index] * lower[row][index] * diagonal[index] for index in range(row)
            )
            if diagonal[row] == 0:
                if abs(numerator) > tolerance:
                    return False
                lower[below][row] = Decimal("0")
            else:
                lower[below][row] = numerator / diagonal[row]
    return True


def _matrix_vector(
    matrix: tuple[tuple[Decimal, ...], ...],
    vector: tuple[Decimal, ...],
) -> tuple[Decimal, ...]:
    return tuple(
        sum((value * vector[index] for index, value in enumerate(row)), Decimal("0"))
        for row in matrix
    )


def _block(
    code: R4RollingBlockerCode,
    detail: str,
    window: R4RollingWindowInput,
) -> R4RollingBlocker:
    return R4RollingBlocker(code=code, detail=detail, fold_id=window.fold.fold_id)


__all__ = ["evaluate_r4_rolling_study"]
