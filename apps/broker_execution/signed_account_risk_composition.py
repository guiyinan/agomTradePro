"""Read live signed QMT balances under the binding used by the snapshot writer."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.db import connections
from django.utils import timezone

from apps.broker_execution.application.execution_contract_capabilities import (
    parse_agent_execution_contracts,
)
from apps.broker_execution.application.execution_price_guard import require_current_execution_price
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionValidationError,
)
from apps.broker_execution.benchmark_day_source_composition import (
    SignedBrokerBalances,
    read_benchmark_broker_balances,
)
from apps.broker_execution.domain.connection_freshness import (
    HEARTBEAT_FRESHNESS,
    heartbeat_times_are_fresh,
)
from apps.broker_execution.domain.plan_order_binding import BrokerPlanOrderBinding
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    TradingControlModel,
)
from apps.broker_execution.infrastructure.order_risk_reservations import (
    OrderReservations,
    read_order_reservations,
    signed_plan_buy_fee,
)


@dataclass(frozen=True, slots=True)
class SignedOrderBalances:
    """Complete live account inputs, the symbol's marked value and original freshness deadline."""

    report: SignedBrokerBalances
    symbol_value: Decimal
    cash_after_reservations: Decimal
    projected_position_value: Decimal
    valid_until: datetime


def _heartbeat_deadline(agent: BrokerAgentModel, now: datetime) -> datetime:
    health = agent.health_snapshot
    if (
        not agent.is_active
        or agent.status != BrokerAgentModel.STATUS_ONLINE
        or not agent.qmt_connected
        or not isinstance(health, dict)
    ):
        raise BrokerExecutionConflictError("signed_account_risk_agent_offline")
    try:
        capabilities = parse_agent_execution_contracts(
            health.get("execution_constraint_schemas", [])
        )
        observed = datetime.fromisoformat(health["source_observed_at"])
    except (KeyError, TypeError, ValueError, BrokerExecutionValidationError) as error:
        raise BrokerExecutionConflictError("signed_account_risk_agent_unavailable") from error
    if not capabilities.supports_submission_v2 or not heartbeat_times_are_fresh(
        source_observed_at=observed, received_at=agent.last_heartbeat_at, evaluated_at=now
    ):
        raise BrokerExecutionConflictError("signed_account_risk_agent_unavailable")
    return observed + HEARTBEAT_FRESHNESS


def _order_symbol_value(
    *,
    report: SignedBrokerBalances,
    reservations: OrderReservations,
    estimated_buy_fee: Decimal,
    binding: BrokerAccountBindingModel,
    asset_code: str,
    side: str,
    quantity: Decimal,
    limit_price: Decimal,
) -> Decimal:
    if any(position.quantity > 0 and position.market_value <= 0 for position in report.positions):
        raise BrokerExecutionConflictError("signed_account_risk_position_value_unavailable")
    held = next((p for p in report.positions if p.asset_code == asset_code), None)
    if quantity * limit_price > binding.max_single_order_amount:
        raise BrokerExecutionConflictError("signed_account_risk_order_amount_limit")
    if side == "BUY":
        if (
            quantity * limit_price
            + estimated_buy_fee
            + reservations.buy_amount
            + reservations.buy_estimated_fees
            > report.cash_available
        ):
            raise BrokerExecutionConflictError("signed_account_risk_cash_insufficient")
        held_symbols = {
            p.asset_code for p in report.positions if p.quantity > 0
        } | reservations.buy_symbols
        if asset_code not in held_symbols and len(held_symbols) >= binding.max_position_count:
            raise BrokerExecutionConflictError("signed_account_risk_position_count")
    elif held is None or quantity + reservations.sell_quantity > held.available_quantity:
        raise BrokerExecutionConflictError("signed_account_risk_sellable_insufficient")
    return (held.market_value if held is not None else Decimal(0)) + reservations.symbol_buy_amount


def locked_signed_order_balances(
    *,
    user_id: int,
    account_id: int,
    client_order_id: UUID,
    plan_binding: BrokerPlanOrderBinding,
    asset_code: str,
    side: str,
    quantity: Decimal,
    limit_price: Decimal,
    using: str,
) -> SignedOrderBalances:
    """Check a proposed order against the most recent authenticated QMT report and credential."""
    db = connections[using]
    if using != "default" or db.vendor != "postgresql" or not db.in_atomic_block:
        raise BrokerExecutionConflictError("signed_account_risk_transaction_required")
    if (
        type(client_order_id) is not UUID
        or side not in ("BUY", "SELL")
        or type(quantity) is not Decimal
        or not quantity.is_finite()
        or quantity <= 0
        or type(limit_price) is not Decimal
        or not limit_price.is_finite()
        or limit_price <= 0
        or not asset_code
        or asset_code != asset_code.strip().upper()
    ):
        raise BrokerExecutionConflictError("signed_account_risk_order_invalid")
    with db.cursor() as cur:
        cur.execute("SHOW transaction_isolation")
        if cur.fetchone() != ("read committed",):
            raise BrokerExecutionConflictError("signed_account_risk_read_committed_required")
        cur.execute("LOCK TABLE broker_execution_trading_control IN SHARE MODE NOWAIT")
    bindings = list(
        BrokerAccountBindingModel._default_manager.using(using)
        .select_related("agent")
        .select_for_update(nowait=True)
        .filter(user_id=user_id, account_id=account_id, agent__user_id=user_id, is_active=True)
        .order_by("pk")[:2]
    )
    if (
        len(bindings) != 1
        or not bindings[0].auto_execution_enabled
        or TradingControlModel._default_manager.using(using)
        .filter(user_id=user_id, account_id__in=(0, account_id), kill_switch_active=True)
        .exists()
    ):
        raise BrokerExecutionConflictError("signed_account_risk_trading_stopped")
    binding = bindings[0]
    if not isinstance(binding.allowed_symbols, list) or asset_code not in binding.allowed_symbols:
        raise BrokerExecutionConflictError("signed_account_risk_symbol_disabled")
    latest = (
        BrokerAccountSnapshotModel._default_manager.using(using)
        .filter(agent_id=binding.agent_id, user_id=user_id, account_id=account_id)
        .order_by("-captured_at", "-pk")
        .values_list("pk", flat=True)
        .first()
    )
    report = (
        read_benchmark_broker_balances(
            snapshot_id=latest, owner_user_id=user_id, account_id=account_id, using=using
        )
        if latest is not None
        else None
    )
    if report is None or report.agent_pk != binding.agent_id or report.currency != "CNY":
        raise BrokerExecutionConflictError("signed_account_risk_complete_report_unavailable")
    now = timezone.now()
    heartbeat = _heartbeat_deadline(binding.agent, now)
    expires = min(
        report.sampling_challenge_at or report.captured_at, report.captured_at
    ) + timedelta(seconds=binding.max_snapshot_age_seconds)
    if not report.captured_at <= report.received_at <= now < expires:
        raise BrokerExecutionConflictError("signed_account_risk_report_stale")
    credential = (
        BrokerAgentCredentialModel._default_manager.using(using)
        .select_for_update(nowait=True)
        .filter(
            credential_id=report.credential_id,
            agent_id=report.agent_pk,
            revoked_at__isnull=True,
            created_at__lte=report.received_at,
            expires_at__gt=now,
        )
        .first()
    )
    if (
        credential is None
        or not isinstance(credential.scopes, list)
        or "agent.snapshots.write" not in credential.scopes
        or not isinstance(credential.allowed_account_ids, list)
        or not any(type(i) is int and i == account_id for i in credential.allowed_account_ids)
    ):
        raise BrokerExecutionConflictError("signed_account_risk_credential_unavailable")
    reservations = read_order_reservations(
        user_id=user_id,
        account_id=account_id,
        client_order_id=client_order_id,
        asset_code=asset_code,
        sampling_challenge_at=report.sampling_challenge_at,
        using=using,
    )
    proposed_fee = (
        signed_plan_buy_fee(
            plan=plan_binding,
            client_order_id=client_order_id,
            account_id=account_id,
            asset_code=asset_code,
            quantity=quantity,
            limit_price=limit_price,
        )
        if side == "BUY"
        else Decimal(0)
    )
    symbol_value = _order_symbol_value(
        report=report,
        reservations=reservations,
        estimated_buy_fee=proposed_fee,
        binding=binding,
        asset_code=asset_code,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
    )
    quote = require_current_execution_price(
        asset_code=asset_code,
        limit_price=limit_price,
        max_deviation=binding.price_deviation_limit_pct,
    )
    deadline = min(quote, heartbeat, expires, credential.expires_at)
    if timezone.now() >= deadline:
        raise BrokerExecutionConflictError("signed_account_risk_expired")
    return SignedOrderBalances(
        report,
        symbol_value,
        max(
            Decimal(0),
            report.cash_available
            - reservations.buy_amount
            - reservations.buy_estimated_fees
            - proposed_fee,
        ),
        report.position_market_value + reservations.buy_amount,
        deadline,
    )
