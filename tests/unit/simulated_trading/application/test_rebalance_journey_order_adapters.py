from __future__ import annotations

from datetime import timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

from apps.portfolio.application.transition_plan_lifecycle import TransitionPlanRevision
from apps.simulated_trading.application.rebalance_journey_order_adapters import (
    JourneyPlanOrderPreviewer,
    JourneyPlanProgressReader,
)
from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyCommand,
    RebalanceJourneyUnavailable,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    RebalanceExactPositionBalance,
)
from apps.simulated_trading.application.transition_plan_execution import (
    PreviewTransitionPlanOrderUseCase,
)
from apps.simulated_trading.application.transition_plan_execution_progress import (
    GetTransitionPlanExecutionProgressUseCase,
    PlanExecutionAccountReconciliation,
    TransitionPlanExecutionProgress,
)
from apps.simulated_trading.domain.transition_plan_execution import (
    reconcile_plan_order_execution,
)
from tests.unit.portfolio.test_transition_plan_revision_asset_identity import _revision


def test_preview_maps_user_attempt_key_separately_from_owner_order_key() -> None:
    revision = cast(TransitionPlanRevision, _revision())
    order = revision.orders[0]
    attempt_key = "user-attempt-key-1"
    owner_order_key = "owner-derived-order-key"
    expires_at = revision.identity.recorded_at + timedelta(minutes=10)
    command = RebalanceJourneyCommand(
        action="preview_order",
        user_id=revision.identity.owner_user_id,
        account_id=revision.identity.account_id,
        plan_id=revision.identity.plan_id,
        plan_version=revision.identity.version,
        revision_hash=revision.identity.revision_hash,
        request_key=attempt_key,
        order_ordinal=order.ordinal,
        order_content_hash=order.order_content_hash,
        plan_order_binding_id=order.plan_order_binding_id,
        quantity=Decimal("25"),
        limit_price=Decimal("10.2500"),
        reason=None,
    )
    binding = order.to_execution_binding(
        revision.identity,
        owner_user_id=revision.identity.owner_user_id,
        action_attempt_key=attempt_key,
    )
    preview = SimpleNamespace(
        token="signed-preview-token",
        expires_at=expires_at,
        result=SimpleNamespace(
            reservation=SimpleNamespace(quantity=command.quantity, limit_price=command.limit_price)
        ),
    )
    preview_result = SimpleNamespace(
        binding=binding,
        revision_recorded_at=revision.identity.recorded_at,
        preview=preview,
    )
    use_case = Mock(spec=PreviewTransitionPlanOrderUseCase)
    use_case.execute.return_value = preview_result
    response_payload: dict[str, object] = {
        "success": True,
        "account_id": revision.identity.account_id,
        "read_only": True,
        "execution_submitted": False,
        "order": {"idempotency_key": owner_order_key},
        "continuation": {
            "action_key": "simulated-trading.order-confirm",
            "input": {
                "account_id": str(revision.identity.account_id),
                "order_key": owner_order_key,
                "preview_token": preview.token,
            },
            "expires_at": expires_at.isoformat(),
        },
    }

    adapter = JourneyPlanOrderPreviewer(use_case)
    with patch(
        "apps.simulated_trading.application.rebalance_journey_order_adapters.owner_order_response_payload",
        return_value=response_payload,
    ):
        display, handoff = adapter.preview(command=command, revision=revision)

    mapped = use_case.execute.call_args.args[0]
    assert mapped.action_attempt_key == attempt_key
    assert mapped.reason == ""
    assert mapped.price == command.limit_price
    assert display["binding"] == binding.to_payload()
    assert "continuation" not in display["preview"]
    assert handoff == response_payload["continuation"]
    assert handoff["input"]["order_key"] == owner_order_key
    assert handoff["input"]["order_key"] != mapped.action_attempt_key


def test_preview_rejects_continuation_order_key_that_differs_from_owner_preview() -> None:
    revision = cast(TransitionPlanRevision, _revision())
    order = revision.orders[0]
    attempt_key = "user-attempt-key-2"
    command = RebalanceJourneyCommand(
        action="preview_order",
        user_id=revision.identity.owner_user_id,
        account_id=revision.identity.account_id,
        plan_id=revision.identity.plan_id,
        plan_version=revision.identity.version,
        revision_hash=revision.identity.revision_hash,
        request_key=attempt_key,
        order_ordinal=order.ordinal,
        order_content_hash=order.order_content_hash,
        plan_order_binding_id=order.plan_order_binding_id,
        quantity=Decimal("25"),
        limit_price=Decimal("10.2500"),
    )
    binding = order.to_execution_binding(
        revision.identity,
        owner_user_id=revision.identity.owner_user_id,
        action_attempt_key=attempt_key,
    )
    expires_at = revision.identity.recorded_at + timedelta(minutes=10)
    preview = SimpleNamespace(
        token="signed-preview-token",
        expires_at=expires_at,
        result=SimpleNamespace(
            reservation=SimpleNamespace(quantity=command.quantity, limit_price=command.limit_price)
        ),
    )
    use_case = Mock(spec=PreviewTransitionPlanOrderUseCase)
    use_case.execute.return_value = SimpleNamespace(
        binding=binding,
        revision_recorded_at=revision.identity.recorded_at,
        preview=preview,
    )
    response_payload: dict[str, object] = {
        "account_id": revision.identity.account_id,
        "order": {"idempotency_key": "owner-order-key"},
        "continuation": {
            "action_key": "simulated-trading.order-confirm",
            "input": {
                "account_id": str(revision.identity.account_id),
                "order_key": "cross-wired-key",
                "preview_token": preview.token,
            },
            "expires_at": expires_at.isoformat(),
        },
    }

    with patch(
        "apps.simulated_trading.application.rebalance_journey_order_adapters.owner_order_response_payload",
        return_value=response_payload,
    ):
        with pytest.raises(RebalanceJourneyUnavailable) as error:
            JourneyPlanOrderPreviewer(use_case).preview(command=command, revision=revision)

    assert error.value.code == "REBALANCE_JOURNEY_PREVIEW_HANDOFF_MISSING"


def test_progress_preserves_unknown_cash_and_exact_offset_without_adding_totals() -> None:
    revision = cast(TransitionPlanRevision, _revision())
    read_at = revision.identity.recorded_at.astimezone(timezone(timedelta(hours=8))) + timedelta(
        seconds=10
    )
    row = reconcile_plan_order_execution(
        revision_identity=revision.identity,
        order=revision.orders[0],
        reservations=(),
        related_family_reservations=(),
        history_complete=False,
        revision_active=True,
        as_of=read_at,
        predecessor_sells_settled=None,
    )
    account = PlanExecutionAccountReconciliation(
        account_id=revision.identity.account_id,
        owner_user_id=revision.identity.owner_user_id,
        read_at=read_at,
        money_unit="CNY",
        exact_cash=Decimal("100.00"),
        active_buy_cash_reserved=None,
        available_cash_after_holds=None,
        exact_balances_complete=False,
        exact_position_balances=(
            RebalanceExactPositionBalance(
                asset_code="600000.SH",
                quantity=Decimal("1000.00"),
                available_quantity=None,
            ),
        ),
        active_reservations=(),
        reason_codes=("ACTIVE_HOLD_HISTORY_UNKNOWN",),
    )
    typed_progress = TransitionPlanExecutionProgress(
        revision=revision,
        read_at=read_at,
        current_head=True,
        account=account,
        resource_snapshot_read_at=read_at,
        history_read_at=read_at,
        orders=(row,),
        read_status="partial",
        reason_codes=("ACTIVE_HOLD_HISTORY_UNKNOWN",),
    )
    use_case = Mock(spec=GetTransitionPlanExecutionProgressUseCase)
    use_case.execute.return_value = typed_progress

    payload = JourneyPlanProgressReader(use_case).read(
        user_id=revision.identity.owner_user_id,
        account_id=revision.identity.account_id,
        revision=revision,
    )

    reconciliation = payload["account_reconciliation"]
    assert reconciliation["cash_available"] is None
    assert reconciliation["active_sell_quantity_reserved"] is None
    assert reconciliation["actual_fees_paid"] is None
    assert reconciliation["positions"][0]["quantity"] == "1000.00"
    assert reconciliation["positions"][0]["available_quantity"] is None
    assert payload["read_at"] == read_at.isoformat()
    assert payload["orders"][0]["progress"]["filled_quantity"] is None
    assert payload["orders"][0]["progress"]["actual_fees_paid"] is None


def test_progress_keeps_delegated_reader_identity_separate_from_plan_owner() -> None:
    revision = cast(TransitionPlanRevision, _revision())
    read_at = revision.identity.recorded_at + timedelta(seconds=10)
    row = reconcile_plan_order_execution(
        revision_identity=revision.identity,
        order=revision.orders[0],
        reservations=(),
        related_family_reservations=(),
        history_complete=False,
        revision_active=True,
        as_of=read_at,
        predecessor_sells_settled=None,
    )
    progress = TransitionPlanExecutionProgress(
        revision=revision,
        read_at=read_at,
        current_head=True,
        account=PlanExecutionAccountReconciliation(
            account_id=revision.identity.account_id,
            owner_user_id=revision.identity.owner_user_id,
            read_at=read_at,
            money_unit="CNY",
            exact_cash=None,
            active_buy_cash_reserved=None,
            available_cash_after_holds=None,
            exact_balances_complete=False,
            exact_position_balances=(),
            active_reservations=(),
            reason_codes=("LEDGER_UNKNOWN",),
        ),
        resource_snapshot_read_at=read_at,
        history_read_at=read_at,
        orders=(row,),
        read_status="partial",
        reason_codes=("LEDGER_UNKNOWN",),
    )
    use_case = Mock(spec=GetTransitionPlanExecutionProgressUseCase, return_value=progress)
    use_case.execute.return_value = progress
    observer_id = revision.identity.owner_user_id + 100

    payload = JourneyPlanProgressReader(use_case).read(
        user_id=observer_id,
        account_id=revision.identity.account_id,
        revision=revision,
    )

    assert use_case.execute.call_args.args[0].actor_user_id == observer_id
    assert payload["plan_identity"]["owner_user_id"] == revision.identity.owner_user_id


def test_progress_rejects_another_account_before_reading_the_use_case() -> None:
    revision = cast(TransitionPlanRevision, _revision())
    use_case = Mock(spec=GetTransitionPlanExecutionProgressUseCase)

    with pytest.raises(RebalanceJourneyUnavailable):
        JourneyPlanProgressReader(use_case).read(
            user_id=revision.identity.owner_user_id,
            account_id=revision.identity.account_id + 1,
            revision=revision,
        )

    use_case.execute.assert_not_called()
