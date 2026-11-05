"""Bind a user-selected plan line to the existing explicit simulated-order flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from apps.portfolio.application.transition_plan_lifecycle import (
    GetExactTransitionPlanRevisionQuery,
    TransitionPlanOrderExecutionBinding,
    TransitionPlanRevision,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.manual_trade_execution import (
    ManualSimulatedTradeRequest,
    UnsupportedManualInstrument,
)
from apps.simulated_trading.application.owner_order_submission import (
    OwnerOrderPreview,
    OwnerOrderSubmissionUseCase,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedTradeSide,
    _require_token,
)
from apps.simulated_trading.domain.transition_plan_execution import (
    derive_plan_order_idempotency_key,
)


class ExactTransitionPlanRevisionReader(Protocol):
    """Read an owner-authorized plan only by its full immutable identity."""

    def execute(self, query: GetExactTransitionPlanRevisionQuery) -> TransitionPlanRevision | None:
        """Return the exact revision or None without resolving a latest alias."""


class TransitionPlanLockedActionGuard(Protocol):
    """Revalidate plan identity and qualification inside the account transaction."""

    def validate_locked_action(
        self,
        *,
        binding: TransitionPlanOrderExecutionBinding,
        account_id: int,
        owner_user_id: int,
        as_of: datetime,
    ) -> TransitionPlanRevision:
        """Return the exact current-family revision or raise on any changed binding."""


@dataclass(frozen=True, slots=True)
class PlanOrderPreviewCommand:
    """One explicit user request to preview a quantity from one exact plan order."""

    actor_user_id: int
    account_id: int
    plan_id: str
    plan_version: int
    expected_revision_hash: str
    order_ordinal: int
    expected_order_content_hash: str
    expected_plan_order_binding_id: str
    action_attempt_key: str
    quantity: Decimal
    price: Decimal
    reason: str
    signal_id: int | None = None

    def __post_init__(self) -> None:
        """Reject coercion, foreign scope, fractional shares, and malformed exact pins."""

        for name in ("actor_user_id", "account_id", "plan_version"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise SimulatedTradeExecutionInputError(f"{name} must be a positive integer")
        if type(self.order_ordinal) is not int or self.order_ordinal < 0:
            raise SimulatedTradeExecutionInputError("order_ordinal must be nonnegative")
        for name in (
            "plan_id",
            "expected_order_content_hash",
            "expected_plan_order_binding_id",
            "action_attempt_key",
        ):
            try:
                _require_token(getattr(self, name), name, max_length=128)
            except (TypeError, ValueError) as error:
                raise SimulatedTradeExecutionInputError(f"{name} is invalid") from error
        for name in ("expected_revision_hash",):
            value = getattr(self, name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise SimulatedTradeExecutionInputError(f"{name} must be SHA-256")
        if (
            type(self.quantity) is not Decimal
            or not self.quantity.is_finite()
            or self.quantity <= 0
            or self.quantity != self.quantity.to_integral_value()
        ):
            raise SimulatedTradeExecutionInputError("plan action quantity must be whole shares")
        if type(self.price) is not Decimal or not self.price.is_finite() or self.price <= 0:
            raise SimulatedTradeExecutionInputError("plan action price must be a positive Decimal")
        if type(self.reason) is not str or len(self.reason) > 200:
            raise SimulatedTradeExecutionInputError("reason must be text of at most 200 chars")
        if self.signal_id is not None and type(self.signal_id) is not int:
            raise SimulatedTradeExecutionInputError("signal_id must be an integer or None")


@dataclass(frozen=True, slots=True)
class PlanOrderPreview:
    """The exact plan/action identity and ordinary read-only reservation preview."""

    binding: TransitionPlanOrderExecutionBinding
    revision_recorded_at: datetime
    preview: OwnerOrderPreview


class PreviewTransitionPlanOrderUseCase:
    """Re-read one approved plan line and delegate preview to the ordinary Owner flow."""

    def __init__(
        self,
        *,
        revision_reader: ExactTransitionPlanRevisionReader,
        order_submission: OwnerOrderSubmissionUseCase,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Inject Portfolio's exact-reader facade and the existing Owner submission use case."""

        self._revisions = revision_reader
        self._orders = order_submission
        self._clock = clock

    def execute(
        self, command: PlanOrderPreviewCommand, *, fee_budget: Decimal | None = None
    ) -> PlanOrderPreview:
        """Create a normal source-qualified preview without reserving or executing an order."""

        if type(command) is not PlanOrderPreviewCommand:
            raise SimulatedTradeExecutionInputError("必须提供精确计划订单预览请求")
        command.__post_init__()
        query = GetExactTransitionPlanRevisionQuery(
            actor_user_id=command.actor_user_id,
            account_id=command.account_id,
            plan_id=command.plan_id,
            version=command.plan_version,
            expected_revision_hash=command.expected_revision_hash,
        )
        revision = self._revisions.execute(query)
        if type(revision) is not TransitionPlanRevision:
            raise SimulatedTradeExecutionBlocked(
                "指定计划版本不可用",
                code="TRANSITION_PLAN_REVISION_UNAVAILABLE",
            )
        revision.__post_init__()
        identity = revision.identity
        as_of = self._clock.now()
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise SimulatedTradeExecutionBlocked("执行计划时钟不可核验")
        if identity.owner_user_id != command.actor_user_id:
            raise SimulatedTradeExecutionInputError("普通用户只能预览本人账户的计划")
        if identity.account_id != command.account_id:
            raise SimulatedTradeExecutionInputError("计划账户与当前账户不一致")
        if as_of < identity.recorded_at:
            raise SimulatedTradeExecutionBlocked(
                "计划版本尚未生效",
                code="TRANSITION_PLAN_NOT_YET_KNOWN",
            )
        if as_of >= identity.valid_until:
            raise SimulatedTradeExecutionBlocked(
                "计划已过期，请重新审核",
                code="TRANSITION_PLAN_EXPIRED",
            )
        if revision.plan.status in {"CANCELLED", "REJECTED"}:
            raise SimulatedTradeExecutionBlocked(
                "计划已撤回或拒绝，不能再关联新订单",
                code="TRANSITION_PLAN_NOT_ACTIVE",
            )
        if command.order_ordinal >= len(revision.orders):
            raise SimulatedTradeExecutionInputError("计划订单序号不存在")
        order = revision.orders[command.order_ordinal]
        if (
            order.ordinal != command.order_ordinal
            or order.order_content_hash != command.expected_order_content_hash
            or order.plan_order_binding_id != command.expected_plan_order_binding_id
            or order.approved_quantity <= 0
            or command.quantity > Decimal(order.approved_quantity)
        ):
            raise SimulatedTradeExecutionBlocked(
                "计划订单内容或批准数量已变化",
                code="TRANSITION_PLAN_ORDER_BINDING_MISMATCH",
            )
        typed_binding = order.to_execution_binding(
            identity,
            owner_user_id=command.actor_user_id,
            action_attempt_key=command.action_attempt_key,
        )
        if command.price <= 0 or (
            typed_binding.approved_limit_price is not None
            and command.price != typed_binding.approved_limit_price
        ):
            raise SimulatedTradeExecutionInputError("订单价格与计划限价授权不一致")
        try:
            manual_request = ManualSimulatedTradeRequest(
                account_id=command.account_id,
                user_id=command.actor_user_id,
                idempotency_key=derive_plan_order_idempotency_key(typed_binding.content_hash),
                asset_code=typed_binding.asset_code,
                asset_name=typed_binding.asset_code,
                asset_type=typed_binding.asset_type,
                side=SimulatedTradeSide(typed_binding.side),
                quantity=command.quantity,
                price=command.price,
                reason=command.reason,
                signal_id=command.signal_id,
            )
        except UnsupportedManualInstrument as error:
            raise SimulatedTradeExecutionBlocked(
                "当前模拟下单服务不支持此计划资产类型，请保留人工清单处理",
                code="TRANSITION_PLAN_ASSET_TYPE_UNSUPPORTED",
            ) from error
        preview = self._orders.preview(
            manual_request,
            fee_budget=fee_budget,
            transition_plan_binding=typed_binding,
            transition_plan_recorded_at=identity.recorded_at,
        )
        return PlanOrderPreview(
            binding=typed_binding,
            revision_recorded_at=identity.recorded_at,
            preview=preview,
        )
