"""Native owner preview/confirm/readback over retained synthetic vendor input.

Only the outbound Sina transport is replaced. Source/configuration/calendar,
Session/CSRF, Risk evaluation, ordinary holds and the V4 ledger are real local
implementations. The response body is explicitly a fixture, not live-source
or brokerage acceptance.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

import pytest
from django.db import connection, transaction
from django.urls import reverse

from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center.domain.sina_quote_capture import (
    build_sina_quote_request_url,
    parse_sina_quote_capture,
)
from apps.simulated_trading import owner_order_submission_composition as composition
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _locked_fill_chain,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.owner_order_submission_composition import SINA_SUBMISSION_POLICIES_KEY
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    AS_OF,
    ASSET_CODE,
    ASSET_NAME,
    SECURITY_ID,
    _owner_session_client,
    _persist_sell_position,
    _QualifiedCallerContext,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _clear_runtime_profile_history as _clear_runtime_profile_history,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _freeze_auto_fixture_knowledge_clocks as _freeze_auto_fixture_knowledge_clocks,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    qualified_caller_context as qualified_caller_context,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
)
from tests.support.ash03_auto_calendar_clock_v2 import advance_auto_uow_fixture_clocks
from tests.support.ash03_auto_uow_fixture import _runtime_public_write_clock
from tests.unit.risk_center.test_local_simulated_market_provider import _body, _policy

pytestmark = pytest.mark.django_db(transaction=True)


def _post(
    client: Any,
    csrf: str,
    name: str,
    account_id: int,
    body: dict[str, object],
    *,
    order_key: str | None = None,
) -> Any:
    kwargs: dict[str, object] = {"account_id": account_id}
    if order_key is not None:
        kwargs["order_key"] = order_key
    response = client.post(
        reverse(f"api_simulated_trading:{name}", kwargs=kwargs),
        body,
        format="json",
        secure=True,
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="https://testserver",
    )
    assert response["Content-Type"].startswith("application/json")
    return response


@pytest.fixture
def public_order_context(
    qualified_caller_context: _QualifiedCallerContext, monkeypatch: pytest.MonkeyPatch
) -> tuple[_QualifiedCallerContext, list[str]]:
    context = qualified_caller_context
    base = context.uow.rule_bundle.execution_submission_v2.execution_rule_v1
    policy = replace(
        _policy(),
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
        market=base.market,
        board=base.board,
        effective_from=AS_OF.date(),
        effective_until=AS_OF.date(),
        content_hash="",
    )
    with _runtime_public_write_clock():
        activate_runtime_profile_patch(
            environment="development",
            patch={SINA_SUBMISSION_POLICIES_KEY: {"policies": [policy.to_payload()]}},
            actor="test-owner-order-source",
            reason="explicit synthetic paper-market fixture",
        )
    calls: list[str] = []

    def capture(asset_code: str) -> object:
        calls.append(asset_code)
        url = build_sina_quote_request_url(asset_code)
        return parse_sina_quote_capture(
            asset_code=asset_code,
            requested_url=url,
            final_url=url,
            request_started_at=AS_OF - timedelta(milliseconds=200),
            response_completed_at=AS_OF - timedelta(milliseconds=100),
            http_status=200,
            http_date=None,
            content_type="application/javascript; charset=GB18030",
            charset="GB18030",
            content_encoding=None,
            body=_body(source_date=AS_OF.date().isoformat(), source_time="09:59:59"),
        )

    monkeypatch.setattr(composition, "capture_sina_quote", capture)
    return context, calls


def test_owner_preview_confirm_partial_cancel_and_original_readback(
    public_order_context: tuple[_QualifiedCallerContext, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    context, calls = public_order_context
    account = context.account
    position = _persist_sell_position(account)
    account.current_market_value = position.market_value
    account.total_value = account.current_cash + position.market_value
    account.save(
        update_fields=[
            "current_market_value",
            "total_value",
            "cash_known",
            "cash_reconciliation_status",
        ]
    )
    client, csrf = _owner_session_client(context.owner_id)
    before = (
        account.current_cash,
        position.quantity,
        position.available_quantity,
        SimulatedTradeModel.objects.count(),
    )
    writes: list[str] = []

    def observer(execute: Any, sql: str, params: object, many: bool, ctx: object) -> object:
        if sql.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
            writes.append(sql.split()[0])
        return execute(sql, params, many, ctx)

    with connection.execute_wrapper(observer):
        preview = _post(
            client,
            csrf,
            "order-preview",
            account.pk,
            {
                "asset_code": ASSET_CODE,
                "asset_name": ASSET_NAME,
                "side": "sell",
                "quantity": "300",
                "limit_price": "10.00",
            },
        )
    assert preview.status_code == 200, preview.data
    assert not writes
    assert preview.data["read_only"] is True
    qualification = preview.data["market_qualification"]
    assert qualification["decision_scope"] == "local_simulation_only"
    assert qualification["freshness"] == "fresh"
    assert qualification["must_not_use_for_decision"] is False
    assert qualification["blocking_reasons"] == []
    assert qualification["market_available_at_basis"] == (
        "local_response_completed_at_not_vendor_published_at"
    )
    assert "preview_token" not in preview.data
    continuation = preview.data["continuation"]
    assert datetime.fromisoformat(continuation["expires_at"]).utcoffset() == timedelta(0)
    token = continuation["input"]["preview_token"]
    key = continuation["input"]["order_key"]
    assert calls == [ASSET_CODE]
    account.refresh_from_db()
    position.refresh_from_db()
    assert (
        account.current_cash,
        position.quantity,
        position.available_quantity,
        SimulatedTradeModel.objects.count(),
    ) == before
    assert SimulatedOrderReservationModel.objects.filter(account=account).count() == 0
    confirmed = _post(
        client,
        csrf,
        "order-confirm",
        account.pk,
        {"preview_token": token, "confirmed": True},
        order_key=key,
    )
    assert confirmed.status_code == 200, confirmed.data
    order = SimulatedOrderReservationModel.objects.get(pk=confirmed.data["order_id"])
    assert order.shares_reserved == Decimal("300")
    assert order.filled_quantity == 0
    assert "submission_market" in order.plan_snapshot
    with transaction.atomic():
        chain = _locked_fill_chain(reservation_row=order, using="default")
        assert chain.intent.idempotency_key == key
    fill_at = AS_OF + timedelta(seconds=1)
    event = LocalSimulatedFillEventV1(
        source_namespace="test.fixture.public-owner-fill",
        source_version="fixture-v1",
        source_event_id="partial-001",
        event_payload_hash=sha256(b"explicit synthetic owner fill 001").hexdigest(),
        source_snapshot_id="fixture-owner-match",
        source_snapshot_hash=sha256(b"fixture match source").hexdigest(),
        reservation_id=order.pk,
        account_id=account.pk,
        user_id=context.owner_id,
        order_idempotency_key=key,
        intent_payload_hash=order.intent_payload_hash,
        reservation_request_hash=order.reservation_request_hash,
        plan_snapshot_hash=order.plan_snapshot_hash,
        security_id=order.security_id,
        asset_code=order.asset_code,
        side=SimulatedTradeSide.SELL,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("100"),
        price=Decimal("10"),
        occurred_at=fill_at,
        source_observed_at=fill_at,
        source_available_at=fill_at,
        recorded_at=fill_at,
    )
    proof = build_order_fill_settlement_proof(
        calendar_evidence=context.uow.calendar_evidence,
        calendar_read_cutoff=fill_at,
        fill_occurred_at=fill_at,
        settlement_exchange=context.uow.calendar_evidence.snapshot.exchange,
        settlement_lag_sessions=context.uow.rule_bundle.settlement_policy_v1.settlement_lag_sessions,
    )
    reader = _EventReader(event, [])
    filled = DjangoSimulatedOrderFillRepository(
        event_reader=reader, using="default"
    ).apply_fill_event(
        event=event,
        expected_event_payload_hash=event.event_payload_hash,
        settlement_proof=proof,
        clock=_FixedClock(fill_at),
    )
    assert filled.replayed is False
    position.refresh_from_db()
    account.refresh_from_db()
    order.refresh_from_db()
    assert position.quantity == Decimal("900")
    assert position.available_quantity == Decimal("900")
    assert order.filled_quantity == Decimal("100")
    assert order.shares_consumed == Decimal("100")
    assert account.current_cash == before[0] + Decimal("993.48")
    advance_auto_uow_fixture_clocks(monkeypatch, as_of=fill_at + timedelta(seconds=1))
    cancelled = client.post(
        reverse(
            "api_simulated_trading:order-cancel",
            kwargs={"account_id": account.pk, "order_id": order.pk},
        ),
        {"confirmed": True},
        format="json",
        secure=True,
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="https://testserver",
    )
    assert cancelled.status_code == 200, cancelled.data
    order.refresh_from_db()
    assert order.shares_released == Decimal("200")
    recovered = client.get(
        reverse(
            "api_simulated_trading:order-by-key",
            kwargs={"account_id": account.pk, "order_key": key},
        ),
        secure=True,
    )
    assert recovered.status_code == 200, recovered.data
    assert recovered.data["order_id"] == order.pk
    assert recovered.data["order"]["filled_quantity"] == "100.000000"
    assert len(calls) == 1
    replay = _post(
        client,
        csrf,
        "order-confirm",
        account.pk,
        {"preview_token": token, "confirmed": True},
        order_key=key,
    )
    assert replay.status_code == 200, replay.data
    assert replay.data["replayed"] is True
    assert len(calls) == 1
    assert SimulatedOrderReservationModel.objects.filter(account=account).count() == 1
    assert SimulatedTradeModel.objects.filter(account=account).count() == 1


@pytest.mark.parametrize(
    "body",
    [
        {"confirmed": "true"},
        {"preview_token": "x", "confirmed": 1},
        {"preview_token": "x", "confirmed": True, "quantity": "999"},
    ],
)
def test_owner_confirmation_rejects_forged_or_extra_inputs(
    public_order_context: tuple[_QualifiedCallerContext, list[str]], body: dict[str, object]
) -> None:
    context, calls = public_order_context
    client, csrf = _owner_session_client(context.owner_id)
    response = _post(
        client, csrf, "order-confirm", context.account.pk, body, order_key="unknown-original-order"
    )
    assert response.status_code == 400
    assert calls == []
    assert not SimulatedOrderReservationModel.objects.filter(account=context.account).exists()
