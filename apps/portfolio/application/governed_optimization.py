"""Trusted assembly of a solver problem from the governed R8 input set."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, TypeAlias, TypeVar, cast

from apps.portfolio.domain._optimization_canonical import (
    hash_components,
    require_aware,
    require_sha256,
    require_token,
    utc_text,
)
from apps.portfolio.domain.canonical_snapshots import CanonicalPortfolioSnapshot
from apps.portfolio.domain.constrained_optimization import (
    CandidateEvaluation,
    assess_optimization_problem,
    evaluate_solver_output,
)
from apps.portfolio.domain.constrained_optimization_contracts import (
    AssetCovarianceMatrix,
    AssetOptimizationInput,
    MacroRiskBudget,
    ManualRestriction,
    OptimizationEvidenceBinding,
    OptimizationObjective,
    OptimizationProblem,
    OptimizationValidationPolicy,
    ScenarioLossConstraint,
    SolverOutput,
    build_asset_universe_hash,
    build_optimization_problem,
)
from apps.portfolio.domain.current_baseline import (
    CurrentConfigurationBaseline,
    build_current_configuration_baseline,
)
from apps.portfolio.domain.governed_input_set import (
    ExactPromotionAttestation,
    GovernedOptimizationInputSet,
    GovernedOptimizationPayload,
    OwnerBoundPayloadEvidence,
    exact_promotion_attestation_hash,
    governed_input_set_hash,
)
from apps.portfolio.domain.input_payloads import (
    AssetCovariancePayload,
    CashRequirementPayload,
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
from apps.portfolio.domain.investable_universe import InvestableUniverseSnapshot
from apps.portfolio.domain.macro_factor_risk import (
    FactorCovarianceVersion,
    MacroExposureVersion,
)
from apps.portfolio.domain.market_constraints import TradingConstraintsPayload
from apps.portfolio.domain.optimization_input_receipt import (
    RECEIPT_VERSION,
    GovernedOptimizationInputReceipt,
)
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleOwnerAttestation,
    OptimizationResearchLifecycleEvent,
    create_optimization_lifecycle_event,
    create_optimization_lifecycle_root,
)
from apps.portfolio.domain.optimization_research_result import (
    GovernedOptimizationResearchResult,
)
from apps.portfolio.domain.optimizer_inputs import (
    OptimizationInputKind,
    PromotionReference,
)
from apps.portfolio.domain.path_drawdown import DrawdownRiskBudgetPayload


class GovernedOptimizationUnavailable(ValueError):
    """Authoritative R8 input or authorization evidence is unavailable."""


class GovernedOptimizationInputReceiptProvider(Protocol):
    """Authoritative ID-only port for one independently persisted input receipt."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity used for the exact PIT read."""

    def get_exact(
        self,
        *,
        input_set_id: str,
        evaluated_at: datetime,
    ) -> GovernedOptimizationInputReceipt | None:
        """Return the canonical receipt known and active at the supplied time."""


GovernedOptimizationInputSetProvider: TypeAlias = GovernedOptimizationInputReceiptProvider


class CanonicalGovernedOptimizationInputSetProvider(Protocol):
    """Portfolio Application port for an exact persisted input-set identity."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction/lock identity used by this provider."""

    def get_exact(
        self,
        *,
        input_set_id: str,
        input_set_version: str,
        evaluated_at: datetime,
    ) -> GovernedOptimizationInputSet | None:
        """Return the owner-persisted input-set aggregate by identity only."""


@dataclass(frozen=True)
class CanonicalGovernedOptimizationOwnerGraph:
    """Independent authoritative projection of all 13 payload-owner bindings."""

    payloads: tuple[GovernedOptimizationPayload, ...]
    owner_bindings: tuple[OwnerBoundPayloadEvidence, ...]

    def __post_init__(self) -> None:
        """Require complete, unique and canonically ordered owner graph members."""

        payload_kinds = tuple(item.kind for item in self.payloads)
        binding_kinds = tuple(item.kind for item in self.owner_bindings)
        expected = tuple(sorted(OptimizationInputKind, key=lambda item: item.value))
        if payload_kinds != expected or binding_kinds != expected:
            raise ValueError("canonical owner graph requires ordered exact 13-input membership")


class ExactGovernedOptimizationOwnerGraphProvider(Protocol):
    """Exact provider for the 13 canonical payload owners and PIT evidence."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction/lock identity used by this provider."""

    def get_exact(
        self,
        *,
        input_set_id: str,
        input_set_version: str,
        evaluated_at: datetime,
    ) -> CanonicalGovernedOptimizationOwnerGraph | None:
        """Return the complete owner graph, never a caller-supplied partial graph."""


class ExactInvestableUniverseProvider(Protocol):
    """Portfolio-owned exact Published universe lookup."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction/lock identity used by this provider."""

    def get_exact(
        self,
        *,
        universe_id: str,
        universe_version: str,
        evaluated_at: datetime,
    ) -> InvestableUniverseSnapshot | None:
        """Return one exact active Published membership snapshot."""


class ExactCanonicalPortfolioSnapshotProvider(Protocol):
    """Portfolio-owned exact canonical snapshot lookup."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction/lock identity used by this provider."""

    def get_exact(
        self,
        *,
        snapshot_id: str,
        evaluated_at: datetime,
    ) -> CanonicalPortfolioSnapshot | None:
        """Return one exact source-as-of canonical portfolio snapshot."""


class GovernedOptimizationReceiptRegistrationBoundary(Protocol):
    """Composition-private shared transaction boundary for receipt registration."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction/lock identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared registration transaction."""


class GovernedOptimizationReceiptWriter(Protocol):
    """Non-exported closure contract for one already-verified canonical graph."""

    def __call__(
        self,
        input_set: GovernedOptimizationInputSet,
        server_recorded_at: datetime,
    ) -> GovernedOptimizationInputReceipt:
        """Persist the already-authoritatively-reconstructed input set."""


class GovernedOptimizationRegistrationClock(Protocol):
    """Server clock used for every provider read and the receipt seal."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""


class ExactPromotionProvider(Protocol):
    """Research-owned Application port for exact active Promotion evidence."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction/lock identity used by this provider."""

    def get_exact(
        self,
        *,
        capability_key: str,
        decision_id: str,
        evaluated_at: datetime,
    ) -> ExactPromotionAttestation | None:
        """Return the exact Research decision, including retirement state."""


@dataclass(frozen=True)
class RegisterGovernedOptimizationInputReceiptCommand:
    """ID-only request; callers cannot submit any evidentiary graph object."""

    input_set_id: str
    input_set_version: str

    def __post_init__(self) -> None:
        """Validate only stable lookup identity."""

        require_token(self.input_set_id, "input_set_id")
        require_token(self.input_set_version, "input_set_version")


class RegisterGovernedOptimizationInputReceiptUseCase:
    """Reconstruct a receipt exclusively from exact canonical owner providers."""

    def __init__(
        self,
        *,
        transaction_boundary: GovernedOptimizationReceiptRegistrationBoundary,
        writer: GovernedOptimizationReceiptWriter,
        input_set_provider: CanonicalGovernedOptimizationInputSetProvider,
        owner_graph_provider: ExactGovernedOptimizationOwnerGraphProvider,
        universe_provider: ExactInvestableUniverseProvider,
        snapshot_provider: ExactCanonicalPortfolioSnapshotProvider,
        promotion_provider: ExactPromotionProvider,
        clock: GovernedOptimizationRegistrationClock,
    ) -> None:
        self._transaction_boundary = transaction_boundary
        self._writer = writer
        self._input_set_provider = input_set_provider
        self._owner_graph_provider = owner_graph_provider
        self._universe_provider = universe_provider
        self._snapshot_provider = snapshot_provider
        self._promotion_provider = promotion_provider
        self._clock = clock

    def execute(
        self,
        command: RegisterGovernedOptimizationInputReceiptCommand,
    ) -> GovernedOptimizationInputReceipt:
        """Read, compare and store the complete graph in one server-clocked UoW."""

        expected_key = self._transaction_boundary.unit_of_work_key
        provider_keys = (
            self._input_set_provider.unit_of_work_key,
            self._owner_graph_provider.unit_of_work_key,
            self._universe_provider.unit_of_work_key,
            self._snapshot_provider.unit_of_work_key,
            self._promotion_provider.unit_of_work_key,
        )
        if any(item != expected_key for item in provider_keys):
            raise GovernedOptimizationUnavailable(
                "receipt registration providers do not share one locked unit of work"
            )
        with self._transaction_boundary.atomic():
            recorded_at = self._clock.now()
            require_aware(recorded_at, "receipt registration server clock")
            input_set = self._input_set_provider.get_exact(
                input_set_id=command.input_set_id,
                input_set_version=command.input_set_version,
                evaluated_at=recorded_at,
            )
            if input_set is None:
                raise GovernedOptimizationUnavailable(
                    "canonical governed optimization input set is unavailable"
                )
            if (
                input_set.input_set_id != command.input_set_id
                or input_set.input_set_version != command.input_set_version
                or input_set.content_hash != governed_input_set_hash(input_set)
            ):
                raise ValueError("canonical governed optimization input set is substituted")
            if not input_set.created_at <= recorded_at < input_set.valid_until:
                raise GovernedOptimizationUnavailable(
                    "canonical governed optimization input set is not current"
                )
            owner_graph = self._owner_graph_provider.get_exact(
                input_set_id=input_set.input_set_id,
                input_set_version=input_set.input_set_version,
                evaluated_at=recorded_at,
            )
            if owner_graph is None:
                raise GovernedOptimizationUnavailable(
                    "canonical governed optimization owner graph is unavailable"
                )
            if (
                owner_graph.payloads != input_set.payloads
                or owner_graph.owner_bindings != input_set.owner_bindings
            ):
                raise ValueError("canonical governed optimization owner graph is substituted")
            universe = self._universe_provider.get_exact(
                universe_id=input_set.universe.universe_id,
                universe_version=input_set.universe.version,
                evaluated_at=recorded_at,
            )
            if universe is None:
                raise GovernedOptimizationUnavailable(
                    "canonical governed optimization universe is unavailable"
                )
            if universe != input_set.universe:
                raise ValueError("canonical governed optimization universe is substituted")
            snapshot = self._snapshot_provider.get_exact(
                snapshot_id=input_set.portfolio_snapshot_id,
                evaluated_at=recorded_at,
            )
            if snapshot is None:
                raise GovernedOptimizationUnavailable(
                    "canonical governed optimization snapshot is unavailable"
                )
            if (
                snapshot.snapshot_id != input_set.portfolio_snapshot_id
                or snapshot.content_hash != input_set.portfolio_snapshot_hash
                or snapshot.as_of > recorded_at
            ):
                raise ValueError("canonical governed optimization snapshot is substituted")
            _validate_exact_promotions(
                input_set=input_set,
                provider=self._promotion_provider,
                evaluated_at=recorded_at,
            )
            return self._writer(input_set, recorded_at)


@dataclass(frozen=True)
class AssembleGovernedOptimizationCommand:
    """Explicit trusted inputs that are not inferred from database non-emptiness."""

    problem_id: str
    problem_version: str
    decision_snapshot_id: str
    canonical_snapshot: CanonicalPortfolioSnapshot
    input_set_id: str
    objective: OptimizationObjective
    validation_policy: OptimizationValidationPolicy
    macro_exposure_version: MacroExposureVersion
    macro_factor_covariance: FactorCovarianceVersion
    macro_risk_budget: MacroRiskBudget
    created_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Validate command identity and aware clocks before assembly."""

        for field_name, value in (
            ("problem_id", self.problem_id),
            ("problem_version", self.problem_version),
            ("decision_snapshot_id", self.decision_snapshot_id),
            ("input_set_id", self.input_set_id),
        ):
            require_token(value, field_name)
        require_aware(self.created_at, "assembly created_at")
        require_aware(self.valid_until, "assembly valid_until")
        if self.valid_until <= self.created_at:
            raise ValueError("assembly valid_until must follow created_at")


@dataclass(frozen=True)
class GovernedOptimizationAssembly:
    """Trusted numerical problem plus its unmodified current configuration."""

    assembly_version: str
    input_receipt_id: str
    input_receipt_hash: str
    input_set_id: str
    input_set_hash: str
    problem: OptimizationProblem
    current_configuration: CurrentConfigurationBaseline
    assembled_at: datetime
    content_hash: str
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        """Recompute the assembly seal and preserve research-only status."""

        require_token(self.assembly_version, "assembly_version")
        require_sha256(self.input_receipt_id, "input_receipt_id")
        require_sha256(self.input_receipt_hash, "input_receipt_hash")
        require_token(self.input_set_id, "input_set_id")
        require_sha256(self.input_set_hash, "input_set_hash")
        require_aware(self.assembled_at, "assembled_at")
        if self.problem.governed_input_set is None:
            raise ValueError("assembled problem lacks governed input-set evidence")
        if (
            self.problem.governed_input_set.input_set_id != self.input_set_id
            or self.problem.governed_input_set.content_hash != self.input_set_hash
        ):
            raise ValueError("assembled problem input-set identity mismatch")
        if self.current_configuration.snapshot_id != self.problem.canonical_snapshot.snapshot_id:
            raise ValueError("current configuration snapshot mismatch")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("governed optimization assembly must remain research-only")
        require_sha256(self.content_hash, "assembly content_hash")
        if self.content_hash != governed_optimization_assembly_hash(self):
            raise ValueError("governed optimization assembly content hash mismatch")


class AssembleGovernedOptimizationProblemUseCase:
    """Rebuild all legacy solver fields from the exact thirteen typed payloads."""

    def __init__(
        self,
        *,
        input_set_provider: GovernedOptimizationInputSetProvider,
        promotion_provider: ExactPromotionProvider,
    ) -> None:
        self._input_set_provider = input_set_provider
        self._promotion_provider = promotion_provider

    def execute(
        self,
        command: AssembleGovernedOptimizationCommand,
    ) -> GovernedOptimizationAssembly:
        """Assemble a problem or fail closed on any lineage/numerical mismatch."""

        receipt = self._input_set_provider.get_exact(
            input_set_id=command.input_set_id,
            evaluated_at=command.created_at,
        )
        if receipt is None:
            raise GovernedOptimizationUnavailable("canonical governed input receipt is unavailable")
        input_set = receipt.input_set
        if input_set.input_set_id != command.input_set_id:
            raise ValueError("canonical governed input set identity mismatch")
        _validate_exact_promotions(
            input_set=input_set,
            provider=self._promotion_provider,
            evaluated_at=command.created_at,
        )
        _validate_snapshot_binding(command, input_set)
        if input_set.created_at > command.created_at:
            raise ValueError("assembly cannot predate the governed input set")
        if input_set.valid_until <= command.created_at:
            raise ValueError("governed input set has expired")
        if command.valid_until > input_set.valid_until:
            raise ValueError("assembled problem cannot outlive governed inputs")
        payloads = {item.kind: item for item in input_set.payloads}
        expected_return = _payload(
            payloads, OptimizationInputKind.EXPECTED_RETURN, ExpectedReturnPayload
        )
        macro = _payload(payloads, OptimizationInputKind.MACRO_EXPOSURE, MacroExposurePayload)
        covariance_payload = _payload(
            payloads,
            OptimizationInputKind.ASSET_COVARIANCE,
            AssetCovariancePayload,
        )
        scenarios = _payload(payloads, OptimizationInputKind.SCENARIO_LOSS, ScenarioLossPayload)
        drawdown = _payload(
            payloads,
            OptimizationInputKind.DRAWDOWN_RISK_BUDGET,
            DrawdownRiskBudgetPayload,
        )
        costs = _payload(payloads, OptimizationInputKind.TRANSACTION_COST, TransactionCostPayload)
        turnover = _payload(payloads, OptimizationInputKind.TURNOVER_LIMIT, TurnoverLimitPayload)
        liquidity = _payload(payloads, OptimizationInputKind.LIQUIDITY_LIMIT, LiquidityLimitPayload)
        bounds = _payload(payloads, OptimizationInputKind.POSITION_BOUNDS, PositionBoundsPayload)
        restrictions = _payload(
            payloads,
            OptimizationInputKind.MANUAL_RESTRICTIONS,
            ManualRestrictionsPayload,
        )
        cash = _payload(payloads, OptimizationInputKind.CASH_REQUIREMENT, CashRequirementPayload)
        feedback = _payload(
            payloads,
            OptimizationInputKind.EXECUTION_FEEDBACK,
            ExecutionFeedbackPayload,
        )
        trading = _payload(
            payloads,
            OptimizationInputKind.TRADING_CONSTRAINTS,
            TradingConstraintsPayload,
        )
        _validate_macro_artifact(command, input_set, macro)

        current = build_current_configuration_baseline(
            snapshot=command.canonical_snapshot,
            universe=input_set.universe,
            weight_tolerance=command.validation_policy.weight_tolerance,
        )
        codes = tuple(item.asset_code for item in input_set.universe.members)
        legacy_universe_hash = build_asset_universe_hash(codes)
        bindings = {item.kind: item for item in input_set.owner_bindings}
        _validate_row_level_pit(
            input_set=input_set,
            trading=trading,
            drawdown=drawdown,
            assembled_at=command.created_at,
        )
        covariance_binding = bindings[OptimizationInputKind.ASSET_COVARIANCE]
        covariance = AssetCovarianceMatrix.create(
            version=covariance_binding.version,
            asset_codes=covariance_payload.asset_codes,
            values=covariance_payload.values,
            observed_at=covariance_binding.observed_at,
            valid_until=covariance_binding.valid_until,
            universe_hash=legacy_universe_hash,
        )
        expected_by_asset = {item.asset_code: item.value for item in expected_return.values}
        cost_by_asset = {item.asset_code: item.value for item in costs.cost_rates}
        liquidity_by_asset = {
            item.asset_code: item.value for item in liquidity.maximum_trade_weights
        }
        bounds_by_asset = {item.asset_code: item for item in bounds.bounds}
        restriction_by_asset = {
            item.asset_code: ManualRestriction(item.restriction)
            for item in restrictions.restrictions
        }
        member_by_asset = {item.asset_code: item for item in input_set.universe.members}
        current_by_asset = dict(zip(current.asset_codes, current.weights, strict=True))
        asset_inputs = tuple(
            AssetOptimizationInput(
                asset_code=code,
                expected_return=expected_by_asset[code],
                minimum_weight=_effective_membership_bounds(
                    minimum_weight=bounds_by_asset[code].minimum_weight,
                    maximum_weight=bounds_by_asset[code].maximum_weight,
                    current_weight=current_by_asset[code],
                    can_buy=member_by_asset[code].can_buy,
                    can_sell=member_by_asset[code].can_sell,
                    retain_if_held=member_by_asset[code].retain_if_held,
                )[0],
                maximum_weight=_effective_membership_bounds(
                    minimum_weight=bounds_by_asset[code].minimum_weight,
                    maximum_weight=bounds_by_asset[code].maximum_weight,
                    current_weight=current_by_asset[code],
                    can_buy=member_by_asset[code].can_buy,
                    can_sell=member_by_asset[code].can_sell,
                    retain_if_held=member_by_asset[code].retain_if_held,
                )[1],
                maximum_trade_weight=liquidity_by_asset[code],
                transaction_cost_rate=cost_by_asset[code],
                drawdown_loss=None,
                manual_restriction=_merge_membership_restriction(
                    explicit=restriction_by_asset[code],
                    can_buy=member_by_asset[code].can_buy,
                    can_sell=member_by_asset[code].can_sell,
                ),
            )
            for code in codes
        )
        scenario_constraints = tuple(
            ScenarioLossConstraint(
                scenario_revision_id=item.scenario_revision_id,
                scenario_version=item.scenario_version,
                asset_codes=codes,
                loss_rates=tuple(loss.loss_rate for loss in item.losses),
                maximum_portfolio_loss=item.maximum_portfolio_loss,
                evidence_hash=item.evidence_hash,
            )
            for item in scenarios.scenarios
        )
        evidence_bindings = tuple(
            OptimizationEvidenceBinding(
                kind=binding.kind,
                version=binding.version,
                evidence_ref=binding.evidence_ref,
                content_hash=payloads[binding.kind].content_hash,
                universe_hash=legacy_universe_hash,
            )
            for binding in input_set.owner_bindings
        )
        promotions = tuple(
            PromotionReference(
                capability_key=item.capability_key,
                version=item.artifact_version,
                decision_ref=item.decision_id,
                approved_at=item.approved_at,
                valid_until=item.valid_until,
            )
            for item in input_set.promotions
        )
        problem = build_optimization_problem(
            problem_id=command.problem_id,
            problem_version=command.problem_version,
            canonical_snapshot=command.canonical_snapshot,
            decision_snapshot_id=command.decision_snapshot_id,
            asset_inputs=asset_inputs,
            covariance=covariance,
            scenario_losses=scenario_constraints,
            minimum_cash_weight=cash.minimum_cash_weight,
            target_cash_weight=cash.target_cash_weight,
            maximum_turnover=turnover.maximum_turnover,
            maximum_transaction_cost=costs.maximum_total_cost,
            maximum_drawdown=drawdown.maximum_drawdown,
            execution_feedback_hash=feedback.content_hash,
            objective=command.objective,
            validation_policy=command.validation_policy,
            evidence_bindings=evidence_bindings,
            promotions=promotions,
            macro_exposure_version=command.macro_exposure_version,
            macro_factor_covariance=command.macro_factor_covariance,
            macro_risk_budget=command.macro_risk_budget,
            created_at=command.created_at,
            valid_until=command.valid_until,
            drawdown_path=drawdown,
            governed_input_set=input_set,
        )
        content_hash = _assembly_hash_values(
            input_receipt_id=receipt.receipt_id,
            input_receipt_hash=receipt.content_hash,
            input_set_id=input_set.input_set_id,
            input_set_hash=input_set.content_hash,
            problem_hash=problem.content_hash,
            current_configuration_hash=current.content_hash,
            assembled_at=command.created_at,
        )
        return GovernedOptimizationAssembly(
            assembly_version="governed-optimization-assembly.v2",
            input_receipt_id=receipt.receipt_id,
            input_receipt_hash=receipt.content_hash,
            input_set_id=input_set.input_set_id,
            input_set_hash=input_set.content_hash,
            problem=problem,
            current_configuration=current,
            assembled_at=command.created_at,
            content_hash=content_hash,
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )


class GovernedOptimizationEngineProtocol(Protocol):
    """Deterministic four-candidate engine used after trusted assembly."""

    def current_configuration_baseline(self, problem: OptimizationProblem) -> SolverOutput:
        """Return observed canonical weights without projection."""

    def equal_weight_baseline(self, problem: OptimizationProblem) -> SolverOutput:
        """Return the equal-weight benchmark."""

    def asset_risk_parity_baseline(self, problem: OptimizationProblem) -> SolverOutput:
        """Return the asset-risk-parity benchmark."""

    def solve_candidate(self, problem: OptimizationProblem) -> SolverOutput:
        """Return the bounded deterministic research candidate."""


@dataclass(frozen=True)
class GovernedOptimizationRunBundle:
    """Atomic result and deterministic lifecycle root."""

    result: GovernedOptimizationResearchResult
    lifecycle_root: OptimizationResearchLifecycleEvent

    def __post_init__(self) -> None:
        """Require exact result identity on the lifecycle root."""

        if (
            self.lifecycle_root.result_id != self.result.result_id
            or self.lifecycle_root.result_hash != self.result.content_hash
            or self.lifecycle_root.sequence != 1
        ):
            raise ValueError("optimization run bundle lifecycle root mismatch")


class GovernedOptimizationLedgerRepository(Protocol):
    """Append-only persistence boundary for one result/root bundle."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity used for receipt/result writes."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared receipt-read/result-write unit of work."""

    def append_bundle(
        self,
        bundle: GovernedOptimizationRunBundle,
    ) -> GovernedOptimizationRunBundle:
        """Append atomically and return an exact idempotent replay."""


class GovernedOptimizationLifecycleRepository(Protocol):
    """Append-only persistence port; it is not an authorization source."""

    def append_lifecycle_event(
        self,
        event: OptimizationResearchLifecycleEvent,
    ) -> OptimizationResearchLifecycleEvent:
        """Append an already-authorized exact lifecycle event."""


class ExactPortfolioLifecycleAuthorizationProvider(Protocol):
    """Portfolio-owned exact authorization lookup for terminal events."""

    def get_exact(
        self,
        *,
        attestation_id: str,
        result_id: str,
        result_hash: str,
        event_type: OptimizationLifecycleEventType,
        evaluated_at: datetime,
    ) -> OptimizationLifecycleOwnerAttestation | None:
        """Return one exact active owner authorization, or no evidence."""


class AppendGovernedOptimizationLifecycleEventUseCase:
    """Authorize an exact lifecycle transition before append-only persistence."""

    def __init__(
        self,
        *,
        promotion_provider: ExactPromotionProvider,
        owner_authorization_provider: ExactPortfolioLifecycleAuthorizationProvider,
        repository: GovernedOptimizationLifecycleRepository,
    ) -> None:
        self._promotion_provider = promotion_provider
        self._owner_authorization_provider = owner_authorization_provider
        self._repository = repository

    def execute(
        self,
        *,
        result: GovernedOptimizationResearchResult,
        previous_events: tuple[OptimizationResearchLifecycleEvent, ...],
        event_type: OptimizationLifecycleEventType,
        occurred_at: datetime,
        recorded_at: datetime,
        reason_codes: tuple[str, ...],
        promotion_attestation: ExactPromotionAttestation | None = None,
        owner_attestation: OptimizationLifecycleOwnerAttestation | None = None,
    ) -> OptimizationResearchLifecycleEvent:
        """Re-read the canonical authorization, build the event, and append it."""

        if event_type is OptimizationLifecycleEventType.PROMOTION_ATTESTED:
            if promotion_attestation is None or owner_attestation is not None:
                raise ValueError("promotion lifecycle transition requires exact Research evidence")
            trusted_promotion = self._promotion_provider.get_exact(
                capability_key="r8",
                decision_id=promotion_attestation.decision_id,
                evaluated_at=occurred_at,
            )
            if trusted_promotion is None:
                raise GovernedOptimizationUnavailable(
                    "Research Promotion authorization is unavailable"
                )
            if trusted_promotion != promotion_attestation:
                raise ValueError("Research Promotion authorization is not authoritative")
        elif event_type in {
            OptimizationLifecycleEventType.RETIRED,
            OptimizationLifecycleEventType.ROLLED_BACK,
        }:
            if owner_attestation is None or promotion_attestation is not None:
                raise ValueError("terminal lifecycle transition requires exact Portfolio evidence")
            trusted_owner = self._owner_authorization_provider.get_exact(
                attestation_id=owner_attestation.attestation_id,
                result_id=result.result_id,
                result_hash=result.content_hash,
                event_type=event_type,
                evaluated_at=recorded_at,
            )
            if trusted_owner is None:
                raise GovernedOptimizationUnavailable(
                    "Portfolio lifecycle authorization is unavailable"
                )
            if trusted_owner != owner_attestation:
                raise ValueError("Portfolio lifecycle authorization is not authoritative")
        else:
            raise ValueError("lifecycle append use case only accepts governed transitions")
        event = create_optimization_lifecycle_event(
            result=result,
            previous_events=previous_events,
            event_type=event_type,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            reason_codes=reason_codes,
            promotion_attestation=promotion_attestation,
            owner_attestation=owner_attestation,
        )
        return self._repository.append_lifecycle_event(event)


class RunGovernedOptimizationResearchUseCase:
    """Assemble, assess, compare and persist without execution side effects."""

    def __init__(
        self,
        *,
        assembler: AssembleGovernedOptimizationProblemUseCase,
        engine: GovernedOptimizationEngineProtocol,
        repository: GovernedOptimizationLedgerRepository,
        input_receipt_provider: GovernedOptimizationInputReceiptProvider,
        promotion_provider: ExactPromotionProvider,
    ) -> None:
        self._assembler = assembler
        self._engine = engine
        self._repository = repository
        self._input_receipt_provider = input_receipt_provider
        self._promotion_provider = promotion_provider

    def execute(
        self,
        *,
        command: AssembleGovernedOptimizationCommand,
        run_key: str,
        run_version: str,
    ) -> GovernedOptimizationRunBundle:
        """Run only after every exact input has assembled successfully."""

        if not (
            self._repository.unit_of_work_key
            == self._input_receipt_provider.unit_of_work_key
            == self._promotion_provider.unit_of_work_key
        ):
            raise GovernedOptimizationUnavailable(
                "receipt, Promotion and result providers do not share one locked unit of work"
            )
        with self._repository.atomic():
            return self._execute_inside_unit_of_work(
                command=command,
                run_key=run_key,
                run_version=run_version,
            )

    def _execute_inside_unit_of_work(
        self,
        *,
        command: AssembleGovernedOptimizationCommand,
        run_key: str,
        run_version: str,
    ) -> GovernedOptimizationRunBundle:
        """Re-read the receipt immediately before the atomic result append."""

        assembly = self._assembler.execute(command)
        assessment = assess_optimization_problem(
            assembly.problem,
            evaluated_at=command.created_at,
        )
        evaluations: tuple[CandidateEvaluation, ...] = ()
        if assessment.ready_for_solver:
            current_output = self._engine.current_configuration_baseline(assembly.problem)
            if (
                current_output.weights != assembly.current_configuration.weights
                or current_output.cash_weight != assembly.current_configuration.cash_weight
            ):
                raise ValueError("engine current baseline rewrites the canonical configuration")
            evaluations = (
                evaluate_solver_output(assembly.problem, current_output),
                evaluate_solver_output(
                    assembly.problem,
                    self._engine.equal_weight_baseline(assembly.problem),
                ),
                evaluate_solver_output(
                    assembly.problem,
                    self._engine.asset_risk_parity_baseline(assembly.problem),
                ),
                evaluate_solver_output(
                    assembly.problem,
                    self._engine.solve_candidate(assembly.problem),
                ),
            )
        blockers = tuple(
            (f"optimization_problem.{item.code.value}", item.detail) for item in assessment.blockers
        )
        result = GovernedOptimizationResearchResult.create(
            run_key=run_key,
            run_version=run_version,
            assembly_hash=assembly.content_hash,
            problem_id=assembly.problem.problem_id,
            problem_hash=assembly.problem.content_hash,
            input_set_id=assembly.input_set_id,
            input_set_hash=assembly.input_set_hash,
            input_receipt_id=assembly.input_receipt_id,
            input_receipt_hash=assembly.input_receipt_hash,
            input_receipt_schema_version=RECEIPT_VERSION,
            candidate_evaluations=evaluations,
            problem_blockers=blockers,
            evaluated_at=command.created_at,
            valid_until=command.valid_until,
        )
        bundle = GovernedOptimizationRunBundle(
            result=result,
            lifecycle_root=create_optimization_lifecycle_root(result),
        )
        trusted_receipt = self._input_receipt_provider.get_exact(
            input_set_id=command.input_set_id,
            evaluated_at=command.created_at,
        )
        if trusted_receipt is None:
            raise GovernedOptimizationUnavailable(
                "canonical governed input receipt disappeared before result persistence"
            )
        if (
            trusted_receipt.receipt_id != assembly.input_receipt_id
            or trusted_receipt.content_hash != assembly.input_receipt_hash
            or trusted_receipt.input_set != assembly.problem.governed_input_set
            or trusted_receipt.input_set.content_hash != assembly.input_set_hash
        ):
            raise ValueError("canonical governed input receipt changed before result persistence")
        _validate_exact_promotions(
            input_set=trusted_receipt.input_set,
            provider=self._promotion_provider,
            evaluated_at=command.created_at,
        )
        return self._repository.append_bundle(bundle)


_PayloadT = TypeVar("_PayloadT")


def _payload(
    payloads: dict[OptimizationInputKind, GovernedOptimizationPayload],
    kind: OptimizationInputKind,
    expected_type: type[_PayloadT],
) -> _PayloadT:
    candidate = payloads[kind]
    if type(candidate) is not expected_type:
        raise ValueError(f"{kind.value} typed payload mismatch")
    return cast(_PayloadT, candidate)


def _validate_snapshot_binding(
    command: AssembleGovernedOptimizationCommand,
    input_set: GovernedOptimizationInputSet,
) -> None:
    if (
        input_set.portfolio_snapshot_id != command.canonical_snapshot.snapshot_id
        or input_set.portfolio_snapshot_hash != command.canonical_snapshot.content_hash
    ):
        raise ValueError("governed input set does not bind the canonical snapshot")


def _validate_macro_artifact(
    command: AssembleGovernedOptimizationCommand,
    input_set: GovernedOptimizationInputSet,
    payload: MacroExposurePayload,
) -> None:
    promotions = {item.capability_key: item for item in input_set.promotions}
    r3 = promotions["r3"]
    r4 = promotions["r4"]
    exposure_version = command.macro_exposure_version
    covariance_version = command.macro_factor_covariance
    if (
        exposure_version.version_id != r4.artifact_id
        or exposure_version.promotion_decision_id != r4.decision_id
        or exposure_version.promoted_factor_version != r3.artifact_version
    ):
        raise ValueError("macro exposure does not match exact R3/R4 promotion evidence")
    bindings = {item.kind: item for item in input_set.owner_bindings}
    exposure_binding = bindings[OptimizationInputKind.MACRO_EXPOSURE]
    covariance_binding = bindings[OptimizationInputKind.ASSET_COVARIANCE]
    if (
        exposure_version.pit_manifest_id != exposure_binding.pit_manifest_id
        or covariance_version.pit_manifest_id != covariance_binding.pit_manifest_id
    ):
        raise ValueError("macro exposure/covariance PIT manifest mismatch")
    exposure_values = tuple(
        sorted(
            (
                exposure.asset_code,
                beta.factor_code,
                beta.beta,
            )
            for exposure in exposure_version.exposures
            for beta in exposure.betas
        )
    )
    payload_values = tuple(
        (item.asset_code, item.factor_code, item.value) for item in payload.exposures
    )
    if exposure_values != payload_values:
        raise ValueError("macro exposure numerical payload mismatch")
    if (
        covariance_version.factor_codes != payload.factor_codes
        or covariance_version.values != payload.factor_covariance_values
    ):
        raise ValueError("macro factor covariance numerical payload mismatch")
    if (
        exposure_version.observed_at > command.created_at
        or covariance_version.observed_at > command.created_at
        or exposure_version.valid_until <= command.created_at
        or covariance_version.valid_until <= command.created_at
    ):
        raise ValueError("macro numerical evidence is not current")


def _validate_exact_promotions(
    *,
    input_set: GovernedOptimizationInputSet,
    provider: ExactPromotionProvider,
    evaluated_at: datetime,
) -> None:
    """Re-read each Research decision and reject stale self-attestation."""

    if input_set.content_hash != governed_input_set_hash(input_set):
        raise ValueError("canonical governed input set content hash mismatch")
    for claimed in input_set.promotions:
        trusted = provider.get_exact(
            capability_key=claimed.capability_key,
            decision_id=claimed.decision_id,
            evaluated_at=evaluated_at,
        )
        if trusted is None:
            raise GovernedOptimizationUnavailable(
                "exact Research promotion evidence is unavailable"
            )
        if trusted != claimed:
            raise ValueError("exact Research promotion evidence is substituted")
        if trusted.attestation_hash != exact_promotion_attestation_hash(trusted):
            raise ValueError("exact Research promotion evidence hash mismatch")
        if (
            trusted.owner != "research"
            or trusted.approved_at > evaluated_at
            or trusted.valid_until <= evaluated_at
            or trusted.retired_at is not None
        ):
            raise ValueError("exact Research promotion is not active")


def _validate_row_level_pit(
    *,
    input_set: GovernedOptimizationInputSet,
    trading: TradingConstraintsPayload,
    drawdown: DrawdownRiskBudgetPayload,
    assembled_at: datetime,
) -> None:
    """Recheck nested market and path clocks at every research run."""

    bindings = {item.kind: item for item in input_set.owner_bindings}
    trading_cutoff = bindings[OptimizationInputKind.TRADING_CONSTRAINTS].knowledge_as_of
    for rule in trading.constraints:
        if (
            rule.available_at > trading_cutoff
            or rule.available_at > assembled_at
            or rule.valid_until <= assembled_at
        ):
            raise ValueError("market constraint row is unavailable at assembly time")
    drawdown_cutoff = bindings[OptimizationInputKind.DRAWDOWN_RISK_BUDGET].knowledge_as_of
    if any(
        observation.period_end > drawdown_cutoff or observation.period_end > assembled_at
        for observation in drawdown.observations
    ):
        raise ValueError("drawdown path observation exceeds the assembly PIT cutoff")


def _effective_membership_bounds(
    *,
    minimum_weight: Decimal,
    maximum_weight: Decimal,
    current_weight: Decimal,
    can_buy: bool,
    can_sell: bool,
    retain_if_held: bool,
) -> tuple[Decimal, Decimal]:
    """Convert Published buy/sell/retention rights into hard weight bounds."""

    if current_weight > 0 and not (can_sell or retain_if_held):
        raise ValueError("held asset lacks a governed sell or retention right")
    lower = minimum_weight if can_sell else max(minimum_weight, current_weight)
    upper = maximum_weight if can_buy else min(maximum_weight, current_weight)
    if lower > upper:
        raise ValueError("Published membership rights conflict with position bounds")
    return lower, upper


def _merge_membership_restriction(
    *,
    explicit: ManualRestriction,
    can_buy: bool,
    can_sell: bool,
) -> ManualRestriction:
    """Combine manual and Published rights without weakening either source."""

    membership = ManualRestriction.NONE
    if not can_buy and not can_sell:
        membership = ManualRestriction.FIXED
    elif not can_buy:
        membership = ManualRestriction.NO_BUY
    elif not can_sell:
        membership = ManualRestriction.NO_SELL
    if explicit is ManualRestriction.FIXED or membership is ManualRestriction.FIXED:
        return ManualRestriction.FIXED
    if explicit is ManualRestriction.NONE:
        return membership
    if membership is ManualRestriction.NONE or membership is explicit:
        return explicit
    return ManualRestriction.FIXED


def governed_optimization_assembly_hash(
    assembly: GovernedOptimizationAssembly,
) -> str:
    """Recompute the trusted assembly digest."""

    return _assembly_hash_values(
        input_receipt_id=assembly.input_receipt_id,
        input_receipt_hash=assembly.input_receipt_hash,
        input_set_id=assembly.input_set_id,
        input_set_hash=assembly.input_set_hash,
        problem_hash=assembly.problem.content_hash,
        current_configuration_hash=assembly.current_configuration.content_hash,
        assembled_at=assembly.assembled_at,
    )


def _assembly_hash_values(
    *,
    input_receipt_id: str,
    input_receipt_hash: str,
    input_set_id: str,
    input_set_hash: str,
    problem_hash: str,
    current_configuration_hash: str,
    assembled_at: datetime,
) -> str:
    return hash_components(
        "governed-optimization-assembly.v2",
        input_receipt_id,
        input_receipt_hash,
        input_set_id,
        input_set_hash,
        problem_hash,
        current_configuration_hash,
        utc_text(assembled_at),
        "research_only",
        "must_not_execute",
        "must_not_use_for_decision",
    )


__all__ = [
    "AssembleGovernedOptimizationCommand",
    "AssembleGovernedOptimizationProblemUseCase",
    "AppendGovernedOptimizationLifecycleEventUseCase",
    "CanonicalGovernedOptimizationInputSetProvider",
    "CanonicalGovernedOptimizationOwnerGraph",
    "ExactCanonicalPortfolioSnapshotProvider",
    "ExactGovernedOptimizationOwnerGraphProvider",
    "ExactInvestableUniverseProvider",
    "ExactPromotionProvider",
    "ExactPortfolioLifecycleAuthorizationProvider",
    "GovernedOptimizationAssembly",
    "GovernedOptimizationEngineProtocol",
    "GovernedOptimizationLedgerRepository",
    "GovernedOptimizationLifecycleRepository",
    "GovernedOptimizationInputSetProvider",
    "GovernedOptimizationInputReceiptProvider",
    "GovernedOptimizationRegistrationClock",
    "GovernedOptimizationRunBundle",
    "GovernedOptimizationUnavailable",
    "RegisterGovernedOptimizationInputReceiptCommand",
    "RegisterGovernedOptimizationInputReceiptUseCase",
    "RunGovernedOptimizationResearchUseCase",
    "governed_optimization_assembly_hash",
]
