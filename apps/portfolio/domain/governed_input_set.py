"""Exact owner, PIT, Promotion and payload binding for R8 research inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias

from apps.portfolio.domain.optimizer_inputs import OptimizationInputKind

from ._optimization_canonical import (
    hash_components,
    require_aware,
    require_sha256,
    require_text,
    require_token,
    utc_text,
)
from .input_payloads import (
    AssetCovariancePayload,
    CashRequirementPayload,
    CoreOptimizationPayload,
    ExecutionFeedbackPayload,
    ExpectedReturnPayload,
    LiquidityLimitPayload,
    MacroExposurePayload,
    ManualRestrictionsPayload,
    PositionBoundsPayload,
    ScenarioLossPayload,
    TransactionCostPayload,
    TurnoverLimitPayload,
)
from .investable_universe import InvestableUniverseSnapshot
from .market_constraints import TradingConstraintsPayload
from .path_drawdown import DrawdownRiskBudgetPayload

CANONICAL_OPTIMIZATION_OWNERS: dict[OptimizationInputKind, str] = {
    OptimizationInputKind.EXPECTED_RETURN: "research",
    OptimizationInputKind.MACRO_EXPOSURE: "portfolio",
    OptimizationInputKind.ASSET_COVARIANCE: "portfolio",
    OptimizationInputKind.SCENARIO_LOSS: "risk_center",
    OptimizationInputKind.DRAWDOWN_RISK_BUDGET: "risk_center",
    OptimizationInputKind.TRANSACTION_COST: "portfolio",
    OptimizationInputKind.TURNOVER_LIMIT: "portfolio",
    OptimizationInputKind.LIQUIDITY_LIMIT: "portfolio",
    OptimizationInputKind.POSITION_BOUNDS: "portfolio",
    OptimizationInputKind.TRADING_CONSTRAINTS: "portfolio",
    OptimizationInputKind.MANUAL_RESTRICTIONS: "portfolio",
    OptimizationInputKind.CASH_REQUIREMENT: "portfolio",
    OptimizationInputKind.EXECUTION_FEEDBACK: "portfolio",
}


GovernedOptimizationPayload: TypeAlias = (
    CoreOptimizationPayload | DrawdownRiskBudgetPayload | TradingConstraintsPayload
)


@dataclass(frozen=True)
class OwnerBoundPayloadEvidence:
    """Canonical owner attestation over one exact bitemporal PIT payload."""

    kind: OptimizationInputKind
    owner: str
    version: str
    evidence_ref: str
    observed_at: datetime
    available_at: datetime
    knowledge_as_of: datetime
    valid_until: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    universe_hash: str
    payload_hash: str
    source_content_hashes: tuple[str, ...]
    owner_attestation_hash: str

    def __post_init__(self) -> None:
        """Recompute owner evidence including bitemporal and PIT identity."""

        require_token(self.owner, "payload owner")
        require_token(self.version, "payload evidence version")
        require_text(self.evidence_ref, "payload evidence_ref")
        require_aware(self.observed_at, "payload observed_at")
        require_aware(self.available_at, "payload available_at")
        require_aware(self.knowledge_as_of, "payload knowledge_as_of")
        require_aware(self.valid_until, "payload valid_until")
        if not (self.observed_at <= self.available_at <= self.knowledge_as_of < self.valid_until):
            raise ValueError("payload bitemporal availability window is invalid")
        require_token(self.pit_manifest_id, "payload pit_manifest_id")
        require_sha256(self.pit_manifest_hash, "payload pit_manifest_hash")
        require_sha256(self.universe_hash, "payload universe_hash")
        require_sha256(self.payload_hash, "payload hash")
        if (
            not self.source_content_hashes
            or len(self.source_content_hashes) != len(set(self.source_content_hashes))
            or self.source_content_hashes != tuple(sorted(self.source_content_hashes))
        ):
            raise ValueError("payload source hashes must be non-empty, unique, and ordered")
        for item in self.source_content_hashes:
            require_sha256(item, "payload source content hash")
        require_sha256(self.owner_attestation_hash, "owner_attestation_hash")
        if self.owner_attestation_hash != owner_bound_payload_hash(self):
            raise ValueError("owner attestation hash mismatch")


def build_owner_bound_payload_evidence(
    *,
    kind: OptimizationInputKind,
    owner: str,
    version: str,
    evidence_ref: str,
    observed_at: datetime,
    available_at: datetime,
    knowledge_as_of: datetime,
    valid_until: datetime,
    pit_manifest_id: str,
    pit_manifest_hash: str,
    universe_hash: str,
    payload_hash: str,
    source_content_hashes: tuple[str, ...],
) -> OwnerBoundPayloadEvidence:
    """Seal one typed payload using its real canonical owner and PIT sources."""

    ordered_sources = tuple(sorted(source_content_hashes))
    digest = _owner_bound_payload_hash_values(
        kind=kind,
        owner=owner,
        version=version,
        evidence_ref=evidence_ref,
        observed_at=observed_at,
        available_at=available_at,
        knowledge_as_of=knowledge_as_of,
        valid_until=valid_until,
        pit_manifest_id=pit_manifest_id,
        pit_manifest_hash=pit_manifest_hash,
        universe_hash=universe_hash,
        payload_hash=payload_hash,
        source_content_hashes=ordered_sources,
    )
    return OwnerBoundPayloadEvidence(
        kind=kind,
        owner=owner,
        version=version,
        evidence_ref=evidence_ref,
        observed_at=observed_at,
        available_at=available_at,
        knowledge_as_of=knowledge_as_of,
        valid_until=valid_until,
        pit_manifest_id=pit_manifest_id,
        pit_manifest_hash=pit_manifest_hash,
        universe_hash=universe_hash,
        payload_hash=payload_hash,
        source_content_hashes=ordered_sources,
        owner_attestation_hash=digest,
    )


def owner_bound_payload_hash(evidence: OwnerBoundPayloadEvidence) -> str:
    """Recompute one owner attestation."""

    return _owner_bound_payload_hash_values(
        kind=evidence.kind,
        owner=evidence.owner,
        version=evidence.version,
        evidence_ref=evidence.evidence_ref,
        observed_at=evidence.observed_at,
        available_at=evidence.available_at,
        knowledge_as_of=evidence.knowledge_as_of,
        valid_until=evidence.valid_until,
        pit_manifest_id=evidence.pit_manifest_id,
        pit_manifest_hash=evidence.pit_manifest_hash,
        universe_hash=evidence.universe_hash,
        payload_hash=evidence.payload_hash,
        source_content_hashes=evidence.source_content_hashes,
    )


def _owner_bound_payload_hash_values(
    *,
    kind: OptimizationInputKind,
    owner: str,
    version: str,
    evidence_ref: str,
    observed_at: datetime,
    available_at: datetime,
    knowledge_as_of: datetime,
    valid_until: datetime,
    pit_manifest_id: str,
    pit_manifest_hash: str,
    universe_hash: str,
    payload_hash: str,
    source_content_hashes: tuple[str, ...],
) -> str:
    return hash_components(
        "optimizer-payload-owner-attestation.v2",
        kind.value,
        owner,
        version,
        evidence_ref,
        utc_text(observed_at),
        utc_text(available_at),
        utc_text(knowledge_as_of),
        utc_text(valid_until),
        pit_manifest_id,
        pit_manifest_hash,
        universe_hash,
        payload_hash,
        *source_content_hashes,
    )


@dataclass(frozen=True)
class ExactPromotionAttestation:
    """Exact approved, active Research decision for one upstream artifact."""

    capability_key: str
    artifact_id: str
    artifact_version: str
    artifact_content_hash: str
    decision_id: str
    decision_content_hash: str
    owner: str
    approved_at: datetime
    valid_until: datetime
    retired_at: datetime | None
    attestation_hash: str

    @classmethod
    def create(
        cls,
        *,
        capability_key: str,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_content_hash: str,
        owner: str,
        approved_at: datetime,
        valid_until: datetime,
        retired_at: datetime | None = None,
    ) -> ExactPromotionAttestation:
        """Seal the approved decision and retirement state."""

        return cls(
            capability_key=capability_key,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            artifact_content_hash=artifact_content_hash,
            decision_id=decision_id,
            decision_content_hash=decision_content_hash,
            owner=owner,
            approved_at=approved_at,
            valid_until=valid_until,
            retired_at=retired_at,
            attestation_hash=_promotion_attestation_hash_values(
                capability_key=capability_key,
                artifact_id=artifact_id,
                artifact_version=artifact_version,
                artifact_content_hash=artifact_content_hash,
                decision_id=decision_id,
                decision_content_hash=decision_content_hash,
                owner=owner,
                approved_at=approved_at,
                valid_until=valid_until,
                retired_at=retired_at,
            ),
        )

    def __post_init__(self) -> None:
        """Recompute exact artifact, decision, expiry and retirement identity."""

        for field_name, value in (
            ("capability_key", self.capability_key),
            ("artifact_id", self.artifact_id),
            ("artifact_version", self.artifact_version),
            ("decision_id", self.decision_id),
            ("owner", self.owner),
        ):
            require_token(value, field_name)
        require_sha256(self.artifact_content_hash, "promotion artifact_content_hash")
        require_sha256(self.decision_content_hash, "promotion decision_content_hash")
        require_aware(self.approved_at, "promotion approved_at")
        require_aware(self.valid_until, "promotion valid_until")
        if self.valid_until <= self.approved_at:
            raise ValueError("promotion valid_until must follow approved_at")
        if self.retired_at is not None:
            require_aware(self.retired_at, "promotion retired_at")
            if self.retired_at < self.approved_at:
                raise ValueError("promotion retired_at cannot predate approval")
        require_sha256(self.attestation_hash, "promotion attestation_hash")
        if self.attestation_hash != exact_promotion_attestation_hash(self):
            raise ValueError("promotion attestation hash mismatch")


def exact_promotion_attestation_hash(attestation: ExactPromotionAttestation) -> str:
    """Recompute the exact approved/retired decision attestation."""

    return _promotion_attestation_hash_values(
        capability_key=attestation.capability_key,
        artifact_id=attestation.artifact_id,
        artifact_version=attestation.artifact_version,
        artifact_content_hash=attestation.artifact_content_hash,
        decision_id=attestation.decision_id,
        decision_content_hash=attestation.decision_content_hash,
        owner=attestation.owner,
        approved_at=attestation.approved_at,
        valid_until=attestation.valid_until,
        retired_at=attestation.retired_at,
    )


def _promotion_attestation_hash_values(
    *,
    capability_key: str,
    artifact_id: str,
    artifact_version: str,
    artifact_content_hash: str,
    decision_id: str,
    decision_content_hash: str,
    owner: str,
    approved_at: datetime,
    valid_until: datetime,
    retired_at: datetime | None,
) -> str:
    return hash_components(
        "exact-research-promotion-attestation.v2",
        capability_key,
        artifact_id,
        artifact_version,
        artifact_content_hash,
        decision_id,
        decision_content_hash,
        "approved",
        owner,
        utc_text(approved_at),
        utc_text(valid_until),
        "" if retired_at is None else utc_text(retired_at),
    )


@dataclass(frozen=True)
class GovernedOptimizationInputSet:
    """Exact 13-payload bundle permitted only for offline research comparison."""

    input_set_id: str
    input_set_version: str
    contract_version: str
    portfolio_snapshot_id: str
    portfolio_snapshot_hash: str
    universe: InvestableUniverseSnapshot
    payloads: tuple[GovernedOptimizationPayload, ...]
    owner_bindings: tuple[OwnerBoundPayloadEvidence, ...]
    promotions: tuple[ExactPromotionAttestation, ...]
    created_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    @classmethod
    def create(
        cls,
        *,
        input_set_id: str,
        input_set_version: str,
        contract_version: str,
        portfolio_snapshot_id: str,
        portfolio_snapshot_hash: str,
        universe: InvestableUniverseSnapshot,
        payloads: tuple[GovernedOptimizationPayload, ...],
        owner_bindings: tuple[OwnerBoundPayloadEvidence, ...],
        promotions: tuple[ExactPromotionAttestation, ...],
        created_at: datetime,
        valid_until: datetime,
    ) -> GovernedOptimizationInputSet:
        """Order and seal a complete set without filling a missing input."""

        ordered_payloads = tuple(sorted(payloads, key=lambda item: item.kind.value))
        ordered_bindings = tuple(sorted(owner_bindings, key=lambda item: item.kind.value))
        ordered_promotions = tuple(sorted(promotions, key=lambda item: item.capability_key))
        digest = governed_input_set_hash_values(
            input_set_id=input_set_id,
            input_set_version=input_set_version,
            contract_version=contract_version,
            portfolio_snapshot_id=portfolio_snapshot_id,
            portfolio_snapshot_hash=portfolio_snapshot_hash,
            universe=universe,
            payloads=ordered_payloads,
            owner_bindings=ordered_bindings,
            promotions=ordered_promotions,
            created_at=created_at,
            valid_until=valid_until,
        )
        return cls(
            input_set_id=input_set_id,
            input_set_version=input_set_version,
            contract_version=contract_version,
            portfolio_snapshot_id=portfolio_snapshot_id,
            portfolio_snapshot_hash=portfolio_snapshot_hash,
            universe=universe,
            payloads=ordered_payloads,
            owner_bindings=ordered_bindings,
            promotions=ordered_promotions,
            created_at=created_at,
            valid_until=valid_until,
            content_hash=digest,
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )

    def __post_init__(self) -> None:
        """Validate exact types, owners, lineage, clocks and content hash."""

        for field_name, value in (
            ("input_set_id", self.input_set_id),
            ("input_set_version", self.input_set_version),
            ("contract_version", self.contract_version),
            ("portfolio_snapshot_id", self.portfolio_snapshot_id),
        ):
            require_token(value, field_name)
        require_sha256(self.portfolio_snapshot_hash, "portfolio_snapshot_hash")
        require_aware(self.created_at, "input set created_at")
        require_aware(self.valid_until, "input set valid_until")
        if self.valid_until <= self.created_at:
            raise ValueError("input set valid_until must follow created_at")
        if self.universe.available_at > self.created_at:
            raise ValueError("input set cannot predate universe availability")
        if self.valid_until > self.universe.valid_until:
            raise ValueError("input set cannot outlive its universe")
        if self.payloads != tuple(sorted(self.payloads, key=lambda item: item.kind.value)):
            raise ValueError("input set payloads must be canonically ordered")
        if self.owner_bindings != tuple(
            sorted(self.owner_bindings, key=lambda item: item.kind.value)
        ):
            raise ValueError("input set owner bindings must be canonically ordered")
        if self.promotions != tuple(sorted(self.promotions, key=lambda item: item.capability_key)):
            raise ValueError("input set promotions must be canonically ordered")
        payload_by_kind = _validate_payloads(self.payloads, self.universe)
        binding_by_kind = _validate_bindings(
            self.owner_bindings,
            payload_by_kind,
            self.universe,
            self.created_at,
            self.valid_until,
        )
        _validate_payload_temporal_bounds(
            payload_by_kind,
            binding_by_kind,
            self.created_at,
        )
        promotion_by_key = _validate_promotions(
            self.promotions,
            self.created_at,
            self.valid_until,
        )
        _validate_promoted_lineage(binding_by_kind, promotion_by_key)
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("governed input set must remain non-executable research")
        require_sha256(self.content_hash, "input set content_hash")
        if self.content_hash != governed_input_set_hash(self):
            raise ValueError("input set content hash mismatch")


def _validate_payloads(
    payloads: tuple[GovernedOptimizationPayload, ...],
    universe: InvestableUniverseSnapshot,
) -> dict[OptimizationInputKind, GovernedOptimizationPayload]:
    expected_types: dict[OptimizationInputKind, type[object]] = {
        OptimizationInputKind.EXPECTED_RETURN: ExpectedReturnPayload,
        OptimizationInputKind.MACRO_EXPOSURE: MacroExposurePayload,
        OptimizationInputKind.ASSET_COVARIANCE: AssetCovariancePayload,
        OptimizationInputKind.SCENARIO_LOSS: ScenarioLossPayload,
        OptimizationInputKind.DRAWDOWN_RISK_BUDGET: DrawdownRiskBudgetPayload,
        OptimizationInputKind.TRANSACTION_COST: TransactionCostPayload,
        OptimizationInputKind.TURNOVER_LIMIT: TurnoverLimitPayload,
        OptimizationInputKind.LIQUIDITY_LIMIT: LiquidityLimitPayload,
        OptimizationInputKind.POSITION_BOUNDS: PositionBoundsPayload,
        OptimizationInputKind.TRADING_CONSTRAINTS: TradingConstraintsPayload,
        OptimizationInputKind.MANUAL_RESTRICTIONS: ManualRestrictionsPayload,
        OptimizationInputKind.CASH_REQUIREMENT: CashRequirementPayload,
        OptimizationInputKind.EXECUTION_FEEDBACK: ExecutionFeedbackPayload,
    }
    payload_by_kind = {item.kind: item for item in payloads}
    if len(payload_by_kind) != len(payloads) or set(payload_by_kind) != set(OptimizationInputKind):
        raise ValueError("input set requires every canonical payload exactly once")
    universe_codes = tuple(item.asset_code for item in universe.members)
    universe_market = {item.asset_code: item.market for item in universe.members}
    for kind, payload in payload_by_kind.items():
        if type(payload) is not expected_types[kind]:
            raise ValueError("input kind does not match its typed payload")
        if payload.universe_hash != universe.universe_hash:
            raise ValueError("payload universe hash mismatch")
        payload_codes = payload_asset_codes(payload)
        if payload_codes is not None and payload_codes != universe_codes:
            raise ValueError(f"{kind.value} payload does not cover the exact universe")
        if isinstance(payload, TradingConstraintsPayload):
            if any(
                item.market is not universe_market[item.asset_code] for item in payload.constraints
            ):
                raise ValueError("trading constraint market does not match the universe")
    return payload_by_kind


def _validate_bindings(
    bindings: tuple[OwnerBoundPayloadEvidence, ...],
    payloads: dict[OptimizationInputKind, GovernedOptimizationPayload],
    universe: InvestableUniverseSnapshot,
    created_at: datetime,
    valid_until: datetime,
) -> dict[OptimizationInputKind, OwnerBoundPayloadEvidence]:
    by_kind = {item.kind: item for item in bindings}
    if len(by_kind) != len(bindings) or set(by_kind) != set(OptimizationInputKind):
        raise ValueError("input set requires every owner binding exactly once")
    for kind, binding in by_kind.items():
        if binding.owner != CANONICAL_OPTIMIZATION_OWNERS[kind]:
            raise ValueError(f"{kind.value} canonical owner mismatch")
        if binding.payload_hash != payloads[kind].content_hash:
            raise ValueError(f"{kind.value} payload hash mismatch")
        if binding.universe_hash != universe.universe_hash:
            raise ValueError(f"{kind.value} owner binding universe mismatch")
        if binding.knowledge_as_of > created_at or binding.valid_until <= created_at:
            raise ValueError(f"{kind.value} owner binding is not current")
        if valid_until > binding.valid_until:
            raise ValueError("input set cannot outlive an owner binding")
    return by_kind


def _validate_promotions(
    promotions: tuple[ExactPromotionAttestation, ...],
    created_at: datetime,
    valid_until: datetime,
) -> dict[str, ExactPromotionAttestation]:
    by_key = {item.capability_key: item for item in promotions}
    if len(by_key) != len(promotions) or set(by_key) != {"r3", "r4", "r5"}:
        raise ValueError("input set requires exact r3/r4/r5 promotion attestations")
    for promotion in promotions:
        if promotion.owner != "research":
            raise ValueError("promotion attestation owner must be research")
        if promotion.approved_at > created_at or promotion.valid_until <= created_at:
            raise ValueError("promotion attestation is not current")
        if promotion.retired_at is not None:
            raise ValueError("retired promotion cannot be consumed")
        if valid_until > promotion.valid_until:
            raise ValueError("input set cannot outlive a promotion attestation")
    return by_key


def _validate_payload_temporal_bounds(
    payloads: dict[OptimizationInputKind, GovernedOptimizationPayload],
    bindings: dict[OptimizationInputKind, OwnerBoundPayloadEvidence],
    created_at: datetime,
) -> None:
    """Reject future or stale row-level evidence hidden inside a payload."""

    trading = payloads[OptimizationInputKind.TRADING_CONSTRAINTS]
    if not isinstance(trading, TradingConstraintsPayload):
        raise ValueError("trading constraints typed payload mismatch")
    trading_binding = bindings[OptimizationInputKind.TRADING_CONSTRAINTS]
    for rule in trading.constraints:
        if (
            rule.available_at > trading_binding.knowledge_as_of
            or rule.available_at > created_at
            or rule.valid_until <= created_at
        ):
            raise ValueError("market constraint row is not current at input-set creation")

    drawdown = payloads[OptimizationInputKind.DRAWDOWN_RISK_BUDGET]
    if not isinstance(drawdown, DrawdownRiskBudgetPayload):
        raise ValueError("drawdown risk budget typed payload mismatch")
    drawdown_binding = bindings[OptimizationInputKind.DRAWDOWN_RISK_BUDGET]
    if (
        drawdown.pit_manifest_id != drawdown_binding.pit_manifest_id
        or drawdown.pit_manifest_hash != drawdown_binding.pit_manifest_hash
    ):
        raise ValueError("drawdown payload PIT manifest does not match its owner binding")
    if any(
        observation.period_end > drawdown_binding.knowledge_as_of
        or observation.period_end > created_at
        for observation in drawdown.observations
    ):
        raise ValueError("drawdown path contains observations beyond the PIT cutoff")


def _validate_promoted_lineage(
    bindings: dict[OptimizationInputKind, OwnerBoundPayloadEvidence],
    promotions: dict[str, ExactPromotionAttestation],
) -> None:
    if set(bindings[OptimizationInputKind.EXPECTED_RETURN].source_content_hashes) != {
        promotions["r3"].artifact_content_hash,
        promotions["r5"].artifact_content_hash,
    }:
        raise ValueError("expected return payload lacks exact promoted R3/R5 lineage")
    for kind in (
        OptimizationInputKind.MACRO_EXPOSURE,
        OptimizationInputKind.ASSET_COVARIANCE,
    ):
        if bindings[kind].source_content_hashes != (promotions["r4"].artifact_content_hash,):
            raise ValueError(f"{kind.value} payload lacks exact promoted R4 lineage")


def payload_asset_codes(
    payload: GovernedOptimizationPayload,
) -> tuple[str, ...] | None:
    """Return the exact asset dimension when the payload is asset-aligned."""

    if isinstance(payload, ExpectedReturnPayload):
        return tuple(item.asset_code for item in payload.values)
    if isinstance(payload, MacroExposurePayload):
        return tuple(sorted({item.asset_code for item in payload.exposures}))
    if isinstance(payload, AssetCovariancePayload):
        return payload.asset_codes
    if isinstance(payload, ScenarioLossPayload):
        return tuple(item.asset_code for item in payload.scenarios[0].losses)
    if isinstance(payload, DrawdownRiskBudgetPayload):
        return tuple(item.asset_code for item in payload.observations[0].asset_returns)
    if isinstance(payload, TransactionCostPayload):
        return tuple(item.asset_code for item in payload.cost_rates)
    if isinstance(payload, LiquidityLimitPayload):
        return tuple(item.asset_code for item in payload.maximum_trade_weights)
    if isinstance(payload, PositionBoundsPayload):
        return tuple(item.asset_code for item in payload.bounds)
    if isinstance(payload, TradingConstraintsPayload):
        return tuple(item.asset_code for item in payload.constraints)
    if isinstance(payload, ManualRestrictionsPayload):
        return tuple(item.asset_code for item in payload.restrictions)
    if isinstance(payload, ExecutionFeedbackPayload):
        return tuple(item.asset_code for item in payload.feedback)
    return None


def governed_input_set_hash(input_set: GovernedOptimizationInputSet) -> str:
    """Recompute the complete input-set seal."""

    return governed_input_set_hash_values(
        input_set_id=input_set.input_set_id,
        input_set_version=input_set.input_set_version,
        contract_version=input_set.contract_version,
        portfolio_snapshot_id=input_set.portfolio_snapshot_id,
        portfolio_snapshot_hash=input_set.portfolio_snapshot_hash,
        universe=input_set.universe,
        payloads=input_set.payloads,
        owner_bindings=input_set.owner_bindings,
        promotions=input_set.promotions,
        created_at=input_set.created_at,
        valid_until=input_set.valid_until,
    )


def governed_input_set_hash_values(
    *,
    input_set_id: str,
    input_set_version: str,
    contract_version: str,
    portfolio_snapshot_id: str,
    portfolio_snapshot_hash: str,
    universe: InvestableUniverseSnapshot,
    payloads: tuple[GovernedOptimizationPayload, ...],
    owner_bindings: tuple[OwnerBoundPayloadEvidence, ...],
    promotions: tuple[ExactPromotionAttestation, ...],
    created_at: datetime,
    valid_until: datetime,
) -> str:
    """Hash every payload, owner, Promotion and active window."""

    return hash_components(
        "governed-optimizer-input-set.v2",
        input_set_id,
        input_set_version,
        contract_version,
        portfolio_snapshot_id,
        portfolio_snapshot_hash,
        universe.universe_hash,
        universe.owner_attestation_hash,
        *(f"{item.kind.value}|{item.content_hash}" for item in payloads),
        *(f"{item.kind.value}|{item.owner_attestation_hash}" for item in owner_bindings),
        *(f"{item.capability_key}|{item.attestation_hash}" for item in promotions),
        utc_text(created_at),
        utc_text(valid_until),
        "research_only",
        "must_not_execute",
        "must_not_use_for_decision",
    )


__all__ = [
    "CANONICAL_OPTIMIZATION_OWNERS",
    "ExactPromotionAttestation",
    "GovernedOptimizationInputSet",
    "GovernedOptimizationPayload",
    "OwnerBoundPayloadEvidence",
    "build_owner_bound_payload_evidence",
    "exact_promotion_attestation_hash",
    "governed_input_set_hash",
    "owner_bound_payload_hash",
    "payload_asset_codes",
]
