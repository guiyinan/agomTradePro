"""Application orchestration for R6 simple-baseline shortfall evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.domain.state_model_baseline import (
    BaselineEvaluationEvidence,
    BaselineEvaluationSpecification,
    BaselineShortfallReport,
    evaluate_baseline_shortfall,
)


class BaselineEvaluationSpecificationProvider(Protocol):
    """Read the active Research-owned evaluation specification."""

    def get_active(
        self,
        *,
        baseline_key: str,
        evaluated_at: datetime,
    ) -> BaselineEvaluationSpecification:
        """Return the exact version active at the requested time."""


class BaselineEvaluationEvidenceProvider(Protocol):
    """Read immutable PIT-bound evaluation evidence."""

    def get_latest(
        self,
        *,
        specification: BaselineEvaluationSpecification,
        evaluated_at: datetime,
    ) -> BaselineEvaluationEvidence:
        """Return evidence without recomputing it from revised current data."""


class EvaluateSimpleBaselineShortfallUseCase:
    """Decide whether evidence permits proposing advanced R6 research."""

    def __init__(
        self,
        *,
        specification_provider: BaselineEvaluationSpecificationProvider,
        evidence_provider: BaselineEvaluationEvidenceProvider,
    ) -> None:
        self._specification_provider = specification_provider
        self._evidence_provider = evidence_provider

    def execute(
        self,
        *,
        baseline_key: str,
        evaluated_at: datetime,
    ) -> BaselineShortfallReport:
        """Evaluate only the active specification and its frozen evidence."""

        specification = self._specification_provider.get_active(
            baseline_key=baseline_key,
            evaluated_at=evaluated_at,
        )
        evidence = self._evidence_provider.get_latest(
            specification=specification,
            evaluated_at=evaluated_at,
        )
        return evaluate_baseline_shortfall(
            specification=specification,
            evidence=evidence,
            evaluated_at=evaluated_at,
        )
