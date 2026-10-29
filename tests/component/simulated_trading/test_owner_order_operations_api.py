"""Owner Apply and Cancel routes over real retained decisions and ledger rows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import connection, models
from django.middleware.csrf import get_token
from django.test import RequestFactory
from rest_framework.test import APIClient

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    ApplySimulatedOrderFillUseCase,
    LocalSimulatedFillSourceBinding,
)
from apps.simulated_trading.application.order_reservation_fill_calendar import (
    OrderFillSettlementCalendarResolver,
)
from apps.simulated_trading.application.owner_order_operations import (
    OwnerOrderCancelTarget,
    OwnerOrderFillTarget,
    OwnerOrderOperationsUseCase,
)
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus
from apps.simulated_trading.execution_settlement_composition import (
    build_cancel_simulated_order_reservation_use_case,
)
from apps.simulated_trading.infrastructure.local_daily_match_codec import (
    encode_event,
    event_payload_hash,
    record_digest_values,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import _record_values
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.owner_order_operation_targets import (
    DjangoOwnerOrderOperationTargetReader,
)
from apps.simulated_trading.interface import owner_order_operation_views
from apps.simulated_trading.owner_order_operations_composition import (
    build_owner_order_operations_use_case,
)
from tests.component.simulated_trading.test_local_daily_match_repository import (
    _FixedClock,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    _APPLY_AT,
    _OrderDecisionHistoryCase,
)
from tests.component.simulated_trading.test_order_decision_history_api import ledger as ledger
from tests.component.simulated_trading.test_order_decision_history_api import (
    local_daily_match_schema as local_daily_match_schema,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    order_decision_history_case as order_decision_history_case,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _ExchangeCalendarReader,
)

pytestmark = pytest.mark.django_db(transaction=True)

_APPLY_PATH = (
    "/api/simulated-trading/accounts/{account_id}/orders/{order_id}/"
    "decisions/{decision_id}/apply/"
)
_CANCEL_PATH = "/api/simulated-trading/accounts/{account_id}/orders/{order_id}/cancel/"


def build_owner_operations(case: _OrderDecisionHistoryCase) -> OwnerOrderOperationsUseCase:
    """Compose the real target reader and writers around this case's verified calendar.

    This fixture adapter keeps the stable owner API producer real while fixing
    the test knowledge clock and calendar to the existing decision case.
    """

    evidence = case.harness.preparer._calendar_reader.evidence
    assert evidence is not None
    clock: SimulatedTradeExecutionClock = _FixedClock(_APPLY_AT)
    event_reader = DjangoLocalDailyMatchEventReader(using="default")
    calendar_reader = _ExchangeCalendarReader(evidence)
    apply_use_case = ApplySimulatedOrderFillUseCase(
        repository=DjangoSimulatedOrderFillRepository(
            using="default",
            event_reader=event_reader,
            current_calendar_reader=calendar_reader,
        ),
        clock=clock,
        source_binding=LocalSimulatedFillSourceBinding(
            reader=event_reader,
            source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
            source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        ),
        settlement_resolver=OrderFillSettlementCalendarResolver(
            calendar_reader=calendar_reader,
            clock=clock,
        ),
    )
    return OwnerOrderOperationsUseCase(
        target_reader=DjangoOwnerOrderOperationTargetReader(using="default", clock=clock),
        apply_use_case=apply_use_case,
        cancel_use_case=build_cancel_simulated_order_reservation_use_case(
            using="default", clock=clock
        ),
    )


def _session_client(owner: object, *, csrf: bool = True) -> tuple[APIClient, str | None]:
    """Create a real owner session and optionally attach a valid CSRF token."""

    client = APIClient(enforce_csrf_checks=True)
    client.force_login(cast(AbstractBaseUser, owner))
    if not csrf:
        return client, None
    request = RequestFactory().get("/")
    token = get_token(request)
    client.cookies[settings.CSRF_COOKIE_NAME] = token
    return client, token


def _post_json(client: APIClient, url: str, csrf_token: str | None) -> object:
    """Send the exact literal confirmation through the real session-auth path."""

    headers = {} if csrf_token is None else {"HTTP_X_CSRFTOKEN": csrf_token}
    return client.post(url, {"confirmed": True}, format="json", **headers)


def _patch_owner_operations(
    monkeypatch: pytest.MonkeyPatch,
    case: _OrderDecisionHistoryCase,
) -> None:
    """Inject only the fixture calendar while keeping both production writers real."""

    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        lambda: build_owner_operations(case),
    )


def _receipt_count(case: _OrderDecisionHistoryCase) -> int:
    """Count persisted receipts for the exact reservation, not fixture-wide rows."""

    return SimulatedOrderFillReceiptModel._base_manager.filter(reservation_id=case.order.pk).count()


def _decision_id(case: _OrderDecisionHistoryCase, *, matched: bool) -> int:
    """Resolve the public numeric decision ID from its persisted operation key."""

    decision = case.matched if matched else case.no_match
    row = LocalDailyMatchModel._base_manager.get(
        reservation=case.order,
        operation_key=decision.command.operation_key,
    )
    assert type(row.pk) is int
    return row.pk


def test_owner_apply_requires_session_and_csrf(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject anonymous and session-authenticated writes without a CSRF token."""

    case = order_decision_history_case
    _patch_owner_operations(monkeypatch, case)
    url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=_decision_id(case, matched=True),
    )
    anonymous = APIClient(enforce_csrf_checks=True).post(url, {"confirmed": True}, format="json")
    assert anonymous.status_code in (401, 403)

    session_client, _token = _session_client(case.owner, csrf=False)
    missing_csrf = _post_json(session_client, url, None)
    assert missing_csrf.status_code == 403


def test_apply_persists_and_exactly_replays_the_retained_match(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply a real MATCHED event once, then recover its exact immutable result."""

    case = order_decision_history_case
    _patch_owner_operations(monkeypatch, case)
    client, csrf_token = _session_client(case.owner)
    decision_id = _decision_id(case, matched=True)
    url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=decision_id,
    )

    first = _post_json(client, url, csrf_token)
    assert first.status_code == 200
    assert first["Content-Type"].startswith("application/json")
    assert first.data["success"] is True
    assert first.data["replayed"] is False
    assert first.data["account_id"] == case.harness.account.pk
    assert first.data["order_id"] == case.order.pk
    assert first.data["decision_id"] == decision_id
    assert first.data["fill_sequence"] == 1
    assert first.data["quantity"] == str(case.matched.result.matched_quantity)
    assert first.data["price"] == str(case.matched.result.matched_price)
    assert set(first.data["incremental_fees"]) == {
        "commission",
        "transfer_fee",
        "stamp_duty",
        "slippage",
        "total_fee",
    }
    assert _receipt_count(case) == 1
    for forbidden in (
        "source_namespace",
        "source_version",
        "event_payload_hash",
        "idempotency_key",
        "receipt_id",
        "recorded_at",
        "observation_basis",
    ):
        assert forbidden not in first.data

    second = _post_json(client, url, csrf_token)
    assert second.status_code == 200
    assert second.data["replayed"] is True
    assert second.data["trade_id"] == first.data["trade_id"]
    assert second.data["fill_sequence"] == first.data["fill_sequence"]
    assert second.data["gross_amount"] == first.data["gross_amount"]
    assert second.data["incremental_fees"] == first.data["incremental_fees"]
    assert _receipt_count(case) == 1

    history = client.get(
        f"/api/simulated-trading/accounts/{case.harness.account.pk}/orders/{case.order.pk}/fills/"
    )
    assert history.status_code == 200
    assert len(history.data["fills"]) == 1
    assert history.data["fills"][0]["trade_id"] == first.data["trade_id"]
    assert history.data["fills"][0]["receipt_id"] == _receipt_count_row(case).pk


def _receipt_count_row(case: _OrderDecisionHistoryCase) -> SimulatedOrderFillReceiptModel:
    """Fetch the unique persisted receipt for the just-applied event."""

    return SimulatedOrderFillReceiptModel._base_manager.get(reservation_id=case.order.pk)


def _financial_snapshot(case: _OrderDecisionHistoryCase) -> dict[str, object]:
    """Capture the owner account, position, reservation and ledger rows exactly."""

    account = SimulatedAccountModel._base_manager.filter(pk=case.harness.account.pk).values().get()
    position = (
        PositionModel._base_manager.filter(
            account_id=case.harness.account.pk,
            asset_code=case.order.asset_code,
        )
        .values()
        .get()
    )
    reservation = type(case.order)._base_manager.filter(pk=case.order.pk).values().get()
    trades = list(
        SimulatedTradeModel._base_manager.filter(account_id=case.harness.account.pk)
        .order_by("pk")
        .values()
    )
    receipts = list(
        SimulatedOrderFillReceiptModel._base_manager.filter(reservation_id=case.order.pk)
        .order_by("pk")
        .values()
    )
    return {
        "account": account,
        "position": position,
        "reservation": reservation,
        "trades": trades,
        "receipts": receipts,
    }


def test_no_match_is_blocked_and_foreign_account_is_hidden(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the exact owner's retained MATCHED decision reaches the fill writer."""

    case = order_decision_history_case
    _patch_owner_operations(monkeypatch, case)
    client, token = _session_client(case.owner)
    no_match_id = _decision_id(case, matched=False)
    no_match_url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=no_match_id,
    )
    blocked = _post_json(client, no_match_url, token)
    assert blocked.status_code == 409
    assert blocked.data["success"] is False
    assert blocked.data["code"] == "OWNER_ORDER_DECISION_NOT_MATCHED"
    assert _receipt_count(case) == 0

    foreign = _APPLY_PATH.format(
        account_id=case.harness.account.pk + 999,
        order_id=case.order.pk,
        decision_id=no_match_id,
    )
    hidden = _post_json(client, foreign, token)
    assert hidden.status_code == 404
    assert hidden.data["code"] == "OWNER_ORDER_NOT_FOUND"
    assert _receipt_count(case) == 0


def test_cancel_blocks_while_a_matched_decision_is_unapplied(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not release a reservation while its retained match is still pending."""

    case = order_decision_history_case
    _patch_owner_operations(monkeypatch, case)
    client, token = _session_client(case.owner)
    url = _CANCEL_PATH.format(account_id=case.harness.account.pk, order_id=case.order.pk)

    before = _financial_snapshot(case)
    blocked = _post_json(client, url, token)
    assert blocked.status_code == 409
    assert blocked.data["success"] is False
    assert blocked.data["code"] == "LOCAL_DAILY_MATCH_PENDING_FILL"
    assert _financial_snapshot(case) == before
    assert _receipt_count(case) == 0


def test_cancel_after_fill_releases_only_the_remaining_hold_cumulatively(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the applied fill and expose the original reservation's cumulative remainder."""

    case = order_decision_history_case
    _patch_owner_operations(monkeypatch, case)
    client, token = _session_client(case.owner)
    decision_id = _decision_id(case, matched=True)
    apply_url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=decision_id,
    )
    applied = _post_json(client, apply_url, token)
    assert applied.status_code == 200
    cancel_url = _CANCEL_PATH.format(account_id=case.harness.account.pk, order_id=case.order.pk)
    cancelled = _post_json(client, cancel_url, token)
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == OrderReservationStatus.CANCELLED.value
    assert cancelled.data["released_shares"] == "90.000000"
    assert cancelled.data["remaining_shares"] == "0.000000"
    assert _receipt_count(case) == 1

    after_cancel = _financial_snapshot(case)
    retry = _post_json(client, cancel_url, token)
    assert retry.status_code == 200
    assert retry.data == cancelled.data
    assert retry.data["released_shares"] == "90.000000"
    assert retry.data["remaining_shares"] == "0.000000"
    assert _financial_snapshot(case) == after_cancel
    assert _receipt_count(case) == 1


@pytest.mark.parametrize(
    ("operation", "existing_receipt"),
    [("apply", False), ("apply", True), ("cancel", False)],
)
def test_actor_deactivated_after_target_resolution_cannot_write_or_replay(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    existing_receipt: bool,
) -> None:
    """Recheck actor activation in the writer after the owner target was resolved."""

    case = order_decision_history_case
    _patch_owner_operations(monkeypatch, case)
    client, token = _session_client(case.owner)
    decision_id = _decision_id(case, matched=True)
    if operation == "apply" and existing_receipt:
        first = _post_json(
            client,
            _APPLY_PATH.format(
                account_id=case.harness.account.pk,
                order_id=case.order.pk,
                decision_id=decision_id,
            ),
            token,
        )
        assert first.status_code == 200
        assert _receipt_count(case) == 1

    original_fill = DjangoOwnerOrderOperationTargetReader.resolve_fill_target
    original_cancel = DjangoOwnerOrderOperationTargetReader.resolve_cancel_target
    owner_id = case.harness.user_id

    def deactivate_owner() -> None:
        get_user_model()._base_manager.filter(pk=owner_id).update(is_active=False)

    def resolve_fill_then_deactivate(
        reader: DjangoOwnerOrderOperationTargetReader,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
    ) -> OwnerOrderFillTarget:
        target = original_fill(
            reader,
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            decision_id=decision_id,
        )
        deactivate_owner()
        return target

    def resolve_cancel_then_deactivate(
        reader: DjangoOwnerOrderOperationTargetReader,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
    ) -> OwnerOrderCancelTarget:
        target = original_cancel(
            reader,
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
        )
        deactivate_owner()
        return target

    if operation == "apply":
        monkeypatch.setattr(
            DjangoOwnerOrderOperationTargetReader,
            "resolve_fill_target",
            resolve_fill_then_deactivate,
        )
        path = _APPLY_PATH.format(
            account_id=case.harness.account.pk,
            order_id=case.order.pk,
            decision_id=decision_id,
        )
    else:
        monkeypatch.setattr(
            DjangoOwnerOrderOperationTargetReader,
            "resolve_cancel_target",
            resolve_cancel_then_deactivate,
        )
        path = _CANCEL_PATH.format(
            account_id=case.harness.account.pk,
            order_id=case.order.pk,
        )
    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        lambda: build_owner_operations(case),
    )

    response = _post_json(client, path, token)

    assert response.status_code == 404
    assert response.data["code"] == "OWNER_ORDER_NOT_FOUND"
    assert _receipt_count(case) == (1 if existing_receipt else 0)


def test_default_composition_replays_receipt_without_reading_current_configuration(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production composition must recover the persisted event before calendar/config reads."""

    case = order_decision_history_case
    fixture_operations = build_owner_operations(case)
    event = case.matched
    assert event.event is not None
    applied = fixture_operations.apply_retained_fill(
        account_id=case.harness.account.pk,
        user_id=case.harness.user_id,
        order_id=case.order.pk,
        decision_id=_decision_id(case, matched=True),
        confirmed=True,
    )
    assert applied.result.replayed is False
    assert _receipt_count(case) == 1

    def unexpected_current_configuration(*args: object, **kwargs: object) -> object:
        """An exact receipt replay must not consult a current calendar publication."""

        del args, kwargs
        raise AssertionError("exact receipt replay read current source configuration")

    from apps.simulated_trading import (
        execution_current_reference_composition,
        execution_settlement_composition,
        initial_position_mark_composition,
        local_daily_simulation_policy_composition,
        owner_order_operations_composition,
    )

    for module, name in (
        (execution_current_reference_composition, "read_calendar_capture_configuration_at"),
        (owner_order_operations_composition, "read_calendar_capture_configuration_reference_at"),
        (owner_order_operations_composition, "read_current_exchange_calendar_reference"),
        (execution_current_reference_composition, "get_active_runtime_value"),
        (execution_settlement_composition, "get_active_runtime_value"),
        (initial_position_mark_composition, "get_active_runtime_value"),
        (local_daily_simulation_policy_composition, "get_active_runtime_value"),
    ):
        monkeypatch.setattr(module, name, unexpected_current_configuration)
    monkeypatch.setattr(
        DjangoLocalDailyMatchEventReader,
        "read_event",
        unexpected_current_configuration,
    )
    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        build_owner_order_operations_use_case,
    )
    client, token = _session_client(case.owner)
    url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=_decision_id(case, matched=True),
    )
    replay = _post_json(client, url, token)
    assert replay.status_code == 200
    assert replay.data["replayed"] is True
    assert replay.data["trade_id"] == applied.result.trade_id
    assert _receipt_count(case) == 1


def test_default_composition_applies_using_real_calendar_configuration_selection(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the real config selector and locked writer path for a first Apply."""

    from apps.data_center.application.calendar_capture_configuration import (
        CalendarCaptureConfiguration,
    )
    from apps.data_center.infrastructure.catalog_models import (
        DatasetContractModel,
        DatasetProviderBindingModel,
        DatasetPublicationPolicyModel,
    )
    from apps.data_center.infrastructure.models import ProviderConfigModel
    from apps.simulated_trading import (
        execution_current_reference_composition,
        owner_order_operations_composition,
    )
    from tests.component.data_center.test_calendar_workbench_scope import (
        DATASET_KEY,
        _write_configuration,
    )
    from tests.support.isolated_schema import isolated_schema

    case = order_decision_history_case
    evidence = case.harness.preparer._calendar_reader.evidence
    assert evidence is not None
    config_time = _APPLY_AT - timedelta(seconds=1)
    config_models = (
        DatasetContractModel,
        DatasetPublicationPolicyModel,
        DatasetProviderBindingModel,
        ProviderConfigModel,
    )
    config_reads: list[tuple[object, bool, int]] = []
    calendar_builds: list[tuple[str, str]] = []

    with isolated_schema(config_models):
        _write_configuration()
        for model in config_models[:3]:
            models.QuerySet.update(
                model._base_manager.all(),
                created_at=config_time,
                updated_at=config_time,
            )
        models.QuerySet.update(
            ProviderConfigModel._base_manager.filter(name="calendar-workbench-provider-fixture"),
            created_at=config_time,
            updated_at=config_time,
        )

        original_reader = (
            owner_order_operations_composition.read_calendar_capture_configuration_reference_at
        )

        def read_selected_configuration(*, as_of: datetime) -> CalendarCaptureConfiguration:
            """Record the actual Config Center selection inside the locked writer UoW."""

            selected = original_reader(as_of=as_of)
            config_reads.append((as_of, connection.in_atomic_block, len(connection.atomic_blocks)))
            assert selected.dataset.value == DATASET_KEY
            assert selected.known_at == _APPLY_AT
            return selected

        def published_calendar_reader(
            *,
            dataset_key: str,
            runtime_environment: str,
            read_publication: object,
        ) -> _ExchangeCalendarReader:
            """Use the decision fixture's real sealed calendar for publication output."""

            assert callable(read_publication)
            calendar_builds.append((dataset_key, runtime_environment))
            assert dataset_key == DATASET_KEY
            assert runtime_environment == "development"
            return _ExchangeCalendarReader(evidence)

        monkeypatch.setattr(
            owner_order_operations_composition,
            "read_calendar_capture_configuration_reference_at",
            read_selected_configuration,
        )
        monkeypatch.setattr(
            owner_order_operations_composition,
            "_ServerUTCClock",
            lambda: _FixedClock(_APPLY_AT),
        )
        monkeypatch.setattr(
            execution_current_reference_composition,
            "build_current_published_execution_calendar_reader",
            published_calendar_reader,
        )
        client, token = _session_client(case.owner)
        url = _APPLY_PATH.format(
            account_id=case.harness.account.pk,
            order_id=case.order.pk,
            decision_id=_decision_id(case, matched=True),
        )

        response = _post_json(client, url, token)

        assert response.status_code == 200
        assert response.data["success"] is True
        assert response.data["replayed"] is False
        assert response.data["status"] == "applied"
        assert response.data["fill_sequence"] == 1
        assert _receipt_count(case) == 1
        assert config_reads == [(_APPLY_AT, True, 1)]
        assert calendar_builds == [(DATASET_KEY, "development")]


def test_inactive_account_still_allows_cancel_after_real_fill(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Account deactivation cannot strand a local pending hold for its active owner."""

    case = order_decision_history_case
    _patch_owner_operations(monkeypatch, case)
    client, token = _session_client(case.owner)
    apply_url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=_decision_id(case, matched=True),
    )
    applied = _post_json(client, apply_url, token)
    assert applied.status_code == 200
    account_model = type(case.harness.account)
    account_model._base_manager.filter(pk=case.harness.account.pk).update(is_active=False)
    cancel_url = _CANCEL_PATH.format(account_id=case.harness.account.pk, order_id=case.order.pk)

    cancelled = _post_json(client, cancel_url, token)
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == OrderReservationStatus.CANCELLED.value
    assert cancelled.data["released_shares"] == "90.000000"
    assert cancelled.data["remaining_shares"] == "0.000000"
    assert _receipt_count(case) == 1


def test_inactive_account_still_allows_exact_receipt_replay(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal account state does not make an already committed fill unverifiable."""

    case = order_decision_history_case
    _patch_owner_operations(monkeypatch, case)
    client, token = _session_client(case.owner)
    apply_url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=_decision_id(case, matched=True),
    )
    applied = _post_json(client, apply_url, token)
    assert applied.status_code == 200
    type(case.harness.account)._base_manager.filter(pk=case.harness.account.pk).update(
        is_active=False
    )
    replay = _post_json(client, apply_url, token)
    assert replay.status_code == 200
    assert replay.data["replayed"] is True
    assert replay.data["trade_id"] == applied.data["trade_id"]
    assert _receipt_count(case) == 1


def test_future_but_consistently_sealed_decision_is_rejected_without_financial_write(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a self-consistent decision whose event-record clock is after Apply cutoff."""

    case = order_decision_history_case
    assert case.matched.event is not None
    future_recorded_at = _APPLY_AT + timedelta(minutes=1)
    event = replace(case.matched.event, recorded_at=future_recorded_at)
    event = replace(event, event_payload_hash=event_payload_hash(event))
    stored = LocalDailyMatchModel._base_manager.get(
        account_id=case.harness.account.pk,
        reservation_id=case.order.pk,
        operation_key=case.matched.command.operation_key,
    )
    stored.recorded_at = future_recorded_at
    stored.event_payload = encode_event(event)
    stored.record_digest = record_digest_values(_record_values(stored))
    models.QuerySet.update(
        LocalDailyMatchModel._base_manager.filter(pk=stored.pk),
        recorded_at=stored.recorded_at,
        event_payload=stored.event_payload,
        record_digest=stored.record_digest,
    )
    before = _financial_snapshot(case)
    _patch_owner_operations(monkeypatch, case)
    client, token = _session_client(case.owner)
    url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=stored.pk,
    )

    response = _post_json(client, url, token)

    assert response.status_code == 409
    assert response.data["code"] == "OWNER_ORDER_DECISION_FUTURE"
    assert "recorded_at" not in response.data
    assert "event_payload" not in response.data
    assert _financial_snapshot(case) == before
    assert _receipt_count(case) == 0


def test_corrupt_decision_seal_is_rejected_without_financial_write(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A damaged retained decision seal cannot reach the fill writer."""

    case = order_decision_history_case
    stored = LocalDailyMatchModel._base_manager.get(
        account_id=case.harness.account.pk,
        reservation_id=case.order.pk,
        operation_key=case.matched.command.operation_key,
    )
    models.QuerySet.update(
        LocalDailyMatchModel._base_manager.filter(pk=stored.pk),
        record_digest="0" * 64,
    )
    before = _financial_snapshot(case)
    _patch_owner_operations(monkeypatch, case)
    client, token = _session_client(case.owner)
    url = _APPLY_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
        decision_id=stored.pk,
    )

    response = _post_json(client, url, token)

    assert response.status_code == 409
    assert response.data["success"] is False
    assert response.data["code"] == "LOCAL_DAILY_MATCH_RECORD_INVALID"
    assert "record_digest" not in response.data
    assert _financial_snapshot(case) == before
    assert _receipt_count(case) == 0
