"""Actual frozen-weight NAV path and peak-to-trough drawdown evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.portfolio.domain.optimizer_inputs import OptimizationInputKind

from ._optimization_canonical import (
    decimal_text,
    hash_components,
    require_aware,
    require_finite,
    require_ordered_unique,
    require_positive,
    require_sha256,
    require_token,
    require_unit_interval,
    utc_text,
    validate_content_hash,
)
from .input_payloads import AssetDecimalValue


@dataclass(frozen=True)
class DrawdownPathObservation:
    """One PIT period return vector used to reconstruct a portfolio NAV path."""

    period_end: datetime
    asset_returns: tuple[AssetDecimalValue, ...]
    cash_return: Decimal

    def __post_init__(self) -> None:
        """Require ordered returns, an aware period end, and possible losses."""

        require_aware(self.period_end, "drawdown period_end")
        require_ordered_unique(
            tuple(item.asset_code for item in self.asset_returns),
            "drawdown path assets",
        )
        require_finite(self.cash_return, "drawdown cash_return")
        if self.cash_return < -1 or any(item.value < -1 for item in self.asset_returns):
            raise ValueError("drawdown path returns cannot be below -100%")


@dataclass(frozen=True)
class DrawdownRiskBudgetPayload:
    """PIT return path plus its explicit maximum drawdown budget."""

    universe_hash: str
    maximum_drawdown: Decimal
    path_id: str
    path_version: str
    pit_manifest_id: str
    pit_manifest_hash: str
    observations: tuple[DrawdownPathObservation, ...]
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        """Return the fixed optimization input category."""

        return OptimizationInputKind.DRAWDOWN_RISK_BUDGET

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        maximum_drawdown: Decimal,
        path_id: str,
        path_version: str,
        pit_manifest_id: str,
        pit_manifest_hash: str,
        observations: tuple[DrawdownPathObservation, ...],
    ) -> DrawdownRiskBudgetPayload:
        """Seal a supplied real path; never synthesize a return observation."""

        digest = drawdown_payload_hash(
            universe_hash=universe_hash,
            maximum_drawdown=maximum_drawdown,
            path_id=path_id,
            path_version=path_version,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            observations=observations,
        )
        return cls(
            universe_hash=universe_hash,
            maximum_drawdown=maximum_drawdown,
            path_id=path_id,
            path_version=path_version,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            observations=observations,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Validate PIT identity, chronology, universe stability and hash."""

        require_sha256(self.universe_hash, "drawdown universe_hash")
        require_unit_interval(self.maximum_drawdown, "maximum_drawdown")
        require_token(self.path_id, "drawdown path_id")
        require_token(self.path_version, "drawdown path_version")
        require_token(self.pit_manifest_id, "drawdown pit_manifest_id")
        require_sha256(self.pit_manifest_hash, "drawdown pit_manifest_hash")
        if len(self.observations) < 2:
            raise ValueError("drawdown path requires at least two period observations")
        times = tuple(item.period_end for item in self.observations)
        if times != tuple(sorted(times)) or len(times) != len(set(times)):
            raise ValueError("drawdown path observations must be unique and ordered")
        asset_codes = tuple(item.asset_code for item in self.observations[0].asset_returns)
        if any(
            tuple(item.asset_code for item in observation.asset_returns) != asset_codes
            for observation in self.observations
        ):
            raise ValueError("drawdown path asset universe changes between periods")
        validate_content_hash(
            self.content_hash,
            drawdown_payload_hash(
                universe_hash=self.universe_hash,
                maximum_drawdown=self.maximum_drawdown,
                path_id=self.path_id,
                path_version=self.path_version,
                pit_manifest_id=self.pit_manifest_id,
                pit_manifest_hash=self.pit_manifest_hash,
                observations=self.observations,
            ),
            "drawdown risk budget payload",
        )


def drawdown_payload_hash(
    *,
    universe_hash: str,
    maximum_drawdown: Decimal,
    path_id: str,
    path_version: str,
    pit_manifest_id: str,
    pit_manifest_hash: str,
    observations: tuple[DrawdownPathObservation, ...],
) -> str:
    """Recompute path, PIT manifest and budget identity."""

    observation_parts = tuple(
        "|".join(
            (
                utc_text(item.period_end),
                decimal_text(item.cash_return),
                *(
                    f"{asset.asset_code},{decimal_text(asset.value)}"
                    for asset in item.asset_returns
                ),
            )
        )
        for item in observations
    )
    return hash_components(
        "drawdown-risk-budget-payload.v1",
        universe_hash,
        decimal_text(maximum_drawdown),
        path_id,
        path_version,
        pit_manifest_id,
        pit_manifest_hash,
        *observation_parts,
    )


@dataclass(frozen=True)
class FrozenWeightPathDrawdown:
    """Peak-to-trough result reconstructed from explicit frozen sleeves."""

    path_id: str
    path_hash: str
    nav_path: tuple[Decimal, ...]
    maximum_drawdown: Decimal
    budget_breached: bool

    def __post_init__(self) -> None:
        """Validate result shape and finite values."""

        require_token(self.path_id, "path_id")
        require_sha256(self.path_hash, "path_hash")
        if len(self.nav_path) < 3:
            raise ValueError("drawdown result requires initial NAV and two observations")
        for nav in self.nav_path:
            require_finite(nav, "path NAV")
            if nav < 0:
                raise ValueError("path NAV cannot be negative")
        require_unit_interval(self.maximum_drawdown, "maximum_drawdown")
        if not isinstance(self.budget_breached, bool):
            raise ValueError("budget_breached must be a boolean")


def calculate_frozen_weight_path_drawdown(
    *,
    payload: DrawdownRiskBudgetPayload,
    weights: tuple[Decimal, ...],
    cash_weight: Decimal,
    weight_tolerance: Decimal,
) -> FrozenWeightPathDrawdown:
    """Calculate NAV peak-to-trough drawdown without linear loss proxies."""

    asset_count = len(payload.observations[0].asset_returns)
    if len(weights) != asset_count:
        raise ValueError("drawdown weights must align with the path universe")
    for weight in weights:
        require_unit_interval(weight, "drawdown weight")
    require_unit_interval(cash_weight, "drawdown cash_weight")
    require_positive(weight_tolerance, "drawdown weight_tolerance")
    if abs(sum(weights, cash_weight) - Decimal("1")) > weight_tolerance:
        raise ValueError("drawdown weights and cash must sum to one")
    sleeves = list(weights)
    cash_sleeve = cash_weight
    nav_path: list[Decimal] = [Decimal("1")]
    peak = Decimal("1")
    maximum = Decimal("0")
    for observation in payload.observations:
        sleeves = [
            sleeve * (Decimal("1") + observed.value)
            for sleeve, observed in zip(
                sleeves,
                observation.asset_returns,
                strict=True,
            )
        ]
        cash_sleeve *= Decimal("1") + observation.cash_return
        nav = sum(sleeves, cash_sleeve)
        nav_path.append(nav)
        peak = max(peak, nav)
        maximum = max(maximum, (peak - nav) / peak)
    return FrozenWeightPathDrawdown(
        path_id=payload.path_id,
        path_hash=payload.content_hash,
        nav_path=tuple(nav_path),
        maximum_drawdown=maximum,
        budget_breached=maximum > payload.maximum_drawdown,
    )


__all__ = [
    "DrawdownPathObservation",
    "DrawdownRiskBudgetPayload",
    "FrozenWeightPathDrawdown",
    "calculate_frozen_weight_path_drawdown",
    "drawdown_payload_hash",
]
