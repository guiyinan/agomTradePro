"""Pure domain values for scenario-research quick wins.

The values in this module deliberately carry evidence timestamps and blocking
state.  A missing input is never converted into a neutral score.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType


class EvidenceState(str, Enum):
    """Publication and freshness state of one research input."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNPUBLISHED = "unpublished"
    BLOCKED = "blocked"


class EvidenceDirection(str, Enum):
    """Directional interpretation without forcing a composite conclusion."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidencePoint:
    """One published fact used by a quick-win decision surface."""

    key: str
    value: float | str | None
    source: str
    observed_at: datetime | None
    state: EvidenceState
    coverage: float
    direction: EvidenceDirection = EvidenceDirection.UNKNOWN

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.source.strip():
            raise ValueError("evidence key and source are required")
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError("evidence coverage must be between 0 and 1")
        if self.observed_at is not None and self.observed_at.utcoffset() is None:
            raise ValueError("evidence observed_at must be timezone-aware")
        if self.state is EvidenceState.FRESH and self.observed_at is None:
            raise ValueError("fresh evidence requires its source observation time")
        if self.state is EvidenceState.MISSING and self.value is not None:
            raise ValueError("missing evidence cannot publish a value")

    @property
    def decision_usable(self) -> bool:
        """Return whether the evidence can support a decision result."""

        return self.state is EvidenceState.FRESH and self.observed_at is not None


@dataclass(frozen=True)
class ScoreComponent:
    """One governed score input and its version-supplied weight."""

    key: str
    score: float | None
    weight: float
    evidence: EvidencePoint
    critical: bool = True

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("score component key is required")
        if self.weight <= 0:
            raise ValueError("score component weight must be positive")
        if self.score is not None and not 0.0 <= self.score <= 100.0:
            raise ValueError("score component value must be between 0 and 100")


@dataclass(frozen=True)
class DecisionScorecard:
    """Ex-ante environment-fit and valuation-odds scores."""

    environment_fit_score: float | None
    valuation_odds_score: float | None
    environment_components: tuple[ScoreComponent, ...]
    valuation_components: tuple[ScoreComponent, ...]
    weight_configuration_version: str
    as_of_time: datetime
    missing_items: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        if self.as_of_time.utcoffset() is None:
            raise ValueError("scorecard as_of_time must be timezone-aware")
        if not self.weight_configuration_version.strip():
            raise ValueError("scorecard weight configuration version is required")
        for value in (self.environment_fit_score, self.valuation_odds_score):
            if value is not None and not 0.0 <= value <= 100.0:
                raise ValueError("scorecard values must be between 0 and 100")
        if self.must_not_use_for_decision and (
            self.environment_fit_score is not None or self.valuation_odds_score is not None
        ):
            raise ValueError("blocked scorecards cannot publish decision scores")


@dataclass(frozen=True)
class MarketDimension:
    """One of the five market-state evidence dimensions."""

    key: str
    label: str
    evidence: tuple[EvidencePoint, ...]
    direction: EvidenceDirection
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.label.strip():
            raise ValueError("market dimension key and label are required")
        if not self.evidence:
            raise ValueError("market dimension must retain its evidence")

    @property
    def decision_usable(self) -> bool:
        """Return whether all facts in this dimension are usable."""

        return all(item.decision_usable for item in self.evidence)


@dataclass(frozen=True)
class MarketStateEvidenceCard:
    """Five-dimensional state card that preserves conflicting evidence."""

    dimensions: tuple[MarketDimension, ...]
    as_of_time: datetime
    blocked_reasons: tuple[str, ...]
    must_not_use_for_decision: bool

    REQUIRED_DIMENSIONS = frozenset({"macro", "industry", "earnings", "liquidity", "valuation"})

    def __post_init__(self) -> None:
        if self.as_of_time.utcoffset() is None:
            raise ValueError("market-state as_of_time must be timezone-aware")
        keys = {dimension.key for dimension in self.dimensions}
        if keys != self.REQUIRED_DIMENSIONS:
            raise ValueError("market-state card requires exactly five canonical dimensions")


@dataclass(frozen=True)
class ScenarioImpact:
    """Impact of an immutable scenario revision on one portfolio snapshot."""

    scenario_revision_id: str
    probability: float
    portfolio_return: float
    asset_impacts: Mapping[str, float]
    invalidation_logic: str
    evidence: tuple[EvidencePoint, ...]

    def __post_init__(self) -> None:
        if not self.scenario_revision_id.strip() or not self.invalidation_logic.strip():
            raise ValueError("scenario revision and invalidation logic are required")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("scenario probability must be between 0 and 1")
        object.__setattr__(self, "asset_impacts", MappingProxyType(dict(self.asset_impacts)))

    @property
    def decision_usable(self) -> bool:
        """Return whether every scenario input is published and fresh."""

        return bool(self.evidence) and all(item.decision_usable for item in self.evidence)


@dataclass(frozen=True)
class ScenarioMatrixPreview:
    """Probability-weighted preview that never executes a trade."""

    scenario_set_revision_id: str
    portfolio_snapshot_id: str
    allocation_policy_version: str
    impacts: tuple[ScenarioImpact, ...]
    weighted_portfolio_return: float | None
    as_of_time: datetime
    blocked_reasons: tuple[str, ...]
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        if self.as_of_time.utcoffset() is None:
            raise ValueError("scenario preview as_of_time must be timezone-aware")
        references = (
            self.scenario_set_revision_id,
            self.portfolio_snapshot_id,
            self.allocation_policy_version,
        )
        if any(not item.strip() for item in references):
            raise ValueError("scenario, portfolio, and allocation versions are required")
        probability = sum(item.probability for item in self.impacts)
        if abs(probability - 1.0) > 1e-9:
            raise ValueError("scenario probabilities must sum to 1")
        if self.must_not_use_for_decision and self.weighted_portfolio_return is not None:
            raise ValueError("blocked scenario previews cannot publish weighted results")


@dataclass(frozen=True)
class StrategyBrief:
    """Auditable brief generated from structured facts only."""

    title: str
    sections: Mapping[str, str]
    fact_references: tuple[str, ...]
    scenario_set_revision_id: str
    prompt_version: str
    generated_at: datetime
    blocked_reasons: tuple[str, ...]
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        if self.generated_at.utcoffset() is None:
            raise ValueError("strategy brief generated_at must be timezone-aware")
        required = {
            "environment",
            "market_state",
            "scenarios",
            "scorecard",
            "portfolio_vulnerabilities",
            "counter_view",
            "data_quality",
        }
        if set(self.sections) != required:
            raise ValueError("strategy brief requires all canonical sections")
        if not self.fact_references:
            raise ValueError("strategy brief requires fact references")
        object.__setattr__(self, "sections", MappingProxyType(dict(self.sections)))


@dataclass(frozen=True)
class AssetGroupRevision:
    """Versioned custom asset group; members never live in Python constants."""

    group_key: str
    version: int
    members: tuple[str, ...]
    effective_from: date
    effective_to: date | None
    source: str

    def __post_init__(self) -> None:
        if not self.group_key.strip() or not self.source.strip() or self.version < 1:
            raise ValueError("asset group identity, version, and source are required")
        if not self.members or any(not member.strip() for member in self.members):
            raise ValueError("asset group members must be non-empty")
        if len(set(self.members)) != len(self.members):
            raise ValueError("asset group members must be unique")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("asset group effective range is invalid")


class SensitivityOperator(str, Enum):
    """Finite operator set for typed sensitivity templates."""

    MULTIPLY = "multiply"
    ADD = "add"


@dataclass(frozen=True)
class SensitivityStep:
    """One safe, non-script sensitivity calculation step."""

    output_key: str
    operator: SensitivityOperator
    input_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.output_key.strip() or len(self.input_keys) < 2:
            raise ValueError("sensitivity step requires an output and at least two inputs")
        if any(not key.strip() for key in self.input_keys):
            raise ValueError("sensitivity input keys must be non-empty")


@dataclass(frozen=True)
class SensitivityTemplate:
    """Database-supplied finite calculation template."""

    template_key: str
    version: int
    steps: tuple[SensitivityStep, ...]
    source: str

    def __post_init__(self) -> None:
        if not self.template_key.strip() or self.version < 1 or not self.source.strip():
            raise ValueError("sensitivity template identity and source are required")
        if not self.steps:
            raise ValueError("sensitivity template requires at least one finite step")
