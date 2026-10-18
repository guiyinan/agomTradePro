"""Build and validate persisted simulated settlement-plan bindings."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TypeAlias

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_current_reference import (
    SettlementExecutionPlanV3,
    SimulatedSettlementPlanBindingV3,
    bind_settlement_execution_plan_v3,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import SettlementExecutionPlanV2
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SimulatedSettlementPlanBindingV1,
    SimulatedSettlementPlanBindingV2,
    bind_settlement_execution_plan,
    bind_settlement_execution_plan_v2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    SettlementExecutionPlan,
    SimulatedTradeExecutionReceipt,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    calculate_trade_fees,
    validate_ledger_money,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel

SettlementPlanBinding: TypeAlias = (
    SimulatedSettlementPlanBindingV1
    | SimulatedSettlementPlanBindingV2
    | SimulatedSettlementPlanBindingV3
)

_MONEY_CENT = Decimal("0.01")


def build_settlement_plan_binding_for_execution(
    plan: SettlementExecutionPlan | SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
    *,
    executed_at: datetime,
) -> tuple[SettlementPlanBinding, int, str | None]:
    """Seal one exact plan and return its existing storage version and exchange."""

    if type(plan) is SettlementExecutionPlanV3:
        binding_v3 = bind_settlement_execution_plan_v3(plan, executed_at=executed_at)
        return binding_v3, 3, plan.identity_evidence.source_exchange
    if type(plan) is SettlementExecutionPlanV2:
        binding_v2 = bind_settlement_execution_plan_v2(plan, executed_at=executed_at)
        return binding_v2, 2, plan.identity_evidence.source_exchange
    if type(plan) is SettlementExecutionPlan:
        return bind_settlement_execution_plan(plan, executed_at=executed_at), 1, None
    raise SimulatedTradeExecutionBlocked("settlement plan binding type is unsupported")


def build_simulated_trade_execution_receipt(
    row: SimulatedTradeModel | None,
    *,
    replayed: bool = False,
) -> SimulatedTradeExecutionReceipt:
    """Validate and map one exact persisted normal-simulation row."""

    if row is None:
        raise SimulatedTradeExecutionBlocked("idempotency result is not available")
    if (
        row.idempotency_key is None
        or row.request_payload_hash is None
        or row.transfer_fee is None
        or row.stamp_duty is None
        or row.fee_schedule_snapshot is None
        or row.fee_schedule_hash is None
        or row.fee_config_id is None
        or row.settlement_security_id is None
        or row.settlement_market is None
        or row.settlement_board is None
    ):
        raise SimulatedTradeExecutionBlocked("persisted UoW trade binding is incomplete")
    try:
        account_user_id = row.account.user_id
        if type(account_user_id) is not int:
            raise SimulatedTradeExecutionBlocked(
                "persisted UoW account has no stable owner identity"
            )
        intent = SimulatedTradeIntent(
            account_id=row.account_id,
            user_id=account_user_id,
            idempotency_key=row.idempotency_key,
            side=SimulatedTradeSide(row.action),
            security_id=row.settlement_security_id,
            asset_code=row.asset_code,
            asset_name=row.asset_name,
            asset_type=row.asset_type,
            market=row.settlement_market,
            board=row.settlement_board,
            quantity=row.quantity,
            price=row.price,
            reason=row.reason,
            signal_id=row.signal_id,
        )
        if intent.request_payload_hash != row.request_payload_hash:
            raise SimulatedTradeExecutionBlocked(
                "persisted trade fields no longer match their idempotency payload hash"
            )
        snapshot = row.fee_schedule_snapshot
        if type(snapshot) is not dict:
            raise SimulatedTradeExecutionBlocked("persisted fee snapshot is not an object")
        schema = snapshot.get("schema")
        fee_policy_v2: SimulatedFeePolicyV2 | None = None
        if schema is None:
            fee_schedule = ExecutionFeeSchedule.from_payload(snapshot)
            if (
                fee_schedule.config_id != row.fee_config_id
                or fee_schedule.content_hash != row.fee_schedule_hash
                or fee_schedule.precision_basis.value != row.fee_precision_basis
                or fee_schedule.calculation_purpose.value != row.fee_calculation_purpose
                or fee_schedule.rounding_policy.value != row.fee_rounding_policy
            ):
                raise SimulatedTradeExecutionBlocked(
                    "persisted V1 fee snapshot no longer matches its metadata hash"
                )
        elif schema == "simulated-fee-policy.v2":
            fee_policy_v2 = SimulatedFeePolicyV2.from_payload(snapshot)
            fee_schedule = fee_policy_v2.fee_schedule_v1
            if (
                fee_schedule.config_id != row.fee_config_id
                or fee_policy_v2.content_hash != row.fee_schedule_hash
                or fee_schedule.precision_basis.value != row.fee_precision_basis
                or fee_schedule.calculation_purpose.value != row.fee_calculation_purpose
                or fee_schedule.rounding_policy.value != row.fee_rounding_policy
            ):
                raise SimulatedTradeExecutionBlocked(
                    "persisted V2 fee snapshot no longer matches its metadata hash"
                )
            fee_policy_v2.validate_at(row.execution_time)
        else:
            raise SimulatedTradeExecutionBlocked("persisted fee snapshot schema is unknown")
        amount = validate_ledger_money(
            (intent.quantity * intent.price).quantize(_MONEY_CENT, rounding=ROUND_HALF_EVEN),
            "persisted_trade.amount",
            allow_zero=False,
        )
        if amount != row.amount:
            raise SimulatedTradeExecutionBlocked(
                "persisted trade amount differs from its exact quantity and price"
            )
        if fee_policy_v2 is None:
            calculated_fees = calculate_trade_fees(
                fee_schedule,
                side=intent.side,
                amount=amount,
                market=intent.market,
            )
        else:
            calculated_fees = fee_policy_v2.calculate_for(
                asset_type=intent.asset_type,
                market=intent.market,
                board=intent.board,
                side=intent.side,
                amount=amount,
                as_of=row.execution_time,
            )
        if (
            calculated_fees.commission != row.commission
            or calculated_fees.transfer_fee != row.transfer_fee
            or calculated_fees.stamp_duty != row.stamp_duty
            or calculated_fees.slippage != row.slippage
        ):
            raise SimulatedTradeExecutionBlocked(
                "persisted fee components differ from their exact fee snapshot"
            )
        validate_stored_settlement_plan_binding(
            row=row,
            intent=intent,
            fee_policy_v2=fee_policy_v2,
        )
        receipt = SimulatedTradeExecutionReceipt(
            trade_id=int(row.pk),
            account_id=row.account_id,
            idempotency_key=row.idempotency_key,
            request_payload_hash=row.request_payload_hash,
            side=SimulatedTradeSide(row.action),
            asset_code=row.asset_code,
            quantity=row.quantity,
            price=row.price,
            amount=row.amount,
            commission=row.commission,
            transfer_fee=row.transfer_fee,
            stamp_duty=row.stamp_duty,
            slippage=row.slippage,
            total_cost=row.total_cost,
            settlement_status=row.settlement_status,
            settlement_release_date=row.settlement_release_date,
            replayed=replayed,
        )
        SimulatedTradeExecutionReceipt.__post_init__(receipt)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "persisted simulated trade failed exact receipt validation"
        ) from error
    return receipt


def pending_settlement_source_exchange(row: SimulatedTradeModel) -> str:
    """Validate a pending receipt and return its exact originally bound exchange."""

    build_simulated_trade_execution_receipt(row)
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
        binding = SimulatedSettlementPlanBindingV1.from_payload(payload)
        if binding.calendar_snapshot.exchange != row.settlement_market:
            raise SimulatedTradeExecutionBlocked(
                "legacy V1 calendar exchange differs from its original rule market"
            )
        return binding.calendar_snapshot.exchange
    if version == 2:
        binding_v2 = SimulatedSettlementPlanBindingV2.from_payload(payload)
        source_exchange = binding_v2.identity_evidence.source_exchange
        if row.settlement_exchange != source_exchange:
            raise SimulatedTradeExecutionBlocked(
                "V2 settlement exchange differs from its original identity binding"
            )
        return source_exchange
    if version == 3:
        binding_v3 = SimulatedSettlementPlanBindingV3.from_payload(payload)
        source_exchange = binding_v3.identity_evidence.source_exchange
        if row.settlement_exchange != source_exchange:
            raise SimulatedTradeExecutionBlocked(
                "V3 settlement exchange differs from its original identity binding"
            )
        return source_exchange
    raise SimulatedTradeExecutionBlocked(
        "pending settlement has no immutable original execution-plan binding"
    )


def validate_stored_settlement_plan_binding(
    *,
    row: SimulatedTradeModel,
    intent: SimulatedTradeIntent,
    fee_policy_v2: SimulatedFeePolicyV2 | None,
) -> SettlementPlanBinding | None:
    """Revalidate a stored original-plan envelope against its trade row.

    Version 0 is a deliberately unbound pre-existing row and can only use
    the legacy receipt path. Versions 1, 2, and 3 require complete independently
    hashed bindings; those digests are integrity checksums, not source
    signatures or substitutes for source revalidation.
    """

    version = row.settlement_plan_binding_version
    payload = row.settlement_plan_binding_payload
    supplied_hash = row.settlement_plan_binding_hash
    if type(version) is not int:
        raise SimulatedTradeExecutionBlocked("persisted settlement-plan binding version is invalid")
    if version == 0:
        if payload is not None or supplied_hash is not None or row.settlement_exchange is not None:
            raise SimulatedTradeExecutionBlocked(
                "legacy settlement-plan version unexpectedly contains binding data"
            )
        return None
    if version not in (1, 2, 3):
        raise SimulatedTradeExecutionBlocked(
            "persisted settlement-plan binding version is unsupported"
        )
    if type(row.status) is not str or row.status != "executed":
        raise SimulatedTradeExecutionBlocked(
            "bound simulated trade execution status is not executed"
        )
    if payload is None or type(supplied_hash) is not str:
        raise SimulatedTradeExecutionBlocked("persisted settlement-plan binding pair is incomplete")

    binding: SettlementPlanBinding
    common_binding: SimulatedSettlementPlanBindingV1
    binding_content_hash: str
    if version == 1:
        if row.settlement_exchange is not None:
            raise SimulatedTradeExecutionBlocked(
                "V1 settlement binding unexpectedly has a source-exchange column"
            )
        binding_v1 = SimulatedSettlementPlanBindingV1.from_payload(payload)
        binding = binding_v1
        common_binding = binding_v1
        binding_content_hash = binding_v1.content_hash
        source_exchange = binding_v1.calendar_snapshot.exchange
        if source_exchange != row.settlement_market:
            raise SimulatedTradeExecutionBlocked(
                "legacy V1 calendar exchange differs from its original rule market"
            )
    elif version == 2:
        if row.settlement_exchange is None:
            raise SimulatedTradeExecutionBlocked(
                "V2 settlement binding is missing its explicit source exchange"
            )
        binding_v2 = SimulatedSettlementPlanBindingV2.from_payload(payload)
        binding = binding_v2
        common_binding = binding_v2.common_binding
        binding_content_hash = binding_v2.content_hash
        identity_v2 = binding_v2.identity_evidence
        identity_row_values: tuple[tuple[str, object, object], ...] = (
            ("identity.security_id", identity_v2.security_id, intent.security_id),
            ("identity.asset_code", identity_v2.asset_code, row.asset_code),
            ("identity.source_exchange", identity_v2.source_exchange, row.settlement_exchange),
            ("identity.rule_market", identity_v2.rule_market, row.settlement_market),
            ("identity.board", identity_v2.board, row.settlement_board),
        )
        for field_name, binding_value, row_value in identity_row_values:
            if binding_value != row_value:
                raise SimulatedTradeExecutionBlocked(
                    f"V2 instrument identity differs from trade field {field_name}"
                )
        source_exchange = identity_v2.source_exchange
    else:
        if row.settlement_exchange is None:
            raise SimulatedTradeExecutionBlocked(
                "V3 settlement binding is missing its explicit source exchange"
            )
        binding_v3 = SimulatedSettlementPlanBindingV3.from_payload(payload)
        binding = binding_v3
        common_binding = binding_v3.common_binding
        binding_content_hash = binding_v3.content_hash
        current_identity = binding_v3.identity_evidence
        identity_row_values = (
            ("identity.security_id", current_identity.security_id, intent.security_id),
            ("identity.asset_code", current_identity.asset_code, row.asset_code),
            ("identity.source_exchange", current_identity.source_exchange, row.settlement_exchange),
            ("identity.rule_market", current_identity.rule_market, row.settlement_market),
            ("identity.board", current_identity.board, row.settlement_board),
        )
        for field_name, binding_value, row_value in identity_row_values:
            if binding_value != row_value:
                raise SimulatedTradeExecutionBlocked(
                    f"V3 instrument identity differs from trade field {field_name}"
                )
        try:
            current_identity.validate_for(intent=intent, as_of=row.execution_time)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "V3 current-reference identity is invalid at the stored execution time"
            ) from error
        source_exchange = current_identity.source_exchange
    if binding_content_hash != supplied_hash:
        raise SimulatedTradeExecutionBlocked(
            "persisted settlement-plan binding hash differs from its exact payload"
        )
    account_user_id = row.account.user_id
    if type(account_user_id) is not int or fee_policy_v2 is None:
        raise SimulatedTradeExecutionBlocked(
            "bound trade is missing its exact owner or V2 fee policy"
        )
    fee_snapshot = fee_policy_v2.to_payload()
    calendar_snapshot = common_binding.calendar_snapshot
    calendar_publication = common_binding.calendar_publication
    expected_row_values: tuple[tuple[str, object, object], ...] = (
        ("account_id", common_binding.account_id, row.account_id),
        ("user_id", common_binding.user_id, account_user_id),
        ("idempotency_key", common_binding.idempotency_key, row.idempotency_key),
        (
            "request_payload_hash",
            common_binding.request_payload_hash,
            row.request_payload_hash,
        ),
        ("executed_at", common_binding.executed_at, row.execution_time),
        ("market_session/order_date", common_binding.market_session, row.order_date),
        ("market_session/execution_date", common_binding.market_session, row.execution_date),
        (
            "market_session/settlement_market_session",
            common_binding.market_session,
            row.settlement_market_session,
        ),
        (
            "settlement_lag_sessions",
            common_binding.settlement_lag_sessions,
            row.settlement_lag_sessions,
        ),
        (
            "settlement_release_date",
            common_binding.settlement_release_date,
            row.settlement_release_date,
        ),
        (
            "settlement_bundle_id",
            common_binding.settlement_bundle_id,
            row.settlement_bundle_id,
        ),
        (
            "settlement_bundle_version",
            common_binding.settlement_bundle_version,
            row.settlement_bundle_version,
        ),
        (
            "settlement_bundle_hash",
            common_binding.settlement_bundle_hash,
            row.settlement_bundle_hash,
        ),
        (
            "settlement_policy_id",
            common_binding.settlement_policy_id,
            row.settlement_policy_id,
        ),
        (
            "settlement_policy_version",
            common_binding.settlement_policy_version,
            row.settlement_policy_version,
        ),
        (
            "settlement_policy_hash",
            common_binding.settlement_policy_hash,
            row.settlement_policy_hash,
        ),
        (
            "execution_rule_v2_hash",
            common_binding.execution_rule_v2_hash,
            row.execution_rule_v2_hash,
        ),
        (
            "calendar_evidence_hash",
            common_binding.calendar_evidence_hash,
            row.settlement_calendar_evidence_hash,
        ),
        (
            "calendar_snapshot_id",
            calendar_snapshot.snapshot_id,
            row.settlement_calendar_snapshot_id,
        ),
        ("calendar_exchange", calendar_snapshot.exchange, source_exchange),
        (
            "calendar_content_hash",
            calendar_snapshot.content_hash,
            row.settlement_calendar_content_hash,
        ),
        (
            "calendar_record_digest",
            calendar_snapshot.record_digest,
            row.settlement_calendar_record_digest,
        ),
        (
            "calendar_publication_id",
            calendar_publication.publication_id,
            row.settlement_calendar_publication_id,
        ),
        (
            "calendar_publication_hash",
            calendar_publication.publication_hash,
            row.settlement_calendar_publication_hash,
        ),
        (
            "calendar_policy_hash",
            calendar_publication.policy_hash,
            row.settlement_calendar_policy_hash,
        ),
        (
            "calendar_timezone",
            calendar_publication.timezone_name,
            row.settlement_calendar_timezone,
        ),
        ("fee_policy_schema", common_binding.fee_policy_schema, fee_snapshot.get("schema")),
        (
            "fee_policy_content_hash",
            common_binding.fee_policy_content_hash,
            row.fee_schedule_hash,
        ),
        (
            "fee_policy_hash",
            common_binding.fee_policy_content_hash,
            fee_policy_v2.content_hash,
        ),
    )
    for field_name, binding_value, row_value in expected_row_values:
        if binding_value != row_value:
            raise SimulatedTradeExecutionBlocked(
                f"persisted settlement-plan binding differs from trade field {field_name}"
            )
    if common_binding.request_payload_hash != intent.request_payload_hash:
        raise SimulatedTradeExecutionBlocked(
            "settlement-plan binding differs from the recomputed trade intent hash"
        )
    return binding
