"""Owner API reads for durable local daily-match decisions."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, models
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
    LocalDailyMatchDecision,
    QualifiedLocalDailyMatchInput,
    RecordLocalDailyMatchUseCase,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    ApplySimulatedOrderFillCommand,
    ApplySimulatedOrderFillUseCase,
    LocalSimulatedFillSourceBinding,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.application.order_reservation_fill_calendar import (
    OrderFillSettlementCalendarResolver,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.local_order_matching import LocalMatchOutcome
from apps.simulated_trading.domain.order_reservation import SimulatedTradeSide
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import LocalDailyMatchModel
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
)
from apps.simulated_trading.infrastructure.local_daily_match_source_reader import (
    RetainedLocalDailyMatchSourceReader,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.interface import order_history_views
from apps.simulated_trading.order_history_composition import build_read_order_history_use_case
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF as RESERVATION_AS_OF,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _calendar as _build_calendar,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_local_daily_match_repository import (
    _AS_OF as PRODUCER_AS_OF,
)
from tests.component.simulated_trading.test_local_daily_match_repository import (
    _command,
    _FixedClock,
    _QualificationReader,
    _qualified_input,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _create_position,
    _ExchangeCalendarReader,
    _set_consistent_account_mark,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True)

_DECISIONS_PATH = "/api/simulated-trading/accounts/{account_id}/orders/{order_id}/decisions/"
_NO_MATCH_SESSION = date(2026, 10, 16)
_MATCH_SESSION = date(2026, 10, 19)
_MATCH_AS_OF = datetime(2026, 10, 20, 1, 59, tzinfo=UTC)
_MATCH_INTERVAL_END = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
_MATCH_KNOWN_AT = datetime(2026, 10, 20, 1, 30, tzinfo=UTC)
_APPLY_AT = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
_APPLY_IDENTITY_EXPIRY = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)


@pytest.fixture
def local_daily_match_schema(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> Iterator[None]:
    """Keep the append-only decision table inside its reservation dependency."""

    del reservation_harness, persisted_receipt_schema
    with isolated_schema((LocalDailyMatchModel,)):
        yield


@dataclass(frozen=True, slots=True)
class _OrderDecisionHistoryCase:
    """Real accepted owner order with a no-match and a later matched decision."""

    harness: _Harness
    order: SimulatedOrderReservationModel
    owner: object
    no_match: LocalDailyMatchDecision
    matched: LocalDailyMatchDecision


def _qualified_for_session(
    *,
    security_id: str,
    session_date: date,
    close_price: Decimal,
    as_of: datetime,
    interval_end_at: datetime,
    local_known_at: datetime,
    evidence_identity: str,
    evidence_hash: str,
) -> QualifiedLocalDailyMatchInput:
    """Build the existing typed source fixture at one exact daily cutoff."""

    qualified = _qualified_input(
        security_id=security_id,
        close_price=close_price,
        as_of=as_of,
    )
    observation = replace(
        qualified.observation,
        session_date=session_date,
        observation_id=stable_local_daily_observation_id(security_id, session_date),
        observed_at=interval_end_at,
        available_at=local_known_at,
        traded_volume=Decimal("100"),
    )
    evidence = tuple(
        replace(
            reference,
            identity=evidence_identity,
            content_hash=evidence_hash,
            recorded_at=local_known_at,
        )
        for reference in qualified.evidence
    )
    return replace(qualified, observation=observation, evidence=evidence)


def build_order_decision_history(
    harness: _Harness,
    *,
    monkeypatch: pytest.MonkeyPatch,
    order_key: str | None = None,
) -> _OrderDecisionHistoryCase:
    """Create a real SELL reservation and two source-qualified decisions.

    The first decision is a known NO_MATCH for 2026-10-16. A later session
    creates one durable MATCHED event, which callers may apply through the
    ordinary fill use case. Inputs use the existing typed fixture source; they
    do not claim live provider qualification.
    """

    assert type(harness.account.pk) is int
    assert type(harness.account.user_id) is int
    _create_position(harness.account)
    _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))
    stable_order_key = order_key or f"decision-history-order-{uuid4().hex}"
    intent = _intent_for(
        harness,
        side=SimulatedTradeSide.SELL,
        key=stable_order_key,
        quantity=Decimal("100"),
    )
    identity_reader = harness.preparer._identity_reader
    original_identity_read = identity_reader.get_execution_instrument_identity

    def identity_valid_through_apply(
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        """Set the explicit identity window before sealing the reservation."""

        evidence = original_identity_read(
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        return replace(evidence, identity_valid_until=_APPLY_IDENTITY_EXPIRY)

    monkeypatch.setattr(
        identity_reader,
        "get_execution_instrument_identity",
        identity_valid_through_apply,
    )
    harness.preparer._calendar_reader.evidence = _build_calendar(
        as_of=RESERVATION_AS_OF,
        open_dates={
            date(2026, 10, 16),
            date(2026, 10, 19),
            date(2026, 10, 20),
            date(2026, 10, 21),
        },
    )
    harness.reserve.execute(intent, fee_budget=None, as_of=RESERVATION_AS_OF)
    order = SimulatedOrderReservationModel._base_manager.get(
        account=harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert order.status == SimulatedOrderReservationModel.STATUS_ACTIVE

    def record(
        *,
        operation_key: str,
        session_date: date,
        close_price: Decimal,
        as_of: datetime,
        interval_end_at: datetime,
        local_known_at: datetime,
        evidence_identity: str,
        evidence_hash: str,
    ) -> LocalDailyMatchDecision:
        """Persist one decision through the real Application and repository."""

        command = replace(
            _command(
                harness,
                operation_key=operation_key,
                order_key=order.idempotency_key,
            ),
            session_date=session_date,
        )
        qualified = _qualified_for_session(
            security_id=order.security_id,
            session_date=session_date,
            close_price=close_price,
            as_of=as_of,
            interval_end_at=interval_end_at,
            local_known_at=local_known_at,
            evidence_identity=evidence_identity,
            evidence_hash=evidence_hash,
        )
        return RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=_QualificationReader(qualified),
            clock=_FixedClock(as_of),
        ).execute(command)

    no_match = record(
        operation_key=f"decision-history-no-match-{uuid4().hex}",
        session_date=_NO_MATCH_SESSION,
        close_price=Decimal("9.50"),
        as_of=PRODUCER_AS_OF,
        interval_end_at=datetime(2026, 10, 16, 7, 0, tzinfo=UTC),
        local_known_at=datetime(2026, 10, 17, 1, 30, tzinfo=UTC),
        evidence_identity="history-price-fact-2026-10-16",
        evidence_hash="c" * 64,
    )
    matched = record(
        operation_key=f"decision-history-match-{uuid4().hex}",
        session_date=_MATCH_SESSION,
        close_price=Decimal("10.50"),
        as_of=_MATCH_AS_OF,
        interval_end_at=_MATCH_INTERVAL_END,
        local_known_at=_MATCH_KNOWN_AT,
        evidence_identity="history-price-fact-2026-10-19",
        evidence_hash="d" * 64,
    )
    assert no_match.result.outcome is LocalMatchOutcome.NO_MATCH
    assert no_match.event is None
    assert matched.result.outcome is LocalMatchOutcome.MATCHED
    assert matched.event is not None
    assert matched.event.quantity == Decimal("10.000000")

    owner = get_user_model()._default_manager.get(pk=harness.user_id)
    return _OrderDecisionHistoryCase(
        harness=harness,
        order=order,
        owner=owner,
        no_match=no_match,
        matched=matched,
    )


@pytest.fixture
def order_decision_history_case(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    local_daily_match_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> _OrderDecisionHistoryCase:
    """Expose the same real decision setup to the API and browser journeys."""

    del persisted_receipt_schema, local_daily_match_schema
    return build_order_decision_history(reservation_harness, monkeypatch=monkeypatch)


def _apply_matched_decision(
    case: _OrderDecisionHistoryCase,
) -> tuple[SimulatedOrderFillResult, SimulatedOrderFillReceiptModel]:
    """Apply the exact durable MATCHED event through the ordinary fill path."""

    harness = case.harness
    order = case.order
    decision = case.matched
    assert decision.event is not None
    calendar_evidence = harness.preparer._calendar_reader.evidence
    assert calendar_evidence is not None
    current_calendar_reader = _ExchangeCalendarReader(calendar_evidence)
    event_reader = DjangoLocalDailyMatchEventReader(using="default")
    clock = _FixedClock(_APPLY_AT)
    apply_use_case = ApplySimulatedOrderFillUseCase(
        repository=DjangoSimulatedOrderFillRepository(
            using="default",
            event_reader=event_reader,
            current_calendar_reader=current_calendar_reader,
        ),
        clock=clock,
        source_binding=LocalSimulatedFillSourceBinding(
            reader=event_reader,
            source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
            source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        ),
        settlement_resolver=OrderFillSettlementCalendarResolver(
            calendar_reader=current_calendar_reader,
            clock=clock,
        ),
    )
    applied = apply_use_case.execute(
        ApplySimulatedOrderFillCommand(
            account_id=decision.command.account_id,
            user_id=decision.command.user_id,
            order_idempotency_key=decision.command.order_idempotency_key,
            source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
            fill_event_id=decision.command.operation_key,
            expected_event_payload_hash=decision.event.event_payload_hash,
        )
    )
    receipt = SimulatedOrderFillReceiptModel._base_manager.get(
        reservation_id=order.pk,
        trade_id=applied.trade_id,
    )
    return applied, receipt


def _authenticated_client(user: object) -> APIClient:
    """Authenticate the direct owner API request as its exact database user."""

    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _api_write_queries(queries: list[dict[str, object]]) -> list[str]:
    """Return SQL that would mutate a durable decision, receipt, or ledger row."""

    return [
        str(query["sql"])
        for query in queries
        if re.match(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", str(query["sql"]), re.I)
    ]


def test_owner_reads_durable_match_before_and_after_real_fill_application(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose a real NO_MATCH and MATCHED record, then its exact fill receipt."""

    harness = order_decision_history_case.harness
    order = order_decision_history_case.order
    owner = order_decision_history_case.owner
    no_match = order_decision_history_case.no_match
    decision = order_decision_history_case.matched
    command = decision.command
    stored = LocalDailyMatchModel._base_manager.get(
        account=harness.account,
        reservation=order,
        operation_key=command.operation_key,
    )
    stored_no_match = LocalDailyMatchModel._base_manager.get(
        account=harness.account,
        reservation=order,
        operation_key=no_match.command.operation_key,
    )
    client = _authenticated_client(owner)
    url = _DECISIONS_PATH.format(account_id=harness.account.pk, order_id=order.pk)

    def unexpected_write(*args: object, **kwargs: object) -> None:
        """A GET must not re-qualify, record, or apply a decision."""

        del args, kwargs
        raise AssertionError("decision history attempted source qualification or a ledger write")

    with monkeypatch.context() as read_only:
        read_only.setattr(RetainedLocalDailyMatchSourceReader, "read", unexpected_write)
        read_only.setattr(DjangoLocalDailyMatchRepository, "record_decision", unexpected_write)
        read_only.setattr(DjangoSimulatedOrderFillRepository, "apply_fill_event", unexpected_write)
        with CaptureQueriesContext(connection) as queries:
            unresolved = client.get(url, {"limit": 5})

    assert unresolved.status_code == 200
    assert unresolved["Content-Type"].startswith("application/json")
    assert unresolved.data["success"] is True
    assert unresolved.data["membership_cutoff"]
    assert unresolved.data["read_at"]
    assert unresolved.data["account_id"] == harness.account.pk
    assert unresolved.data["order_id"] == order.pk
    assert unresolved.data["has_more"] is False
    assert unresolved.data["next_cursor"] is None
    assert "尚未确认" in unresolved.data["decision_scope_note"]
    assert len(unresolved.data["decisions"]) == 2
    items_by_id = {item["decision_id"]: item for item in unresolved.data["decisions"]}
    assert set(items_by_id) == {stored_no_match.pk, stored.pk}
    no_match_item = items_by_id[stored_no_match.pk]
    assert no_match_item == {
        "decision_id": stored_no_match.pk,
        "order_id": order.pk,
        "session_date": no_match.command.session_date.isoformat(),
        "outcome": "no_match",
        "matched_quantity": str(no_match.result.matched_quantity),
        "matched_price": None,
        "recorded_at": stored_no_match.recorded_at.isoformat(),
        "occurred_at": None,
        "posting_state": "not_applicable",
        "receipt_id": None,
        "trade_id": None,
    }
    item = items_by_id[stored.pk]
    assert set(item) == {
        "decision_id",
        "order_id",
        "session_date",
        "outcome",
        "matched_quantity",
        "matched_price",
        "recorded_at",
        "occurred_at",
        "posting_state",
        "receipt_id",
        "trade_id",
    }
    assert item == {
        "decision_id": stored.pk,
        "order_id": order.pk,
        "session_date": command.session_date.isoformat(),
        "outcome": "matched",
        "matched_quantity": str(decision.result.matched_quantity),
        "matched_price": str(decision.result.matched_price),
        "recorded_at": decision.event.recorded_at.isoformat(),
        "occurred_at": decision.event.occurred_at.isoformat(),
        "posting_state": "unconfirmed",
        "receipt_id": None,
        "trade_id": None,
    }
    assert _api_write_queries(queries.captured_queries) == []
    assert "request_hash" not in item
    assert "qmt_binding_id" not in item
    assert "event_payload_hash" not in item
    assert "evidence" not in item

    applied, receipt = _apply_matched_decision(order_decision_history_case)
    assert applied.replayed is False

    with monkeypatch.context() as read_only:
        read_only.setattr(RetainedLocalDailyMatchSourceReader, "read", unexpected_write)
        read_only.setattr(DjangoLocalDailyMatchRepository, "record_decision", unexpected_write)
        read_only.setattr(DjangoSimulatedOrderFillRepository, "apply_fill_event", unexpected_write)
        with CaptureQueriesContext(connection) as queries:
            posted = client.get(url, {"limit": 5})

    assert posted.status_code == 200
    assert posted.data["account_id"] == harness.account.pk
    assert posted.data["order_id"] == order.pk
    assert len(posted.data["decisions"]) == 2
    posted_items_by_id = {
        posted_item["decision_id"]: posted_item for posted_item in posted.data["decisions"]
    }
    posted_item = posted_items_by_id[stored.pk]
    assert posted_item == {
        **item,
        "posting_state": "applied",
        "receipt_id": receipt.pk,
        "trade_id": applied.trade_id,
    }
    assert posted_items_by_id[stored_no_match.pk] == no_match_item
    assert _api_write_queries(queries.captured_queries) == []


def test_decision_history_cursor_is_order_scoped_and_keeps_membership_cutoff(
    order_decision_history_case: _OrderDecisionHistoryCase,
) -> None:
    """Page the two retained outcomes and reject a cursor for another order."""

    case = order_decision_history_case
    harness = case.harness
    client = _authenticated_client(case.owner)
    first_url = _DECISIONS_PATH.format(account_id=harness.account.pk, order_id=case.order.pk)
    first = client.get(first_url, {"limit": 1})
    assert first.status_code == 200
    assert first.data["has_more"] is True
    assert isinstance(first.data["next_cursor"], str)
    assert len(first.data["decisions"]) == 1

    second = client.get(
        first_url,
        {"limit": 1, "cursor": first.data["next_cursor"]},
    )
    assert second.status_code == 200
    assert second.data["membership_cutoff"] == first.data["membership_cutoff"]
    assert second.data["has_more"] is False
    assert second.data["next_cursor"] is None
    first_id = first.data["decisions"][0]["decision_id"]
    second_id = second.data["decisions"][0]["decision_id"]
    stored_ids = {
        LocalDailyMatchModel._base_manager.get(
            account=harness.account,
            reservation=case.order,
            operation_key=case.no_match.command.operation_key,
        ).pk,
        LocalDailyMatchModel._base_manager.get(
            account=harness.account,
            reservation=case.order,
            operation_key=case.matched.command.operation_key,
        ).pk,
    }
    assert first_id != second_id
    assert {first_id, second_id} == stored_ids

    other_intent = _intent_for(
        harness,
        side=SimulatedTradeSide.BUY,
        key=f"decision-history-other-order-{uuid4().hex}",
        quantity=Decimal("10"),
    )
    harness.reserve.execute(other_intent, fee_budget=Decimal("5.00"), as_of=RESERVATION_AS_OF)
    other_order = SimulatedOrderReservationModel._base_manager.get(
        account=harness.account,
        idempotency_key=other_intent.idempotency_key,
    )
    other_url = _DECISIONS_PATH.format(account_id=harness.account.pk, order_id=other_order.pk)
    crossed = client.get(other_url, {"limit": 1, "cursor": first.data["next_cursor"]})
    assert crossed.status_code == 400
    assert crossed["Content-Type"].startswith("application/json")


def test_decision_history_enforces_owner_active_actor_and_read_only_http_contract(
    order_decision_history_case: _OrderDecisionHistoryCase,
) -> None:
    """Reject foreign/staff or inactive principals and non-GET inputs safely."""

    case = order_decision_history_case
    harness = case.harness
    url = _DECISIONS_PATH.format(account_id=harness.account.pk, order_id=case.order.pk)
    foreign_staff = get_user_model()._default_manager.create_user(
        username=f"decision-history-staff-{uuid4().hex}",
        password="test-password",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    foreign = _authenticated_client(foreign_staff).get(url)
    assert foreign.status_code == 404
    assert foreign["Content-Type"].startswith("application/json")
    assert "decisions" not in foreign.data

    missing = _authenticated_client(case.owner).get(
        _DECISIONS_PATH.format(account_id=harness.account.pk, order_id=case.order.pk + 100000)
    )
    assert missing.status_code == 404
    assert "decisions" not in missing.data

    forged_owner = _authenticated_client(case.owner).get(url, {"user_id": str(harness.user_id)})
    assert forged_owner.status_code == 400
    assert forged_owner["Content-Type"].startswith("application/json")

    invalid_limit = _authenticated_client(case.owner).get(url, {"limit": "not-an-integer"})
    assert invalid_limit.status_code == 400

    anonymous = APIClient().get(url)
    assert anonymous.status_code == 403
    assert anonymous["Content-Type"].startswith("application/json")

    duplicate_limit = _authenticated_client(case.owner).get(f"{url}?limit=1&limit=2")
    assert duplicate_limit.status_code == 400
    assert duplicate_limit["Content-Type"].startswith("application/json")

    method = _authenticated_client(case.owner).post(url, {}, format="json")
    assert method.status_code == 405
    assert method["Content-Type"].startswith("application/json")

    case.owner.is_active = False
    case.owner.save(update_fields=["is_active"])
    inactive = _authenticated_client(case.owner).get(url)
    assert inactive.status_code == 403
    assert inactive.data["code"] == "ACTOR_INACTIVE"


def test_corrupt_decision_digest_blocks_the_owner_history_page(
    order_decision_history_case: _OrderDecisionHistoryCase,
) -> None:
    """Never expose a partial decision page after a retained row fails its seal."""

    case = order_decision_history_case
    stored = LocalDailyMatchModel._base_manager.get(
        account=case.harness.account,
        reservation=case.order,
        operation_key=case.matched.command.operation_key,
    )
    models.QuerySet.update(
        LocalDailyMatchModel._base_manager.filter(pk=stored.pk),
        record_digest="0" * 64,
    )
    client = _authenticated_client(case.owner)
    url = _DECISIONS_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
    )
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, {"limit": 5})

    assert response.status_code == 409
    assert "decisions" not in response.data
    assert "record_digest" not in response.data
    assert _api_write_queries(queries.captured_queries) == []


def test_corrupt_exact_receipt_blocks_decision_posting_status(
    order_decision_history_case: _OrderDecisionHistoryCase,
) -> None:
    """A damaged receipt must not turn a MATCHED event into verified posting."""

    case = order_decision_history_case
    _applied, receipt = _apply_matched_decision(case)
    models.QuerySet.update(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=receipt.pk),
        receipt_hash="0" * 64,
    )
    client = _authenticated_client(case.owner)
    url = _DECISIONS_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
    )
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, {"limit": 5})

    assert response.status_code == 409
    assert "decisions" not in response.data
    assert "receipt_hash" not in response.data
    assert _api_write_queries(queries.captured_queries) == []


def test_cursor_membership_keeps_receipt_posted_before_current_read_visible(
    order_decision_history_case: _OrderDecisionHistoryCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later verified receipt is visible on a fixed decision-membership cursor."""

    case = order_decision_history_case
    harness = case.harness
    client = _authenticated_client(case.owner)
    url = _DECISIONS_PATH.format(account_id=harness.account.pk, order_id=case.order.pk)
    first_read_at = _MATCH_AS_OF + timedelta(seconds=1)
    assert case.matched.event is not None
    assert first_read_at > case.matched.event.recorded_at
    monkeypatch.setattr(
        order_history_views,
        "build_read_order_history_use_case",
        lambda: build_read_order_history_use_case(clock=_FixedClock(first_read_at)),
    )
    first = client.get(url, {"limit": 1})
    assert first.status_code == 200
    assert first.data["has_more"] is True
    assert first.data["decisions"][0]["outcome"] == "no_match"
    cursor = first.data["next_cursor"]
    membership_cutoff = first.data["membership_cutoff"]

    applied, receipt = _apply_matched_decision(case)
    assert applied.replayed is False
    assert receipt.created_at > first_read_at
    later_read_at = timezone.now().astimezone(UTC)
    assert receipt.created_at <= later_read_at
    monkeypatch.setattr(
        order_history_views,
        "build_read_order_history_use_case",
        lambda: build_read_order_history_use_case(clock=_FixedClock(later_read_at)),
    )
    with CaptureQueriesContext(connection) as queries:
        second = client.get(url, {"limit": 1, "cursor": cursor})

    assert second.status_code == 200
    assert second.data["membership_cutoff"] == membership_cutoff
    assert second.data["read_at"] == later_read_at.isoformat()
    assert second.data["has_more"] is False
    assert len(second.data["decisions"]) == 1
    posted = second.data["decisions"][0]
    assert (
        posted["decision_id"]
        == LocalDailyMatchModel._base_manager.get(
            account=harness.account,
            reservation=case.order,
            operation_key=case.matched.command.operation_key,
        ).pk
    )
    assert posted["posting_state"] == "applied"
    assert posted["receipt_id"] == receipt.pk
    assert posted["trade_id"] == applied.trade_id
    assert _api_write_queries(queries.captured_queries) == []


def test_receipt_bound_to_another_owner_order_is_not_downgraded_to_unconfirmed(
    order_decision_history_case: _OrderDecisionHistoryCase,
) -> None:
    """Find a same-account event locator on the wrong order and fail closed."""

    case = order_decision_history_case
    harness = case.harness
    other_intent = _intent_for(
        harness,
        side=SimulatedTradeSide.BUY,
        key=f"decision-history-receipt-target-{uuid4().hex}",
        quantity=Decimal("10"),
    )
    harness.reserve.execute(other_intent, fee_budget=Decimal("5.00"), as_of=RESERVATION_AS_OF)
    other_order = SimulatedOrderReservationModel._base_manager.get(
        account=harness.account,
        idempotency_key=other_intent.idempotency_key,
    )
    _applied, receipt = _apply_matched_decision(case)
    models.QuerySet.update(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=receipt.pk),
        reservation_id=other_order.pk,
    )
    client = _authenticated_client(case.owner)
    url = _DECISIONS_PATH.format(account_id=harness.account.pk, order_id=case.order.pk)
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, {"limit": 5})

    assert response.status_code == 409
    assert "decisions" not in response.data
    assert "reservation_id" not in response.data
    assert _api_write_queries(queries.captured_queries) == []


def test_receipt_created_after_current_read_is_rejected(
    order_decision_history_case: _OrderDecisionHistoryCase,
) -> None:
    """Reject future receipt clocks instead of claiming applied or unconfirmed."""

    case = order_decision_history_case
    _applied, receipt = _apply_matched_decision(case)
    future_created_at = timezone.now().astimezone(UTC) + timedelta(days=1)
    models.QuerySet.update(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=receipt.pk),
        created_at=future_created_at,
    )
    client = _authenticated_client(case.owner)
    url = _DECISIONS_PATH.format(
        account_id=case.harness.account.pk,
        order_id=case.order.pk,
    )
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, {"limit": 5})

    assert response.status_code == 409
    assert "decisions" not in response.data
    assert "created_at" not in response.data
    assert _api_write_queries(queries.captured_queries) == []
