"""Unit coverage for the governed R8 numerical input boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.portfolio.application.governed_optimization import (
    AssembleGovernedOptimizationCommand,
    AssembleGovernedOptimizationProblemUseCase,
    GovernedOptimizationRunBundle,
    GovernedOptimizationUnavailable,
    RunGovernedOptimizationResearchUseCase,
)
from apps.portfolio.composition import make_governed_optimization_research_runtime
from apps.portfolio.domain.canonical_snapshots import (
    CanonicalPortfolioSnapshot,
    CanonicalPosition,
    build_canonical_cash_projection,
    build_canonical_portfolio_snapshot,
    build_canonical_positions_projection,
)
from apps.portfolio.domain.constrained_optimization import (
    OptimizationBlockerCode,
    evaluate_solver_output,
)
from apps.portfolio.domain.constrained_optimization_contracts import (
    CandidateKind,
    MacroRiskBudget,
    OptimizationObjective,
    OptimizationValidationPolicy,
    SolverConvergenceStatus,
    build_solver_output,
)
from apps.portfolio.domain.governed_optimization_inputs import (
    CANONICAL_OPTIMIZATION_OWNERS,
    AShareTradingConstraint,
    AssetCovariancePayload,
    AssetDecimalValue,
    AssetFactorExposure,
    AssetMarket,
    BondTradingConstraint,
    CashRequirementPayload,
    CommodityTradingConstraint,
    DrawdownPathObservation,
    DrawdownRiskBudgetPayload,
    ExactPromotionAttestation,
    ExecutionFeedbackPayload,
    ExecutionFeedbackValue,
    ExpectedReturnPayload,
    FundTradingConstraint,
    GovernedOptimizationInputSet,
    InvestableUniverseMember,
    LiquidityLimitPayload,
    MacroExposurePayload,
    ManualRestrictionsPayload,
    ManualRestrictionValue,
    OwnerBoundPayloadEvidence,
    PositionBoundsPayload,
    PositionBoundValue,
    ScenarioAssetLoss,
    ScenarioLossPayload,
    ScenarioLossVector,
    TradingConstraintsPayload,
    TransactionCostPayload,
    TurnoverLimitPayload,
    build_current_configuration_baseline,
    build_investable_universe_snapshot,
    build_owner_bound_payload_evidence,
    calculate_frozen_weight_path_drawdown,
)
from apps.portfolio.domain.macro_factor_risk import (
    AssetMacroExposure,
    FactorCovarianceVersion,
    MacroExposureVersion,
    MacroFactorBeta,
)
from apps.portfolio.domain.optimizer_inputs import OptimizationInputKind
from apps.portfolio.infrastructure.deterministic_optimizer import (
    DeterministicConstrainedSearchAdapter,
)

NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)
LATER = NOW + timedelta(days=30)
H = "a" * 64


def _position(asset_code: str, value: str) -> CanonicalPosition:
    return CanonicalPosition(
        asset_code=asset_code,
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        market_value_base=Decimal(value),
        position_source_ref=f"position:{asset_code}:v1",
        position_observed_at=NOW,
        valuation_source_ref=f"valuation:{asset_code}:v1",
        valuation_observed_at=NOW,
    )


def _snapshot() -> CanonicalPortfolioSnapshot:
    return build_canonical_portfolio_snapshot(
        cash_projection=build_canonical_cash_projection(
            account_ref="account:governed",
            base_currency="CNY",
            cash_balance=Decimal("100"),
            evidence_ref="cash:published:v1",
            version="cash.v1",
            observed_at=NOW,
        ),
        positions_projection=build_canonical_positions_projection(
            account_ref="account:governed",
            evidence_ref="positions:published:v1",
            version="positions.v1",
            observed_at=NOW,
            positions=(
                _position("A.SH", "400"),
                _position("B.FUND", "300"),
                _position("C.BOND", "200"),
            ),
        ),
    )


def _member(
    asset_code: str,
    market: AssetMarket,
    *,
    can_buy: bool = True,
    can_sell: bool = True,
    retain_if_held: bool = False,
) -> InvestableUniverseMember:
    return InvestableUniverseMember(
        asset_code=asset_code,
        market=market,
        currency="CNY",
        membership_ref=f"publication:universe:{asset_code}",
        membership_version="membership.v1",
        membership_content_hash=H,
        can_buy=can_buy,
        can_sell=can_sell,
        retain_if_held=retain_if_held,
    )


def _universe():
    return build_investable_universe_snapshot(
        universe_id="universe:multi-asset:v1",
        version="universe.v1",
        owner="portfolio",
        membership_publication_id="publication:investable-universe:v1",
        membership_publication_version="publication.v1",
        membership_publication_content_hash="b" * 64,
        observed_at=NOW,
        available_at=NOW,
        valid_until=LATER,
        members=(
            _member("A.SH", AssetMarket.A_SHARE),
            _member("B.FUND", AssetMarket.FUND),
            _member("C.BOND", AssetMarket.BOND, can_buy=False, retain_if_held=True),
            _member("D.COM", AssetMarket.COMMODITY),
        ),
    )


def _market_constraints(universe_hash: str) -> TradingConstraintsPayload:
    common = {
        "rule_version": "rule.v1",
        "rule_evidence_ref": "publication:market-rule:v1",
        "rule_content_hash": "c" * 64,
        "observed_at": NOW,
        "available_at": NOW,
        "valid_until": LATER,
    }
    return TradingConstraintsPayload.create(
        universe_hash=universe_hash,
        constraints=(
            AShareTradingConstraint(
                asset_code="A.SH",
                board_lot_size=Decimal("100"),
                settlement_days=1,
                minimum_order_notional=Decimal("1000"),
                maximum_participation_rate=Decimal("0.10"),
                price_limit_rate=Decimal("0.10"),
                **common,
            ),
            FundTradingConstraint(
                asset_code="B.FUND",
                minimum_subscription_amount=Decimal("100"),
                minimum_redemption_units=Decimal("1"),
                subscription_settlement_days=1,
                redemption_settlement_days=2,
                maximum_daily_amount=Decimal("1000000"),
                **common,
            ),
            BondTradingConstraint(
                asset_code="C.BOND",
                face_value_lot=Decimal("1000"),
                settlement_days=1,
                minimum_trade_notional=Decimal("100000"),
                accrued_interest_required=True,
                maximum_daily_notional=Decimal("5000000"),
                **common,
            ),
            CommodityTradingConstraint(
                asset_code="D.COM",
                contract_multiplier=Decimal("10"),
                lot_size=Decimal("1"),
                initial_margin_rate=Decimal("0.12"),
                settlement_days=0,
                price_limit_rate=Decimal("0.08"),
                maximum_daily_contracts=Decimal("50"),
                **common,
            ),
        ),
    )


def _payloads(universe_hash: str):
    codes = ("A.SH", "B.FUND", "C.BOND", "D.COM")
    vector = tuple(AssetDecimalValue(code, Decimal("0.01")) for code in codes)
    return (
        ExpectedReturnPayload.create(universe_hash=universe_hash, values=vector),
        MacroExposurePayload.create(
            universe_hash=universe_hash,
            exposures=tuple(AssetFactorExposure(code, "growth", Decimal("0.20")) for code in codes),
            factor_codes=("growth",),
            factor_covariance_values=((Decimal("0.03"),),),
        ),
        AssetCovariancePayload.create(
            universe_hash=universe_hash,
            asset_codes=codes,
            values=tuple(
                tuple(Decimal("0.04") if i == j else Decimal("0.01") for j in range(4))
                for i in range(4)
            ),
        ),
        ScenarioLossPayload.create(
            universe_hash=universe_hash,
            scenarios=(
                ScenarioLossVector(
                    scenario_revision_id="scenario:stress:v1",
                    scenario_version="scenario.v1",
                    maximum_portfolio_loss=Decimal("0.20"),
                    losses=tuple(ScenarioAssetLoss(code, Decimal("0.05")) for code in codes),
                    evidence_hash="d" * 64,
                ),
            ),
        ),
        DrawdownRiskBudgetPayload.create(
            universe_hash=universe_hash,
            maximum_drawdown=Decimal("0.15"),
            path_id="path:historical:v1",
            path_version="path.v1",
            pit_manifest_id="pit:optimizer-inputs:v1",
            pit_manifest_hash="8" * 64,
            observations=(
                DrawdownPathObservation(
                    period_end=NOW - timedelta(days=2),
                    asset_returns=tuple(AssetDecimalValue(code, Decimal("0.10")) for code in codes),
                    cash_return=Decimal("0"),
                ),
                DrawdownPathObservation(
                    period_end=NOW - timedelta(days=1),
                    asset_returns=tuple(
                        AssetDecimalValue(code, Decimal("-0.20")) for code in codes
                    ),
                    cash_return=Decimal("0"),
                ),
            ),
        ),
        TransactionCostPayload.create(
            universe_hash=universe_hash,
            cost_rates=vector,
            maximum_total_cost=Decimal("0.01"),
        ),
        TurnoverLimitPayload.create(
            universe_hash=universe_hash,
            maximum_turnover=Decimal("0.25"),
        ),
        LiquidityLimitPayload.create(
            universe_hash=universe_hash,
            maximum_trade_weights=vector,
        ),
        PositionBoundsPayload.create(
            universe_hash=universe_hash,
            bounds=tuple(PositionBoundValue(code, Decimal("0"), Decimal("0.60")) for code in codes),
        ),
        _market_constraints(universe_hash),
        ManualRestrictionsPayload.create(
            universe_hash=universe_hash,
            restrictions=tuple(ManualRestrictionValue(code, "none") for code in codes),
        ),
        CashRequirementPayload.create(
            universe_hash=universe_hash,
            minimum_cash_weight=Decimal("0.05"),
            target_cash_weight=Decimal("0.10"),
        ),
        ExecutionFeedbackPayload.create(
            universe_hash=universe_hash,
            source_bundle_hash="f" * 64,
            feedback=tuple(
                ExecutionFeedbackValue(
                    asset_code=code,
                    feedback_id=f"feedback:{code}:v1",
                    realized_cost_rate=Decimal("0.001"),
                    realized_slippage_rate=Decimal("0.0005"),
                    fill_rate=Decimal("0.95"),
                    evidence_hash="1" * 64,
                )
                for code in codes
            ),
        ),
    )


def _promotions() -> tuple[ExactPromotionAttestation, ...]:
    return tuple(
        ExactPromotionAttestation.create(
            capability_key=key,
            artifact_id=f"artifact:{key}:v1",
            artifact_version=f"{key}.v1",
            artifact_content_hash=character * 64,
            decision_id=f"promotion:{key}:v1",
            decision_content_hash=(character.upper().lower()) * 64,
            owner="research",
            approved_at=NOW,
            valid_until=LATER,
        )
        for key, character in (("r3", "2"), ("r4", "3"), ("r5", "4"))
    )


def _bindings(payloads, universe_hash: str, promotions):
    by_key = {item.capability_key: item for item in promotions}
    result: list[OwnerBoundPayloadEvidence] = []
    for payload in payloads:
        source_hashes = ("9" * 64,)
        if payload.kind is OptimizationInputKind.EXPECTED_RETURN:
            source_hashes = (
                by_key["r3"].artifact_content_hash,
                by_key["r5"].artifact_content_hash,
            )
        elif payload.kind in {
            OptimizationInputKind.MACRO_EXPOSURE,
            OptimizationInputKind.ASSET_COVARIANCE,
        }:
            source_hashes = (by_key["r4"].artifact_content_hash,)
        result.append(
            build_owner_bound_payload_evidence(
                kind=payload.kind,
                owner=CANONICAL_OPTIMIZATION_OWNERS[payload.kind],
                version=f"{payload.kind.value}.v1",
                evidence_ref=f"evidence:{payload.kind.value}:v1",
                observed_at=NOW,
                available_at=NOW,
                knowledge_as_of=NOW,
                valid_until=LATER,
                pit_manifest_id="pit:optimizer-inputs:v1",
                pit_manifest_hash="8" * 64,
                universe_hash=universe_hash,
                payload_hash=payload.content_hash,
                source_content_hashes=source_hashes,
            )
        )
    return tuple(result)


def _input_set() -> GovernedOptimizationInputSet:
    universe = _universe()
    payloads = _payloads(universe.universe_hash)
    promotions = _promotions()
    return GovernedOptimizationInputSet.create(
        input_set_id="optimizer-input-set:v1",
        input_set_version="governed-optimizer-input-set.v1",
        contract_version="optimizer-contract.v2",
        portfolio_snapshot_id=_snapshot().snapshot_id,
        portfolio_snapshot_hash=_snapshot().content_hash,
        universe=universe,
        payloads=payloads,
        owner_bindings=_bindings(payloads, universe.universe_hash, promotions),
        promotions=promotions,
        created_at=NOW,
        valid_until=LATER,
    )


def _with_binding_pit_manifests(
    input_set: GovernedOptimizationInputSet,
    *,
    exposure_pit_manifest_id: str,
    covariance_pit_manifest_id: str,
) -> GovernedOptimizationInputSet:
    replacements = {
        OptimizationInputKind.MACRO_EXPOSURE: exposure_pit_manifest_id,
        OptimizationInputKind.ASSET_COVARIANCE: covariance_pit_manifest_id,
    }
    bindings = tuple(
        build_owner_bound_payload_evidence(
            kind=binding.kind,
            owner=binding.owner,
            version=binding.version,
            evidence_ref=binding.evidence_ref,
            observed_at=binding.observed_at,
            available_at=binding.available_at,
            knowledge_as_of=binding.knowledge_as_of,
            valid_until=binding.valid_until,
            pit_manifest_id=replacements.get(binding.kind, binding.pit_manifest_id),
            pit_manifest_hash=binding.pit_manifest_hash,
            universe_hash=binding.universe_hash,
            payload_hash=binding.payload_hash,
            source_content_hashes=binding.source_content_hashes,
        )
        for binding in input_set.owner_bindings
    )
    return GovernedOptimizationInputSet.create(
        input_set_id="optimizer-input-set:distinct-macro-pit:v1",
        input_set_version=input_set.input_set_version,
        contract_version=input_set.contract_version,
        portfolio_snapshot_id=input_set.portfolio_snapshot_id,
        portfolio_snapshot_hash=input_set.portfolio_snapshot_hash,
        universe=input_set.universe,
        payloads=input_set.payloads,
        owner_bindings=bindings,
        promotions=input_set.promotions,
        created_at=input_set.created_at,
        valid_until=input_set.valid_until,
    )


class _InputSetProvider:
    def __init__(self, input_set: GovernedOptimizationInputSet | None) -> None:
        self._input_set = input_set

    def get_exact(
        self,
        *,
        input_set_id: str,
        evaluated_at: datetime,
    ) -> GovernedOptimizationInputSet | None:
        del evaluated_at
        if self._input_set is None or self._input_set.input_set_id != input_set_id:
            return None
        return self._input_set


class _PromotionProvider:
    def __init__(self, promotions: tuple[ExactPromotionAttestation, ...]) -> None:
        self._promotions = {(item.capability_key, item.decision_id): item for item in promotions}

    def get_exact(
        self,
        *,
        capability_key: str,
        decision_id: str,
        evaluated_at: datetime,
    ) -> ExactPromotionAttestation | None:
        del evaluated_at
        return self._promotions.get((capability_key, decision_id))


class _RunRepository:
    def __init__(self) -> None:
        self.bundles: list[GovernedOptimizationRunBundle] = []

    def append_bundle(
        self,
        bundle: GovernedOptimizationRunBundle,
    ) -> GovernedOptimizationRunBundle:
        self.bundles.append(bundle)
        return bundle


def _command(input_set: GovernedOptimizationInputSet) -> AssembleGovernedOptimizationCommand:
    exposures = tuple(
        AssetMacroExposure(
            asset_code=code,
            betas=(
                MacroFactorBeta(
                    factor_code="growth",
                    beta=Decimal("0.20"),
                    confidence_low=Decimal("0.10"),
                    confidence_high=Decimal("0.30"),
                ),
            ),
            residual_variance=Decimal("0.01"),
            r_squared=Decimal("0.60"),
            stability_score=Decimal("0.80"),
        )
        for code in ("A.SH", "B.FUND", "C.BOND", "D.COM")
    )
    return AssembleGovernedOptimizationCommand(
        problem_id="problem:governed:v1",
        problem_version="problem.v2",
        decision_snapshot_id="decision:snapshot:v1",
        canonical_snapshot=_snapshot(),
        input_set_id=input_set.input_set_id,
        objective=OptimizationObjective(
            objective_version="objective.v1",
            expected_return_weight=Decimal("1"),
            variance_penalty=Decimal("1"),
            transaction_cost_penalty=Decimal("1"),
        ),
        validation_policy=OptimizationValidationPolicy(
            policy_version="validation.v1",
            activated_at=NOW,
            valid_until=LATER,
            weight_tolerance=Decimal("0.000001"),
            covariance_symmetry_tolerance=Decimal("0.000001"),
            covariance_psd_tolerance=Decimal("0.000001"),
            solver_max_iterations=10,
            solver_initial_step=Decimal("0.05"),
            solver_minimum_step=Decimal("0.001"),
            risk_parity_max_iterations=10,
            risk_parity_tolerance=Decimal("0.01"),
        ),
        macro_exposure_version=MacroExposureVersion(
            version_id="artifact:r4:v1",
            promoted_factor_version="r3.v1",
            promotion_decision_id="promotion:r4:v1",
            pit_manifest_id="pit:optimizer-inputs:v1",
            code_version="code.v1",
            parameter_version="parameter.v1",
            observed_at=NOW,
            valid_until=LATER,
            exposures=exposures,
        ),
        macro_factor_covariance=FactorCovarianceVersion(
            version_id="macro-covariance:v1",
            factor_codes=("growth",),
            values=((Decimal("0.03"),),),
            pit_manifest_id="pit:optimizer-inputs:v1",
            estimator_version="estimator.v1",
            observed_at=NOW,
            valid_until=LATER,
        ),
        macro_risk_budget=MacroRiskBudget.create(
            budget_version="macro-budget.v1",
            maximum_factor_variance=Decimal("1"),
            target_contribution_shares=(("growth", Decimal("1")),),
            maximum_target_deviation=Decimal("1"),
        ),
        created_at=NOW,
        valid_until=LATER,
    )


def test_published_universe_retains_held_sell_only_asset_and_builds_current_baseline() -> None:
    universe = _universe()
    baseline = build_current_configuration_baseline(
        snapshot=_snapshot(),
        universe=universe,
        weight_tolerance=Decimal("0.000001"),
    )

    assert baseline.asset_codes == ("A.SH", "B.FUND", "C.BOND", "D.COM")
    assert baseline.weights == (
        Decimal("0.4"),
        Decimal("0.3"),
        Decimal("0.2"),
        Decimal("0"),
    )
    assert baseline.cash_weight == Decimal("0.1")
    assert baseline.snapshot_hash == _snapshot().content_hash

    with pytest.raises(ValueError, match="universe content hash mismatch"):
        replace(
            universe,
            members=tuple(item for item in universe.members if item.asset_code != "C.BOND"),
        )


def test_four_market_constraints_are_tagged_and_path_drawdown_uses_real_nav_path() -> None:
    universe = _universe()
    payload = _market_constraints(universe.universe_hash)
    assert tuple(item.market for item in payload.constraints) == tuple(AssetMarket)

    drawdown_payload = next(
        item
        for item in _payloads(universe.universe_hash)
        if item.kind is OptimizationInputKind.DRAWDOWN_RISK_BUDGET
    )
    result = calculate_frozen_weight_path_drawdown(
        payload=drawdown_payload,
        weights=(Decimal("0.4"), Decimal("0.3"), Decimal("0.2"), Decimal("0")),
        cash_weight=Decimal("0.1"),
        weight_tolerance=Decimal("0.000001"),
    )
    assert result.nav_path == (Decimal("1"), Decimal("1.09"), Decimal("0.892"))
    assert result.maximum_drawdown == (Decimal("1.09") - Decimal("0.892")) / Decimal("1.09")

    repeating = Decimal("1") / Decimal("3")
    calculate_frozen_weight_path_drawdown(
        payload=drawdown_payload,
        weights=(repeating, repeating, repeating, Decimal("0")),
        cash_weight=Decimal("0"),
        weight_tolerance=Decimal("0.000001"),
    )


def test_governed_input_set_recomputes_all_13_payload_and_owner_hashes() -> None:
    universe = _universe()
    payloads = _payloads(universe.universe_hash)
    promotions = _promotions()
    bindings = _bindings(payloads, universe.universe_hash, promotions)
    input_set = GovernedOptimizationInputSet.create(
        input_set_id="optimizer-input-set:v1",
        input_set_version="governed-optimizer-input-set.v1",
        contract_version="optimizer-contract.v2",
        portfolio_snapshot_id=_snapshot().snapshot_id,
        portfolio_snapshot_hash=_snapshot().content_hash,
        universe=universe,
        payloads=payloads,
        owner_bindings=bindings,
        promotions=promotions,
        created_at=NOW,
        valid_until=LATER,
    )

    assert len(input_set.payloads) == len(OptimizationInputKind) == 13
    assert {item.kind for item in input_set.payloads} == set(OptimizationInputKind)
    assert all(item.owner_attestation_hash for item in input_set.owner_bindings)
    assert input_set.research_only is True
    assert input_set.must_not_execute is True

    with pytest.raises(ValueError, match="owner attestation hash mismatch"):
        replace(input_set.owner_bindings[0], payload_hash="0" * 64)
    with pytest.raises(ValueError, match="owner attestation hash mismatch"):
        replace(input_set.owner_bindings[0], owner_attestation_hash="0" * 64)
    with pytest.raises(ValueError, match="requires every canonical payload exactly once"):
        replace(input_set, payloads=input_set.payloads[:-1])


def test_governed_input_set_rejects_fake_owner_and_missing_exact_promotion_lineage() -> None:
    universe = _universe()
    payloads = _payloads(universe.universe_hash)
    promotions = _promotions()
    bindings = list(_bindings(payloads, universe.universe_hash, promotions))
    bindings[0] = build_owner_bound_payload_evidence(
        kind=bindings[0].kind,
        owner="owner-expected-return",
        version=bindings[0].version,
        evidence_ref=bindings[0].evidence_ref,
        observed_at=bindings[0].observed_at,
        available_at=bindings[0].available_at,
        knowledge_as_of=bindings[0].knowledge_as_of,
        valid_until=bindings[0].valid_until,
        pit_manifest_id=bindings[0].pit_manifest_id,
        pit_manifest_hash=bindings[0].pit_manifest_hash,
        universe_hash=bindings[0].universe_hash,
        payload_hash=bindings[0].payload_hash,
        source_content_hashes=bindings[0].source_content_hashes,
    )
    with pytest.raises(ValueError, match="canonical owner mismatch"):
        GovernedOptimizationInputSet.create(
            input_set_id="optimizer-input-set:v1",
            input_set_version="governed-optimizer-input-set.v1",
            contract_version="optimizer-contract.v2",
            portfolio_snapshot_id=_snapshot().snapshot_id,
            portfolio_snapshot_hash=_snapshot().content_hash,
            universe=universe,
            payloads=payloads,
            owner_bindings=tuple(bindings),
            promotions=promotions,
            created_at=NOW,
            valid_until=LATER,
        )

    with pytest.raises(ValueError, match="exact r3/r4/r5 promotion attestations"):
        GovernedOptimizationInputSet.create(
            input_set_id="optimizer-input-set:v1",
            input_set_version="governed-optimizer-input-set.v1",
            contract_version="optimizer-contract.v2",
            portfolio_snapshot_id=_snapshot().snapshot_id,
            portfolio_snapshot_hash=_snapshot().content_hash,
            universe=universe,
            payloads=payloads,
            owner_bindings=_bindings(payloads, universe.universe_hash, promotions),
            promotions=promotions[:-1],
            created_at=NOW,
            valid_until=LATER,
        )


def test_trusted_assembler_rebuilds_solver_problem_from_all_typed_payloads() -> None:
    input_set = _input_set()
    command = _command(input_set)
    assembly = AssembleGovernedOptimizationProblemUseCase(
        input_set_provider=_InputSetProvider(input_set),
        promotion_provider=_PromotionProvider(input_set.promotions),
    ).execute(command)

    assert assembly.problem.governed_input_set == input_set
    assert assembly.problem.drawdown_path is not None
    assert tuple(item.current_weight for item in assembly.problem.assets) == (
        Decimal("0.4"),
        Decimal("0.3"),
        Decimal("0.2"),
        Decimal("0"),
    )
    assert all(item.drawdown_loss is None for item in assembly.problem.assets)
    held_only = next(item for item in assembly.problem.assets if item.asset_code == "C.BOND")
    assert held_only.maximum_weight == held_only.current_weight
    assert held_only.manual_restriction.value == "no_buy"
    assert len(assembly.problem.evidence_bindings) == 13
    assert assembly.current_configuration.observed_turnover == 0
    assert assembly.current_configuration.observed_transaction_cost == 0

    traded = evaluate_solver_output(
        assembly.problem,
        build_solver_output(
            candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
            weights=(Decimal("0.35"), Decimal("0.35"), Decimal("0.2"), Decimal("0")),
            cash_weight=Decimal("0.1"),
            status=SolverConvergenceStatus.LOCAL_STATIONARY,
            iterations=1,
            residual=Decimal("0.001"),
            detail="weight-only research draft",
        ),
    )
    assert OptimizationBlockerCode.MARKET_CONSTRAINT_NOT_ENFORCED in {
        item.code for item in traded.blockers
    }

    with pytest.raises(ValueError, match="canonical governed input set is unavailable"):
        AssembleGovernedOptimizationProblemUseCase(
            input_set_provider=_InputSetProvider(None),
            promotion_provider=_PromotionProvider(input_set.promotions),
        ).execute(command)
    with pytest.raises(ValueError, match="exact Research promotion evidence is unavailable"):
        AssembleGovernedOptimizationProblemUseCase(
            input_set_provider=_InputSetProvider(input_set),
            promotion_provider=_PromotionProvider(input_set.promotions[:-1]),
        ).execute(command)

    distinct_pit_input_set = _with_binding_pit_manifests(
        input_set,
        exposure_pit_manifest_id="pit:macro-exposure:v1",
        covariance_pit_manifest_id="pit:asset-covariance:v1",
    )
    distinct_pit_command = replace(
        command,
        input_set_id=distinct_pit_input_set.input_set_id,
        macro_exposure_version=replace(
            command.macro_exposure_version,
            pit_manifest_id="pit:macro-exposure:v1",
        ),
        macro_factor_covariance=replace(
            command.macro_factor_covariance,
            pit_manifest_id="pit:asset-covariance:v1",
        ),
    )
    distinct_pit_assembler = AssembleGovernedOptimizationProblemUseCase(
        input_set_provider=_InputSetProvider(distinct_pit_input_set),
        promotion_provider=_PromotionProvider(distinct_pit_input_set.promotions),
    )
    distinct_pit_assembler.execute(distinct_pit_command)

    with pytest.raises(ValueError, match="macro exposure/covariance PIT manifest mismatch"):
        distinct_pit_assembler.execute(
            replace(
                distinct_pit_command,
                macro_exposure_version=replace(
                    distinct_pit_command.macro_exposure_version,
                    pit_manifest_id="pit:asset-covariance:v1",
                ),
                macro_factor_covariance=replace(
                    distinct_pit_command.macro_factor_covariance,
                    pit_manifest_id="pit:macro-exposure:v1",
                ),
            )
        )


def test_governed_run_compares_all_four_candidates_and_stays_research_only() -> None:
    input_set = _input_set()
    repository = _RunRepository()
    use_case = RunGovernedOptimizationResearchUseCase(
        assembler=AssembleGovernedOptimizationProblemUseCase(
            input_set_provider=_InputSetProvider(input_set),
            promotion_provider=_PromotionProvider(input_set.promotions),
        ),
        engine=DeterministicConstrainedSearchAdapter(),
        repository=repository,
    )

    bundle = use_case.execute(
        command=_command(input_set),
        run_key="r8-governed-run",
        run_version="v1",
    )

    assert repository.bundles == [bundle]
    assert {item.candidate_kind for item in bundle.result.candidates} == set(CandidateKind)
    assert bundle.result.research_only is True
    assert bundle.result.must_not_execute is True
    assert bundle.result.must_not_use_for_decision is True


def test_production_composition_is_constructable_but_unavailable_before_any_write() -> None:
    runtime = make_governed_optimization_research_runtime()

    with patch.object(runtime.repository, "append_bundle") as append_bundle:
        with pytest.raises(
            GovernedOptimizationUnavailable,
            match="canonical governed input set is unavailable",
        ):
            runtime.run.execute(
                command=_command(_input_set()),
                run_key="r8-production-unavailable",
                run_version="v1",
            )

    append_bundle.assert_not_called()


def test_nested_market_and_drawdown_rows_cannot_cross_the_pit_cutoff() -> None:
    universe = _universe()
    payloads = list(_payloads(universe.universe_hash))
    promotions = _promotions()

    trading_index = next(
        index
        for index, item in enumerate(payloads)
        if item.kind is OptimizationInputKind.TRADING_CONSTRAINTS
    )
    trading = payloads[trading_index]
    assert isinstance(trading, TradingConstraintsPayload)
    payloads[trading_index] = TradingConstraintsPayload.create(
        universe_hash=universe.universe_hash,
        constraints=(
            replace(trading.constraints[0], available_at=NOW + timedelta(minutes=1)),
            *trading.constraints[1:],
        ),
    )
    with pytest.raises(ValueError, match="market constraint row is not current"):
        GovernedOptimizationInputSet.create(
            input_set_id="optimizer-input-set:future-market",
            input_set_version="governed-optimizer-input-set.v1",
            contract_version="optimizer-contract.v2",
            portfolio_snapshot_id=_snapshot().snapshot_id,
            portfolio_snapshot_hash=_snapshot().content_hash,
            universe=universe,
            payloads=tuple(payloads),
            owner_bindings=_bindings(tuple(payloads), universe.universe_hash, promotions),
            promotions=promotions,
            created_at=NOW,
            valid_until=LATER,
        )

    payloads = list(_payloads(universe.universe_hash))
    drawdown_index = next(
        index
        for index, item in enumerate(payloads)
        if item.kind is OptimizationInputKind.DRAWDOWN_RISK_BUDGET
    )
    drawdown = payloads[drawdown_index]
    assert isinstance(drawdown, DrawdownRiskBudgetPayload)
    payloads[drawdown_index] = DrawdownRiskBudgetPayload.create(
        universe_hash=drawdown.universe_hash,
        maximum_drawdown=drawdown.maximum_drawdown,
        path_id=drawdown.path_id,
        path_version=drawdown.path_version,
        pit_manifest_id=drawdown.pit_manifest_id,
        pit_manifest_hash=drawdown.pit_manifest_hash,
        observations=(
            drawdown.observations[0],
            replace(drawdown.observations[1], period_end=NOW + timedelta(minutes=1)),
        ),
    )
    with pytest.raises(ValueError, match="drawdown path contains observations"):
        GovernedOptimizationInputSet.create(
            input_set_id="optimizer-input-set:future-path",
            input_set_version="governed-optimizer-input-set.v1",
            contract_version="optimizer-contract.v2",
            portfolio_snapshot_id=_snapshot().snapshot_id,
            portfolio_snapshot_hash=_snapshot().content_hash,
            universe=universe,
            payloads=tuple(payloads),
            owner_bindings=_bindings(tuple(payloads), universe.universe_hash, promotions),
            promotions=promotions,
            created_at=NOW,
            valid_until=LATER,
        )


def test_new_payload_hashes_are_decimal_scale_independent() -> None:
    universe_hash = _universe().universe_hash
    canonical = ExpectedReturnPayload.create(
        universe_hash=universe_hash,
        values=(
            AssetDecimalValue("A.SH", Decimal("0.1")),
            AssetDecimalValue("B.FUND", Decimal("0.1")),
            AssetDecimalValue("C.BOND", Decimal("0.1")),
            AssetDecimalValue("D.COM", Decimal("0.1")),
        ),
    )
    scaled = ExpectedReturnPayload.create(
        universe_hash=universe_hash,
        values=(
            AssetDecimalValue("A.SH", Decimal("0.10")),
            AssetDecimalValue("B.FUND", Decimal("0.10")),
            AssetDecimalValue("C.BOND", Decimal("0.10")),
            AssetDecimalValue("D.COM", Decimal("0.10")),
        ),
    )

    assert canonical.content_hash == scaled.content_hash
