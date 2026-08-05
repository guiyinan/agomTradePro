"""Current-configuration benchmark derived from Portfolio canonical truth."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.portfolio.domain.canonical_snapshots import CanonicalPortfolioSnapshot
from apps.portfolio.domain.constrained_optimization_contracts import CandidateKind

from ._optimization_canonical import (
    decimal_text,
    hash_components,
    require_ordered_unique,
    require_positive,
    require_sha256,
    require_token,
    require_unit_interval,
)
from .investable_universe import InvestableUniverseSnapshot


@dataclass(frozen=True)
class CurrentConfigurationBaseline:
    """Observed weights with zero turnover/cost and no feasibility rewriting."""

    candidate_kind: CandidateKind
    snapshot_id: str
    snapshot_hash: str
    universe_hash: str
    asset_codes: tuple[str, ...]
    weights: tuple[Decimal, ...]
    cash_weight: Decimal
    weight_tolerance: Decimal
    observed_turnover: Decimal
    observed_transaction_cost: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        """Recompute the exact canonical-snapshot benchmark."""

        if self.candidate_kind is not CandidateKind.CURRENT_CONFIGURATION:
            raise ValueError("current baseline candidate kind is invalid")
        require_token(self.snapshot_id, "snapshot_id")
        require_sha256(self.snapshot_hash, "snapshot_hash")
        require_sha256(self.universe_hash, "universe_hash")
        require_ordered_unique(self.asset_codes, "current baseline assets")
        if len(self.weights) != len(self.asset_codes):
            raise ValueError("current baseline weights must align with assets")
        for weight in self.weights:
            require_unit_interval(weight, "current baseline weight")
        require_unit_interval(self.cash_weight, "current baseline cash_weight")
        require_positive(self.weight_tolerance, "current baseline weight_tolerance")
        if abs(sum(self.weights, self.cash_weight) - Decimal("1")) > self.weight_tolerance:
            raise ValueError("current baseline weights and cash must sum to one")
        if self.observed_turnover != 0 or self.observed_transaction_cost != 0:
            raise ValueError("current baseline must preserve zero observed trade and cost")
        require_sha256(self.content_hash, "current baseline content_hash")
        if self.content_hash != current_configuration_hash(self):
            raise ValueError("current baseline content hash mismatch")


def build_current_configuration_baseline(
    *,
    snapshot: CanonicalPortfolioSnapshot,
    universe: InvestableUniverseSnapshot,
    weight_tolerance: Decimal,
) -> CurrentConfigurationBaseline:
    """Derive current weights, preserving held-only and zero-weight new members."""

    member_by_code = {item.asset_code: item for item in universe.members}
    for position in snapshot.positions:
        member = member_by_code.get(position.asset_code)
        if member is None:
            raise ValueError("canonical holding is absent from the Published universe")
        if not (member.can_sell or member.retain_if_held):
            raise ValueError("canonical holding lacks a governed held-retention rule")
    total_value = snapshot.cash_balance + sum(
        (item.market_value_base for item in snapshot.positions),
        Decimal("0"),
    )
    if total_value <= 0:
        raise ValueError("canonical snapshot total value must be positive")
    values = {item.asset_code: item.market_value_base for item in snapshot.positions}
    codes = tuple(item.asset_code for item in universe.members)
    weights = tuple(values.get(code, Decimal("0")) / total_value for code in codes)
    cash_weight = snapshot.cash_balance / total_value
    digest = _current_configuration_hash_values(
        snapshot.snapshot_id,
        snapshot.content_hash,
        universe.universe_hash,
        codes,
        weights,
        cash_weight,
        weight_tolerance,
    )
    return CurrentConfigurationBaseline(
        candidate_kind=CandidateKind.CURRENT_CONFIGURATION,
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.content_hash,
        universe_hash=universe.universe_hash,
        asset_codes=codes,
        weights=weights,
        cash_weight=cash_weight,
        weight_tolerance=weight_tolerance,
        observed_turnover=Decimal("0"),
        observed_transaction_cost=Decimal("0"),
        content_hash=digest,
    )


def current_configuration_hash(baseline: CurrentConfigurationBaseline) -> str:
    """Recompute the current-configuration benchmark digest."""

    return _current_configuration_hash_values(
        baseline.snapshot_id,
        baseline.snapshot_hash,
        baseline.universe_hash,
        baseline.asset_codes,
        baseline.weights,
        baseline.cash_weight,
        baseline.weight_tolerance,
    )


def _current_configuration_hash_values(
    snapshot_id: str,
    snapshot_hash: str,
    universe_hash: str,
    asset_codes: tuple[str, ...],
    weights: tuple[Decimal, ...],
    cash_weight: Decimal,
    weight_tolerance: Decimal,
) -> str:
    return hash_components(
        "current-configuration-baseline.v1",
        CandidateKind.CURRENT_CONFIGURATION.value,
        snapshot_id,
        snapshot_hash,
        universe_hash,
        *(
            f"{code}|{decimal_text(weight)}"
            for code, weight in zip(asset_codes, weights, strict=True)
        ),
        decimal_text(cash_weight),
        decimal_text(weight_tolerance),
        "observed_turnover=0",
        "observed_transaction_cost=0",
    )


__all__ = [
    "CurrentConfigurationBaseline",
    "build_current_configuration_baseline",
    "current_configuration_hash",
]
