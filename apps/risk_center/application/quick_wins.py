"""Application services for evidence-led scenario research quick wins."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from apps.risk_center.domain.quick_wins import (
    AssetGroupRevision,
    DecisionScorecard,
    EvidenceDirection,
    EvidencePoint,
    MarketDimension,
    MarketStateEvidenceCard,
    ScenarioImpact,
    ScenarioMatrixPreview,
    ScoreComponent,
    SensitivityOperator,
    SensitivityTemplate,
    StrategyBrief,
)


def _weighted_score(components: tuple[ScoreComponent, ...]) -> float:
    """Calculate a score after callers have passed evidence gates."""

    total_weight = sum(component.weight for component in components)
    if total_weight <= 0:
        raise ValueError("score component weights must have a positive sum")
    weighted_total = 0.0
    for component in components:
        if component.score is None:
            raise ValueError("usable score components require numeric values")
        weighted_total += component.score * component.weight
    return round(weighted_total / total_weight, 2)


class BuildDecisionScorecard:
    """Build QW-2 without replacing unavailable inputs with neutral values."""

    def execute(
        self,
        *,
        environment_components: tuple[ScoreComponent, ...],
        valuation_components: tuple[ScoreComponent, ...],
        weight_configuration_version: str,
        as_of_time: datetime,
    ) -> DecisionScorecard:
        """Return a usable dual score or an explicit blocked result."""

        if not environment_components or not valuation_components:
            raise ValueError("both scorecard component groups are required")
        all_components = environment_components + valuation_components
        missing = tuple(
            component.key
            for component in all_components
            if component.score is None or not component.evidence.decision_usable
        )
        critical_missing = tuple(
            component.key
            for component in all_components
            if component.critical
            and (component.score is None or not component.evidence.decision_usable)
        )
        blocked = bool(critical_missing)
        reasons = (
            ("critical score evidence unavailable: " + ", ".join(critical_missing),)
            if blocked
            else ()
        )
        return DecisionScorecard(
            environment_fit_score=(None if blocked else _weighted_score(environment_components)),
            valuation_odds_score=(None if blocked else _weighted_score(valuation_components)),
            environment_components=environment_components,
            valuation_components=valuation_components,
            weight_configuration_version=weight_configuration_version,
            as_of_time=as_of_time,
            missing_items=missing,
            blocked_reasons=reasons,
            must_not_use_for_decision=blocked,
        )


class BuildMarketStateEvidenceCard:
    """Build QW-3 while retaining directional conflicts and missing facts."""

    def execute(
        self,
        *,
        dimensions: tuple[MarketDimension, ...],
        as_of_time: datetime,
    ) -> MarketStateEvidenceCard:
        """Return a five-dimensional evidence card with stable blocking reasons."""

        unavailable = tuple(
            dimension.key for dimension in dimensions if not dimension.decision_usable
        )
        reasons = (
            ("market-state evidence unavailable: " + ", ".join(unavailable),) if unavailable else ()
        )
        return MarketStateEvidenceCard(
            dimensions=dimensions,
            as_of_time=as_of_time,
            blocked_reasons=reasons,
            must_not_use_for_decision=bool(unavailable),
        )


class PreviewScenarioMatrix:
    """Build QW-1 probability-weighted portfolio impact without side effects."""

    def execute(
        self,
        *,
        scenario_set_revision_id: str,
        portfolio_snapshot_id: str,
        allocation_policy_version: str,
        impacts: tuple[ScenarioImpact, ...],
        as_of_time: datetime,
    ) -> ScenarioMatrixPreview:
        """Return an auditable preview or fail closed on stale inputs."""

        unusable = tuple(
            impact.scenario_revision_id for impact in impacts if not impact.decision_usable
        )
        reasons = ("scenario evidence unavailable: " + ", ".join(unusable),) if unusable else ()
        weighted = (
            None
            if unusable
            else round(
                sum(impact.probability * impact.portfolio_return for impact in impacts),
                8,
            )
        )
        return ScenarioMatrixPreview(
            scenario_set_revision_id=scenario_set_revision_id,
            portfolio_snapshot_id=portfolio_snapshot_id,
            allocation_policy_version=allocation_policy_version,
            impacts=impacts,
            weighted_portfolio_return=weighted,
            as_of_time=as_of_time,
            blocked_reasons=reasons,
            must_not_use_for_decision=bool(unusable),
        )


class GenerateStructuredStrategyBrief:
    """Build QW-4 from already-calculated, explicitly referenced facts."""

    def execute(
        self,
        *,
        title: str,
        sections: Mapping[str, str],
        fact_references: tuple[str, ...],
        scenario_set_revision_id: str,
        prompt_version: str,
        generated_at: datetime,
        blocked_reasons: tuple[str, ...] = (),
    ) -> StrategyBrief:
        """Return a brief without calculating or silently repairing financial facts."""

        must_block = bool(blocked_reasons)
        normalized_sections = dict(sections)
        if must_block:
            normalized_sections["data_quality"] = "；".join(blocked_reasons)
        return StrategyBrief(
            title=title,
            sections=normalized_sections,
            fact_references=fact_references,
            scenario_set_revision_id=scenario_set_revision_id,
            prompt_version=prompt_version,
            generated_at=generated_at,
            blocked_reasons=blocked_reasons,
            must_not_use_for_decision=must_block,
        )


class BuildFixedIncomeSpreadRadar:
    """QW-5 coverage gate; no trading output is produced."""

    REQUIRED_SERIES = frozenset(
        {"government_10y", "government_2y", "policy_rate", "short_funding", "credit_spread"}
    )

    def execute(self, evidence: Mapping[str, EvidencePoint]) -> dict[str, object]:
        """Return a read-only radar or an explicit unavailable result."""

        missing = sorted(self.REQUIRED_SERIES.difference(evidence))
        unusable = sorted(
            key
            for key in self.REQUIRED_SERIES.intersection(evidence)
            if not evidence[key].decision_usable
        )
        blocked = missing + unusable
        if blocked:
            return {
                "status": "blocked",
                "must_not_use_for_decision": True,
                "blocked_reason": "fixed-income coverage unavailable: " + ", ".join(blocked),
                "spreads": {},
            }
        values: dict[str, float] = {}
        for key in self.REQUIRED_SERIES:
            value = evidence[key].value
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"fixed-income evidence must be numeric: {key}")
            values[key] = float(value)
        return {
            "status": "available",
            "must_not_use_for_decision": False,
            "unit": "bp",
            "spreads": {
                "term_10y_2y": round((values["government_10y"] - values["government_2y"]) * 100, 4),
                "government_10y_policy": round(
                    (values["government_10y"] - values["policy_rate"]) * 100, 4
                ),
                "government_2y_funding": round(
                    (values["government_2y"] - values["short_funding"]) * 100, 4
                ),
                "credit": round(values["credit_spread"] * 100, 4),
            },
        }


class CompareAssetGroups:
    """QW-6 comparison over database-supplied group revisions."""

    def execute(
        self,
        *,
        left: AssetGroupRevision,
        right: AssetGroupRevision,
        metrics: Mapping[str, Mapping[str, EvidencePoint]],
    ) -> dict[str, object]:
        """Compare fresh group facts without converting them into a trade signal."""

        group_keys = {left.group_key, right.group_key}
        if set(metrics) != group_keys:
            raise ValueError("metrics must match both asset group revisions")
        blocked = sorted(
            f"{group_key}.{metric_key}"
            for group_key, group_metrics in metrics.items()
            for metric_key, point in group_metrics.items()
            if not point.decision_usable
        )
        return {
            "status": "blocked" if blocked else "descriptive",
            "must_not_use_for_decision": bool(blocked),
            "blocked_items": blocked,
            "group_versions": {
                left.group_key: left.version,
                right.group_key: right.version,
            },
            "metrics": {
                group_key: {metric_key: point.value for metric_key, point in group_metrics.items()}
                for group_key, group_metrics in metrics.items()
            },
            "interpretation": "structure_description_only",
        }


class RunSensitivityWorksheet:
    """QW-7 finite-operator worksheet; arbitrary formulas are impossible."""

    def execute(
        self,
        *,
        template: SensitivityTemplate,
        assumptions: Mapping[str, float],
    ) -> dict[str, float]:
        """Evaluate a typed base/bull/bear input set through finite operations."""

        values = {key: float(value) for key, value in assumptions.items()}
        for step in template.steps:
            try:
                inputs = [values[key] for key in step.input_keys]
            except KeyError as exc:
                raise ValueError(f"missing sensitivity input: {exc.args[0]}") from exc
            if step.operator is SensitivityOperator.MULTIPLY:
                result = 1.0
                for value in inputs:
                    result *= value
            elif step.operator is SensitivityOperator.ADD:
                result = sum(inputs)
            else:
                raise ValueError("unsupported sensitivity operator")
            values[step.output_key] = result
        return values


def infer_dimension_direction(evidence: tuple[EvidencePoint, ...]) -> EvidenceDirection:
    """Preserve conflict instead of averaging opposed evidence directions."""

    directions = {
        item.direction
        for item in evidence
        if item.direction not in {EvidenceDirection.UNKNOWN, EvidenceDirection.NEUTRAL}
    }
    if len(directions) > 1:
        return EvidenceDirection.MIXED
    if directions:
        return next(iter(directions))
    if any(item.direction is EvidenceDirection.NEUTRAL for item in evidence):
        return EvidenceDirection.NEUTRAL
    return EvidenceDirection.UNKNOWN
