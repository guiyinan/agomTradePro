"""Exact derivation checks for sealed R4 rolling research outputs."""

from __future__ import annotations

from decimal import Decimal

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind

from .macro_risk_rolling_contracts import (
    R4MethodBacktestSummary,
    R4MethodWindowMetrics,
    R4RegimeExposureSummary,
    R4RollingExposurePoint,
    R4RollingStudyInput,
)


def _exposures_match_study(
    study: R4RollingStudyInput,
    exposure_points: tuple[R4RollingExposurePoint, ...],
) -> bool:
    expected = tuple(
        sorted(
            (
                window.fold.fold_id,
                window.regime_assignment.regime_code,
                exposure.asset_code,
                beta.factor_code,
                beta.beta,
                beta.confidence_low,
                beta.confidence_high,
                exposure.residual_variance,
                exposure.r_squared,
                exposure.stability_score,
            )
            for window in study.windows
            for exposure in window.macro_projection.exposure_version.exposures
            for beta in exposure.betas
        )
    )
    actual = tuple(
        sorted(
            (
                item.fold_id,
                item.regime_code,
                item.asset_code,
                item.factor_code,
                item.beta,
                item.confidence_low,
                item.confidence_high,
                item.residual_variance,
                item.r_squared,
                item.stability_score,
            )
            for item in exposure_points
        )
    )
    return actual == expected


def _regime_summaries_match_points(
    exposure_points: tuple[R4RollingExposurePoint, ...],
    regime_summaries: tuple[R4RegimeExposureSummary, ...],
) -> bool:
    groups: dict[tuple[str, str, str], list[R4RollingExposurePoint]] = {}
    for point in exposure_points:
        groups.setdefault((point.regime_code, point.asset_code, point.factor_code), []).append(
            point
        )
    expected = []
    for identity, values in sorted(groups.items()):
        divisor = Decimal(len(values))
        betas = tuple(item.beta for item in values)
        expected.append(
            (
                *identity,
                len(values),
                sum(betas, Decimal("0")) / divisor,
                min(betas),
                max(betas),
                sum((item.residual_variance for item in values), Decimal("0")) / divisor,
                sum((item.r_squared for item in values), Decimal("0")) / divisor,
                sum((item.stability_score for item in values), Decimal("0")) / divisor,
            )
        )
    actual = tuple(
        (
            item.regime_code,
            item.asset_code,
            item.factor_code,
            item.window_count,
            item.mean_beta,
            item.minimum_beta,
            item.maximum_beta,
            item.mean_residual_variance,
            item.mean_r_squared,
            item.mean_stability_score,
        )
        for item in sorted(
            regime_summaries,
            key=lambda value: (value.regime_code, value.asset_code, value.factor_code),
        )
    )
    return actual == tuple(expected)


def _path_summary(values: tuple[Decimal, ...]) -> tuple[Decimal, Decimal, Decimal]:
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))
    nav = Decimal("1")
    peak = Decimal("1")
    maximum_drawdown = Decimal("0")
    for value in values:
        nav *= Decimal("1") + value
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, (peak - nav) / peak)
    return nav - Decimal("1"), variance, maximum_drawdown


def _method_summaries_match_metrics(
    expected_fold_ids: tuple[str, ...],
    window_metrics: tuple[R4MethodWindowMetrics, ...],
    method_summaries: tuple[R4MethodBacktestSummary, ...],
) -> bool:
    expected = []
    for kind in MacroRiskCandidateKind:
        values = tuple(
            next(item for item in window_metrics if item.fold_id == fold_id and item.kind is kind)
            for fold_id in expected_fold_ids
        )
        semantics = {item.cost_semantics_version for item in values}
        if len(semantics) != 1:
            return False
        period_returns = tuple(value for item in values for value in item.period_returns)
        gross_return, variance, maximum_drawdown = _path_summary(period_returns)
        expected.append(
            (
                kind,
                len(values),
                gross_return,
                variance,
                maximum_drawdown,
                sum((item.turnover for item in values), Decimal("0")),
                sum((item.expected_cost for item in values), Decimal("0")),
                next(iter(semantics)),
            )
        )
    actual = tuple(
        (
            item.kind,
            item.window_count,
            item.compounded_gross_return,
            item.realized_variance,
            item.maximum_drawdown,
            item.total_turnover,
            item.total_expected_cost,
            item.cost_semantics_version,
        )
        for item in sorted(method_summaries, key=lambda value: value.kind.value)
    )
    return actual == tuple(sorted(expected, key=lambda value: value[0].value))


def artifact_is_complete(
    *,
    study: R4RollingStudyInput | None,
    expected_fold_ids: tuple[str, ...],
    window_metrics: tuple[R4MethodWindowMetrics, ...],
    exposure_points: tuple[R4RollingExposurePoint, ...],
    regime_summaries: tuple[R4RegimeExposureSummary, ...],
    method_summaries: tuple[R4MethodBacktestSummary, ...],
) -> bool:
    """Recompute completeness and all aggregate values from sealed lower-level evidence."""

    expected_methods = frozenset(MacroRiskCandidateKind)
    expected_identities = {
        (fold_id, kind) for fold_id in expected_fold_ids for kind in expected_methods
    }
    identities = {(item.fold_id, item.kind) for item in window_metrics}
    exposure_identities = tuple(
        (item.fold_id, item.regime_code, item.asset_code, item.factor_code)
        for item in exposure_points
    )
    exposure_shape_by_fold = {
        fold_id: {
            (item.asset_code, item.factor_code)
            for item in exposure_points
            if item.fold_id == fold_id
        }
        for fold_id in expected_fold_ids
    }
    exposure_shapes = tuple(exposure_shape_by_fold.values())
    expected_regime_identities = {
        (item.regime_code, item.asset_code, item.factor_code) for item in exposure_points
    }
    regime_identities = {
        (item.regime_code, item.asset_code, item.factor_code) for item in regime_summaries
    }
    regime_counts = {
        identity: len(
            {
                item.fold_id
                for item in exposure_points
                if (item.regime_code, item.asset_code, item.factor_code) == identity
            }
        )
        for identity in expected_regime_identities
    }
    return (
        identities == expected_identities
        and len(window_metrics) == len(expected_identities)
        and {item.kind for item in method_summaries} == expected_methods
        and len(method_summaries) == len(expected_methods)
        and all(item.window_count == len(expected_fold_ids) for item in method_summaries)
        and bool(exposure_points)
        and {item.fold_id for item in exposure_points} == set(expected_fold_ids)
        and len(exposure_identities) == len(set(exposure_identities))
        and bool(exposure_shapes[0])
        and all(shape == exposure_shapes[0] for shape in exposure_shapes[1:])
        and regime_identities == expected_regime_identities
        and len(regime_summaries) == len(regime_identities)
        and all(
            item.window_count
            == regime_counts[(item.regime_code, item.asset_code, item.factor_code)]
            for item in regime_summaries
        )
        and (study is None or _exposures_match_study(study, exposure_points))
        and _regime_summaries_match_points(exposure_points, regime_summaries)
        and _method_summaries_match_metrics(
            expected_fold_ids,
            window_metrics,
            method_summaries,
        )
    )


__all__ = ["artifact_is_complete"]
