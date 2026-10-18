"""Same-database implementation of the settlement-bound simulated ledger UoW."""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from math import isfinite
from typing import TypeAlias

from django.db import transaction
from django.db.models import QuerySet

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeIdempotencyConflict,
    _validate_plan_bundle_binding,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import (
    PendingSettlementScopeV1,
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SimulatedSettlementPlanBindingV1 as SimulatedSettlementPlanBindingV1,
)
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SimulatedSettlementPlanBindingV2 as SimulatedSettlementPlanBindingV2,
)
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    bind_settlement_execution_plan,
    bind_settlement_execution_plan_v2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionCalendarEvidence,
    SettlementExecutionPlan,
    SimulatedTradeExecutionReceipt,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    _execution_quantity_deny_code,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)

from .execution_settlement_plan_binding_repository import (
    SettlementPlanBinding as SettlementPlanBinding,
)
from .execution_settlement_plan_binding_repository import (
    build_simulated_trade_execution_receipt as _build_simulated_trade_execution_receipt,
)

_MONEY_CENT = Decimal("0.01")
_PRICE_TICK = Decimal("0.0001")
SettlementPlan: TypeAlias = SettlementExecutionPlan | SettlementExecutionPlanV2


def _aware_time(value: object) -> datetime:
    """Require an aware execution clock before any timestamp is stored."""

    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedTradeExecutionBlocked("execution clock must be timezone-aware")
    try:
        if value.utcoffset() is None:
            raise SimulatedTradeExecutionBlocked("execution clock must be timezone-aware")
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked("execution clock must be timezone-aware") from error
    return value


def _money_sum(*values: Decimal) -> Decimal:
    """Add exact money values and enforce the account/trade column range."""

    with localcontext() as context:
        context.prec = 80
        value = sum(values, Decimal("0")).quantize(_MONEY_CENT, rounding=ROUND_HALF_EVEN)
    return validate_ledger_money(value, "ledger_money")


def _rebased_account_market_value(
    aggregate_value: Decimal,
    old_position_value: Decimal,
    new_position_value: Decimal,
) -> Decimal:
    """Replace one revalued position inside the account's aggregate market value."""

    aggregate = validate_ledger_money(aggregate_value, "account.current_market_value")
    old_value = validate_ledger_money(old_position_value, "position.market_value_before_trade")
    new_value = validate_ledger_money(new_position_value, "position.market_value_after_trade")
    if old_value > aggregate:
        raise SimulatedTradeExecutionBlocked(
            "account aggregate market value is smaller than the locked position value"
        )
    return validate_ledger_money(
        aggregate - old_value + new_value,
        "account.current_market_value_after_position_revaluation",
    )


def _allocate_sale_cost_basis(
    *,
    total_cost: Decimal,
    sold_quantity: Decimal,
    total_quantity: Decimal,
) -> Decimal:
    """Allocate stored cost cents proportionally, leaving the final residual intact."""

    if sold_quantity == total_quantity:
        return validate_ledger_money(total_cost, "position.total_cost", allow_zero=False)
    try:
        with localcontext() as context:
            context.prec = 80
            share = (total_cost * sold_quantity / total_quantity).quantize(
                _MONEY_CENT,
                rounding=ROUND_HALF_EVEN,
            )
    except (InvalidOperation, OverflowError, ZeroDivisionError) as error:
        raise SimulatedTradeExecutionBlocked(
            "sell cost basis cannot be allocated safely"
        ) from error
    if share <= 0 or share >= total_cost:
        raise SimulatedTradeExecutionBlocked(
            "partial sell cannot preserve a positive cent-denominated remaining cost basis"
        )
    return validate_ledger_money(share, "sell.cost_basis", allow_zero=False)


def _signed_money(value: Decimal, field_name: str) -> Decimal:
    """Round one signed P&L value without applying the nonnegative cash constraint."""

    try:
        with localcontext() as context:
            context.prec = 80
            result = value.quantize(_MONEY_CENT, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError) as error:
        raise SimulatedTradeExecutionBlocked(
            f"{field_name} cannot be represented at ledger precision"
        ) from error
    if not result.is_finite() or abs(result) >= Decimal("10000000000000"):
        raise SimulatedTradeExecutionBlocked(f"{field_name} exceeds the ledger range")
    return result


def _multiply_money(quantity: Decimal, price: Decimal, field_name: str) -> Decimal:
    """Calculate the cent-rounded market amount using the UoW's declared policy."""

    try:
        with localcontext() as context:
            context.prec = 80
            value = (quantity * price).quantize(_MONEY_CENT, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError) as error:
        raise SimulatedTradeExecutionBlocked(
            f"{field_name} cannot be represented at ledger precision"
        ) from error
    return validate_ledger_money(value, field_name, allow_zero=False)


def _average_cost(total_cost: Decimal, quantity: Decimal) -> Decimal:
    """Return four-decimal average cost from the exact stored cost basis."""

    if quantity <= 0:
        raise SimulatedTradeExecutionBlocked("position quantity must remain positive")
    try:
        with localcontext() as context:
            context.prec = 80
            value = (total_cost / quantity).quantize(_PRICE_TICK, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError, ZeroDivisionError) as error:
        raise SimulatedTradeExecutionBlocked("position average cost is invalid") from error
    return validate_ledger_price(value, "avg_cost", allow_zero=False)


def _percentage(numerator: Decimal, denominator: Decimal) -> float:
    """Convert an exact ledger ratio to the legacy FloatField representation."""

    if denominator <= 0:
        raise SimulatedTradeExecutionBlocked("percentage denominator must be positive")
    with localcontext() as context:
        context.prec = 80
        value = float((numerator / denominator) * Decimal("100"))
    if not isfinite(value):
        raise SimulatedTradeExecutionBlocked("percentage exceeds the persisted float range")
    return value


class DjangoSimulatedTradeExecutionRepository:
    """Apply simulated settlement, cash, position, fee, and trade changes atomically.

    This repository only handles new normal simulated orders. Existing trade
    imports and corrected actual-fill facts continue to use their own fee-neutral
    paths and leave all UoW metadata NULL.
    """

    def __init__(self, *, using: str) -> None:
        """Bind the complete ledger operation to one explicit Django database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be a nonempty database alias")
        self._using = using
        self._fee_policy_repository = DjangoFeePolicyV2Repository(using=using)

    def _validate_rule_quantity(
        self,
        *,
        intent: SimulatedTradeIntent,
        bundle: ExecutionSettlementBundleV3,
        locked_position: tuple[Decimal, Decimal] | None = None,
    ) -> None:
        """Enforce one V3 quantity rule, using locked balance only for SELL exceptions."""

        rule = bundle.execution_submission_v2.execution_rule_v1
        quantity_rule = (
            rule.buy_quantity if intent.side is SimulatedTradeSide.BUY else rule.sell_quantity
        )
        deny_code = _execution_quantity_deny_code(
            side=intent.side,
            quantity=intent.quantity,
            minimum=quantity_rule.minimum,
            step=quantity_rule.step,
            maximum=quantity_rule.maximum,
            sell_odd_lot_mode=rule.sell_odd_lot_mode.value,
            locked_position=locked_position,
        )
        if deny_code is not None:
            raise SimulatedTradeExecutionBlocked(
                "trade quantity violates the exact Risk V3 quantity rule",
                code=deny_code,
            )

    def get_execution_fee_policy(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        as_of: datetime,
    ) -> SimulatedFeePolicyV2 | None:
        """Read a strict V2 exact-case policy for the exact account and cutoff."""

        return self._fee_policy_repository.get_execution_fee_policy(
            account_id=account_id,
            user_id=user_id,
            asset_type=asset_type,
            market=market,
            board=board,
            side=side,
            as_of=as_of,
        )

    def find_idempotent_result(
        self,
        *,
        account_id: int,
        user_id: int,
        idempotency_key: str,
    ) -> SimulatedTradeExecutionReceipt | None:
        """Read an exact owner/account-scoped result without touching ledger rows."""

        model = (
            SimulatedTradeModel._default_manager.using(self._using)
            .select_related("account")
            .filter(
                account_id=account_id,
                account__user_id=user_id,
                idempotency_key=idempotency_key,
            )
            .first()
        )
        return self._receipt(model) if model is not None else None

    def get_pending_settlement_start(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
    ) -> date | None:
        """Read and validate the earliest original session before external IO."""

        scope = self.get_pending_settlement_scope(
            account_id=account_id,
            user_id=user_id,
            asset_code=asset_code,
        )
        return scope.earliest_session if scope is not None else None

    def get_pending_settlement_scope(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
    ) -> PendingSettlementScopeV1 | None:
        """Return the validated earliest session and original source exchange."""

        rows = list(
            SimulatedTradeModel._default_manager.using(self._using)
            .select_related("account")
            .filter(
                account_id=account_id,
                account__user_id=user_id,
                asset_code=asset_code,
                action="buy",
                settlement_status="pending",
            )
            .order_by("settlement_market_session", "pk")
        )
        return self._pending_scope_for_rows(rows)

    def execute_trade(
        self,
        *,
        plan: SettlementPlan,
        execution_bundle: ExecutionSettlementBundleV3,
        clock: SimulatedTradeExecutionClock,
    ) -> SimulatedTradeExecutionReceipt:
        """Lock account, position, and pending rows in order and commit one UoW."""

        if type(plan) not in (SettlementExecutionPlan, SettlementExecutionPlanV2):
            raise SimulatedTradeExecutionBlocked(
                "repository requires an exact V1 or V2 settlement plan"
            )
        fee_policy_value: object = plan.fee_policy_v2
        if type(fee_policy_value) is not SimulatedFeePolicyV2:
            raise SimulatedTradeExecutionBlocked(
                "repository requires an exact V2 fee snapshot before ledger writes"
            )
        fee_policy = fee_policy_value
        try:
            plan.__post_init__()
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked("settlement plan failed revalidation") from error
        intent = plan.intent
        try:
            with transaction.atomic(using=self._using):
                account = self._locked_account(
                    account_id=intent.account_id,
                    user_id=intent.user_id,
                    require_active=True,
                )
                existing = (
                    SimulatedTradeModel._default_manager.using(self._using)
                    .filter(
                        account_id=intent.account_id,
                        idempotency_key=intent.idempotency_key,
                    )
                    .first()
                )
                if existing is not None:
                    if existing.request_payload_hash != intent.request_payload_hash:
                        raise SimulatedTradeIdempotencyConflict(
                            "idempotency key already belongs to another exact request"
                        )
                    return self._receipt(existing, replayed=True)

                _validate_plan_bundle_binding(
                    plan=plan,
                    bundle=execution_bundle,
                    as_of=plan.pre_read_at,
                )
                self._validate_rule_quantity(
                    intent=intent,
                    bundle=execution_bundle,
                )
                position = self._locked_position(intent.account_id, intent.asset_code)
                pending_rows = self._locked_pending(intent.account_id, intent.asset_code)
                pending_scope = self._pending_scope_for_rows(pending_rows)
                now = self._now(clock)
                try:
                    _validate_plan_bundle_binding(
                        plan=plan,
                        bundle=execution_bundle,
                        as_of=now,
                    )
                    current_session = plan.calendar_evidence.current_open_session(now)
                    if pending_scope is not None:
                        plan_exchange = (
                            plan.identity_evidence.source_exchange
                            if type(plan) is SettlementExecutionPlanV2
                            else plan.intent.market
                        )
                        if pending_scope.source_exchange != plan_exchange:
                            raise ValueError(
                                "pending source exchange differs from the execution plan"
                            )
                        plan.calendar_evidence.elapsed_open_sessions(
                            pending_scope.earliest_session,
                            current_session,
                        )
                except (ArithmeticError, TypeError, ValueError) as error:
                    raise SimulatedTradeExecutionBlocked(
                        "settlement evidence expired or changed before row locks were acquired"
                    ) from error
                position, _ = self._release_pending_rows(
                    position=position,
                    pending_rows=pending_rows,
                    evidence=plan.calendar_evidence,
                    through_session=current_session,
                    released_at=now,
                )
                locked_position: tuple[Decimal, Decimal] | None = None
                if position is not None:
                    self._validate_position(position)
                    locked_position = (position.quantity, position.available_quantity)
                self._validate_rule_quantity(
                    intent=intent,
                    bundle=execution_bundle,
                    locked_position=locked_position,
                )
                return self._apply_trade(
                    account=account,
                    position=position,
                    plan=plan,
                    fee_policy=fee_policy,
                    execution_time=now,
                )
        except (SimulatedTradeExecutionBlocked, SimulatedTradeIdempotencyConflict):
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "simulated trade ledger calculation failed exact validation"
            ) from error

    def release_due_settlements(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
        calendar_evidence: ExecutionCalendarEvidence,
        clock: SimulatedTradeExecutionClock,
    ) -> int:
        """Release due rows only after re-counting original lags on current calendar facts."""

        if type(calendar_evidence) is not ExecutionCalendarEvidence:
            raise SimulatedTradeExecutionBlocked("release requires exact calendar evidence")
        try:
            with transaction.atomic(using=self._using):
                self._locked_account(
                    account_id=account_id,
                    user_id=user_id,
                    require_active=False,
                )
                position = self._locked_position(account_id, asset_code)
                pending_rows = self._locked_pending(account_id, asset_code)
                pending_scope = self._pending_scope_for_rows(pending_rows)
                now = self._now(clock)
                try:
                    calendar_evidence.validate_for(now)
                    current_session = calendar_evidence.current_open_session(now)
                    if pending_scope is not None:
                        if pending_scope.source_exchange != calendar_evidence.snapshot.exchange:
                            raise ValueError(
                                "calendar exchange differs from the original pending source"
                            )
                        calendar_evidence.elapsed_open_sessions(
                            pending_scope.earliest_session,
                            current_session,
                        )
                except (ArithmeticError, TypeError, ValueError) as error:
                    raise SimulatedTradeExecutionBlocked(
                        "published calendar does not cover the complete release interval"
                    ) from error
                _, released = self._release_pending_rows(
                    position=position,
                    pending_rows=pending_rows,
                    evidence=calendar_evidence,
                    through_session=current_session,
                    released_at=now,
                )
                return released
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "settlement release failed exact ledger validation"
            ) from error

    def _locked_account(
        self,
        *,
        account_id: int,
        user_id: int | None,
        require_active: bool,
    ) -> SimulatedAccountModel:
        """Acquire the first lock and enforce simulated-account ownership."""

        query = SimulatedAccountModel._default_manager.using(self._using).select_for_update()
        filters: dict[str, object] = {
            "pk": account_id,
            "account_type": "simulated",
        }
        if user_id is not None:
            filters["user_id"] = user_id
        if require_active:
            filters["is_active"] = True
        account = query.filter(**filters).first()
        if account is None:
            raise SimulatedTradeExecutionBlocked(
                "simulated account is missing, inactive, or outside the caller's owner scope"
            )
        return account

    def _locked_position(self, account_id: int, asset_code: str) -> PositionModel | None:
        """Acquire the second lock for the account/security aggregate."""

        row = (
            PositionModel._default_manager.using(self._using)
            .select_for_update()
            .filter(account_id=account_id, asset_code=asset_code)
            .first()
        )
        return row

    def _locked_pending(self, account_id: int, asset_code: str) -> list[SimulatedTradeModel]:
        """Acquire third-order pending-fill locks in deterministic date/PK order."""

        rows: QuerySet[SimulatedTradeModel] = (
            SimulatedTradeModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                account_id=account_id,
                asset_code=asset_code,
                action="buy",
                settlement_status="pending",
            )
            .order_by("settlement_market_session", "pk")
        )
        return list(rows)

    def _pending_scope_for_rows(
        self,
        rows: list[SimulatedTradeModel],
    ) -> PendingSettlementScopeV1 | None:
        """Validate every pending receipt and derive one unambiguous source scope."""

        if not rows:
            return None
        sessions: list[date] = []
        exchanges: set[str] = set()
        for row in rows:
            session = row.settlement_market_session
            if type(session) is not date:
                raise SimulatedTradeExecutionBlocked(
                    "pending settlement is missing its original market session"
                )
            sessions.append(session)
            exchanges.add(self._pending_source_exchange(row))
        if len(exchanges) != 1:
            raise SimulatedTradeExecutionBlocked(
                "pending settlements contain multiple original source exchanges"
            )
        exchange = next(iter(exchanges))
        try:
            return PendingSettlementScopeV1(min(sessions), exchange)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "pending settlement scope failed exact validation"
            ) from error

    def _pending_source_exchange(self, row: SimulatedTradeModel) -> str:
        """Validate one persisted pending receipt and return its original exchange."""

        self._receipt(row)
        version = row.settlement_plan_binding_version
        payload = row.settlement_plan_binding_payload
        if type(version) is not int or type(payload) is not dict:
            raise SimulatedTradeExecutionBlocked(
                "pending settlement has no immutable original execution-plan binding"
            )
        if version == 1:
            if row.settlement_exchange is not None:
                raise SimulatedTradeExecutionBlocked(
                    "legacy V1 settlement row unexpectedly contains a V2 exchange column"
                )
            binding_v1 = SimulatedSettlementPlanBindingV1.from_payload(payload)
            if binding_v1.calendar_snapshot.exchange != row.settlement_market:
                raise SimulatedTradeExecutionBlocked(
                    "legacy V1 calendar exchange differs from its original rule market"
                )
            return binding_v1.calendar_snapshot.exchange
        if version == 2:
            binding_v2 = SimulatedSettlementPlanBindingV2.from_payload(payload)
            source_exchange = binding_v2.identity_evidence.source_exchange
            if row.settlement_exchange != source_exchange:
                raise SimulatedTradeExecutionBlocked(
                    "V2 settlement exchange differs from its original identity binding"
                )
            return source_exchange
        raise SimulatedTradeExecutionBlocked(
            "pending settlement has no immutable original execution-plan binding"
        )

    def _now(self, clock: SimulatedTradeExecutionClock) -> datetime:
        """Read and validate the fresh clock only after all row locks are held."""

        return _aware_time(clock.now())

    def _release_pending_rows(
        self,
        *,
        position: PositionModel | None,
        pending_rows: list[SimulatedTradeModel],
        evidence: ExecutionCalendarEvidence,
        through_session: date,
        released_at: datetime,
    ) -> tuple[PositionModel | None, int]:
        """Release only rows whose stored lag elapsed under this complete current snapshot."""

        # Validate the complete locked batch before changing any available-share
        # value. Version 0 is the explicit pre-binding/legacy state and cannot
        # prove which original plan authorized a pending release.
        for row in pending_rows:
            if self._pending_source_exchange(row) != evidence.snapshot.exchange:
                raise SimulatedTradeExecutionBlocked(
                    "current calendar exchange differs from the frozen trade source exchange"
                )

        if pending_rows and position is None:
            raise SimulatedTradeExecutionBlocked(
                "pending settlement exists without its account/security position"
            )
        if position is not None:
            quantity = validate_ledger_quantity(position.quantity, "position.quantity")
            available = validate_ledger_quantity(
                position.available_quantity,
                "position.available_quantity",
            )
            if available > quantity:
                raise SimulatedTradeExecutionBlocked(
                    "available position quantity exceeds the recorded total quantity"
                )
        released_count = 0
        publication = evidence.publication
        if publication is None:
            raise SimulatedTradeExecutionBlocked(
                "settlement release requires a formal calendar publication binding"
            )
        for row in pending_rows:
            trade_session = row.settlement_market_session
            lag = row.settlement_lag_sessions
            if type(trade_session) is not date or type(lag) is not int or lag < 0:
                raise SimulatedTradeExecutionBlocked(
                    "pending trade lacks its immutable original settlement lag/session"
                )
            expected_exchange = (
                row.settlement_market
                if row.settlement_plan_binding_version == 1
                else row.settlement_exchange
            )
            if expected_exchange != evidence.snapshot.exchange:
                raise SimulatedTradeExecutionBlocked(
                    "current calendar exchange differs from the frozen trade source exchange"
                )
            try:
                elapsed = evidence.elapsed_open_sessions(trade_session, through_session)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise SimulatedTradeExecutionBlocked(
                    "current calendar does not prove the original settlement interval"
                ) from error
            if elapsed < lag:
                continue
            assert position is not None
            trade_quantity = validate_ledger_quantity(row.quantity, "pending_trade.quantity")
            total_quantity = validate_ledger_quantity(position.quantity, "position.quantity")
            available_quantity = validate_ledger_quantity(
                position.available_quantity,
                "position.available_quantity",
            )
            next_available = validate_ledger_quantity(
                available_quantity + trade_quantity,
                "position.available_quantity_after_release",
            )
            if next_available > total_quantity:
                raise SimulatedTradeExecutionBlocked(
                    "releasing a pending trade would exceed the total recorded quantity"
                )
            position.available_quantity = next_available
            position.save(
                using=self._using, update_fields=["available_quantity", "last_update_date"]
            )
            row.settlement_status = "released"
            row.settlement_released_at = released_at
            row.settlement_release_session = through_session
            self._set_release_evidence(row, evidence)
            row.save(
                using=self._using,
                update_fields=[
                    "settlement_status",
                    "settlement_released_at",
                    "settlement_release_session",
                    "settlement_release_calendar_snapshot_id",
                    "settlement_release_calendar_content_hash",
                    "settlement_release_calendar_record_digest",
                    "settlement_release_calendar_publication_id",
                    "settlement_release_calendar_publication_hash",
                    "settlement_release_calendar_policy_hash",
                    "settlement_release_calendar_evidence_hash",
                    "settlement_release_calendar_timezone",
                ],
            )
            released_count += 1
        return position, released_count

    def _set_release_evidence(
        self,
        row: SimulatedTradeModel,
        evidence: ExecutionCalendarEvidence,
    ) -> None:
        """Save the actual release proof separately from the buy-time forecast."""

        publication = evidence.publication
        if publication is None:
            raise SimulatedTradeExecutionBlocked("calendar release proof has no publication")
        row.settlement_release_calendar_snapshot_id = evidence.snapshot.snapshot_id
        row.settlement_release_calendar_content_hash = evidence.snapshot.content_hash
        row.settlement_release_calendar_record_digest = evidence.snapshot.record_digest
        row.settlement_release_calendar_publication_id = publication.publication_id
        row.settlement_release_calendar_publication_hash = publication.publication_hash
        row.settlement_release_calendar_policy_hash = publication.policy_hash
        row.settlement_release_calendar_evidence_hash = evidence.evidence_hash
        row.settlement_release_calendar_timezone = publication.timezone_name

    def _apply_trade(
        self,
        *,
        account: SimulatedAccountModel,
        position: PositionModel | None,
        plan: SettlementPlan,
        fee_policy: SimulatedFeePolicyV2,
        execution_time: datetime,
    ) -> SimulatedTradeExecutionReceipt:
        """Apply one buy or sell with the locked ledger values and exact fee snapshot."""

        intent = plan.intent
        try:
            if type(plan) is SettlementExecutionPlanV2:
                plan_binding: SettlementPlanBinding = bind_settlement_execution_plan_v2(
                    plan,
                    executed_at=execution_time,
                )
                binding_version = 2
                settlement_exchange: str | None = plan.identity_evidence.source_exchange
            else:
                plan_binding = bind_settlement_execution_plan(plan, executed_at=execution_time)
                binding_version = 1
                settlement_exchange = None
            plan_binding_payload = plan_binding.to_payload()
            plan_binding_hash = plan_binding.content_hash
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "settlement execution plan could not be sealed for persistence"
            ) from error
        if (
            type(account.current_cash) is not Decimal
            or type(account.current_market_value) is not Decimal
        ):
            raise SimulatedTradeExecutionBlocked("account money fields are not exact Decimals")
        cash = validate_ledger_money(account.current_cash, "account.current_cash")
        market_value = validate_ledger_money(
            account.current_market_value,
            "account.current_market_value",
        )
        amount = plan.amount
        fees = fee_policy.calculate_for(
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            side=intent.side,
            amount=amount,
            as_of=execution_time,
        )
        total_fees = fees.total_fee
        next_position: PositionModel | None = position
        if intent.side is SimulatedTradeSide.BUY:
            total_cost = _money_sum(amount, total_fees)
            if cash < total_cost:
                raise SimulatedTradeExecutionBlocked("account cash is insufficient for this buy")
            next_cash = validate_ledger_money(cash - total_cost, "account.current_cash_after_buy")
            old_position_value = (
                validate_ledger_money(position.market_value, "position.market_value")
                if position is not None
                else Decimal("0.00")
            )
            next_position = self._apply_buy_position(
                position=position,
                intent=plan.intent,
                total_cost=total_cost,
                market_session=plan.market_session,
                released_immediately=plan.settlement_lag_sessions == 0,
            )
            next_market_value = _rebased_account_market_value(
                market_value,
                old_position_value,
                validate_ledger_money(
                    next_position.market_value, "position.market_value_after_buy"
                ),
            )
            realized_pnl = None
            realized_pnl_pct = None
            settlement_status = "released" if plan.settlement_lag_sessions == 0 else "pending"
        else:
            if position is None:
                raise SimulatedTradeExecutionBlocked("sell requires an existing position")
            total_cost = total_fees
            net_proceeds = amount - total_fees
            if net_proceeds < 0 and cash < -net_proceeds:
                raise SimulatedTradeExecutionBlocked(
                    "account cash cannot cover the net sell fee debit"
                )
            next_cash = _money_sum(cash, net_proceeds)
            old_position_value = validate_ledger_money(
                position.market_value,
                "position.market_value_before_sell",
            )
            next_position, realized_pnl, realized_pnl_pct = self._apply_sell_position(
                position=position,
                intent=plan.intent,
                amount=amount,
                total_cost=total_cost,
                market_session=plan.market_session,
            )
            new_position_value = (
                validate_ledger_money(
                    next_position.market_value,
                    "position.market_value_after_sell",
                )
                if next_position is not None
                else Decimal("0.00")
            )
            next_market_value = _rebased_account_market_value(
                market_value,
                old_position_value,
                new_position_value,
            )
            settlement_status = None

        account.current_cash = next_cash
        account.current_market_value = next_market_value
        account.total_value = _money_sum(next_cash, next_market_value)
        account.total_trades += 1
        if realized_pnl is not None and realized_pnl > 0:
            account.winning_trades += 1
        account.last_trade_date = plan.market_session
        account.save(
            using=self._using,
            update_fields=[
                "current_cash",
                "current_market_value",
                "total_value",
                "total_trades",
                "winning_trades",
                "last_trade_date",
                "updated_at",
            ],
        )

        evidence = plan.calendar_evidence
        publication = evidence.publication
        if publication is None:
            raise SimulatedTradeExecutionBlocked("trade calendar binding is missing")
        fee_schedule = fee_policy.fee_schedule_v1
        fee_payload = fee_policy.to_payload()
        immediate_release = (
            intent.side is SimulatedTradeSide.BUY and plan.settlement_lag_sessions == 0
        )
        trade = SimulatedTradeModel._default_manager.using(self._using).create(
            account=account,
            asset_code=intent.asset_code,
            asset_name=intent.asset_name,
            asset_type=intent.asset_type,
            action=intent.side.value,
            quantity=intent.quantity,
            price=intent.price,
            amount=amount,
            commission=fees.commission,
            transfer_fee=fees.transfer_fee,
            stamp_duty=fees.stamp_duty,
            slippage=fees.slippage,
            total_cost=total_cost,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            reason=intent.reason,
            signal_id=intent.signal_id,
            order_date=plan.market_session,
            execution_date=plan.market_session,
            execution_time=execution_time,
            status="executed",
            idempotency_key=intent.idempotency_key,
            request_payload_hash=intent.request_payload_hash,
            settlement_plan_binding_version=binding_version,
            settlement_plan_binding_payload=plan_binding_payload,
            settlement_plan_binding_hash=plan_binding_hash,
            fee_config_id=fee_schedule.config_id,
            fee_schedule_hash=fee_policy.content_hash,
            fee_schedule_snapshot=fee_payload,
            fee_precision_basis=fee_schedule.precision_basis.value,
            fee_calculation_purpose=fee_schedule.calculation_purpose.value,
            fee_rounding_policy=fee_schedule.rounding_policy.value,
            settlement_status=settlement_status,
            settlement_security_id=intent.security_id,
            settlement_market=intent.market,
            settlement_exchange=settlement_exchange,
            settlement_board=intent.board,
            settlement_market_session=plan.market_session,
            settlement_lag_sessions=plan.settlement_lag_sessions,
            settlement_bundle_id=plan.settlement_bundle_id,
            settlement_bundle_version=plan.settlement_bundle_version,
            settlement_bundle_hash=plan.settlement_bundle_hash,
            settlement_policy_id=plan.settlement_policy_id,
            settlement_policy_version=plan.settlement_policy_version,
            settlement_policy_hash=plan.settlement_policy_hash,
            execution_rule_v2_hash=plan.execution_rule_v2_hash,
            settlement_release_date=plan.settlement_release_date,
            settlement_calendar_snapshot_id=evidence.snapshot.snapshot_id,
            settlement_calendar_content_hash=evidence.snapshot.content_hash,
            settlement_calendar_record_digest=evidence.snapshot.record_digest,
            settlement_calendar_publication_id=publication.publication_id,
            settlement_calendar_publication_hash=publication.publication_hash,
            settlement_calendar_policy_hash=publication.policy_hash,
            settlement_calendar_evidence_hash=evidence.evidence_hash,
            settlement_calendar_timezone=publication.timezone_name,
            settlement_released_at=execution_time if immediate_release else None,
            settlement_release_session=plan.market_session if immediate_release else None,
            settlement_release_calendar_snapshot_id=(
                evidence.snapshot.snapshot_id if immediate_release else None
            ),
            settlement_release_calendar_content_hash=(
                evidence.snapshot.content_hash if immediate_release else None
            ),
            settlement_release_calendar_record_digest=(
                evidence.snapshot.record_digest if immediate_release else None
            ),
            settlement_release_calendar_publication_id=(
                publication.publication_id if immediate_release else None
            ),
            settlement_release_calendar_publication_hash=(
                publication.publication_hash if immediate_release else None
            ),
            settlement_release_calendar_policy_hash=(
                publication.policy_hash if immediate_release else None
            ),
            settlement_release_calendar_evidence_hash=(
                evidence.evidence_hash if immediate_release else None
            ),
            settlement_release_calendar_timezone=(
                publication.timezone_name if immediate_release else None
            ),
        )
        SimulatedTradeModel._default_manager.using(self._using).filter(pk=trade.pk).update(
            execution_time=execution_time
        )
        # Keep the explicit settlement-clock write and its in-memory value aligned.
        # The model now also preserves supplied instants via its current-time default.
        trade.execution_time = execution_time
        return self._receipt(trade)

    def _apply_buy_position(
        self,
        *,
        position: PositionModel | None,
        intent: SimulatedTradeIntent,
        total_cost: Decimal,
        market_session: date,
        released_immediately: bool,
    ) -> PositionModel:
        """Add an exact buy while preserving every preexisting sellable share."""

        if type(intent) is not SimulatedTradeIntent:
            raise SimulatedTradeExecutionBlocked("buy position requires a typed order intent")
        new_quantity = intent.quantity
        market_value = _multiply_money(new_quantity, intent.price, "position.market_value")
        if position is None:
            avg_cost = _average_cost(total_cost, new_quantity)
            return PositionModel._default_manager.using(self._using).create(
                account_id=intent.account_id,
                asset_code=intent.asset_code,
                asset_name=intent.asset_name,
                asset_type=intent.asset_type,
                quantity=new_quantity,
                available_quantity=(new_quantity if released_immediately else Decimal("0")),
                avg_cost=avg_cost,
                total_cost=total_cost,
                current_price=intent.price,
                market_value=market_value,
                unrealized_pnl=market_value - total_cost,
                unrealized_pnl_pct=_percentage(market_value - total_cost, total_cost),
                first_buy_date=market_session,
                signal_id=intent.signal_id,
                entry_reason=intent.reason,
            )
        self._validate_position(position)
        if position.is_invalidated:
            raise SimulatedTradeExecutionBlocked("invalidated position cannot receive a new buy")
        if position.asset_type != intent.asset_type:
            raise SimulatedTradeExecutionBlocked("position asset type differs from buy intent")
        old_quantity = validate_ledger_quantity(position.quantity, "position.quantity")
        old_available = validate_ledger_quantity(
            position.available_quantity,
            "position.available_quantity",
        )
        old_cost = validate_ledger_money(position.total_cost, "position.total_cost")
        next_quantity = validate_ledger_quantity(
            old_quantity + new_quantity,
            "position.quantity_after_buy",
            allow_zero=False,
        )
        next_cost = _money_sum(old_cost, total_cost)
        next_market_value = _multiply_money(next_quantity, intent.price, "position.market_value")
        next_avg_cost = _average_cost(next_cost, next_quantity)
        next_available = validate_ledger_quantity(
            old_available + (new_quantity if released_immediately else Decimal("0")),
            "position.available_quantity_after_buy",
        )
        if next_available > next_quantity:
            raise SimulatedTradeExecutionBlocked("buy would corrupt sellable quantity")
        position.quantity = next_quantity
        position.available_quantity = next_available
        position.avg_cost = next_avg_cost
        position.total_cost = next_cost
        position.current_price = intent.price
        position.market_value = next_market_value
        position.unrealized_pnl = next_market_value - next_cost
        position.unrealized_pnl_pct = _percentage(position.unrealized_pnl, next_cost)
        position.last_update_date = market_session
        position.signal_id = intent.signal_id
        position.entry_reason = intent.reason or position.entry_reason
        position.save(
            using=self._using,
            update_fields=[
                "quantity",
                "available_quantity",
                "avg_cost",
                "total_cost",
                "current_price",
                "market_value",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "last_update_date",
                "signal_id",
                "entry_reason",
            ],
        )
        return position

    def _apply_sell_position(
        self,
        *,
        position: PositionModel,
        intent: SimulatedTradeIntent,
        amount: Decimal,
        total_cost: Decimal,
        market_session: date,
    ) -> tuple[PositionModel | None, Decimal, float]:
        """Sell only explicitly available shares and preserve exact remaining cost basis."""

        if type(intent) is not SimulatedTradeIntent:
            raise SimulatedTradeExecutionBlocked("sell position requires a typed order intent")
        self._validate_position(position)
        if position.asset_type != intent.asset_type:
            raise SimulatedTradeExecutionBlocked("position asset type differs from sell intent")
        quantity = validate_ledger_quantity(position.quantity, "position.quantity")
        available = validate_ledger_quantity(
            position.available_quantity,
            "position.available_quantity",
        )
        if intent.quantity > available:
            raise SimulatedTradeExecutionBlocked(
                "sell quantity exceeds explicitly available shares"
            )
        if intent.quantity > quantity:
            raise SimulatedTradeExecutionBlocked("sell quantity exceeds total shares")
        stored_cost = validate_ledger_money(
            position.total_cost,
            "position.total_cost",
            allow_zero=False,
        )
        cost_basis = _allocate_sale_cost_basis(
            total_cost=stored_cost,
            sold_quantity=intent.quantity,
            total_quantity=quantity,
        )
        realized_pnl = _signed_money(amount - total_cost - cost_basis, "realized_pnl")
        realized_pct = _percentage(realized_pnl, cost_basis)
        remaining = validate_ledger_quantity(
            quantity - intent.quantity,
            "position.quantity_after_sell",
        )
        if remaining == 0:
            position.delete(using=self._using)
            return None, realized_pnl, realized_pct
        remaining_cost = validate_ledger_money(
            stored_cost - cost_basis,
            "position.remaining_cost_basis",
            allow_zero=False,
        )
        remaining_market_value = _multiply_money(
            remaining,
            intent.price,
            "position.market_value_after_sell",
        )
        position.quantity = remaining
        position.available_quantity = validate_ledger_quantity(
            available - intent.quantity,
            "position.available_quantity_after_sell",
        )
        position.avg_cost = _average_cost(remaining_cost, remaining)
        position.total_cost = remaining_cost
        position.current_price = intent.price
        position.market_value = remaining_market_value
        position.unrealized_pnl = remaining_market_value - remaining_cost
        position.unrealized_pnl_pct = _percentage(position.unrealized_pnl, remaining_cost)
        position.last_update_date = market_session
        position.save(
            using=self._using,
            update_fields=[
                "quantity",
                "available_quantity",
                "avg_cost",
                "total_cost",
                "current_price",
                "market_value",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "last_update_date",
            ],
        )
        return position, realized_pnl, realized_pct

    def _validate_position(self, position: PositionModel) -> None:
        """Reject malformed historic aggregates without rebuilding missing lot history."""

        quantity = validate_ledger_quantity(position.quantity, "position.quantity")
        available = validate_ledger_quantity(
            position.available_quantity,
            "position.available_quantity",
        )
        validate_ledger_money(position.total_cost, "position.total_cost")
        validate_ledger_money(position.market_value, "position.market_value")
        validate_ledger_price(position.current_price, "position.current_price", allow_zero=False)
        validate_ledger_price(position.avg_cost, "position.avg_cost", allow_zero=False)
        if quantity <= 0 or available > quantity:
            raise SimulatedTradeExecutionBlocked(
                "historic position aggregate has inconsistent total/available quantities"
            )

    def _receipt(
        self,
        row: SimulatedTradeModel | None,
        *,
        replayed: bool = False,
    ) -> SimulatedTradeExecutionReceipt:
        """Delegate to the existing strict persisted-binding receipt reader."""

        return _build_simulated_trade_execution_receipt(row, replayed=replayed)
