"""Authenticated owner Match API over the real durable daily-match writer.

The qualification reader in these tests reuses the existing typed local match
fixture. It proves request handling and durable decision behavior; it is not a
claim that a live market provider or QMT source was qualified.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.middleware.csrf import get_token
from django.test import RequestFactory
from rest_framework.response import Response
from rest_framework.test import APIClient

from apps.data_center.infrastructure.qmt_bridge_models import QmtBridgeBindingModel
from apps.data_center.qmt_bridge_composition import build_qmt_bridge_service
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    QualifiedLocalDailyMatchInput,
    RecordLocalDailyMatchUseCase,
)
from apps.simulated_trading.application.order_reservation_fill import OrderFillContext
from apps.simulated_trading.application.owner_order_matching import OwnerOrderMatchUseCase
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import LocalDailyMatchModel
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.owner_order_operation_targets import (
    DjangoOwnerOrderOperationTargetReader,
)
from apps.simulated_trading.interface import owner_order_matching_views
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF as RESERVATION_AS_OF,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _calendar as _build_calendar,
)
from tests.component.simulated_trading.test_local_daily_match_repository import (
    _FixedClock,
    _reserve,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    _MATCH_AS_OF,
    _MATCH_INTERVAL_END,
    _MATCH_KNOWN_AT,
    _MATCH_SESSION,
    _qualified_for_session,
)
from tests.component.simulated_trading.test_order_decision_history_api import ledger as ledger
from tests.component.simulated_trading.test_order_decision_history_api import (
    local_daily_match_schema as local_daily_match_schema,
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
    _account_financial_state,
    _ledger_counts,
)
from tests.component.simulated_trading.test_order_reservation_repository import _Harness

pytestmark = pytest.mark.django_db(transaction=True)

_MATCH_PATH = "/api/simulated-trading/accounts/{account_id}/orders/{order_id}/match/"
_NEXT_SESSION = date(2026, 10, 20)
_NEXT_AS_OF = datetime(2026, 10, 21, 1, 59, tzinfo=UTC)
_NEXT_INTERVAL_END = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)
_NEXT_KNOWN_AT = datetime(2026, 10, 21, 1, 30, tzinfo=UTC)


@dataclass(slots=True)
class _MutableClock:
    """Return an explicit test cutoff that can advance between owner requests."""

    value: datetime

    def now(self) -> datetime:
        """Return the configured aware cutoff without consulting wall time."""

        return self.value


class _ScenarioQualificationReader:
    """Return a finite sequence of typed fixtures for preview and locked reread."""

    def __init__(self, values: Sequence[QualifiedLocalDailyMatchInput | None]) -> None:
        self.values = tuple(values)
        self.calls: list[tuple[LocalDailyMatchCommand, datetime]] = []

    def read(
        self,
        *,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
    ) -> QualifiedLocalDailyMatchInput | None:
        """Record each qualification read and expose no implicit source fallback."""

        del context
        self.calls.append((command, as_of))
        index = len(self.calls) - 1
        if index >= len(self.values):
            raise AssertionError("the matcher made more source reads than this scenario allows")
        return self.values[index]


@pytest.fixture
def owner_match_harness(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    local_daily_match_schema: None,
    preserve_account_authority_generation: None,
    monkeypatch: pytest.MonkeyPatch,
) -> _Harness:
    """Use the existing real owner/account/reservation and durable row fixtures."""

    del persisted_receipt_schema, local_daily_match_schema, preserve_account_authority_generation
    identity_reader = reservation_harness.preparer._identity_reader
    original_read = identity_reader.get_execution_instrument_identity

    def valid_identity(
        *, security_id: str, asset_code: str, as_of: datetime
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        evidence = original_read(security_id=security_id, asset_code=asset_code, as_of=as_of)
        return replace(evidence, identity_valid_until=datetime(2026, 10, 21, 2, 0, tzinfo=UTC))

    monkeypatch.setattr(identity_reader, "get_execution_instrument_identity", valid_identity)
    reservation_harness.preparer._calendar_reader.evidence = _build_calendar(
        as_of=RESERVATION_AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
    )
    return reservation_harness


def _create_owner_order_and_binding(
    harness: _Harness,
    *,
    order_key: str,
    binding_suffix: str | None = None,
) -> tuple[SimulatedOrderReservationModel, object, QmtBridgeBindingModel]:
    """Create a real reserved BUY and one paired owner QMT binding locator."""

    order = _reserve(harness, order_key=order_key)
    owner = get_user_model()._base_manager.get(pk=harness.user_id)
    binding = QmtBridgeBindingModel._base_manager.create(
        owner_id=harness.user_id,
        agent_id=f"owner-match-{binding_suffix or uuid4().hex}",
        server_url="https://qmt.example.test/bridge",
        assets=[order.asset_code],
        paired_at=_MATCH_AS_OF - timedelta(days=1),
        enabled=True,
        revoked=False,
    )
    return order, owner, binding


def _qualified_fixture(
    order: SimulatedOrderReservationModel,
    *,
    session_date: date = _MATCH_SESSION,
    close_price: Decimal = Decimal("9.50"),
    as_of: datetime = _MATCH_AS_OF,
    interval_end_at: datetime = _MATCH_INTERVAL_END,
    known_at: datetime = _MATCH_KNOWN_AT,
    identity: str | None = None,
    hash_character: str = "e",
) -> QualifiedLocalDailyMatchInput:
    """Reuse the existing typed policy/observation fixture at this exact cutoff."""

    return _qualified_for_session(
        security_id=order.security_id,
        session_date=session_date,
        close_price=close_price,
        as_of=as_of,
        interval_end_at=interval_end_at,
        local_known_at=known_at,
        evidence_identity=identity or f"owner-match-price-{uuid4().hex}",
        evidence_hash=hash_character * 64,
    )


def build_owner_matching(
    reader: _ScenarioQualificationReader,
    *,
    clock: _FixedClock | _MutableClock,
) -> OwnerOrderMatchUseCase:
    """Compose the actual owner target, matcher, and append-only ORM repository."""

    return OwnerOrderMatchUseCase(
        target_reader=DjangoOwnerOrderOperationTargetReader(
            using="default",
            clock=clock,
            read_bindings=build_qmt_bridge_service(),
        ),
        record_use_case=RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=reader,
            clock=clock,
        ),
    )


def _patch_match_use_case(
    monkeypatch: pytest.MonkeyPatch,
    reader: _ScenarioQualificationReader,
    *,
    clock: _FixedClock | _MutableClock,
) -> None:
    """Inject only typed qualified fixture input; keep target and ORM writer real."""

    monkeypatch.setattr(
        owner_order_matching_views,
        "build_owner_order_matching_use_case",
        lambda: build_owner_matching(reader, clock=clock),
    )


def _session_client(owner: object, *, csrf: bool = True) -> tuple[APIClient, str | None]:
    """Create one session-authenticated client with an optional valid CSRF token."""

    client = APIClient(enforce_csrf_checks=True)
    client.force_login(cast(AbstractBaseUser, owner))
    if not csrf:
        return client, None
    token = get_token(RequestFactory().get("/"))
    client.cookies[settings.CSRF_COOKIE_NAME] = token
    return client, token


def _post_match(
    client: APIClient,
    *,
    account_id: int,
    order_id: int,
    session_date: date,
    csrf_token: str | None,
) -> Response:
    """Send the exact public Match request through the real URL and session stack."""

    url = _MATCH_PATH.format(account_id=account_id, order_id=order_id)
    headers = {} if csrf_token is None else {"HTTP_X_CSRFTOKEN": csrf_token}
    return client.post(
        url,
        {"session_date": session_date.isoformat(), "confirmed": True},
        format="json",
        **headers,
    )


def _decision_rows(order: SimulatedOrderReservationModel) -> list[LocalDailyMatchModel]:
    """Read every retained decision for exactly one newly created order."""

    return list(LocalDailyMatchModel._base_manager.filter(reservation_id=order.pk).order_by("pk"))


def _no_ledger_state(
    harness: _Harness,
    order: SimulatedOrderReservationModel,
) -> tuple[object, ...]:
    """Snapshot all financial rows and reservation counters that Match must leave alone."""

    order.refresh_from_db()
    return (
        _ledger_counts(harness.account),
        _account_financial_state(harness.account),
        order.status,
        order.filled_quantity,
        order.cash_consumed,
        order.shares_consumed,
        order.cash_released,
        order.shares_released,
    )


@pytest.mark.parametrize(
    ("close_price", "expected_outcome", "expected_quantity", "expected_price", "expected_reason"),
    [
        (Decimal("9.50"), "matched", "10.000000", "9.5000", "MATCHED"),
        (Decimal("10.50"), "no_match", "0.000000", None, "LIMIT_NOT_CROSSED"),
    ],
)
def test_owner_match_persists_new_outcomes_and_replays_before_source_changes(
    owner_match_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    close_price: Decimal,
    expected_outcome: str,
    expected_quantity: str,
    expected_price: str | None,
    expected_reason: str,
) -> None:
    """Persist both MATCHED and NO_MATCH, with exact replay independent of current binding."""

    order, owner, binding = _create_owner_order_and_binding(
        owner_match_harness,
        order_key=f"owner-match-{uuid4().hex}",
    )
    qualified = _qualified_fixture(order, close_price=close_price)
    reader = _ScenarioQualificationReader((qualified, qualified))
    clock = _FixedClock(_MATCH_AS_OF)
    _patch_match_use_case(monkeypatch, reader, clock=clock)
    client, csrf_token = _session_client(owner)
    before = _no_ledger_state(owner_match_harness, order)

    first = _post_match(
        client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=csrf_token,
    )

    assert first.status_code == 200, first.data
    assert first["Content-Type"].startswith("application/json")
    assert set(first.data) == {
        "success",
        "outcome",
        "account_id",
        "order_id",
        "session_date",
        "decision_outcome",
        "matched_quantity",
        "matched_price",
        "reason_code",
        "replayed",
        "decision_recorded",
    }
    assert first.data == {
        "success": True,
        "outcome": "success",
        "account_id": owner_match_harness.account.pk,
        "order_id": order.pk,
        "session_date": _MATCH_SESSION.isoformat(),
        "decision_outcome": expected_outcome,
        "matched_quantity": expected_quantity,
        "matched_price": expected_price,
        "reason_code": expected_reason,
        "replayed": False,
        "decision_recorded": True,
    }
    rows = _decision_rows(order)
    assert len(rows) == 1
    assert rows[0].outcome == expected_outcome
    assert (rows[0].event_payload is not None) is (expected_outcome == "matched")
    assert len(reader.calls) == 2
    assert _no_ledger_state(owner_match_harness, order) == before

    QmtBridgeBindingModel._base_manager.filter(pk=binding.pk).update(
        enabled=False,
        revoked=True,
    )

    def unexpected_source_read(
        *,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
    ) -> QualifiedLocalDailyMatchInput | None:
        """Exact replay must return its original decision before a current source read."""

        del command, context, as_of
        raise AssertionError("same-session replay must not reread revoked or changed sources")

    monkeypatch.setattr(reader, "read", unexpected_source_read)
    replay = _post_match(
        client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=csrf_token,
    )
    assert replay.status_code == 200
    assert replay.data == {**first.data, "replayed": True}
    assert len(_decision_rows(order)) == 1
    assert _no_ledger_state(owner_match_harness, order) == before


def test_owner_match_rejects_missing_or_ambiguous_source_without_a_decision(
    owner_match_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing or multiply bound QMT locator cannot persist a local decision."""

    order, owner, _binding = _create_owner_order_and_binding(
        owner_match_harness,
        order_key=f"owner-match-source-scope-{uuid4().hex}",
    )
    extra = QmtBridgeBindingModel._base_manager.create(
        owner_id=owner_match_harness.user_id,
        agent_id=f"owner-match-extra-{uuid4().hex}",
        server_url="https://qmt.example.test/bridge",
        assets=[order.asset_code],
        paired_at=_MATCH_AS_OF,
        enabled=True,
        revoked=False,
    )
    del extra
    qualified = _qualified_fixture(order)
    reader = _ScenarioQualificationReader((qualified, qualified))
    _patch_match_use_case(monkeypatch, reader, clock=_FixedClock(_MATCH_AS_OF))
    client, csrf_token = _session_client(owner)
    before = _no_ledger_state(owner_match_harness, order)

    ambiguous = _post_match(
        client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=csrf_token,
    )

    assert ambiguous.status_code == 409
    assert ambiguous.data["success"] is False
    assert _decision_rows(order) == []
    assert reader.calls == []
    assert _no_ledger_state(owner_match_harness, order) == before

    QmtBridgeBindingModel._base_manager.filter(owner_id=owner_match_harness.user_id).update(
        enabled=False,
        revoked=True,
    )
    missing_binding = _post_match(
        client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=csrf_token,
    )
    assert missing_binding.status_code == 409
    assert missing_binding.data["success"] is False
    assert _decision_rows(order) == []
    assert reader.calls == []
    assert _no_ledger_state(owner_match_harness, order) == before


def test_owner_match_rejects_missing_and_lock_changed_qualification(
    owner_match_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing qualification or a changed locked reread leaves no durable decision."""

    order, owner, _binding = _create_owner_order_and_binding(
        owner_match_harness,
        order_key=f"owner-match-source-change-{uuid4().hex}",
    )
    client, csrf_token = _session_client(owner)
    before = _no_ledger_state(owner_match_harness, order)

    missing_reader = _ScenarioQualificationReader((None,))
    _patch_match_use_case(monkeypatch, missing_reader, clock=_FixedClock(_MATCH_AS_OF))
    missing = _post_match(
        client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=csrf_token,
    )
    assert missing.status_code == 409
    assert _decision_rows(order) == []
    assert _no_ledger_state(owner_match_harness, order) == before

    preview = _qualified_fixture(order, identity="owner-match-preview", hash_character="a")
    changed = _qualified_fixture(
        order,
        close_price=Decimal("9.60"),
        identity="owner-match-locked-change",
        hash_character="b",
    )
    changed_reader = _ScenarioQualificationReader((preview, changed))
    _patch_match_use_case(monkeypatch, changed_reader, clock=_FixedClock(_MATCH_AS_OF))
    changed_response = _post_match(
        client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=csrf_token,
    )
    assert changed_response.status_code == 409
    assert _decision_rows(order) == []
    assert len(changed_reader.calls) == 2
    assert _no_ledger_state(owner_match_harness, order) == before


def test_owner_match_keeps_matched_decision_pending_until_apply(
    owner_match_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second date cannot add another decision while the first MATCHED event is pending."""

    order, owner, _binding = _create_owner_order_and_binding(
        owner_match_harness,
        order_key=f"owner-match-pending-{uuid4().hex}",
    )
    first_qualified = _qualified_fixture(order)
    second_qualified = _qualified_fixture(
        order,
        session_date=_NEXT_SESSION,
        close_price=Decimal("9.40"),
        as_of=_NEXT_AS_OF,
        interval_end_at=_NEXT_INTERVAL_END,
        known_at=_NEXT_KNOWN_AT,
        identity="owner-match-second-session",
        hash_character="f",
    )
    reader = _ScenarioQualificationReader(
        (first_qualified, first_qualified, second_qualified, second_qualified)
    )
    clock = _MutableClock(_MATCH_AS_OF)
    _patch_match_use_case(monkeypatch, reader, clock=clock)
    client, csrf_token = _session_client(owner)
    before = _no_ledger_state(owner_match_harness, order)

    first = _post_match(
        client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=csrf_token,
    )
    assert first.status_code == 200
    assert first.data["decision_outcome"] == "matched"
    assert _no_ledger_state(owner_match_harness, order) == before
    clock.value = _NEXT_AS_OF

    blocked = _post_match(
        client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_NEXT_SESSION,
        csrf_token=csrf_token,
    )
    assert blocked.status_code == 409
    assert blocked.data["success"] is False
    assert len(_decision_rows(order)) == 1
    assert _no_ledger_state(owner_match_harness, order) == before


def test_owner_match_requires_owner_session_csrf_and_exact_json_input(
    owner_match_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enforce session/CSRF, JSON, the exact date field, and literal confirmation."""

    order, owner, _binding = _create_owner_order_and_binding(
        owner_match_harness,
        order_key=f"owner-match-input-{uuid4().hex}",
    )
    reader = _ScenarioQualificationReader((_qualified_fixture(order),))
    _patch_match_use_case(monkeypatch, reader, clock=_FixedClock(_MATCH_AS_OF))
    url = _MATCH_PATH.format(account_id=owner_match_harness.account.pk, order_id=order.pk)
    good_body = {"session_date": _MATCH_SESSION.isoformat(), "confirmed": True}

    anonymous = APIClient(enforce_csrf_checks=True).post(url, good_body, format="json")
    assert anonymous.status_code in (401, 403)

    client, _token = _session_client(owner, csrf=False)
    missing_csrf = client.post(url, good_body, format="json")
    assert missing_csrf.status_code == 403

    client, csrf_token = _session_client(owner)
    assert csrf_token is not None
    headers = {"HTTP_X_CSRFTOKEN": csrf_token}
    invalid_payloads = (
        {"session_date": _MATCH_SESSION.isoformat(), "confirmed": False},
        {
            "session_date": _MATCH_SESSION.isoformat(),
            "confirmed": True,
            "qmt_binding_id": str(uuid4()),
        },
        {"session_date": _MATCH_SESSION.isoformat(), "confirmed": True, "price": "9.50"},
        {"session_date": "2026/10/19", "confirmed": True},
    )
    for payload in invalid_payloads:
        response = client.post(url, payload, format="json", **headers)
        assert response.status_code == 400
        assert response["Content-Type"].startswith("application/json")
        assert response.data["success"] is False
    query = client.post(f"{url}?source=client", good_body, format="json", **headers)
    assert query.status_code == 400
    unsupported = client.post(
        url,
        data='{"session_date":"2026-10-19","confirmed":true}',
        content_type="text/plain",
        **headers,
    )
    assert unsupported.status_code == 415
    assert unsupported["Content-Type"].startswith("application/json")
    get = client.get(url)
    assert get.status_code == 405
    assert get["Content-Type"].startswith("application/json")
    assert _decision_rows(order) == []


def test_owner_match_hides_foreign_or_staff_scope_and_rejects_inactive_actor(
    owner_match_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the active account owner may persist a match decision."""

    order, owner, _binding = _create_owner_order_and_binding(
        owner_match_harness,
        order_key=f"owner-match-owner-{uuid4().hex}",
    )
    qualified = _qualified_fixture(order)
    reader = _ScenarioQualificationReader((qualified, qualified, qualified, qualified))
    _patch_match_use_case(monkeypatch, reader, clock=_FixedClock(_MATCH_AS_OF))
    before = _no_ledger_state(owner_match_harness, order)

    foreign_owner = get_user_model()._default_manager.create_user(
        username=f"owner-match-foreign-{uuid4().hex}", password="test-password"
    )
    foreign_client, foreign_token = _session_client(foreign_owner)
    assert foreign_token is not None
    hidden = _post_match(
        foreign_client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=foreign_token,
    )
    assert hidden.status_code == 404
    assert _decision_rows(order) == []

    staff = get_user_model()._default_manager.create_user(
        username=f"owner-match-staff-{uuid4().hex}",
        password="test-password",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    staff_client, staff_token = _session_client(staff)
    assert staff_token is not None
    denied_staff = _post_match(
        staff_client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=staff_token,
    )
    assert denied_staff.status_code == 404
    assert _decision_rows(order) == []

    owner_client, owner_token = _session_client(owner)
    assert owner_token is not None
    type(owner_match_harness.account)._base_manager.filter(
        pk=owner_match_harness.account.pk
    ).update(is_active=False)
    inactive_account = _post_match(
        owner_client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=owner_token,
    )
    assert inactive_account.status_code == 404
    assert _decision_rows(order) == []
    assert _no_ledger_state(owner_match_harness, order) == before
    type(owner_match_harness.account)._base_manager.filter(
        pk=owner_match_harness.account.pk
    ).update(is_active=True)

    get_user_model()._base_manager.filter(pk=owner_match_harness.user_id).update(is_active=False)
    inactive = _post_match(
        owner_client,
        account_id=owner_match_harness.account.pk,
        order_id=order.pk,
        session_date=_MATCH_SESSION,
        csrf_token=owner_token,
    )
    assert inactive.status_code == 403
    assert _decision_rows(order) == []
    assert _no_ledger_state(owner_match_harness, order) == before
