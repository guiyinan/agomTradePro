"""Read-only validation of persisted simulated settlement-plan bindings."""

from __future__ import annotations

from typing import TypeAlias

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SimulatedSettlementPlanBindingV1,
    SimulatedSettlementPlanBindingV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel

SettlementPlanBinding: TypeAlias = (
    SimulatedSettlementPlanBindingV1 | SimulatedSettlementPlanBindingV2
)


def validate_stored_settlement_plan_binding(
    *,
    row: SimulatedTradeModel,
    intent: SimulatedTradeIntent,
    fee_policy_v2: SimulatedFeePolicyV2 | None,
) -> SettlementPlanBinding | None:
    """Revalidate a stored original-plan envelope against its trade row.

    Version 0 is a deliberately unbound pre-existing row and can only use
    the legacy receipt path. Versions 1 and 2 require complete independently
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
    if version not in (1, 2):
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
    else:
        if row.settlement_exchange is None:
            raise SimulatedTradeExecutionBlocked(
                "V2 settlement binding is missing its explicit source exchange"
            )
        binding_v2 = SimulatedSettlementPlanBindingV2.from_payload(payload)
        binding = binding_v2
        common_binding = binding_v2.common_binding
        binding_content_hash = binding_v2.content_hash
        identity = binding_v2.identity_evidence
        identity_row_values: tuple[tuple[str, object, object], ...] = (
            ("identity.security_id", identity.security_id, intent.security_id),
            ("identity.asset_code", identity.asset_code, row.asset_code),
            ("identity.source_exchange", identity.source_exchange, row.settlement_exchange),
            ("identity.rule_market", identity.rule_market, row.settlement_market),
            ("identity.board", identity.board, row.settlement_board),
        )
        for field_name, binding_value, row_value in identity_row_values:
            if binding_value != row_value:
                raise SimulatedTradeExecutionBlocked(
                    f"V2 instrument identity differs from trade field {field_name}"
                )
        source_exchange = identity.source_exchange
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
