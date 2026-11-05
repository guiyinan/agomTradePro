"""Owner-scoped, read-only reconciliation of plan orders and ledger resources."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Literal, Protocol

from apps.portfolio.application.transition_plan_lifecycle import (
    GetExactTransitionPlanRevisionQuery,
    TransitionPlanOrderBinding,
    TransitionPlanRevision,
    TransitionPlanRevisionIdentity,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    ActiveRebalanceReservation,
    RebalanceExactPositionBalance,
    RebalanceResourceSnapshot,
    RebalanceResourceSnapshotReader,
)
from apps.simulated_trading.application.transition_plan_execution import (
    ExactTransitionPlanRevisionReader,
)
from apps.simulated_trading.domain.transition_plan_execution import (
    PlanExecutionReservation,
    PlanOrderExecutionBinding,
    PlanOrderExecutionProgress,
    reconcile_plan_order_execution,
)


@dataclass(frozen=True, slots=True)
class PlanExecutionHistoryRead:
    """Complete or explicitly incomplete reservation/fill facts for one account."""

    account_id: int
    owner_user_id: int
    read_at: datetime
    reservations: tuple[PlanExecutionReservation, ...]
    complete: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require exact scope, source clocks, and typed durable facts."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be positive")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be positive")
        if type(self.read_at) is not datetime or self.read_at.tzinfo is None:
            raise ValueError("read_at must be timezone aware")
        if self.read_at.utcoffset() is None:
            raise ValueError("read_at must include a real UTC offset")
        if type(self.complete) is not bool:
            raise ValueError("complete must be explicit")
        if type(self.reservations) is not tuple or any(
            type(row) is not PlanExecutionReservation for row in self.reservations
        ):
            raise ValueError("reservations must be typed plan-execution facts")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code for code in self.reason_codes
        ):
            raise ValueError("reason_codes must be stable nonempty strings")


class PlanExecutionHistoryReader(Protocol):
    """Read reservation and receipt facts without mutating the simulated ledger."""

    def read_plan_history(
        self, *, account_id: int, owner_user_id: int, as_of: datetime
    ) -> PlanExecutionHistoryRead:
        """Return all visible plan-bound attempts or mark the read incomplete."""


class TransitionPlanFamilyHeadReader(Protocol):
    """Read the verified current immutable revision for an account and family."""

    def get_family_head(
        self, *, account_id: int, family_id: str, as_of: datetime
    ) -> TransitionPlanRevision | None:
        """Return a verified head without converting it into an execution grant."""


class SimulatedTradeExecutionClock(Protocol):
    """Provide the server clock used to scope a progress read."""

    def now(self) -> datetime:
        """Return one timezone-aware server instant."""


@dataclass(frozen=True, slots=True)
class PlanExecutionProgressQuery:
    """Read progress for one exact plan revision and account owner."""

    actor_user_id: int
    account_id: int
    plan_id: str
    plan_version: int
    expected_revision_hash: str

    def __post_init__(self) -> None:
        """Reject aliases and incomplete owner/revision selectors."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be positive")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be positive")
        if type(self.plan_id) is not str or not self.plan_id.strip():
            raise ValueError("plan_id must be nonempty")
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be positive")
        if (
            type(self.expected_revision_hash) is not str
            or len(self.expected_revision_hash) != 64
            or any(char not in "0123456789abcdef" for char in self.expected_revision_hash)
        ):
            raise ValueError("expected_revision_hash must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class PlanExecutionAccountReconciliation:
    """Exact cash, held resources, and position balances at one ledger read clock."""

    account_id: int
    owner_user_id: int
    read_at: datetime
    money_unit: str
    exact_cash: Decimal | None
    active_buy_cash_reserved: Decimal | None
    available_cash_after_holds: Decimal | None
    exact_balances_complete: bool
    exact_position_balances: tuple[RebalanceExactPositionBalance, ...]
    active_reservations: tuple[ActiveRebalanceReservation, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Preserve exact ledger units and never accept float balances."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be positive")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be positive")
        if type(self.read_at) is not datetime or self.read_at.tzinfo is None:
            raise ValueError("read_at must be aware")
        if type(self.money_unit) is not str or not self.money_unit.strip():
            raise ValueError("money_unit must be explicit")
        for value in (
            self.exact_cash,
            self.active_buy_cash_reserved,
            self.available_cash_after_holds,
        ):
            if value is not None and (
                type(value) is not Decimal or not value.is_finite() or value < 0
            ):
                raise ValueError("account reconciliation amounts must be Decimal or unknown")
        if type(self.exact_balances_complete) is not bool:
            raise ValueError("exact balance completeness must be explicit")
        if type(self.exact_position_balances) is not tuple or any(
            type(item) is not RebalanceExactPositionBalance for item in self.exact_position_balances
        ):
            raise ValueError("position balances must retain exact ledger values")
        if type(self.active_reservations) is not tuple or any(
            type(item) is not ActiveRebalanceReservation for item in self.active_reservations
        ):
            raise ValueError("active reservations must retain exact hold values")


@dataclass(frozen=True, slots=True)
class TransitionPlanExecutionProgress:
    """Exact revision, per-order attempts, and separately clocked account snapshot."""

    revision: TransitionPlanRevision
    read_at: datetime
    current_head: bool
    account: PlanExecutionAccountReconciliation | None
    resource_snapshot_read_at: datetime | None
    history_read_at: datetime
    orders: tuple[PlanOrderExecutionProgress, ...]
    read_status: Literal["complete", "partial", "blocked"]
    reason_codes: tuple[str, ...]


class GetTransitionPlanExecutionProgressUseCase:
    """Reconcile exact plan orders against immutable holds/fills and live resources."""

    def __init__(
        self,
        *,
        revision_reader: ExactTransitionPlanRevisionReader,
        family_head_reader: TransitionPlanFamilyHeadReader,
        history_reader: PlanExecutionHistoryReader,
        resource_reader: RebalanceResourceSnapshotReader,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Inject public Portfolio and existing simulated-ledger read ports."""

        self._revisions = revision_reader
        self._heads = family_head_reader
        self._history = history_reader
        self._resources = resource_reader
        self._clock = clock

    def execute(self, query: PlanExecutionProgressQuery) -> TransitionPlanExecutionProgress:
        """Return progress without creating orders, releasing holds, or posting fills."""

        if type(query) is not PlanExecutionProgressQuery:
            raise ValueError("an exact plan-execution progress query is required")
        query.__post_init__()
        selection_at = self._require_clock(self._clock.now())
        revision = self._revisions.execute(
            GetExactTransitionPlanRevisionQuery(
                actor_user_id=query.actor_user_id,
                account_id=query.account_id,
                plan_id=query.plan_id,
                version=query.plan_version,
                expected_revision_hash=query.expected_revision_hash,
            )
        )
        if type(revision) is not TransitionPlanRevision:
            raise ValueError("exact plan revision is not visible to this owner")
        revision.__post_init__()
        identity = revision.identity
        if identity.account_id != query.account_id or identity.recorded_at > selection_at:
            raise ValueError("exact plan revision is outside the current owner/read scope")
        read_only_actor = query.actor_user_id != identity.owner_user_id
        snapshot = self._resources.read_account_snapshot(
            account_id=query.account_id,
            user_id=identity.owner_user_id,
        )
        history_cutoff = self._require_clock(self._clock.now())
        history = self._history.read_plan_history(
            account_id=query.account_id,
            owner_user_id=identity.owner_user_id,
            as_of=history_cutoff,
        )
        history.__post_init__()
        read_at = self._require_clock(self._clock.now())
        history_complete = history.complete and history.read_at <= read_at
        history_reasons = history.reason_codes
        if history.read_at > read_at:
            history_reasons = (*history_reasons, "TRANSITION_PLAN_HISTORY_READ_AFTER_CUTOFF")
        head = self._heads.get_family_head(
            account_id=query.account_id,
            family_id=identity.family_id,
            as_of=read_at,
        )
        current_head = (
            type(head) is TransitionPlanRevision
            and head.identity.plan_id == identity.plan_id
            and head.identity.version == identity.version
            and head.identity.revision_hash == identity.revision_hash
        )
        revision_active = (
            current_head
            and read_at < identity.valid_until
            and revision.plan.status not in {"CANCELLED", "REJECTED"}
        )
        history_rows = tuple(
            item
            for item in history.reservations
            if item.binding.account_id == query.account_id
            and item.binding.owner_user_id == identity.owner_user_id
        )
        account, resource_reasons = self._account_reconciliation(
            snapshot=snapshot,
            identity=identity,
            money_unit=revision.basis.money_unit,
            read_cutoff=read_at,
        )
        orders = tuple(
            self._order_progress(
                identity=identity,
                order=order,
                reservations=history_rows,
                history_complete=history_complete,
                revision_active=revision_active,
                read_at=read_at,
            )
            for order in revision.orders
        )
        if read_only_actor:
            orders = tuple(self._read_only_progress(result) for result in orders)
        reasons = tuple(
            dict.fromkeys(
                (
                    *(("TRANSITION_PLAN_READ_ONLY_ACTOR",) if read_only_actor else ()),
                    *history_reasons,
                    *resource_reasons,
                    *(code for result in orders for code in result.reason_codes),
                )
            )
        )
        if (
            account is None
            or resource_reasons
            or not history_complete
            or any(result.outcome == "unknown" for result in orders)
        ):
            read_status: Literal["complete", "partial", "blocked"] = "partial"
        elif not revision_active or any(
            result.outcome in {"blocked", "successor_required"} for result in orders
        ):
            read_status = "blocked"
        else:
            read_status = "complete"
        return TransitionPlanExecutionProgress(
            revision=revision,
            read_at=read_at,
            current_head=current_head,
            account=account,
            resource_snapshot_read_at=(snapshot.read_at if snapshot is not None else None),
            history_read_at=history.read_at,
            orders=orders,
            read_status=read_status,
            reason_codes=reasons,
        )

    @staticmethod
    def _read_only_progress(result: PlanOrderExecutionProgress) -> PlanOrderExecutionProgress:
        """Keep reconciled facts visible while removing every order mutation capability."""

        return replace(
            result,
            can_preview=False,
            can_cancel=False,
            can_recover=False,
            reason_codes=tuple(
                dict.fromkeys((*result.reason_codes, "TRANSITION_PLAN_READ_ONLY_ACTOR"))
            ),
        )

    def _order_progress(
        self,
        *,
        identity: TransitionPlanRevisionIdentity,
        order: TransitionPlanOrderBinding,
        reservations: tuple[PlanExecutionReservation, ...],
        history_complete: bool,
        revision_active: bool,
        read_at: datetime,
    ) -> PlanOrderExecutionProgress:
        """Reconcile one immutable order with exact plan and same-security history."""

        if type(order) is not TransitionPlanOrderBinding:
            raise ValueError("revision contains an invalid order binding")
        current_candidates = tuple(
            item
            for item in reservations
            if item.binding.plan_id == identity.plan_id
            and item.binding.plan_version == identity.version
            and item.binding.revision_hash == identity.revision_hash
            and item.binding.order_ordinal == order.ordinal
        )
        current = tuple(
            item for item in current_candidates if self._binding_matches_order(item.binding, order)
        )
        related = tuple(
            item
            for item in reservations
            if item.binding.family_id == identity.family_id
            and not (
                item.binding.plan_id == identity.plan_id
                and item.binding.plan_version == identity.version
                and item.binding.revision_hash == identity.revision_hash
                and item.binding.order_ordinal == order.ordinal
            )
            and item.binding.asset_code == order.asset_code
            and item.binding.security_id == order.security_id
        )
        result = reconcile_plan_order_execution(
            revision_identity=identity,
            order=order,
            reservations=current,
            related_family_reservations=related,
            history_complete=history_complete and len(current) == len(current_candidates),
            revision_active=revision_active,
            as_of=read_at,
            predecessor_sells_settled=None,
        )
        if len(current) != len(current_candidates):
            return replace(
                result,
                reason_codes=tuple(
                    dict.fromkeys(
                        (*result.reason_codes, "TRANSITION_PLAN_EXECUTION_BINDING_MISMATCH")
                    )
                ),
            )
        return result

    @staticmethod
    def _binding_matches_order(
        binding: PlanOrderExecutionBinding, order: TransitionPlanOrderBinding
    ) -> bool:
        """Require durable execution history to match the immutable plan line."""

        return (
            binding.order_content_hash == order.order_content_hash
            and binding.plan_order_binding_id == order.plan_order_binding_id
            and binding.asset_code == order.asset_code
            and binding.security_id == order.security_id
            and binding.asset_type == order.asset_type
            and binding.classification_content_hash == order.classification_content_hash
            and binding.side == order.side
            and binding.approved_quantity == order.approved_quantity
            and binding.approved_limit_price == order.approved_limit_price
            and binding.quantity_unit == order.quantity_unit
            and binding.money_unit == order.money_unit
        )

    @staticmethod
    def _account_reconciliation(
        *,
        snapshot: RebalanceResourceSnapshot | None,
        identity: TransitionPlanRevisionIdentity,
        money_unit: str,
        read_cutoff: datetime,
    ) -> tuple[PlanExecutionAccountReconciliation | None, tuple[str, ...]]:
        """Compute cash after real active holds; retain all unknown balances."""

        if snapshot is None:
            return None, ("TRANSITION_PLAN_ACCOUNT_RESOURCE_SNAPSHOT_UNKNOWN",)
        if snapshot.read_at > read_cutoff:
            return None, ("TRANSITION_PLAN_ACCOUNT_RESOURCE_READ_CLOCK_INVALID",)
        if type(money_unit) is not str or not money_unit.strip():
            return None, ("TRANSITION_PLAN_MONEY_UNIT_UNKNOWN",)
        if (
            snapshot.account.account_id != identity.account_id
            or snapshot.owner_user_id != identity.owner_user_id
        ):
            return None, ("TRANSITION_PLAN_ACCOUNT_RESOURCE_SCOPE_MISMATCH",)
        buy_holds = tuple(
            row.remaining_cash for row in snapshot.active_reservations if row.side == "buy"
        )
        exact_reserved = _sum_exact(buy_holds)
        exact_cash = snapshot.exact_cash
        if exact_cash is not None and exact_cash >= exact_reserved:
            with localcontext() as context:
                context.prec = 80
                available_cash = exact_cash - exact_reserved
        else:
            available_cash = None
        reasons: list[str] = []
        if exact_cash is None:
            reasons.append("TRANSITION_PLAN_ACCOUNT_CASH_UNKNOWN")
        elif available_cash is None:
            reasons.append("TRANSITION_PLAN_ACTIVE_BUY_HOLDS_EXCEED_CASH")
        if not snapshot.exact_balances_complete:
            reasons.append("TRANSITION_PLAN_POSITION_BALANCES_INCOMPLETE")
        reconciliation = PlanExecutionAccountReconciliation(
            account_id=snapshot.account.account_id,
            owner_user_id=snapshot.owner_user_id,
            read_at=snapshot.read_at,
            money_unit=money_unit,
            exact_cash=exact_cash,
            active_buy_cash_reserved=exact_reserved,
            available_cash_after_holds=available_cash,
            exact_balances_complete=snapshot.exact_balances_complete,
            exact_position_balances=snapshot.exact_position_balances,
            active_reservations=tuple(snapshot.active_reservations),
            reason_codes=tuple(reasons),
        )
        return reconciliation, tuple(reasons)

    @staticmethod
    def _require_clock(value: object) -> datetime:
        """Reject a server clock that cannot safely scope a read."""

        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("server clock must return an aware datetime")
        return value


def _sum_exact(values: tuple[Decimal, ...]) -> Decimal:
    """Add exact monetary holds without a caller's low-precision context."""

    with localcontext() as context:
        context.prec = 80
        return sum(values, Decimal("0"))


__all__: tuple[str, ...] = (
    "GetTransitionPlanExecutionProgressUseCase",
    "PlanExecutionAccountReconciliation",
    "PlanExecutionHistoryRead",
    "PlanExecutionHistoryReader",
    "PlanExecutionProgressQuery",
    "TransitionPlanExecutionProgress",
    "TransitionPlanFamilyHeadReader",
)
