"""Persist local simulated-order holds under the shared account ledger lock."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import TypeAlias, cast

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanOrderExecutionBinding,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    CorporateActionTaxCashCoverageReader,
    TaxCashCoverageSnapshot,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeIdempotencyConflict,
    _validate_reservation_plan_bundle_binding,
)
from apps.simulated_trading.application.order_submission_market import (
    OrderSubmissionAccountState,
    OwnerOrderStoredReadback,
    SimulatedOrderSubmissionGuard,
)
from apps.simulated_trading.application.portfolio_risk_execution_gate import (
    PortfolioRiskLockedOrderGuard,
)
from apps.simulated_trading.application.portfolio_risk_locked_transition import (
    revalidate_locked_portfolio_order,
)
from apps.simulated_trading.application.transition_plan_execution import (
    TransitionPlanLockedActionGuard,
)
from apps.simulated_trading.domain.execution_current_reference import (
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import (
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_primitives import SimulatedTradeSide
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    TradeFeeBreakdown,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationError,
    OrderReservationRequest,
    OrderReservationResult,
    OrderReservationStatus,
    reserve_order,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_cash_admission import (
    assert_tax_cash_coverage_before_commit,
    require_current_tax_cash_coverage,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    require_no_pending_local_daily_match,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    JSONValue,
    canonical_snapshot,
    decode_order_reservation,
    plan_snapshot_payload,
    require_stored_submission_market_purpose,
    stored_submission_market_purpose,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _locked_fill_chain,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_ledger_storage import (
    _pending_release_plan,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_release_storage import (
    encode_due_v4_release_proofs,
    lock_v4_pending_fill_chains,
    require_v4_pending_chain_match,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
)
from apps.simulated_trading.infrastructure.order_reservation_identity_guard import (
    require_order_reservation_owner_key,
)
from apps.simulated_trading.infrastructure.order_reservation_repository_support import (
    build_locked_tax_aware_reservation_book,
    persist_order_reservation_model,
    require_exact_order_retry,
    require_locked_reservation_source_precision,
    validate_reservation_owner_row,
)
from apps.simulated_trading.infrastructure.transition_plan_reservation_history import (
    require_final_transition_plan_lease,
    require_no_conflicting_plan_reservation_history,
    require_stored_transition_plan_binding,
    validate_locked_transition_plan_binding,
    validate_transition_plan_intent_binding,
)
from core.exceptions import ResourceNotFoundError

from .execution_settlement_accounting_math import _quantity_difference
from .execution_settlement_uow_repository import DjangoSimulatedTradeExecutionRepository
from .order_reservation_sqlite_precision import PrecisionFamily, require_sqlite_values

ReservationPlan: TypeAlias = SettlementExecutionPlanV2 | SettlementExecutionPlanV3


def _request_from_intent(
    intent: SimulatedTradeIntent,
    *,
    fee_budget: Decimal | None,
) -> OrderReservationRequest:
    """Build the exact cash/share request while preserving the separate full-intent hash."""

    if type(intent) is not SimulatedTradeIntent:
        raise SimulatedTradeExecutionBlocked(
            "order reservation requires an exact simulated trade intent",
            code="ORDER_RESERVATION_REQUEST_INVALID",
        )
    try:
        intent.__post_init__()
        return OrderReservationRequest(
            account_id=intent.account_id,
            security_id=intent.security_id,
            idempotency_key=intent.idempotency_key,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.price,
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            fee_budget=fee_budget,
        )
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "order reservation request failed exact validation",
            code="ORDER_RESERVATION_REQUEST_INVALID",
        ) from error


class DjangoSimulatedOrderReservationRepository:
    """Create, replay, inspect, and cancel holds without writing trade rows."""

    def __init__(
        self,
        *,
        using: str,
        submission_guard: SimulatedOrderSubmissionGuard | None = None,
        portfolio_risk_guard: PortfolioRiskLockedOrderGuard | None = None,
        transition_plan_guard: TransitionPlanLockedActionGuard | None = None,
        tax_cash_coverage_reader: CorporateActionTaxCashCoverageReader | None = None,
    ) -> None:
        """Bind all reservation writes and reads to one explicit database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be a nonempty database alias")
        self._using = using
        self._execution = DjangoSimulatedTradeExecutionRepository(
            using=using, tax_cash_coverage_reader=tax_cash_coverage_reader
        )
        self._submission_guard = submission_guard
        self._portfolio_risk_guard = portfolio_risk_guard
        self._transition_plan_guard = transition_plan_guard
        self._tax_cash_coverage_reader = tax_cash_coverage_reader

    def require_owned_active_account(self, *, account_id: int, user_id: int) -> None:
        """Authorize a new preview before any outbound source capture occurs."""
        with transaction.atomic(using=self._using):
            self._execution._locked_account(
                account_id=account_id, user_id=user_id, require_active=True
            )
            self._lock_active_user(user_id)

    def read_submission_state(
        self, *, plan: ReservationPlan, clock: SimulatedTradeExecutionClock
    ) -> OrderSubmissionAccountState:
        """Project the same due releases as Reserve without changing any ledger row."""
        intent = plan.intent
        with transaction.atomic(using=self._using):
            account = self._execution._locked_account(
                account_id=intent.account_id, user_id=intent.user_id, require_active=True
            )
            self._lock_active_user(intent.user_id)
            active = lock_active_order_reservations(account_id=intent.account_id, using=self._using)
            candidates = self._execution._pending_candidates(intent.account_id, intent.asset_code)
            chains = lock_v4_pending_fill_chains(
                account=account,
                asset_code=intent.asset_code,
                pending_candidates=candidates,
                using=self._using,
            )
            position = self._execution._locked_position(intent.account_id, intent.asset_code)
            pending = self._execution._locked_pending(intent.account_id, intent.asset_code)
            require_v4_pending_chain_match(pending_rows=pending, entries=chains)
            require_locked_reservation_source_precision(
                account=account, position=position, pending_rows=pending, using=self._using
            )
            now = self._execution._now(clock)
            plan.calendar_evidence.validate_for(now)
            tax_coverage = self._read_tax_coverage(plan)
            now = self._execution._now(clock)
            plan.calendar_evidence.validate_for(now)
            book = self._current_book(
                account=account,
                position=position,
                active_rows=active,
                target=None,
                security_id=intent.security_id,
                asset_code=intent.asset_code,
                tax_coverage=tax_coverage,
            )
            if position is None:
                if pending:
                    raise SimulatedTradeExecutionBlocked("无持仓行但存在待结算成交")
                return OrderSubmissionAccountState(book, None, now)
            self._execution._validate_position(position)
            if pending and book.sellable_shares is not None:
                calendar = plan.calendar_evidence
                session = calendar.current_open_session(now)
                _, _, available = _pending_release_plan(
                    pending_rows=pending,
                    position=position,
                    evidence=calendar,
                    settlement_exchange=plan.identity_evidence.source_exchange,
                    now=now,
                    security_id=intent.security_id,
                    v4_release_proofs=encode_due_v4_release_proofs(
                        entries=chains,
                        evidence=calendar,
                        released_at=now,
                        release_session=session,
                    ),
                )
                book = replace(book, sellable_shares=available)
            return OrderSubmissionAccountState(book, position.quantity, now)

    def get_owned_order_id(self, *, intent: SimulatedTradeIntent) -> int:
        """Read the durable numeric order identity without accepting a caller target."""
        with transaction.atomic(using=self._using):
            self._execution._locked_account(
                account_id=intent.account_id, user_id=intent.user_id, require_active=True
            )
            self._lock_active_user(intent.user_id)
            row = self._locked_reservation_by_key(
                account_id=intent.account_id, idempotency_key=intent.idempotency_key
            )
            if (
                row is None
                or type(row.pk) is not int
                or row.intent_payload_hash != intent.request_payload_hash
            ):
                raise SimulatedTradeExecutionBlocked("原订单身份不可核验")
            return row.pk

    def read_owned_order_by_key(
        self, *, account_id: int, user_id: int, order_key: str
    ) -> OwnerOrderStoredReadback:
        """Read one owner record independently of market, fees or current balances."""
        with transaction.atomic(using=self._using):
            account = self._execution._locked_account(
                account_id=account_id, user_id=user_id, require_active=False
            )
            self._lock_active_user(user_id)
            row = self._locked_reservation_by_key(account_id=account_id, idempotency_key=order_key)
            if row is None:
                raise ResourceNotFoundError("当前未找到原订单，请保留原定位继续核对")
            validate_reservation_owner_row(row=row, account=account, user_id=user_id)
            if type(row.pk) is not int:
                raise SimulatedTradeExecutionBlocked("原订单编号无效")
            snapshot = validated_plan_snapshot(row)
            purpose = stored_submission_market_purpose(snapshot)
            return OwnerOrderStoredReadback(
                row.pk,
                self._decode_model(row),
                purpose,
            )

    def _lock_active_user(self, user_id: int) -> None:
        """Lock the authenticated owner row and reject missing or inactive users."""

        actor_active: object = (
            get_user_model()
            ._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=user_id)
            .values_list("is_active", flat=True)
            .first()
        )
        if actor_active is not True:
            raise SimulatedTradeAccountScopeUnavailable()

    def find_idempotent_reservation(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_budget: Decimal | None,
        market_purpose: str | None = None,
        transition_plan_binding: TransitionPlanOrderExecutionBinding | None = None,
        transition_plan_recorded_at: datetime | None = None,
    ) -> OrderReservationResult | None:
        """Replay an exact hold while checking any signed owner-order purpose."""

        request = _request_from_intent(intent, fee_budget=fee_budget)
        with transaction.atomic(using=self._using):
            account = self._execution._locked_account(
                account_id=intent.account_id,
                user_id=intent.user_id,
                require_active=False,
            )
            self._lock_active_user(intent.user_id)
            active_rows = lock_active_order_reservations(
                account_id=intent.account_id,
                using=self._using,
            )
            row = self._locked_reservation_by_key(
                account_id=intent.account_id,
                idempotency_key=intent.idempotency_key,
            )
            if row is None:
                return None
            validate_reservation_owner_row(row=row, account=account, user_id=intent.user_id)
            snapshot = validated_plan_snapshot(row)
            require_stored_submission_market_purpose(snapshot=snapshot, expected=market_purpose)
            require_stored_transition_plan_binding(
                snapshot=snapshot,
                expected_binding=transition_plan_binding,
                expected_recorded_at=transition_plan_recorded_at,
            )
            reservation = self._decode_model(row)
            require_exact_order_retry(
                row=row,
                intent=intent,
                request=request,
                reservation=reservation,
            )
            position = self._execution._locked_position(intent.account_id, intent.asset_code)
            book = self._current_book(
                account=account,
                position=position,
                active_rows=active_rows,
                target=row,
                security_id=intent.security_id,
                asset_code=intent.asset_code,
            )
            return OrderReservationResult(book=book, reservation=reservation, replayed=True)

    def reserve_order(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        fee_budget: Decimal | None,
        clock: SimulatedTradeExecutionClock,
        transition_plan_binding: TransitionPlanOrderExecutionBinding | None = None,
        transition_plan_recorded_at: datetime | None = None,
    ) -> OrderReservationResult:
        """Recheck evidence under ledger locks, then atomically create one hold."""

        if type(plan) not in (SettlementExecutionPlanV2, SettlementExecutionPlanV3):
            raise SimulatedTradeExecutionBlocked(
                "reservation requires a V2 or V3 settlement plan",
                code="ORDER_RESERVATION_PLAN_INVALID",
            )
        if type(execution_bundle) is not ExecutionSettlementBundleV3:
            raise SimulatedTradeExecutionBlocked(
                "reservation requires an exact Risk V3 bundle",
                code="ORDER_RESERVATION_PLAN_INVALID",
            )
        intent = plan.intent
        request = _request_from_intent(intent, fee_budget=fee_budget)
        transition_plan_guard = self._transition_plan_guard
        if transition_plan_binding is None and transition_plan_recorded_at is not None:
            raise SimulatedTradeExecutionBlocked(
                "plan execution binding and its original clock must be supplied together",
                code="TRANSITION_PLAN_EXECUTION_BINDING_INVALID",
            )
        if transition_plan_binding is not None:
            if transition_plan_recorded_at is None:
                raise SimulatedTradeExecutionBlocked(
                    "plan execution binding and its original clock must be supplied together",
                    code="TRANSITION_PLAN_EXECUTION_BINDING_INVALID",
                )
            if transition_plan_guard is None:
                raise SimulatedTradeExecutionBlocked(
                    "plan execution guard is not configured",
                    code="TRANSITION_PLAN_GUARD_UNAVAILABLE",
                )
            validate_transition_plan_intent_binding(
                binding=transition_plan_binding,
                intent=intent,
                owner_user_id=intent.user_id,
                recorded_at=transition_plan_recorded_at,
            )
        submission_market_purpose = (
            self._submission_guard.market_purpose if self._submission_guard else None
        )
        self._require_sqlite_values(
            (
                ("quantity", request.quantity, "quantity"),
                ("limit_price", request.limit_price, "price"),
                ("notional", request.notional, "money"),
                ("fee_budget", request.fee_budget, "money"),
            )
        )
        fee_policy = plan.fee_policy_v2
        if type(fee_policy) is not SimulatedFeePolicyV2:
            raise SimulatedTradeExecutionBlocked(
                "reservation requires an exact FeeV2 policy",
                code="ORDER_RESERVATION_FEE_POLICY_INVALID",
            )
        try:
            _validate_reservation_plan_bundle_binding(
                plan=plan,
                bundle=execution_bundle,
                as_of=plan.pre_read_at,
            )
            self._execution._validate_rule_quantity(
                intent=intent,
                bundle=execution_bundle,
            )
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "reservation plan failed pre-lock validation",
                code="ORDER_RESERVATION_PLAN_INVALID",
            ) from error

        try:
            with transaction.atomic(using=self._using):
                account = self._execution._locked_account(
                    account_id=intent.account_id,
                    user_id=intent.user_id,
                    require_active=True,
                )
                if account.user_id != intent.user_id:
                    raise SimulatedTradeAccountScopeUnavailable()
                self._lock_active_user(intent.user_id)
                active_rows = lock_active_order_reservations(
                    account_id=intent.account_id,
                    using=self._using,
                )
                existing_trade = (
                    SimulatedTradeModel._base_manager.using(self._using)
                    .filter(
                        account_id=intent.account_id,
                        idempotency_key=intent.idempotency_key,
                    )
                    .first()
                )
                if existing_trade is not None:
                    raise SimulatedTradeIdempotencyConflict(
                        "a trade already uses this order idempotency key"
                    )
                existing = self._locked_reservation_by_key(
                    account_id=intent.account_id,
                    idempotency_key=intent.idempotency_key,
                )
                if existing is not None:
                    validate_reservation_owner_row(
                        row=existing, account=account, user_id=intent.user_id
                    )
                    existing_snapshot = validated_plan_snapshot(existing)
                    require_stored_submission_market_purpose(
                        snapshot=existing_snapshot,
                        expected=submission_market_purpose,
                    )
                    require_stored_transition_plan_binding(
                        snapshot=existing_snapshot,
                        expected_binding=transition_plan_binding,
                        expected_recorded_at=transition_plan_recorded_at,
                    )
                    reservation = self._decode_model(existing)
                    require_exact_order_retry(
                        row=existing,
                        intent=intent,
                        request=request,
                        reservation=reservation,
                    )
                    position = self._execution._locked_position(
                        intent.account_id,
                        intent.asset_code,
                    )
                    book = self._current_book(
                        account=account,
                        position=position,
                        active_rows=active_rows,
                        target=existing,
                        security_id=intent.security_id,
                        asset_code=intent.asset_code,
                    )
                    return OrderReservationResult(
                        book=book,
                        reservation=reservation,
                        replayed=True,
                    )

                pending_candidates = self._execution._pending_candidates(
                    intent.account_id,
                    intent.asset_code,
                )
                tax_coverage = self._read_tax_coverage(plan)
                v4_chains = lock_v4_pending_fill_chains(
                    account=account,
                    asset_code=intent.asset_code,
                    pending_candidates=pending_candidates,
                    using=self._using,
                )
                position = self._execution._locked_position(
                    intent.account_id,
                    intent.asset_code,
                )
                pending_rows = self._execution._locked_pending(
                    intent.account_id,
                    intent.asset_code,
                )
                require_v4_pending_chain_match(
                    pending_rows=pending_rows,
                    entries=v4_chains,
                )
                require_locked_reservation_source_precision(
                    account=account,
                    position=position,
                    pending_rows=pending_rows,
                    using=self._using,
                )
                pre_release_book = self._current_book(
                    account=account,
                    position=position,
                    active_rows=active_rows,
                    target=None,
                    security_id=intent.security_id,
                    asset_code=intent.asset_code,
                    tax_coverage=tax_coverage,
                )
                pending_scope = self._execution._pending_scope_for_rows(pending_rows)
                now = self._execution._now(clock)
                if self._portfolio_risk_guard is not None:
                    now = revalidate_locked_portfolio_order(
                        guard=self._portfolio_risk_guard,
                        intent=intent,
                        fee_cap=(
                            cast(Decimal, request.fee_budget)
                            if intent.side is SimulatedTradeSide.BUY
                            else plan.fee_breakdown.total_fee
                        ),
                        market_purpose=submission_market_purpose,
                        execution_session=plan.calendar_evidence.current_open_session(now),
                        as_of=now,
                        read_clock=lambda: self._execution._now(clock),
                        read_execution_session=plan.calendar_evidence.current_open_session,
                    )
                if transition_plan_binding is not None:
                    if transition_plan_guard is None:
                        raise SimulatedTradeExecutionBlocked(
                            "plan execution guard is not configured",
                            code="TRANSITION_PLAN_GUARD_UNAVAILABLE",
                        )
                    if transition_plan_recorded_at is None:
                        raise SimulatedTradeExecutionBlocked(
                            "plan binding lacks its original revision clock",
                            code="TRANSITION_PLAN_EXECUTION_BINDING_INVALID",
                        )
                    locked_revision = transition_plan_guard.validate_locked_action(
                        binding=transition_plan_binding,
                        account_id=intent.account_id,
                        owner_user_id=intent.user_id,
                        as_of=now,
                    )
                    validate_locked_transition_plan_binding(
                        revision=locked_revision,
                        binding=transition_plan_binding,
                        intent=intent,
                        owner_user_id=intent.user_id,
                        as_of=now,
                        recorded_at=transition_plan_recorded_at,
                    )
                    require_no_conflicting_plan_reservation_history(
                        using=self._using,
                        account_id=intent.account_id,
                        owner_user_id=intent.user_id,
                        binding=transition_plan_binding,
                        current_idempotency_key=intent.idempotency_key,
                    )
                try:
                    _validate_reservation_plan_bundle_binding(
                        plan, execution_bundle, now, reservation_locked=True
                    )
                    fee_policy.validate_at(now)
                    current_session = plan.calendar_evidence.current_open_session(now)
                    if pending_scope is not None:
                        if pending_scope.source_exchange != plan.identity_evidence.source_exchange:
                            raise ValueError(
                                "pending source exchange differs from the execution plan"
                            )
                        plan.calendar_evidence.elapsed_open_sessions(
                            pending_scope.earliest_session,
                            current_session,
                        )
                except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
                    raise SimulatedTradeExecutionBlocked(
                        "reservation evidence expired or changed before ledger locks completed",
                        code="ORDER_RESERVATION_PLAN_STALE",
                    ) from error
                position, _ = self._execution._release_pending_rows(
                    position=position,
                    pending_rows=pending_rows,
                    active_held_shares=pre_release_book.active_held_shares,
                    evidence=plan.calendar_evidence,
                    through_session=current_session,
                    released_at=now,
                    v4_release_proofs=encode_due_v4_release_proofs(
                        entries=v4_chains,
                        evidence=plan.calendar_evidence,
                        released_at=now,
                        release_session=current_session,
                    ),
                )
                if position is not None:
                    require_locked_reservation_source_precision(
                        account=account,
                        position=position,
                        pending_rows=[],
                        using=self._using,
                    )
                    self._execution._validate_position(position)
                book = self._current_book(
                    account=account,
                    position=position,
                    active_rows=active_rows,
                    target=None,
                    security_id=intent.security_id,
                    asset_code=intent.asset_code,
                    tax_coverage=tax_coverage,
                )
                held_shares = book.active_held_shares
                locked_position: tuple[Decimal, Decimal] | None = None
                if position is not None:
                    available = validate_ledger_quantity(
                        position.available_quantity,
                        "position.available_quantity",
                    )
                    if held_shares > available:
                        raise SimulatedTradeExecutionBlocked(
                            "active sell reservations exceed the locked sellable balance",
                            code="ORDER_RESERVATION_STATE_INVALID",
                        )
                    locked_position = (
                        position.quantity,
                        _quantity_difference(
                            available,
                            held_shares,
                            "sellable_quantity_after_reservations",
                        ),
                    )
                self._execution._validate_rule_quantity(
                    intent=intent,
                    bundle=execution_bundle,
                    locked_position=locked_position,
                )
                fees = fee_policy.calculate_for(
                    asset_type=intent.asset_type,
                    market=intent.market,
                    board=intent.board,
                    side=intent.side,
                    amount=request.notional,
                    as_of=now,
                )
                if type(fees) is not TradeFeeBreakdown:
                    raise SimulatedTradeExecutionBlocked(
                        "FeeV2 returned an unverifiable component breakdown",
                        code="ORDER_RESERVATION_FEE_POLICY_INVALID",
                    )
                snapshot = plan_snapshot_payload(
                    plan=plan,
                    bundle=execution_bundle,
                    fee_policy=fee_policy,
                    transition_plan_binding=transition_plan_binding,
                    transition_plan_recorded_at=transition_plan_recorded_at,
                )
                if self._submission_guard is not None:
                    market_receipt = self._submission_guard.validate_locked_submission(
                        plan=plan,
                        execution_bundle=execution_bundle,
                        book=book,
                        total_quantity=position.quantity if position is not None else None,
                        as_of=now,
                    )
                    snapshot["submission_market"] = canonical_snapshot(market_receipt)
                result = reserve_order(
                    book,
                    request,
                    fee_policy,
                    reserved_at=now,
                )
                if result.replayed:
                    raise SimulatedTradeExecutionBlocked(
                        "reservation key appeared without a locked repository row",
                        code="ORDER_RESERVATION_STATE_INVALID",
                    )
                row = self._create_model(
                    account=account,
                    intent=intent,
                    reservation=result.reservation,
                    fee_policy=fee_policy,
                    fee_breakdown=fees,
                    plan_snapshot=snapshot,
                    book_cash=book.book_cash,
                    sellable_shares=book.sellable_shares,
                    source_snapshot_at=now,
                    plan=plan,
                )
                require_final_transition_plan_lease(
                    binding=transition_plan_binding,
                    guard=transition_plan_guard,
                    recorded_at=transition_plan_recorded_at,
                    intent=intent,
                    initial_now=now,
                    read_clock=lambda: self._execution._now(clock),
                )
                persisted = self._decode_model(row)
                if tax_coverage is not None:
                    assert_tax_cash_coverage_before_commit(
                        reader=self._tax_cash_coverage_reader,
                        snapshot=tax_coverage,
                        using=self._using,
                    )
                    _validate_reservation_plan_bundle_binding(
                        plan, execution_bundle, self._execution._now(clock), reservation_locked=True
                    )
                    require_final_transition_plan_lease(
                        binding=transition_plan_binding,
                        guard=transition_plan_guard,
                        recorded_at=transition_plan_recorded_at,
                        intent=intent,
                        initial_now=now,
                        read_clock=lambda: self._execution._now(clock),
                    )
                persisted_book = self._current_book(
                    account=account,
                    position=position,
                    active_rows=[*active_rows, row],
                    target=None,
                    security_id=intent.security_id,
                    asset_code=intent.asset_code,
                    tax_coverage=tax_coverage,
                )
                return OrderReservationResult(
                    book=persisted_book,
                    reservation=persisted,
                    replayed=False,
                )
        except SimulatedTradeExecutionBlocked:
            raise
        except SimulatedTradeIdempotencyConflict:
            raise
        except IntegrityError as error:
            recovered = self.find_idempotent_reservation(
                intent=intent,
                fee_budget=fee_budget,
                market_purpose=submission_market_purpose,
            )
            if recovered is not None:
                return recovered
            raise SimulatedTradeExecutionBlocked(
                "reservation could not be committed under its unique account key",
                code="ORDER_RESERVATION_STORAGE_CONFLICT",
            ) from error
        except OrderReservationError as error:
            raise SimulatedTradeExecutionBlocked(
                "订单可用资源或费用预算不满足预留要求",
                code=error.code,
            ) from error
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "reservation failed exact ledger validation",
                code="ORDER_RESERVATION_INVALID",
            ) from error

    def find_order(
        self,
        *,
        account_id: int,
        user_id: int,
        idempotency_key: str,
    ) -> OrderReservation | None:
        """Read one reservation only from its current account-owner scope."""

        require_order_reservation_owner_key(
            account_id=account_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        row = (
            SimulatedOrderReservationModel._base_manager.using(self._using)
            .select_related("account")
            .filter(
                account_id=account_id,
                owner_user_id=user_id,
                account__user_id=user_id,
                idempotency_key=idempotency_key,
            )
            .first()
        )
        if row is None:
            return None
        return self._decode_model(row)

    def cancel_order(
        self,
        *,
        account_id: int,
        user_id: int,
        idempotency_key: str,
        clock: SimulatedTradeExecutionClock,
    ) -> OrderReservation:
        """Release a local hold idempotently, including when its account is inactive."""

        require_order_reservation_owner_key(
            account_id=account_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        try:
            with transaction.atomic(using=self._using):
                account = self._execution._locked_account(
                    account_id=account_id,
                    user_id=user_id,
                    require_active=False,
                )
                self._lock_active_user(user_id)
                lock_active_order_reservations(
                    account_id=account_id,
                    using=self._using,
                )
                row = self._locked_reservation_by_key(
                    account_id=account_id,
                    idempotency_key=idempotency_key,
                )
                if row is None:
                    raise SimulatedTradeExecutionBlocked(
                        "order reservation was not found in this owner scope",
                        code="ORDER_RESERVATION_NOT_FOUND",
                    )
                validate_reservation_owner_row(row=row, account=account, user_id=user_id)
                reservation = self._decode_model(row)
                chain = _locked_fill_chain(
                    reservation_row=row,
                    using=self._using,
                )
                require_no_pending_local_daily_match(
                    reservation_row=row,
                    chain=chain,
                    using=self._using,
                )
                if reservation.status is not OrderReservationStatus.ACTIVE:
                    return reservation
                now = self._execution._now(clock)
                if now < reservation.reserved_at:
                    raise SimulatedTradeExecutionBlocked(
                        "reservation cancellation clock precedes its acceptance time",
                        code="CLOCK_INVALID",
                    )
                cancelled = reservation.release_remaining()
                if cancelled.status is not OrderReservationStatus.CANCELLED:
                    raise SimulatedTradeExecutionBlocked(
                        "active reservation did not produce a cancelled hold",
                        code="ORDER_RESERVATION_STATE_INVALID",
                    )
                updated = SimulatedOrderReservationModel.objects.using(self._using)._cancel_locked(
                    account_id=account_id,
                    owner_user_id=user_id,
                    reservation_id=row.pk,
                    filled_quantity=cancelled.filled_quantity,
                    cash_consumed=cancelled.cash_consumed,
                    shares_consumed=cancelled.shares_consumed,
                    cash_released=cancelled.cash_released,
                    shares_released=cancelled.shares_released,
                    cancelled_at=now,
                    updated_at=now,
                )
                if updated != 1:
                    raise SimulatedTradeExecutionBlocked(
                        "reservation changed while its account lock was held",
                        code="ORDER_RESERVATION_STATE_CONFLICT",
                    )
                row.refresh_from_db(using=self._using)
                decoded = self._decode_model(row)
                if decoded != cancelled:
                    raise SimulatedTradeExecutionBlocked(
                        "cancelled reservation differs from its stored resource audit",
                        code="ORDER_RESERVATION_STATE_INVALID",
                    )
                return decoded
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "order reservation cancellation failed exact validation",
                code="ORDER_RESERVATION_INVALID",
            ) from error

    def _locked_reservation_by_key(
        self,
        *,
        account_id: int,
        idempotency_key: str,
    ) -> SimulatedOrderReservationModel | None:
        """Lock a terminal key row after active rows have been locked in order."""

        return (
            SimulatedOrderReservationModel._base_manager.using(self._using)
            .select_for_update()
            .filter(account_id=account_id, idempotency_key=idempotency_key)
            .first()
        )

    def _decode_model(self, row: SimulatedOrderReservationModel) -> OrderReservation:
        """Decode one stored row through the shared strict persistence codec."""

        return decode_order_reservation(row)

    def _read_tax_coverage(self, plan: ReservationPlan) -> TaxCashCoverageSnapshot | None:
        """Cover BUY funding and any SELL fee deficit before reserving account cash."""
        intent = plan.intent
        if intent.side is SimulatedTradeSide.SELL and plan.fee_breakdown.total_fee <= plan.amount:
            return None
        return require_current_tax_cash_coverage(
            reader=self._tax_cash_coverage_reader,
            physical_account_id=intent.account_id,
            owner_user_id=intent.user_id,
            using=self._using,
        )

    def _current_book(
        self,
        *,
        account: SimulatedAccountModel,
        position: PositionModel | None,
        active_rows: list[SimulatedOrderReservationModel],
        target: SimulatedOrderReservationModel | None,
        security_id: str,
        asset_code: str,
        tax_coverage: TaxCashCoverageSnapshot | None = None,
    ) -> OrderReservationBook:
        """Build one exact current book without treating unknown balances as zero."""

        return build_locked_tax_aware_reservation_book(
            account=account,
            position=position,
            active_rows=active_rows,
            target=target,
            security_id=security_id,
            asset_code=asset_code,
            using=self._using,
            tax_coverage=tax_coverage,
        )

    def _require_sqlite_values(
        self,
        values: tuple[tuple[str, object, PrecisionFamily], ...],
    ) -> None:
        """Reject new SQLite ledger values outside the supported exact envelope."""

        require_sqlite_values(values=values, using=self._using)

    def _create_model(
        self,
        *,
        account: SimulatedAccountModel,
        intent: SimulatedTradeIntent,
        reservation: OrderReservation,
        fee_policy: SimulatedFeePolicyV2,
        fee_breakdown: TradeFeeBreakdown,
        plan_snapshot: dict[str, JSONValue],
        book_cash: Decimal | None,
        sellable_shares: Decimal | None,
        source_snapshot_at: datetime,
        plan: ReservationPlan,
    ) -> SimulatedOrderReservationModel:
        """Persist the prepared order and initial hold with one database write."""

        return persist_order_reservation_model(
            using=self._using,
            validate_values=self._require_sqlite_values,
            account=account,
            intent=intent,
            reservation=reservation,
            fee_policy=fee_policy,
            fee_breakdown=fee_breakdown,
            plan_snapshot=plan_snapshot,
            book_cash=book_cash,
            sellable_shares=sellable_shares,
            source_snapshot_at=source_snapshot_at,
            plan=plan,
        )


__all__: tuple[str, ...] = ("DjangoSimulatedOrderReservationRepository",)
