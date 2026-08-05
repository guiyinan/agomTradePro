"""Typed application-boundary values for governed stress scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from apps.risk_center.domain.scenarios import (
    AssetReturnSeries,
    ScenarioDefinition,
    ScenarioImpact,
    ScenarioParameters,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    ScenarioSourceType,
    ScenarioType,
    stable_content_hash,
)


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class PortfolioPositionDTO:
    """One valued holding in an immutable portfolio snapshot."""

    asset_code: str
    market_value: Decimal
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.asset_code.strip():
            raise ValueError("portfolio position asset_code is required")
        if not self.market_value.is_finite() or self.market_value < 0:
            raise ValueError("portfolio position market_value must be non-negative and finite")


@dataclass(frozen=True)
class PortfolioSnapshotDTO:
    """Provider-neutral immutable portfolio snapshot used by Risk Center."""

    snapshot_id: str
    account_id: str
    as_of_time: datetime
    net_asset_value: Decimal
    cash_value: Decimal
    positions: tuple[PortfolioPositionDTO, ...]
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.account_id.strip():
            raise ValueError("portfolio snapshot identifiers are required")
        _require_aware("PortfolioSnapshotDTO.as_of_time", self.as_of_time)
        if not self.net_asset_value.is_finite() or self.net_asset_value <= 0:
            raise ValueError("portfolio snapshot net_asset_value must be positive and finite")
        if not self.cash_value.is_finite() or self.cash_value < 0:
            raise ValueError("portfolio snapshot cash_value must be non-negative and finite")
        codes = [item.asset_code for item in self.positions]
        if len(codes) != len(set(codes)):
            raise ValueError("portfolio snapshot contains duplicate assets")
        invested = sum((item.market_value for item in self.positions), Decimal("0"))
        if invested + self.cash_value > self.net_asset_value + Decimal("0.000001"):
            raise ValueError("portfolio snapshot components exceed net_asset_value")
        expected = stable_content_hash(
            {
                "snapshot_id": self.snapshot_id,
                "account_id": self.account_id,
                "as_of_time": self.as_of_time,
                "net_asset_value": self.net_asset_value,
                "cash_value": self.cash_value,
                "positions": self.positions,
            }
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("portfolio snapshot content_hash mismatch")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)


@dataclass(frozen=True)
class ScenarioMarketDataDTO:
    """Published/as-of market data plus immutable evidence references."""

    return_series: tuple[AssetReturnSeries, ...]
    evidence_ids: tuple[str, ...]
    observed_at: datetime
    published_at: datetime
    must_not_use_for_decision: bool = False
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _require_aware("ScenarioMarketDataDTO.observed_at", self.observed_at)
        _require_aware("ScenarioMarketDataDTO.published_at", self.published_at)
        if self.published_at < self.observed_at:
            raise ValueError("market data published_at cannot precede observed_at")
        if self.must_not_use_for_decision:
            if not self.blocked_reason.strip():
                raise ValueError("blocked market data requires blocked_reason")
        elif not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("decision-usable market data requires evidence_ids")


@dataclass(frozen=True)
class ScenarioSummaryDTO:
    """Read projection for one definition and its latest eligible revision."""

    definition: ScenarioDefinition
    revision: ScenarioRevision


@dataclass(frozen=True)
class ScenarioRunRequestDTO:
    """Complete version bindings for a reproducible portfolio stress run."""

    scenario_revision_id: str
    portfolio_snapshot_id: str
    as_of_time: datetime
    allocation_policy_version: str
    code_version: str
    scenario_set_revision_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("scenario_revision_id", self.scenario_revision_id),
            ("portfolio_snapshot_id", self.portfolio_snapshot_id),
            ("allocation_policy_version", self.allocation_policy_version),
            ("code_version", self.code_version),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} is required")
        _require_aware("ScenarioRunRequestDTO.as_of_time", self.as_of_time)


@dataclass(frozen=True)
class ScenarioRunResultDTO:
    """Calculated impact paired with its persisted immutable evidence."""

    impact: ScenarioImpact
    evidence: ScenarioRunEvidence


@dataclass(frozen=True)
class ScenarioValidationDTO:
    """Side-effect-free validation result suitable for API transports."""

    valid: bool
    scenario_revision_id: str
    content_hash: str
    errors: tuple[str, ...] = ()
    validated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CreateScenarioRevisionCommandDTO:
    """Server-versioned append command for a draft, candidate, or proposal."""

    scenario_key: str
    scenario_type: ScenarioType
    parameters: ScenarioParameters
    assumptions: tuple[str, ...]
    source_type: ScenarioSourceType
    created_by: str
    change_reason: str
    status: ScenarioRevisionStatus = ScenarioRevisionStatus.DRAFT
    based_on_version: int | None = None
    source_evidence: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {
            ScenarioRevisionStatus.CANDIDATE,
            ScenarioRevisionStatus.DRAFT,
            ScenarioRevisionStatus.PROPOSED,
        }:
            raise ValueError("revision append command cannot activate a scenario")
        if (
            not self.scenario_key.strip()
            or not self.created_by.strip()
            or not self.change_reason.strip()
        ):
            raise ValueError("revision append command requires key, actor, and reason")
        if ScenarioType.for_parameters(self.parameters) is not self.scenario_type:
            raise ValueError("revision append command type does not match parameters")
        if self.based_on_version is not None and self.based_on_version < 1:
            raise ValueError("based_on_version must be positive")


@dataclass(frozen=True)
class ActivateScenarioSetCommandDTO:
    """Optimistic-lock command for an atomic active-set pointer change."""

    environment: str
    purpose: str
    scenario_set_revision_id: str
    activated_by: str
    reason: str
    expected_active_activation_id: str | None
    correlation_id: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("environment", self.environment),
            ("purpose", self.purpose),
            ("scenario_set_revision_id", self.scenario_set_revision_id),
            ("activated_by", self.activated_by),
            ("reason", self.reason),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} is required")


__all__ = [
    "ActivateScenarioSetCommandDTO",
    "CreateScenarioRevisionCommandDTO",
    "PortfolioPositionDTO",
    "PortfolioSnapshotDTO",
    "ScenarioMarketDataDTO",
    "ScenarioRunRequestDTO",
    "ScenarioRunResultDTO",
    "ScenarioSummaryDTO",
    "ScenarioValidationDTO",
]
