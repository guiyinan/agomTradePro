"""Typed evidence contracts for scenario-bound forecast publications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from math import isfinite
from uuid import UUID


class ScenarioProbabilitySource(str, Enum):
    """Probability columns that must remain semantically separate."""

    SUBJECTIVE = "subjective"
    MODEL_INFERRED = "model_inferred"


def _probability(value: object, field_name: str) -> Decimal:
    """Normalize a finite probability without binary-float persistence drift."""

    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite probability")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite probability") from exc
    if not normalized.is_finite() or not Decimal("0") <= normalized <= Decimal("1"):
        raise ValueError(f"{field_name} must be within [0, 1]")
    return normalized


def _nonblank(value: object, field_name: str, *, maximum: int = 64) -> str:
    """Normalize a bounded immutable evidence reference."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def scenario_revision_uuid(value: object, field_name: str) -> UUID:
    """Normalize one stable Risk Center revision reference."""

    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID")
    try:
        return UUID(value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


@dataclass(frozen=True)
class ScenarioForecastBinding:
    """Freeze one Risk Center revision and separately sourced probabilities."""

    scenario_revision_id: UUID
    scenario_set_revision_id: UUID | None
    subjective_probability: Decimal
    subjective_probability_source_version: str
    model_probability: Decimal | None = None
    model_probability_source_version: str | None = None
    model_promotion_decision_id: str | None = None

    @classmethod
    def from_values(
        cls,
        *,
        scenario_revision_id: object,
        scenario_set_revision_id: object | None,
        subjective_probability: object,
        subjective_probability_source_version: object,
        model_probability: object | None = None,
        model_probability_source_version: object | None = None,
        model_promotion_decision_id: object | None = None,
    ) -> ScenarioForecastBinding:
        """Normalize boundary values into one immutable binding."""

        return cls(
            scenario_revision_id=scenario_revision_uuid(
                scenario_revision_id,
                "scenario_revision_id",
            ),
            scenario_set_revision_id=(
                None
                if scenario_set_revision_id is None
                else scenario_revision_uuid(
                    scenario_set_revision_id,
                    "scenario_set_revision_id",
                )
            ),
            subjective_probability=_probability(
                subjective_probability,
                "subjective_probability",
            ),
            subjective_probability_source_version=_nonblank(
                subjective_probability_source_version,
                "subjective_probability_source_version",
            ),
            model_probability=(
                None
                if model_probability is None
                else _probability(model_probability, "model_probability")
            ),
            model_probability_source_version=(
                None
                if model_probability_source_version is None
                else _nonblank(
                    model_probability_source_version,
                    "model_probability_source_version",
                )
            ),
            model_promotion_decision_id=(
                None
                if model_promotion_decision_id is None
                else _nonblank(
                    model_promotion_decision_id,
                    "model_promotion_decision_id",
                )
            ),
        )

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_revision_id, UUID):
            raise ValueError("scenario_revision_id must be a UUID")
        if self.scenario_set_revision_id is not None and not isinstance(
            self.scenario_set_revision_id,
            UUID,
        ):
            raise ValueError("scenario_set_revision_id must be a UUID")
        object.__setattr__(
            self,
            "subjective_probability",
            _probability(self.subjective_probability, "subjective_probability"),
        )
        object.__setattr__(
            self,
            "subjective_probability_source_version",
            _nonblank(
                self.subjective_probability_source_version,
                "subjective_probability_source_version",
            ),
        )
        model_fields = (
            self.model_probability,
            self.model_probability_source_version,
            self.model_promotion_decision_id,
        )
        if all(value is None for value in model_fields):
            return
        if any(value is None for value in model_fields):
            raise ValueError("model probability requires source version and promotion decision")
        object.__setattr__(
            self,
            "model_probability",
            _probability(self.model_probability, "model_probability"),
        )
        object.__setattr__(
            self,
            "model_probability_source_version",
            _nonblank(
                self.model_probability_source_version,
                "model_probability_source_version",
            ),
        )
        object.__setattr__(
            self,
            "model_promotion_decision_id",
            _nonblank(
                self.model_promotion_decision_id,
                "model_promotion_decision_id",
            ),
        )

    @property
    def has_model_probability(self) -> bool:
        """Return whether a promoted model probability was frozen."""

        return self.model_probability is not None


@dataclass(frozen=True)
class ScenarioForecastOutcomeEvidence:
    """One explicit scenario realization and its source-separated row scores."""

    entry_id: str
    binding: ScenarioForecastBinding
    finalized_at: datetime
    scenario_realized: bool
    subjective_brier_score: float
    model_brier_score: float | None

    def __post_init__(self) -> None:
        """Reject ambiguous identifiers, naive times, and invalid row scores."""

        _nonblank(self.entry_id, "entry_id")
        if self.finalized_at.tzinfo is None or self.finalized_at.utcoffset() is None:
            raise ValueError("finalized_at must be timezone-aware")
        for field_name, value in (
            ("subjective_brier_score", self.subjective_brier_score),
            ("model_brier_score", self.model_brier_score),
        ):
            if value is not None and (not isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{field_name} must be within [0, 1]")

    def score_for(self, source: ScenarioProbabilitySource) -> float | None:
        """Return the row score for exactly one probability source."""

        if source is ScenarioProbabilitySource.SUBJECTIVE:
            return self.subjective_brier_score
        return self.model_brier_score


__all__ = [
    "ScenarioForecastBinding",
    "ScenarioForecastOutcomeEvidence",
    "ScenarioProbabilitySource",
    "scenario_revision_uuid",
]
