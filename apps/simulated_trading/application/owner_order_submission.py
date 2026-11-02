"""Preview and explicitly confirm one source-qualified local simulated order."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, cast

from apps.simulated_trading.application.execution_settlement_uow import (
    PreparedSimulatedTrade,
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
    _require_aware_clock,
)
from apps.simulated_trading.application.manual_trade_execution import (
    CurrentReferenceManualIdentityReader,
    ManualSimulatedTradeRequest,
)
from apps.simulated_trading.application.order_reservation import (
    SimulatedOrderPlanPreparer,
    SimulatedOrderReservationRepository,
    _check_result,
    reservation_request_from_intent,
)
from apps.simulated_trading.application.order_submission_market import (
    LocalOrderSubmissionMarketReader,
    LocalSimulatedOrderSubmissionGuard,
    OrderSubmissionAccountState,
    OwnerOrderStoredReadback,
    SimulatedOrderSubmissionGuard,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import SettlementExecutionPlanV2
from apps.simulated_trading.domain.execution_settlement_primitives import (
    _hash_payload,
    _require_token,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationResult,
    reserve_order,
)


class RetainedOrderSubmissionMarket(LocalOrderSubmissionMarketReader, Protocol):
    """Keep an explicit source capture portable through a signed preview."""

    def export_retained_source(self) -> dict[str, object]:
        """Return raw source/provenance for server-signed, scoped recovery only."""


class OwnerOrderSubmissionMarketFactory(Protocol):
    """Capture explicitly for previews, restore without network for confirmation."""

    def capture(self, *, intent: SimulatedTradeIntent) -> RetainedOrderSubmissionMarket:
        """Capture an exact configured source after current account authorization."""

    def restore(self, *, payload: dict[str, object]) -> RetainedOrderSubmissionMarket:
        """Revalidate a server-signed retained capture and current policy binding."""


class OwnerOrderSubmissionRepository(SimulatedOrderReservationRepository, Protocol):
    """Use the ordinary locked reservation ledger without a second order store."""

    def require_owned_active_account(self, *, account_id: int, user_id: int) -> None:
        """Authorize a simulated account before source work."""

    def read_submission_state(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        clock: SimulatedTradeExecutionClock,
    ) -> OrderSubmissionAccountState:
        """Read an exact projection without releasing or reserving any resources."""

    def get_owned_order_id(self, *, intent: SimulatedTradeIntent) -> int:
        """Return the stored order ID after a successful commitment or replay."""

    def read_owned_order_by_key(
        self, *, account_id: int, user_id: int, order_key: str
    ) -> OwnerOrderStoredReadback:
        """Read an exact owner order without requiring current financial evidence."""


class GuardedOrderSubmissionRepositoryFactory(Protocol):
    """Create a writer whose source guard runs inside the ordinary account lock."""

    def build(self, *, guard: SimulatedOrderSubmissionGuard) -> OwnerOrderSubmissionRepository:
        """Return a writer on the same database alias as the preview reader."""


@dataclass(frozen=True, slots=True)
class OwnerOrderPreviewBinding:
    """The exact order and immutable configuration a user has reviewed."""

    intent: SimulatedTradeIntent
    fee_budget: Decimal | None
    fee_policy_hash: str
    settlement_bundle_hash: str
    identity_occurrence: str
    identity_binding_hash: str
    market_source_hash: str
    expires_at: datetime
    retained_source: dict[str, object]


class OwnerOrderPreviewCodec(Protocol):
    """Authenticate server-created previews without trusting submitted source facts."""

    def seal(self, binding: OwnerOrderPreviewBinding) -> str:
        """Sign the complete reviewed intent and retained evidence."""

    def open(self, token: str) -> OwnerOrderPreviewBinding:
        """Verify authentication before decoding and narrowing every field."""


@dataclass(frozen=True, slots=True)
class OwnerOrderPreview:
    """A hypothetical reservation; no trade, hold or release has been persisted."""

    token: str
    result: OrderReservationResult
    market_receipt: dict[str, object]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OwnerOrderSubmissionResult:
    """One durable ordinary reservation and its verified numeric identity."""

    order_id: int
    result: OrderReservationResult


class OwnerOrderSubmissionUseCase:
    """Keep previews read-only and confirmation/recovery on the ordinary writer."""

    def __init__(
        self,
        *,
        identity_reader: CurrentReferenceManualIdentityReader,
        preparer: SimulatedOrderPlanPreparer,
        repository: OwnerOrderSubmissionRepository,
        repository_factory: GuardedOrderSubmissionRepositoryFactory,
        market_factory: OwnerOrderSubmissionMarketFactory,
        codec: OwnerOrderPreviewCodec,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Inject owner ports; construction performs no source reads or writes."""
        self._identities = identity_reader
        self._preparer = preparer
        self._repository = repository
        self._writers = repository_factory
        self._markets = market_factory
        self._codec = codec
        self._clock = clock

    def preview(
        self, request: ManualSimulatedTradeRequest, *, fee_budget: Decimal | None
    ) -> OwnerOrderPreview:
        """Explicitly capture market data and preview an exact local reservation."""
        if type(request) is not ManualSimulatedTradeRequest:
            raise SimulatedTradeExecutionInputError("必须提供精确订单草稿")
        request.__post_init__()
        self._repository.require_owned_active_account(
            account_id=request.account_id, user_id=request.user_id
        )
        intent, _ = self._resolve(request)
        reservation_request_from_intent(intent, fee_budget=fee_budget)
        market = self._markets.capture(intent=intent)
        # Capture completion must precede the final common knowledge cutoff.
        intent, identity = self._resolve(request)
        prepared = self._preparer.prepare(intent, as_of=identity.selection.selected_at)
        fee_policy = _require_prepared(prepared, intent)
        state = self._repository.read_submission_state(plan=prepared.plan, clock=self._clock)
        receipt = LocalSimulatedOrderSubmissionGuard(
            market_reader=market
        ).validate_locked_submission(
            plan=prepared.plan,
            execution_bundle=prepared.execution_bundle,
            book=state.book,
            total_quantity=state.total_quantity,
            as_of=state.read_at,
        )
        result = reserve_order(
            state.book,
            reservation_request_from_intent(intent, fee_budget=fee_budget),
            fee_policy,
            reserved_at=state.read_at,
        )
        expires_at = _require_aware_clock(
            datetime.fromisoformat(cast(str, receipt["valid_until"]))
        ).astimezone(UTC)
        binding = OwnerOrderPreviewBinding(
            intent=intent,
            fee_budget=fee_budget,
            fee_policy_hash=prepared.plan.fee_policy_v2.content_hash,
            settlement_bundle_hash=prepared.execution_bundle.content_hash,
            identity_occurrence=str(identity.source_occurrence_id),
            identity_binding_hash=identity_binding_hash(identity),
            market_source_hash=cast(str, receipt["market_source_hash"]),
            expires_at=expires_at,
            retained_source=market.export_retained_source(),
        )
        return OwnerOrderPreview(
            self._codec.seal(binding),
            result,
            receipt,
            expires_at,
        )

    def recover(self, *, account_id: int, user_id: int, token: str) -> OwnerOrderSubmissionResult:
        """Read only the exact original reservation, without market refresh or mutation."""
        binding = self._codec.open(token)
        intent = binding.intent
        if (intent.account_id, intent.user_id) != (account_id, user_id):
            raise SimulatedTradeExecutionInputError("原预览不属于当前账户和用户")
        previous = self._repository.find_idempotent_reservation(
            intent=intent, fee_budget=binding.fee_budget
        )
        if previous is None:
            raise SimulatedTradeExecutionResultUnknown(
                "当前未找到原预留，请保留原预览继续核对，勿换键新发"
            )
        return self._committed(
            intent,
            _check_result(
                previous,
                reservation_request_from_intent(intent, fee_budget=binding.fee_budget),
                committed=False,
            ),
        )

    def confirm(
        self,
        *,
        account_id: int,
        user_id: int,
        token: str,
        confirmed: bool,
        expected_key: str | None = None,
    ) -> OwnerOrderSubmissionResult:
        """Recover the original order first; new commits recheck current evidence."""
        if confirmed is not True:
            raise SimulatedTradeExecutionInputError("必须明确确认原预览")
        binding = self._codec.open(token)
        intent = binding.intent
        if (intent.account_id, intent.user_id) != (account_id, user_id):
            raise SimulatedTradeExecutionInputError("预览不属于当前账户和用户")
        if expected_key is not None and intent.idempotency_key != expected_key:
            raise SimulatedTradeExecutionInputError("订单定位与原预览不一致")
        previous = self._repository.find_idempotent_reservation(
            intent=intent, fee_budget=binding.fee_budget
        )
        if previous is not None:
            return self._committed(
                intent,
                _check_result(
                    previous,
                    reservation_request_from_intent(intent, fee_budget=binding.fee_budget),
                    committed=False,
                ),
            )
        as_of = _require_aware_clock(self._clock.now())
        if as_of >= binding.expires_at:
            raise SimulatedTradeExecutionBlocked(
                "原预览已过确认截止，请重新预览", code="SIMULATED_ORDER_PREVIEW_EXPIRED"
            )
        prepared = self._preparer.prepare(intent, as_of=as_of)
        _require_prepared(prepared, intent)
        if (
            prepared.plan.fee_policy_v2.content_hash != binding.fee_policy_hash
            or prepared.execution_bundle.content_hash != binding.settlement_bundle_hash
            or type(prepared.plan.identity_evidence) is not ExecutionInstrumentIdentityEvidenceV2
            or str(prepared.plan.identity_evidence.source_occurrence_id)
            != binding.identity_occurrence
            or identity_binding_hash(prepared.plan.identity_evidence)
            != binding.identity_binding_hash
        ):
            raise SimulatedTradeExecutionBlocked("订单配置或证券来源已变化，请重新预览")
        market = self._markets.restore(payload=binding.retained_source)
        writer = self._writers.build(
            guard=LocalSimulatedOrderSubmissionGuard(
                market_reader=market,
                expected_market_source_hash=binding.market_source_hash,
                confirmation_expires_at=binding.expires_at,
            )
        )
        result = writer.reserve_order(
            plan=prepared.plan,
            execution_bundle=prepared.execution_bundle,
            fee_budget=binding.fee_budget,
            clock=self._clock,
        )
        return self._committed(
            intent,
            _check_result(
                result,
                reservation_request_from_intent(intent, fee_budget=binding.fee_budget),
                committed=True,
            ),
        )

    def readback(
        self, *, account_id: int, user_id: int, order_key: str
    ) -> OwnerOrderStoredReadback:
        """Read the exact non-secret locator even after preview-source expiry."""
        if (
            type(account_id) is not int
            or account_id <= 0
            or type(user_id) is not int
            or user_id <= 0
        ):
            raise SimulatedTradeExecutionInputError("订单账户与用户标识无效")
        try:
            _require_token(order_key, "order_key", max_length=128)
        except ValueError as error:
            raise SimulatedTradeExecutionInputError("订单定位无效") from error
        result = self._repository.read_owned_order_by_key(
            account_id=account_id, user_id=user_id, order_key=order_key
        )
        if type(result) is not OwnerOrderStoredReadback:
            raise SimulatedTradeExecutionBlocked("原订单回读合同不可核验")
        result.reservation.__post_init__()
        if (
            result.reservation.identity.account_id,
            result.reservation.identity.idempotency_key,
        ) != (account_id, order_key):
            raise SimulatedTradeExecutionBlocked("原订单回读范围不一致")
        return result

    def _resolve(
        self, request: ManualSimulatedTradeRequest
    ) -> tuple[SimulatedTradeIntent, ExecutionInstrumentIdentityEvidenceV2]:
        cutoff = _require_aware_clock(self._clock.now())
        identity = self._identities.resolve_current_reference_identity(
            asset_code=request.asset_code, as_of=cutoff
        )
        if type(identity) is not ExecutionInstrumentIdentityEvidenceV2:
            raise SimulatedTradeExecutionBlocked("缺少精确证券身份来源")
        identity.__post_init__()
        if identity.asset_code != request.asset_code or identity.selection.selected_at != cutoff:
            raise SimulatedTradeExecutionBlocked("证券身份与当前草稿不一致")
        return (
            SimulatedTradeIntent(
                account_id=request.account_id,
                user_id=request.user_id,
                idempotency_key=request.idempotency_key,
                side=request.side,
                security_id=identity.security_id,
                asset_code=request.asset_code,
                asset_name=request.asset_name,
                asset_type=request.asset_type,
                market=identity.rule_market,
                board=identity.board,
                quantity=request.quantity,
                price=request.price,
                reason=request.reason,
                signal_id=request.signal_id,
            ),
            identity,
        )

    def _committed(
        self, intent: SimulatedTradeIntent, result: OrderReservationResult
    ) -> OwnerOrderSubmissionResult:
        try:
            order_id = self._repository.get_owned_order_id(intent=intent)
        except (SimulatedTradeExecutionBlocked, SimulatedTradeAccountScopeUnavailable) as error:
            raise SimulatedTradeExecutionResultUnknown("请先回读原订单，勿重新提交新单") from error
        return OwnerOrderSubmissionResult(order_id, result)


def identity_binding_hash(identity: ExecutionInstrumentIdentityEvidenceV2) -> str:
    """Bind identity source and selector while allowing a later genuine selection time."""
    identity.__post_init__()
    selection = identity.selection.to_payload()
    selection.pop("selected_at")
    return _hash_payload(
        {
            "source": identity.source_evidence.to_payload(),
            "selection": selection,
            "occurrence": str(identity.source_occurrence_id),
            "reference_response_completed_at": identity.reference_response_completed_at.isoformat(),
        }
    )


def _require_prepared(
    prepared: PreparedSimulatedTrade, intent: SimulatedTradeIntent
) -> SimulatedFeePolicyV2:
    if type(prepared) is not PreparedSimulatedTrade or prepared.plan.intent != intent:
        raise SimulatedTradeExecutionBlocked("预留计划与精确订单草稿不一致")
    fee_policy = prepared.plan.fee_policy_v2
    if type(fee_policy) is not SimulatedFeePolicyV2:
        raise SimulatedTradeExecutionBlocked("模拟订单必须使用完整的 V2 费用政策")
    fee_policy.__post_init__()
    return fee_policy
