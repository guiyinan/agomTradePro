"""Typed canonical numerical payloads for governed R8 optimizer inputs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, TypeAlias, cast

from apps.portfolio.domain.optimizer_inputs import OptimizationInputKind

from ._optimization_canonical import (
    decimal_text,
    hash_components,
    require_finite,
    require_ordered_unique,
    require_sha256,
    require_token,
    require_unit_interval,
    validate_content_hash,
)


@dataclass(frozen=True)
class AssetDecimalValue:
    """One finite Decimal aligned to an asset code."""

    asset_code: str
    value: Decimal

    def __post_init__(self) -> None:
        require_token(self.asset_code, "asset_code")
        require_finite(self.value, "asset value")


@dataclass(frozen=True)
class AssetFactorExposure:
    """One finite asset-by-factor exposure."""

    asset_code: str
    factor_code: str
    value: Decimal

    def __post_init__(self) -> None:
        require_token(self.asset_code, "asset_code")
        require_token(self.factor_code, "factor_code")
        require_finite(self.value, "factor exposure")


@dataclass(frozen=True)
class PositionBoundValue:
    """Governed lower and upper weight bounds for one asset."""

    asset_code: str
    minimum_weight: Decimal
    maximum_weight: Decimal

    def __post_init__(self) -> None:
        require_token(self.asset_code, "asset_code")
        require_unit_interval(self.minimum_weight, "minimum_weight")
        require_unit_interval(self.maximum_weight, "maximum_weight")
        if self.minimum_weight > self.maximum_weight:
            raise ValueError("position bounds must be ordered")


@dataclass(frozen=True)
class ManualRestrictionValue:
    """Explicit human restriction; absence is represented by ``none``."""

    asset_code: str
    restriction: str

    def __post_init__(self) -> None:
        require_token(self.asset_code, "asset_code")
        if self.restriction not in {"none", "fixed", "no_buy", "no_sell"}:
            raise ValueError("manual restriction is invalid")


@dataclass(frozen=True)
class ScenarioAssetLoss:
    """Non-negative loss rate for one asset in one governed scenario."""

    asset_code: str
    loss_rate: Decimal

    def __post_init__(self) -> None:
        require_token(self.asset_code, "asset_code")
        require_unit_interval(self.loss_rate, "scenario loss_rate")


@dataclass(frozen=True)
class ScenarioLossVector:
    """One exact scenario revision and its aligned asset losses."""

    scenario_revision_id: str
    scenario_version: str
    maximum_portfolio_loss: Decimal
    losses: tuple[ScenarioAssetLoss, ...]
    evidence_hash: str

    def __post_init__(self) -> None:
        require_token(self.scenario_revision_id, "scenario_revision_id")
        require_token(self.scenario_version, "scenario_version")
        require_unit_interval(self.maximum_portfolio_loss, "maximum_portfolio_loss")
        require_sha256(self.evidence_hash, "scenario evidence_hash")
        require_ordered_unique(
            tuple(item.asset_code for item in self.losses),
            "scenario loss assets",
        )


@dataclass(frozen=True)
class ExecutionFeedbackValue:
    """Observed broker-reconciled numerical feedback for one asset."""

    asset_code: str
    feedback_id: str
    realized_cost_rate: Decimal
    realized_slippage_rate: Decimal
    fill_rate: Decimal
    evidence_hash: str

    def __post_init__(self) -> None:
        require_token(self.asset_code, "asset_code")
        require_token(self.feedback_id, "feedback_id")
        require_finite(self.realized_cost_rate, "realized_cost_rate")
        require_finite(self.realized_slippage_rate, "realized_slippage_rate")
        require_unit_interval(self.fill_rate, "fill_rate")
        if self.realized_cost_rate < 0:
            raise ValueError("realized_cost_rate cannot be negative")
        require_sha256(self.evidence_hash, "feedback evidence_hash")


@dataclass(frozen=True)
class _AssetVectorPayload:
    universe_hash: str
    values: tuple[AssetDecimalValue, ...]
    content_hash: str

    KIND: ClassVar[OptimizationInputKind]
    SCHEMA: ClassVar[str]

    @property
    def kind(self) -> OptimizationInputKind:
        return self.KIND

    @classmethod
    def _create(
        cls,
        *,
        universe_hash: str,
        values: tuple[AssetDecimalValue, ...],
    ) -> _AssetVectorPayload:
        ordered = tuple(sorted(values, key=lambda item: item.asset_code))
        return cls(
            universe_hash=universe_hash,
            values=ordered,
            content_hash=_asset_vector_hash(cls.SCHEMA, cls.KIND, universe_hash, ordered),
        )

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, f"{self.kind.value} universe_hash")
        require_ordered_unique(
            tuple(item.asset_code for item in self.values),
            f"{self.kind.value} assets",
        )
        validate_content_hash(
            self.content_hash,
            _asset_vector_hash(self.SCHEMA, self.KIND, self.universe_hash, self.values),
            f"{self.kind.value} payload",
        )


def _asset_vector_hash(
    schema: str,
    kind: OptimizationInputKind,
    universe_hash: str,
    values: tuple[AssetDecimalValue, ...],
) -> str:
    return hash_components(
        schema,
        kind.value,
        universe_hash,
        *(f"{item.asset_code}|{decimal_text(item.value)}" for item in values),
    )


@dataclass(frozen=True)
class ExpectedReturnPayload(_AssetVectorPayload):
    """Exact expected-return vector."""

    KIND: ClassVar[OptimizationInputKind] = OptimizationInputKind.EXPECTED_RETURN
    SCHEMA: ClassVar[str] = "expected-return-payload.v1"

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        values: tuple[AssetDecimalValue, ...],
    ) -> ExpectedReturnPayload:
        return cast(
            ExpectedReturnPayload,
            cls._create(universe_hash=universe_hash, values=values),
        )


@dataclass(frozen=True)
class TransactionCostPayload:
    """Broker-derived transaction-cost rates, never default estimates."""

    universe_hash: str
    cost_rates: tuple[AssetDecimalValue, ...]
    maximum_total_cost: Decimal
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        """Return the fixed optimization input category."""

        return OptimizationInputKind.TRANSACTION_COST

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        cost_rates: tuple[AssetDecimalValue, ...],
        maximum_total_cost: Decimal,
    ) -> TransactionCostPayload:
        ordered = tuple(sorted(cost_rates, key=lambda item: item.asset_code))
        return cls(
            universe_hash=universe_hash,
            cost_rates=ordered,
            maximum_total_cost=maximum_total_cost,
            content_hash=transaction_cost_payload_hash(
                universe_hash,
                ordered,
                maximum_total_cost,
            ),
        )

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "transaction cost universe_hash")
        require_ordered_unique(
            tuple(item.asset_code for item in self.cost_rates),
            "transaction cost assets",
        )
        if any(item.value < 0 for item in self.cost_rates):
            raise ValueError("transaction cost values cannot be negative")
        require_unit_interval(self.maximum_total_cost, "maximum_total_cost")
        validate_content_hash(
            self.content_hash,
            transaction_cost_payload_hash(
                self.universe_hash,
                self.cost_rates,
                self.maximum_total_cost,
            ),
            "transaction cost payload",
        )


def transaction_cost_payload_hash(
    universe_hash: str,
    cost_rates: tuple[AssetDecimalValue, ...],
    maximum_total_cost: Decimal,
) -> str:
    """Recompute asset rates and the explicit portfolio cost budget."""

    return hash_components(
        "transaction-cost-payload.v2",
        universe_hash,
        *(f"{item.asset_code}|{decimal_text(item.value)}" for item in cost_rates),
        decimal_text(maximum_total_cost),
    )


@dataclass(frozen=True)
class LiquidityLimitPayload(_AssetVectorPayload):
    """Exact maximum trade weights derived from governed capacity evidence."""

    KIND: ClassVar[OptimizationInputKind] = OptimizationInputKind.LIQUIDITY_LIMIT
    SCHEMA: ClassVar[str] = "liquidity-limit-payload.v1"

    @property
    def maximum_trade_weights(self) -> tuple[AssetDecimalValue, ...]:
        """Expose the semantic vector name."""

        return self.values

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        maximum_trade_weights: tuple[AssetDecimalValue, ...],
    ) -> LiquidityLimitPayload:
        return cast(
            LiquidityLimitPayload,
            cls._create(
                universe_hash=universe_hash,
                values=maximum_trade_weights,
            ),
        )

    def __post_init__(self) -> None:
        super().__post_init__()
        for item in self.values:
            require_unit_interval(item.value, "maximum_trade_weight")


@dataclass(frozen=True)
class MacroExposurePayload:
    """Exact asset exposures plus aligned macro-factor covariance."""

    universe_hash: str
    exposures: tuple[AssetFactorExposure, ...]
    factor_codes: tuple[str, ...]
    factor_covariance_values: tuple[tuple[Decimal, ...], ...]
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        return OptimizationInputKind.MACRO_EXPOSURE

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        exposures: tuple[AssetFactorExposure, ...],
        factor_codes: tuple[str, ...],
        factor_covariance_values: tuple[tuple[Decimal, ...], ...],
    ) -> MacroExposurePayload:
        ordered = tuple(sorted(exposures, key=lambda item: (item.asset_code, item.factor_code)))
        return cls(
            universe_hash,
            ordered,
            factor_codes,
            factor_covariance_values,
            macro_exposure_hash(
                universe_hash,
                ordered,
                factor_codes,
                factor_covariance_values,
            ),
        )

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "macro exposure universe_hash")
        keys = tuple((item.asset_code, item.factor_code) for item in self.exposures)
        if not keys or len(keys) != len(set(keys)) or keys != tuple(sorted(keys)):
            raise ValueError("macro exposures must be non-empty, unique, and ordered")
        require_ordered_unique(self.factor_codes, "macro factor codes")
        size = len(self.factor_codes)
        if len(self.factor_covariance_values) != size or any(
            len(row) != size for row in self.factor_covariance_values
        ):
            raise ValueError("macro factor covariance must be square")
        for row in self.factor_covariance_values:
            for value in row:
                require_finite(value, "macro factor covariance value")
        if {item.factor_code for item in self.exposures} != set(self.factor_codes):
            raise ValueError("macro exposures do not match the factor covariance universe")
        asset_codes = tuple(sorted({item.asset_code for item in self.exposures}))
        expected_cells = {
            (asset_code, factor_code)
            for asset_code in asset_codes
            for factor_code in self.factor_codes
        }
        if set(keys) != expected_cells:
            raise ValueError("macro exposure payload requires the full asset-factor cross-product")
        validate_content_hash(
            self.content_hash,
            macro_exposure_hash(
                self.universe_hash,
                self.exposures,
                self.factor_codes,
                self.factor_covariance_values,
            ),
            "macro exposure payload",
        )


def macro_exposure_hash(
    universe_hash: str,
    exposures: tuple[AssetFactorExposure, ...],
    factor_codes: tuple[str, ...],
    factor_covariance_values: tuple[tuple[Decimal, ...], ...],
) -> str:
    return hash_components(
        "macro-exposure-payload.v1",
        universe_hash,
        *(f"{item.asset_code}|{item.factor_code}|{decimal_text(item.value)}" for item in exposures),
        *factor_codes,
        *("|".join(decimal_text(value) for value in row) for row in factor_covariance_values),
    )


@dataclass(frozen=True)
class AssetCovariancePayload:
    """Exact square asset covariance matrix."""

    universe_hash: str
    asset_codes: tuple[str, ...]
    values: tuple[tuple[Decimal, ...], ...]
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        return OptimizationInputKind.ASSET_COVARIANCE

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        asset_codes: tuple[str, ...],
        values: tuple[tuple[Decimal, ...], ...],
    ) -> AssetCovariancePayload:
        return cls(
            universe_hash,
            asset_codes,
            values,
            asset_covariance_payload_hash(universe_hash, asset_codes, values),
        )

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "asset covariance universe_hash")
        require_ordered_unique(self.asset_codes, "asset covariance assets")
        size = len(self.asset_codes)
        if len(self.values) != size or any(len(row) != size for row in self.values):
            raise ValueError("asset covariance must be square")
        for row in self.values:
            for value in row:
                require_finite(value, "asset covariance value")
        validate_content_hash(
            self.content_hash,
            asset_covariance_payload_hash(self.universe_hash, self.asset_codes, self.values),
            "asset covariance payload",
        )


def asset_covariance_payload_hash(
    universe_hash: str,
    asset_codes: tuple[str, ...],
    values: tuple[tuple[Decimal, ...], ...],
) -> str:
    return hash_components(
        "asset-covariance-payload.v1",
        universe_hash,
        *asset_codes,
        *("|".join(decimal_text(value) for value in row) for row in values),
    )


@dataclass(frozen=True)
class ScenarioLossPayload:
    """Exact scenario revisions, numerical loss vectors and source hashes."""

    universe_hash: str
    scenarios: tuple[ScenarioLossVector, ...]
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        return OptimizationInputKind.SCENARIO_LOSS

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        scenarios: tuple[ScenarioLossVector, ...],
    ) -> ScenarioLossPayload:
        ordered = tuple(sorted(scenarios, key=lambda item: item.scenario_revision_id))
        return cls(universe_hash, ordered, scenario_loss_payload_hash(universe_hash, ordered))

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "scenario loss universe_hash")
        require_ordered_unique(
            tuple(item.scenario_revision_id for item in self.scenarios),
            "scenario loss revisions",
        )
        first_assets = tuple(item.asset_code for item in self.scenarios[0].losses)
        if any(
            tuple(loss.asset_code for loss in scenario.losses) != first_assets
            for scenario in self.scenarios
        ):
            raise ValueError("every scenario loss must cover the exact asset dimension")
        validate_content_hash(
            self.content_hash,
            scenario_loss_payload_hash(self.universe_hash, self.scenarios),
            "scenario loss payload",
        )


def scenario_loss_payload_hash(
    universe_hash: str,
    scenarios: tuple[ScenarioLossVector, ...],
) -> str:
    parts = tuple(
        "|".join(
            (
                item.scenario_revision_id,
                item.scenario_version,
                decimal_text(item.maximum_portfolio_loss),
                item.evidence_hash,
                *(f"{loss.asset_code},{decimal_text(loss.loss_rate)}" for loss in item.losses),
            )
        )
        for item in scenarios
    )
    return hash_components("scenario-loss-payload.v1", universe_hash, *parts)


@dataclass(frozen=True)
class TurnoverLimitPayload:
    """Exact portfolio turnover budget."""

    universe_hash: str
    maximum_turnover: Decimal
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        return OptimizationInputKind.TURNOVER_LIMIT

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        maximum_turnover: Decimal,
    ) -> TurnoverLimitPayload:
        return cls(
            universe_hash,
            maximum_turnover,
            hash_components(
                "turnover-limit-payload.v1",
                universe_hash,
                decimal_text(maximum_turnover),
            ),
        )

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "turnover universe_hash")
        require_unit_interval(self.maximum_turnover, "maximum_turnover")
        validate_content_hash(
            self.content_hash,
            hash_components(
                "turnover-limit-payload.v1",
                self.universe_hash,
                decimal_text(self.maximum_turnover),
            ),
            "turnover limit payload",
        )


@dataclass(frozen=True)
class PositionBoundsPayload:
    """Exact asset position bounds."""

    universe_hash: str
    bounds: tuple[PositionBoundValue, ...]
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        return OptimizationInputKind.POSITION_BOUNDS

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        bounds: tuple[PositionBoundValue, ...],
    ) -> PositionBoundsPayload:
        ordered = tuple(sorted(bounds, key=lambda item: item.asset_code))
        return cls(universe_hash, ordered, position_bounds_hash(universe_hash, ordered))

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "position bounds universe_hash")
        require_ordered_unique(
            tuple(item.asset_code for item in self.bounds),
            "position bound assets",
        )
        validate_content_hash(
            self.content_hash,
            position_bounds_hash(self.universe_hash, self.bounds),
            "position bounds payload",
        )


def position_bounds_hash(
    universe_hash: str,
    bounds: tuple[PositionBoundValue, ...],
) -> str:
    return hash_components(
        "position-bounds-payload.v1",
        universe_hash,
        *(
            f"{item.asset_code}|{decimal_text(item.minimum_weight)}|"
            f"{decimal_text(item.maximum_weight)}"
            for item in bounds
        ),
    )


@dataclass(frozen=True)
class ManualRestrictionsPayload:
    """Exact human restriction vector."""

    universe_hash: str
    restrictions: tuple[ManualRestrictionValue, ...]
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        return OptimizationInputKind.MANUAL_RESTRICTIONS

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        restrictions: tuple[ManualRestrictionValue, ...],
    ) -> ManualRestrictionsPayload:
        ordered = tuple(sorted(restrictions, key=lambda item: item.asset_code))
        return cls(universe_hash, ordered, manual_restrictions_hash(universe_hash, ordered))

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "manual restrictions universe_hash")
        require_ordered_unique(
            tuple(item.asset_code for item in self.restrictions),
            "manual restriction assets",
        )
        validate_content_hash(
            self.content_hash,
            manual_restrictions_hash(self.universe_hash, self.restrictions),
            "manual restrictions payload",
        )


def manual_restrictions_hash(
    universe_hash: str,
    restrictions: tuple[ManualRestrictionValue, ...],
) -> str:
    return hash_components(
        "manual-restrictions-payload.v1",
        universe_hash,
        *(f"{item.asset_code}|{item.restriction}" for item in restrictions),
    )


@dataclass(frozen=True)
class CashRequirementPayload:
    """Exact minimum and target cash weights."""

    universe_hash: str
    minimum_cash_weight: Decimal
    target_cash_weight: Decimal
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        return OptimizationInputKind.CASH_REQUIREMENT

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        minimum_cash_weight: Decimal,
        target_cash_weight: Decimal,
    ) -> CashRequirementPayload:
        return cls(
            universe_hash,
            minimum_cash_weight,
            target_cash_weight,
            cash_requirement_hash(universe_hash, minimum_cash_weight, target_cash_weight),
        )

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "cash requirement universe_hash")
        require_unit_interval(self.minimum_cash_weight, "minimum_cash_weight")
        require_unit_interval(self.target_cash_weight, "target_cash_weight")
        if self.target_cash_weight < self.minimum_cash_weight:
            raise ValueError("target cash cannot be below minimum cash")
        validate_content_hash(
            self.content_hash,
            cash_requirement_hash(
                self.universe_hash,
                self.minimum_cash_weight,
                self.target_cash_weight,
            ),
            "cash requirement payload",
        )


def cash_requirement_hash(
    universe_hash: str,
    minimum_cash_weight: Decimal,
    target_cash_weight: Decimal,
) -> str:
    return hash_components(
        "cash-requirement-payload.v1",
        universe_hash,
        decimal_text(minimum_cash_weight),
        decimal_text(target_cash_weight),
    )


@dataclass(frozen=True)
class ExecutionFeedbackPayload:
    """Exact numerical projection of immutable broker reconciliation feedback."""

    universe_hash: str
    source_bundle_hash: str
    feedback: tuple[ExecutionFeedbackValue, ...]
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        return OptimizationInputKind.EXECUTION_FEEDBACK

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        source_bundle_hash: str,
        feedback: tuple[ExecutionFeedbackValue, ...],
    ) -> ExecutionFeedbackPayload:
        ordered = tuple(sorted(feedback, key=lambda item: item.asset_code))
        return cls(
            universe_hash,
            source_bundle_hash,
            ordered,
            execution_feedback_payload_hash(universe_hash, source_bundle_hash, ordered),
        )

    def __post_init__(self) -> None:
        require_sha256(self.universe_hash, "execution feedback universe_hash")
        require_sha256(self.source_bundle_hash, "execution feedback source_bundle_hash")
        require_ordered_unique(
            tuple(item.asset_code for item in self.feedback),
            "execution feedback assets",
        )
        validate_content_hash(
            self.content_hash,
            execution_feedback_payload_hash(
                self.universe_hash,
                self.source_bundle_hash,
                self.feedback,
            ),
            "execution feedback payload",
        )


def execution_feedback_payload_hash(
    universe_hash: str,
    source_bundle_hash: str,
    feedback: tuple[ExecutionFeedbackValue, ...],
) -> str:
    return hash_components(
        "execution-feedback-payload.v1",
        universe_hash,
        source_bundle_hash,
        *(
            f"{item.asset_code}|{item.feedback_id}|"
            f"{decimal_text(item.realized_cost_rate)}|"
            f"{decimal_text(item.realized_slippage_rate)}|"
            f"{decimal_text(item.fill_rate)}|{item.evidence_hash}"
            for item in feedback
        ),
    )


CoreOptimizationPayload: TypeAlias = (
    ExpectedReturnPayload
    | MacroExposurePayload
    | AssetCovariancePayload
    | ScenarioLossPayload
    | TransactionCostPayload
    | TurnoverLimitPayload
    | LiquidityLimitPayload
    | PositionBoundsPayload
    | ManualRestrictionsPayload
    | CashRequirementPayload
    | ExecutionFeedbackPayload
)


__all__ = [
    "AssetCovariancePayload",
    "AssetDecimalValue",
    "AssetFactorExposure",
    "CashRequirementPayload",
    "CoreOptimizationPayload",
    "ExecutionFeedbackPayload",
    "ExecutionFeedbackValue",
    "ExpectedReturnPayload",
    "LiquidityLimitPayload",
    "MacroExposurePayload",
    "ManualRestrictionValue",
    "ManualRestrictionsPayload",
    "PositionBoundValue",
    "PositionBoundsPayload",
    "ScenarioAssetLoss",
    "ScenarioLossPayload",
    "ScenarioLossVector",
    "TransactionCostPayload",
    "TurnoverLimitPayload",
]
