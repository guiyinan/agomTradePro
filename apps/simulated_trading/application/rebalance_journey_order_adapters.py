"""Adapt the existing plan-bound preview and verified progress use cases."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanOrderBinding,
    TransitionPlanRevision,
)
from apps.simulated_trading.application.owner_order_payloads import owner_order_response_payload
from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyCommand,
    RebalanceJourneyUnavailable,
)
from apps.simulated_trading.application.transition_plan_execution import (
    PlanOrderPreviewCommand,
    PreviewTransitionPlanOrderUseCase,
)
from apps.simulated_trading.application.transition_plan_execution_progress import (
    GetTransitionPlanExecutionProgressUseCase,
    PlanExecutionProgressQuery,
    TransitionPlanExecutionProgress,
)
from apps.simulated_trading.domain.transition_plan_execution import (
    PlanExecutionAttemptProgress,
    PlanOrderExecutionProgress,
)


class JourneyPlanOrderPreviewer:
    """Pass one exact user-selected order to the ordinary signed preview flow."""

    def __init__(self, preview_use_case: PreviewTransitionPlanOrderUseCase) -> None:
        """Inject the existing preview use case without constructing repositories."""

        self._preview = preview_use_case

    def preview(
        self,
        *,
        command: RebalanceJourneyCommand,
        revision: TransitionPlanRevision,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Return a display payload and the untouched ordinary confirmation handoff."""

        _validate_preview_scope(command=command, revision=revision)
        if command.order_ordinal is None or command.request_key is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PREVIEW_INPUT_INVALID")
        if (
            command.order_content_hash is None
            or command.plan_order_binding_id is None
            or command.quantity is None
            or command.limit_price is None
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PREVIEW_INPUT_INVALID")
        request = PlanOrderPreviewCommand(
            actor_user_id=command.user_id,
            account_id=command.account_id,
            plan_id=revision.identity.plan_id,
            plan_version=revision.identity.version,
            expected_revision_hash=revision.identity.revision_hash,
            order_ordinal=command.order_ordinal,
            expected_order_content_hash=command.order_content_hash,
            expected_plan_order_binding_id=command.plan_order_binding_id,
            action_attempt_key=command.request_key,
            quantity=command.quantity,
            price=command.limit_price,
            reason=command.reason if command.reason is not None else "",
        )
        result = self._preview.execute(request)
        if (
            result.revision_recorded_at != revision.identity.recorded_at
            or result.binding.plan_id != revision.identity.plan_id
            or result.binding.family_id != revision.identity.family_id
            or result.binding.root_plan_id != revision.identity.root_plan_id
            or result.binding.plan_version != revision.identity.version
            or result.binding.revision_hash != revision.identity.revision_hash
            or result.binding.account_id != command.account_id
            or result.binding.owner_user_id != command.user_id
            or result.binding.order_ordinal != command.order_ordinal
            or result.binding.order_content_hash != command.order_content_hash
            or result.binding.plan_order_binding_id != command.plan_order_binding_id
            or result.binding.action_attempt_key != command.request_key
            or result.preview.result.reservation.quantity != command.quantity
            or result.preview.result.reservation.limit_price != command.limit_price
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PREVIEW_BINDING_INVALID")
        payload = owner_order_response_payload(result.preview)
        handoff = payload.get("continuation")
        if not isinstance(handoff, dict):
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PREVIEW_HANDOFF_MISSING")
        display_payload = {key: value for key, value in payload.items() if key != "continuation"}
        handoff_payload: dict[str, object] = {
            key: value for key, value in handoff.items() if isinstance(key, str)
        }
        if len(handoff_payload) != len(handoff) or not _owner_handoff_matches(
            handoff=handoff_payload,
            payload=display_payload,
            account_id=command.account_id,
            preview_token=result.preview.token,
            expires_at=result.preview.expires_at,
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PREVIEW_HANDOFF_MISSING")
        display: dict[str, object] = {
            "binding": result.binding.to_payload(),
            "revision_recorded_at": _instant_text(result.revision_recorded_at),
            "preview": display_payload,
        }
        return display, handoff_payload


class JourneyPlanProgressReader:
    """Serialize only the typed, verified progress returned by the read use case."""

    def __init__(self, progress_use_case: GetTransitionPlanExecutionProgressUseCase) -> None:
        """Inject the read-only progress use case; no ledger writer is accepted."""

        self._progress = progress_use_case

    def read(
        self,
        *,
        user_id: int,
        account_id: int,
        revision: TransitionPlanRevision,
    ) -> dict[str, object]:
        """Return exact balances, verified attempts, and unknowns without recomputing totals."""

        revision.__post_init__()
        if (
            type(user_id) is not int
            or user_id <= 0
            or type(account_id) is not int
            or account_id <= 0
            or account_id != revision.identity.account_id
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_SCOPE_INVALID")
        progress = self._progress.execute(
            PlanExecutionProgressQuery(
                actor_user_id=user_id,
                account_id=account_id,
                plan_id=revision.identity.plan_id,
                plan_version=revision.identity.version,
                expected_revision_hash=revision.identity.revision_hash,
            )
        )
        _validate_progress_revision(progress=progress, revision=revision)
        if progress.account is not None and (
            progress.account.account_id != account_id
            or progress.account.owner_user_id != progress.revision.identity.owner_user_id
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_ACCOUNT_MISMATCH")
        expected_by_ordinal: dict[int, TransitionPlanOrderBinding] = {
            order.ordinal: order for order in progress.revision.orders
        }
        if len(expected_by_ordinal) != len(progress.revision.orders):
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_ORDERS_INVALID")
        progress_rows: list[dict[str, object]] = []
        seen_ordinals: set[int] = set()
        for row in progress.orders:
            _validate_order_progress(
                row=row,
                expected_by_ordinal=expected_by_ordinal,
                revision=progress.revision,
            )
            ordinal = row.order.ordinal
            if ordinal in seen_ordinals:
                raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_ORDERS_INVALID")
            seen_ordinals.add(ordinal)
            order = expected_by_ordinal[ordinal]
            progress_rows.append(_order_progress_payload(row=row, order=order))
        if seen_ordinals != set(expected_by_ordinal):
            raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_ORDERS_INVALID")
        identity = progress.revision.identity
        return {
            "plan_identity": {
                "plan_id": identity.plan_id,
                "family_id": identity.family_id,
                "root_plan_id": identity.root_plan_id,
                "version": identity.version,
                "revision_hash": identity.revision_hash,
                "valid_until": _instant_text(identity.valid_until),
                "recorded_at": _instant_text(identity.recorded_at),
                "account_id": identity.account_id,
                "owner_user_id": identity.owner_user_id,
            },
            "read_at": _instant_text(progress.read_at),
            "current_head": progress.current_head,
            "resource_snapshot_read_at": _instant_text(progress.resource_snapshot_read_at),
            "history_read_at": _instant_text(progress.history_read_at),
            "read_status": progress.read_status,
            "reason_codes": list(progress.reason_codes),
            "account_reconciliation": _account_payload(progress),
            "orders": progress_rows,
        }


def _validate_preview_scope(
    *, command: RebalanceJourneyCommand, revision: TransitionPlanRevision
) -> None:
    """Require the preview request to target this exact owner revision."""

    command.__post_init__()
    revision.__post_init__()
    if (
        command.action != "preview_order"
        or command.user_id != revision.identity.owner_user_id
        or command.account_id != revision.identity.account_id
        or command.plan_id != revision.identity.plan_id
        or command.plan_version != revision.identity.version
        or command.revision_hash != revision.identity.revision_hash
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PREVIEW_SCOPE_INVALID")


def _validate_progress_revision(
    *, progress: TransitionPlanExecutionProgress, revision: TransitionPlanRevision
) -> None:
    """Reject a progress result returned for another account or revision."""

    if type(progress) is not TransitionPlanExecutionProgress:
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_INVALID")
    actual = progress.revision.identity
    expected = revision.identity
    if (
        actual.plan_id != expected.plan_id
        or actual.family_id != expected.family_id
        or actual.root_plan_id != expected.root_plan_id
        or actual.version != expected.version
        or actual.revision_hash != expected.revision_hash
        or actual.account_id != expected.account_id
        or actual.owner_user_id != expected.owner_user_id
        or actual.valid_until != expected.valid_until
        or actual.recorded_at != expected.recorded_at
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_REVISION_MISMATCH")


def _validate_order_progress(
    *,
    row: PlanOrderExecutionProgress,
    expected_by_ordinal: dict[int, TransitionPlanOrderBinding],
    revision: TransitionPlanRevision,
) -> None:
    """Require every progress row to match its immutable plan order binding."""

    expected = expected_by_ordinal.get(row.order.ordinal)
    if expected is None:
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_ORDER_MISMATCH")
    if (
        row.order.ordinal != expected.ordinal
        or row.order.order_content_hash != expected.order_content_hash
        or row.order.plan_order_binding_id != expected.plan_order_binding_id
        or row.order.asset_code != expected.asset_code
        or row.order.security_id != expected.security_id
        or row.order.asset_type != expected.asset_type
        or row.order.classification_content_hash != expected.classification_content_hash
        or row.order.side != expected.side
        or row.order.approved_quantity != expected.approved_quantity
        or row.order.approved_limit_price != expected.approved_limit_price
        or row.order.quantity_unit != expected.quantity_unit
        or row.order.money_unit != expected.money_unit
        or row.order.status != expected.status
        or row.order.reason_codes != expected.reason_codes
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_ORDER_MISMATCH")
    actual_identity = row.revision_identity
    expected_identity = revision.identity
    if (
        actual_identity.plan_id != expected_identity.plan_id
        or actual_identity.family_id != expected_identity.family_id
        or actual_identity.root_plan_id != expected_identity.root_plan_id
        or actual_identity.version != expected_identity.version
        or actual_identity.revision_hash != expected_identity.revision_hash
        or actual_identity.account_id != expected_identity.account_id
        or actual_identity.owner_user_id != expected_identity.owner_user_id
        or actual_identity.recorded_at != expected_identity.recorded_at
        or actual_identity.valid_until != expected_identity.valid_until
    ):
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_ORDER_MISMATCH")


def _order_progress_payload(
    *, row: PlanOrderExecutionProgress, order: TransitionPlanOrderBinding
) -> dict[str, object]:
    """Map one already-verified order and its actual attempt facts to JSON values."""

    progress = row
    return {
        "order": order.to_payload(),
        "progress": {
            "outcome": progress.outcome,
            "approved_quantity": progress.approved_quantity,
            "filled_quantity": _decimal_text(progress.filled_quantity),
            "in_flight_quantity": _decimal_text(progress.in_flight_quantity),
            "family_in_flight_quantity": _decimal_text(progress.family_in_flight_quantity),
            "released_quantity": _decimal_text(progress.released_quantity),
            "remaining_quantity": _decimal_text(progress.remaining_quantity),
            "unreserved_remaining_quantity": _decimal_text(progress.unreserved_remaining_quantity),
            "reserved_buy_cash": _decimal_text(progress.reserved_buy_cash),
            "released_buy_cash": _decimal_text(progress.released_buy_cash),
            "active_sell_quantity": _decimal_text(progress.active_sell_quantity),
            "actual_fees_paid": _decimal_text(progress.actual_fees_paid),
            "fees_complete": progress.fees_complete,
            "active_order_ids": list(progress.active_order_ids),
            "family_active_order_ids": list(progress.family_active_order_ids),
            "completed_order_ids": list(progress.completed_order_ids),
            "cancelled_order_ids": list(progress.cancelled_order_ids),
            "replay_order_id": progress.replay_order_id,
            "predecessor_sells_settled": progress.predecessor_sells_settled,
            "reason_codes": list(progress.reason_codes),
        },
        "attempts": [_attempt_payload(item) for item in progress.attempts],
        "can_recover": progress.can_recover,
        "can_preview": progress.can_preview,
        "can_cancel": progress.can_cancel,
        "requires_successor": progress.requires_successor,
        "reason_codes": list(progress.reason_codes),
    }


def _attempt_payload(attempt: PlanExecutionAttemptProgress) -> dict[str, object]:
    """Serialize one already-verified attempt without creating an attempt alias."""

    return {
        "action_attempt_key": attempt.action_attempt_key,
        "reservation_id": attempt.reservation_id,
        "status": attempt.status,
        "reserved_quantity": _decimal_text(attempt.reserved_quantity),
        "filled_quantity": _decimal_text(attempt.filled_quantity),
        "gross_filled_value": _decimal_text(attempt.gross_filled_value),
        "remaining_quantity": _decimal_text(attempt.remaining_quantity),
        "remaining_cash_held": _decimal_text(attempt.remaining_cash_held),
        "cash_consumed": _decimal_text(attempt.cash_consumed),
        "cash_released": _decimal_text(attempt.cash_released),
        "actual_fees_paid": _decimal_text(attempt.actual_fees_paid),
        "fees_complete": attempt.fees_complete,
        "fill_receipt_ids": list(attempt.fill_receipt_ids),
        "trade_ids": list(attempt.trade_ids),
    }


def _owner_handoff_matches(
    *,
    handoff: Mapping[str, object],
    payload: dict[str, object],
    account_id: int,
    preview_token: str,
    expires_at: datetime,
) -> bool:
    """Keep the owner-derived reservation key distinct from the user's attempt key."""

    continuation_input = handoff.get("input")
    order = payload.get("order")
    if not isinstance(continuation_input, dict) or not isinstance(order, dict):
        return False
    order_key = order.get("idempotency_key")
    return (
        handoff.get("action_key") == "simulated-trading.order-confirm"
        and continuation_input.get("account_id") == str(account_id)
        and type(order_key) is str
        and bool(order_key)
        and continuation_input.get("order_key") == order_key
        and continuation_input.get("preview_token") == preview_token
        and handoff.get("expires_at") == expires_at.isoformat()
        and "continuation" not in payload
        and "preview_token" not in payload
    )


def _account_payload(progress: TransitionPlanExecutionProgress) -> dict[str, object] | None:
    """Serialize the typed account read without inventing aggregate values."""

    account = progress.account
    if account is None:
        return None
    return {
        "account_id": account.account_id,
        "owner_user_id": account.owner_user_id,
        "read_at": _instant_text(account.read_at),
        "money_unit": account.money_unit,
        "cash_available": _decimal_text(account.available_cash_after_holds),
        "active_buy_cash_reserved": _decimal_text(account.active_buy_cash_reserved),
        "active_sell_quantity_reserved": None,
        "actual_fees_paid": None,
        "fees_complete": None,
        "exact_cash_before_holds": _decimal_text(account.exact_cash),
        "exact_balances_complete": account.exact_balances_complete,
        "positions": [
            {
                "asset_code": position.asset_code,
                "quantity": _decimal_text(position.quantity),
                "available_quantity": _decimal_text(position.available_quantity),
                "quantity_unit": None,
            }
            for position in account.exact_position_balances
        ],
        "active_reservations": [
            {
                "reservation_id": reservation.reservation_id,
                "asset_code": reservation.asset_code,
                "security_id": reservation.security_id,
                "side": reservation.side,
                "remaining_cash": _decimal_text(reservation.remaining_cash),
                "remaining_shares": _decimal_text(reservation.remaining_shares),
                "remaining_buy_notional": _decimal_text(reservation.remaining_buy_notional),
                "remaining_quantity": _decimal_text(reservation.remaining_quantity),
                "remaining_amount": _decimal_text(reservation.remaining_amount),
            }
            for reservation in account.active_reservations
        ],
        "reason_codes": list(account.reason_codes),
    }


def _instant_text(value: datetime | None) -> str | None:
    """Preserve an aware source/read clock's original offset in ISO text."""

    if value is None:
        return None
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_CLOCK_INVALID")
    return value.isoformat()


def _decimal_text(value: Decimal | None) -> str | None:
    """Keep exact Decimal scale in JSON text and preserve unknown values as null."""

    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise RebalanceJourneyUnavailable(code="REBALANCE_JOURNEY_PROGRESS_VALUE_INVALID")
    return format(value, "f")


__all__: tuple[str, ...] = (
    "JourneyPlanOrderPreviewer",
    "JourneyPlanProgressReader",
)
