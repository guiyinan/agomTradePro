"""Opt-in Native PostgreSQL acceptance for real Sina after-close paper quotes.

Sina's vendor last quote is retained as a close-snapshot simulation reference,
not represented as an official close or an exchange execution. Any partial fill
in this module is an explicitly synthetic fixture passed through the ordinary
local fill writer.
"""

from __future__ import annotations

import json
import os
import traceback
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import apps.simulated_trading.close_snapshot_submission_composition as close_market_composition
import apps.simulated_trading.owner_order_submission_composition as owner_market_composition
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center.application.sina_quote_capture import SinaQuoteCapture
from apps.risk_center.domain.close_snapshot_simulation import (
    CloseSnapshotSimulationPolicy,
    evaluate_close_snapshot_simulation,
)
from apps.risk_center.domain.execution_trading_constraints import SessionState
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_current_reference import (
    SimulatedSettlementPlanBindingV3,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillRequest,
    prepare_order_reservation_fill,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.automatic_trading_invocation_models import (
    AutomaticTradingInvocationModel,
)
from apps.simulated_trading.infrastructure.execution_settlement_plan_binding_repository import (
    build_simulated_trade_execution_receipt,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _locked_fill_chain,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.trade_history_repository import (
    DjangoTradeHistoryRepository,
)
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.component.simulated_trading import test_auto_trading_current_reference_t1 as auto_fixture
from tests.component.simulated_trading import test_live_sina_owner_market_acceptance as live_helpers
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _owner_session_client,
    _persist_sell_position,
)
from tests.component.simulated_trading.test_live_sina_owner_market_acceptance import (
    live_owner_context as live_owner_context,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.ash03_auto_uow_fixture import _runtime_public_write_clock
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        os.environ.get("AGOM_RUN_LIVE_SINA_CLOSE_SNAPSHOT_ACCEPTANCE") != "1",
        reason=(
            "set AGOM_RUN_LIVE_SINA_CLOSE_SNAPSHOT_ACCEPTANCE=1 for "
            "public Sina close-snapshot acceptance"
        ),
    ),
]

ASSET_CODE = "600000.SH"
ASSET_NAME = "Fixture bank"
SECURITY_ID = "SH.ASH03.AUTO.CALLER"
SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_SNAPSHOT_PURPOSE = "close_snapshot_simulation"
CLOSE_SNAPSHOT_POLICIES_KEY = "config_center.market.simulated_sina_close_snapshot_policies"


@dataclass(frozen=True, slots=True)
class _CloseSnapshotEvidence:
    """Keep the actual source, local test policy, and retained route captures."""

    policy: CloseSnapshotSimulationPolicy
    preflight_capture: SinaQuoteCapture
    preflight_index: Path
    routed_captures: list[SinaQuoteCapture]
    routed_indexes: list[Path]


@pytest.fixture(autouse=True)
def _require_native_close_snapshot_database(django_db_use_migrations: bool) -> None:
    """Refuse live source acceptance outside an isolated migrated Native PostgreSQL DB."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.fail("close-snapshot acceptance requires the migrated Native PostgreSQL test DB")
    if str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip().endswith(".production"):
        pytest.fail("close-snapshot acceptance is permitted only under non-production settings")
    assert_native_postgres_test_database()


def _utc(value: datetime) -> datetime:
    """Normalize one aware datetime for exact source and decision comparisons."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise AssertionError("source and decision clocks must be timezone-aware")
    return value.astimezone(UTC)


def _parse_utc(value: object) -> datetime:
    """Parse one timestamp from the public owner response."""

    if type(value) is not str:
        raise AssertionError("HTTP clock must be ISO timestamp text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AssertionError("HTTP clock must carry a timezone offset")
    return parsed.astimezone(UTC)


def _is_qualified(value: object) -> bool:
    """Read the close decision's exact status without coercing other values."""

    status = getattr(value, "value", value)
    return type(status) is str and status.casefold() == "qualified"


def _configure_close_snapshot_source(
    *,
    monkeypatch: pytest.MonkeyPatch,
    context: live_helpers._LiveOwnerContext,
    account_id: int,
    scenario: str,
) -> _CloseSnapshotEvidence:
    """Capture and qualify a real after-close quote, then activate its paper policy."""

    preflight = owner_market_composition.capture_sina_quote(ASSET_CODE)
    artifact_dir = (
        Path(__file__).resolve().parents[3]
        / ".tmp"
        / "ash03-live-sina-close-snapshot-acceptance"
        / f"{scenario}-{timezone.now().astimezone(UTC):%Y%m%d}"
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    preflight_index = live_helpers._retain_capture(preflight, artifact_dir=artifact_dir)
    live_helpers._verify_capture_artifact(preflight, preflight_index)
    quote = preflight.quote
    if not preflight.usable_parse or quote is None or quote.last_price is None:
        pytest.skip(f"actual Sina response has no usable last quote; retained {preflight_index}")
    if quote.source_observed_at is None or quote.source_clock_status.value != "valid":
        pytest.skip(f"actual Sina quote lacks a valid source clock; retained {preflight_index}")

    trade_date = context.uow.market_session
    now = timezone.now().astimezone(UTC)
    local_now = now.astimezone(SHANGHAI)
    if local_now.date() != trade_date:
        pytest.skip(f"system date {local_now.date()} differs from current session {trade_date}")
    close_at = datetime.combine(
        trade_date,
        max(window.ends_at for window in context.policy.session_windows),
        SHANGHAI,
    )
    if _utc(quote.source_observed_at) < _utc(close_at):
        pytest.skip(
            "Sina's vendor last quote was not observed at or after the published close; "
            f"retained {preflight_index}"
        )
    if _utc(preflight.response_completed_at) > now:
        pytest.skip("Sina response completion is later than the actual system clock")
    if _utc(preflight.response_completed_at) < _utc(quote.source_observed_at):
        pytest.skip("Sina response completed before its reported source observation")

    policy = CloseSnapshotSimulationPolicy(
        policy_id=f"ash03-close-snapshot-{uuid4().hex}",
        policy_version="fixture-v1",
        account_id=account_id,
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
        market=context.policy.market,
        board=context.policy.board,
        trading_date=trade_date,
        source_id=context.policy.source_id,
        source_name=context.policy.source_name,
        usage_ttl_seconds=300,
        status_mapping_sha256=context.policy.status_mapping_sha256,
        trusted_vendor_status_codes=context.policy.trusted_vendor_status_codes,
        available_from=max(now - timedelta(minutes=1), _utc(close_at)),
        available_until=min(
            now + timedelta(minutes=5),
            _utc(
                datetime.combine(trade_date + timedelta(days=1), datetime.min.time(), SHANGHAI)
                - timedelta(microseconds=1)
            ),
        ),
        price_rule="exact_vendor_last_after_close.v1",
        price_rule_source_hash=sha256(
            b"test policy: exact vendor last price after published close"
        ).hexdigest(),
        price_boundary_mode=context.policy.price_boundary_mode,
        lower_boundary_factor=context.policy.lower_boundary_factor,
        upper_boundary_factor=context.policy.upper_boundary_factor,
        boundary_rule_source_id=cast(str, context.policy.boundary_rule_source_id),
        boundary_rule_version=cast(str, context.policy.boundary_rule_version),
        boundary_rule_source_hash=cast(str, context.policy.boundary_rule_source_hash),
        unrestricted_reason_code=context.policy.unrestricted_reason_code,
    )
    try:
        open_calendar = live_helpers._local_calendar_context(context=context, as_of=now)
    except (AssertionError, ValueError) as error:
        pytest.skip(f"published calendar cannot establish current session close: {error}")
    evaluation = evaluate_close_snapshot_simulation(
        capture=preflight,
        policy=policy,
        calendar=replace(open_calendar, session_state=SessionState.CLOSED),
        rule=context.uow.rule_bundle.execution_submission_v2,
        account_id=account_id,
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
        trading_date=trade_date,
        requested_price=quote.last_price,
        as_of=now,
    )
    if not _is_qualified(evaluation.decision.status):
        pytest.skip(
            "actual after-close Sina evidence is not eligible under the explicit paper policy: "
            f"{evaluation.decision.reason_codes}; retained {preflight_index}"
        )
    if evaluation.bundle is None:
        pytest.fail("qualified close-snapshot decision omitted the bound market bundle")

    with _runtime_public_write_clock():
        activate_runtime_profile_patch(
            environment="development",
            patch={CLOSE_SNAPSHOT_POLICIES_KEY: {"policies": [policy.to_payload()]}},
            actor="ash03-live-sina-close-snapshot-test",
            reason="explicit bounded local close-snapshot paper policy",
        )
    routed_captures, routed_indexes = live_helpers._install_capture_recorder(
        monkeypatch,
        scenario=f"close-{scenario}",
    )
    monkeypatch.setattr(
        close_market_composition, "capture_sina_quote", owner_market_composition.capture_sina_quote
    )
    original_guard = (
        owner_market_composition._AutomaticStopLossMarketProvider.validate_locked_submission
    )

    def retain_guard_failure(*args: Any, **kwargs: Any) -> Any:
        """Keep the actual exception chain without changing the guard or its outcome."""
        try:
            return original_guard(*args, **kwargs)
        except Exception:
            failure = traceback.format_exc()
            (artifact_dir / "locked-guard-failure.txt").write_text(failure, encoding="utf-8")
            print(failure)
            raise

    monkeypatch.setattr(
        owner_market_composition._AutomaticStopLossMarketProvider,
        "validate_locked_submission",
        retain_guard_failure,
    )
    return _CloseSnapshotEvidence(
        policy=policy,
        preflight_capture=preflight,
        preflight_index=preflight_index,
        routed_captures=routed_captures,
        routed_indexes=routed_indexes,
    )


def _assert_capture_clocks(
    *,
    capture: SinaQuoteCapture,
    index_path: Path,
    expected_price: Decimal,
    trade_date: date,
    close_at: datetime,
) -> None:
    """Bind retained raw bytes to source time, local availability, and price."""

    live_helpers._verify_capture_artifact(capture, index_path)
    quote = capture.quote
    assert quote is not None and quote.last_price is not None
    assert quote.source_observed_at is not None
    assert quote.last_price == expected_price
    assert quote.source_observed_at.astimezone(SHANGHAI).date() == trade_date
    assert _utc(quote.source_observed_at) >= _utc(close_at)
    assert _utc(capture.request_started_at) <= _utc(capture.response_completed_at)
    assert _utc(quote.source_observed_at) <= _utc(capture.response_completed_at)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert type(index) is dict
    assert not {"authorization", "cookie", "token", "csrf"} & set(cast(dict[str, object], index))


def _post_close_stop_loss(
    *,
    client: APIClient,
    csrf: str,
    account_id: int,
    trade_date: date,
    invocation_key: str,
) -> Any:
    """Call the existing owner route in the explicit stop-loss-only scope."""

    response = client.post(
        reverse("api_simulated_trading:auto-trading-run"),
        {
            "trade_date": trade_date.isoformat(),
            "account_ids": [account_id],
            "market_purpose": CLOSE_SNAPSHOT_PURPOSE,
            "execution_scope": "account_stop_loss_only",
            "confirmed": True,
        },
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY=invocation_key,
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="https://testserver",
    )
    assert response["Content-Type"].startswith("application/json")
    return response


def _trade_close_audit(trade: SimulatedTradeModel) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decode the immutable V3 receipt and select its close-source bundle."""

    binding = SimulatedSettlementPlanBindingV3.from_payload(trade.settlement_plan_binding_payload)
    assert binding.content_hash == trade.settlement_plan_binding_hash
    audit = binding.local_market_audit
    assert audit is not None
    identity_source = binding.identity_evidence.source_evidence
    assert identity_source.must_not_use_for_decision is True
    assert identity_source.must_not_execute is True
    audit_payload = audit.to_payload()
    evidence = cast(dict[str, Any], audit_payload["evidence"])
    market_bundle = cast(dict[str, Any], evidence["market_bundle"])
    assert market_bundle["purpose"] == CLOSE_SNAPSHOT_PURPOSE
    return audit_payload, market_bundle


def test_live_close_snapshot_owner_sell_reserves_partial_fill_cancel_and_replay(
    monkeypatch: pytest.MonkeyPatch,
    live_owner_context: live_helpers._LiveOwnerContext,
) -> None:
    """Use a real close quote for preview and Reserve; fill remains a synthetic fixture."""

    context = live_owner_context
    account = context.account
    account_id = cast(int, account.pk)
    evidence = _configure_close_snapshot_source(
        monkeypatch=monkeypatch,
        context=context,
        account_id=account_id,
        scenario="owner-reserve",
    )
    quote = evidence.preflight_capture.quote
    assert quote is not None and quote.last_price is not None
    price = quote.last_price.quantize(Decimal("0.0001"))
    close_at = datetime.combine(
        context.uow.market_session,
        max(window.ends_at for window in context.policy.session_windows),
        SHANGHAI,
    )

    position = _persist_sell_position(account)
    position.current_price = price
    position.market_value = (price * position.quantity).quantize(Decimal("0.01"))
    position.unrealized_pnl = position.market_value - position.total_cost
    position.unrealized_pnl_pct = float(
        (position.unrealized_pnl / position.total_cost) * Decimal("100")
    )
    position.save(
        update_fields=("current_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct")
    )
    account.current_market_value = position.market_value
    account.total_value = account.current_cash + position.market_value
    account.save(update_fields=("current_market_value", "total_value"))

    client, csrf = _owner_session_client(context.owner_id)
    before = (
        account.current_cash,
        position.quantity,
        position.available_quantity,
        SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account_id).count(),
    )
    preview_writes: list[str] = []

    def observe_writes(
        execute: Any,
        sql: str,
        params: object,
        many: bool,
        context_object: object,
    ) -> object:
        """Detect SQL mutation during the owner preview request."""

        if sql.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
            preview_writes.append(sql.split()[0])
        return execute(sql, params, many, context_object)

    with connection.execute_wrapper(observe_writes):
        preview = live_helpers._owner_post(
            client,
            csrf,
            "order-preview",
            account_id=account_id,
            payload={
                "asset_code": ASSET_CODE,
                "asset_name": ASSET_NAME,
                "side": "sell",
                "quantity": "200",
                "limit_price": format(price, ".4f"),
                "market_purpose": CLOSE_SNAPSHOT_PURPOSE,
            },
        )
    assert preview.status_code == 200, preview.data
    assert preview_writes == []
    assert preview.data["read_only"] is True
    assert preview.data["market_purpose"] == CLOSE_SNAPSHOT_PURPOSE
    assert preview.data["purpose"] == CLOSE_SNAPSHOT_PURPOSE
    market = cast(dict[str, Any], preview.data["market"])
    assert context.uow.market_session.isoformat() in json.dumps(
        {
            "market_session": market.get("market_session"),
            "trade_date": market.get("trade_date"),
        },
        sort_keys=True,
    )
    assert market["market_session"] == "CLOSED"
    assert market["security_state"] == "TRADING"
    assert market["snapshot_kind"] == "vendor_last_quote_after_close_not_official_close"
    assert market["price_rule"] == "exact_vendor_last_after_close.v1"
    qualification = cast(dict[str, Any], preview.data["market_qualification"])
    assert qualification["freshness"] == "close_snapshot"
    assert "fresh" != qualification["freshness"]
    assert qualification["local_simulation_qualified"] is True
    assert qualification["must_not_use_for_decision"] is True
    assert qualification["must_not_execute"] is True
    preview_capture = evidence.routed_captures[0]
    preview_quote = preview_capture.quote
    assert preview_quote is not None and preview_quote.last_price == price
    assert Decimal(str(market["reference_price"])) == price
    assert _parse_utc(market["market_observed_at"]) == _utc(
        cast(datetime, preview_quote.source_observed_at)
    )
    assert _parse_utc(market["market_available_at"]) == _utc(preview_capture.response_completed_at)
    assert _parse_utc(market["market_observed_at"]) >= _utc(close_at)
    qualified_at = _parse_utc(qualification["qualified_at"])
    assert qualified_at >= _utc(preview_capture.response_completed_at)
    assert "不是官方收盘价" in cast(str, preview.data["market_notice"])
    assert len(evidence.routed_captures) == 1
    _assert_capture_clocks(
        capture=preview_capture,
        index_path=evidence.routed_indexes[0],
        expected_price=price,
        trade_date=context.uow.market_session,
        close_at=close_at,
    )
    account.refresh_from_db()
    position.refresh_from_db()
    assert (
        account.current_cash,
        position.quantity,
        position.available_quantity,
        SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account_id).count(),
    ) == before

    continuation = cast(dict[str, Any], preview.data["continuation"])
    continuation_input = cast(dict[str, Any], continuation["input"])
    order_key = cast(str, continuation_input["order_key"])
    token = cast(str, continuation_input["preview_token"])
    assert set(continuation_input) == {"account_id", "order_key", "preview_token"}
    assert _parse_utc(continuation["expires_at"]) > _utc(timezone.now())
    confirmed = live_helpers._owner_post(
        client,
        csrf,
        "order-confirm",
        account_id=account_id,
        payload={
            "preview_token": token,
            "confirmed": True,
        },
        order_key=order_key,
    )
    assert confirmed.status_code == 200, confirmed.data
    assert confirmed.data["purpose"] == CLOSE_SNAPSHOT_PURPOSE
    assert confirmed.data["market_purpose"] == CLOSE_SNAPSHOT_PURPOSE
    order = SimulatedOrderReservationModel.objects.get(
        pk=confirmed.data["order_id"],
        account_id=account_id,
    )
    assert order.side == "sell"
    assert order.quantity == Decimal("200.000000")
    assert order.limit_price == price
    assert order.notional == (price * Decimal("200")).quantize(Decimal("0.01"))
    assert order.shares_reserved == Decimal("200.000000")
    assert order.filled_quantity == 0
    assert order.shares_consumed == 0
    assert order.shares_released == 0
    assert order.cash_reserved == 0
    assert order.fee_budget is None
    snapshot_text = json.dumps(order.plan_snapshot, ensure_ascii=False, sort_keys=True)
    assert CLOSE_SNAPSHOT_PURPOSE in snapshot_text
    assert preview_capture.body_sha256 in snapshot_text

    with transaction.atomic():
        chain = _locked_fill_chain(reservation_row=order, using="default")
        full_fee = chain.fee_policy.calculate_for(
            asset_type=chain.intent.asset_type,
            market=chain.intent.market,
            board=chain.intent.board,
            side=SimulatedTradeSide.SELL,
            amount=order.notional,
            as_of=chain.reservation.reserved_at,
        )
    assert order.fee_estimate == full_fee.total_fee
    assert order.commission_estimate == full_fee.commission
    assert order.transfer_fee_estimate == full_fee.transfer_fee
    assert order.stamp_duty_estimate == full_fee.stamp_duty
    assert order.slippage_estimate == full_fee.slippage

    fill_at = _utc(timezone.now())
    assert fill_at >= _utc(order.reserved_at)
    fill_quantity = Decimal("100.000000")
    event = LocalSimulatedFillEventV1(
        source_namespace="test.fixture.close-snapshot-owner-fill",
        source_version="fixture-v1",
        source_event_id=f"close-partial-{uuid4().hex}",
        event_payload_hash=sha256(b"explicit synthetic close-snapshot fill event").hexdigest(),
        source_snapshot_id="test.fixture.synthetic-close-order-fill",
        source_snapshot_hash=sha256(
            b"synthetic fill source, not a Sina market capture"
        ).hexdigest(),
        reservation_id=cast(int, order.pk),
        account_id=account_id,
        user_id=context.owner_id,
        order_idempotency_key=order_key,
        intent_payload_hash=order.intent_payload_hash,
        reservation_request_hash=order.reservation_request_hash,
        plan_snapshot_hash=order.plan_snapshot_hash,
        security_id=order.security_id,
        asset_code=order.asset_code,
        side=SimulatedTradeSide.SELL,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=fill_quantity,
        price=price,
        occurred_at=fill_at,
        source_observed_at=fill_at,
        source_available_at=fill_at,
        recorded_at=fill_at,
    )
    with transaction.atomic():
        fill_chain = _locked_fill_chain(reservation_row=order, using="default")
        expected_fill = prepare_order_reservation_fill(
            OrderReservationFillRequest(
                fill_event_id=event.source_event_id,
                intent=fill_chain.intent,
                stored_intent_payload_hash=order.intent_payload_hash,
                reservation=fill_chain.reservation,
                fee_policy=fill_chain.fee_policy,
                fill_occurred_at=fill_at,
                quantity=fill_quantity,
                price=price,
                prior=fill_chain.accrual,
                close_order=False,
            )
        )
    proof = build_order_fill_settlement_proof(
        calendar_evidence=context.uow.calendar_evidence,
        calendar_read_cutoff=fill_at,
        fill_occurred_at=fill_at,
        settlement_exchange=context.uow.calendar_evidence.snapshot.exchange,
        settlement_lag_sessions=context.uow.rule_bundle.settlement_policy_v1.settlement_lag_sessions,
    )
    filled = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(event, []),
        using="default",
    ).apply_fill_event(
        event=event,
        expected_event_payload_hash=event.event_payload_hash,
        settlement_proof=proof,
        clock=_FixedClock(fill_at),
    )
    assert filled.replayed is False
    assert filled.economics == expected_fill
    fill_trade = SimulatedTradeModel.objects.get(pk=filled.trade_id)
    assert fill_trade.settlement_plan_binding_version == 4
    validated_trade = DjangoTradeHistoryRepository().get_owned_trade_by_id(
        trade_id=cast(int, fill_trade.pk),
        account_id=account_id,
        user_id=context.owner_id,
    )
    assert validated_trade is not None
    assert validated_trade.trade_id == fill_trade.pk
    assert validated_trade.account_id == account_id
    assert validated_trade.action.value == SimulatedTradeSide.SELL.value
    assert fill_trade.action == SimulatedTradeSide.SELL.value
    assert fill_trade.quantity == fill_quantity
    assert fill_trade.price == price
    assert fill_trade.amount == expected_fill.gross_amount
    assert fill_trade.commission == expected_fill.incremental_fees.commission
    assert fill_trade.transfer_fee == expected_fill.incremental_fees.transfer_fee
    assert fill_trade.stamp_duty == expected_fill.incremental_fees.stamp_duty
    assert fill_trade.slippage == expected_fill.incremental_fees.slippage
    assert fill_trade.total_cost == expected_fill.incremental_fees.total_fee

    fill_receipt_row = SimulatedOrderFillReceiptModel.objects.get(trade_id=fill_trade.pk)
    fill_history = client.get(
        reverse(
            "api_simulated_trading:order-fill-history",
            kwargs={"account_id": account_id, "order_id": order.pk},
        ),
        secure=True,
    )
    assert fill_history.status_code == 200, fill_history.data
    assert fill_history["Content-Type"] == "application/json"
    assert fill_history.data["account_id"] == account_id
    assert fill_history.data["order_id"] == order.pk
    assert len(fill_history.data["fills"]) == 1
    fill_row = fill_history.data["fills"][0]
    assert fill_row["receipt_id"] == fill_receipt_row.pk
    assert fill_row["trade_id"] == fill_trade.pk
    assert fill_row["order_id"] == order.pk
    assert fill_row["fill_sequence"] == 1
    assert fill_row["side"] == SimulatedTradeSide.SELL.value
    assert fill_row["quantity"] == str(fill_quantity)
    assert fill_row["price"] == str(price)
    assert fill_row["verification_status"] == "single_receipt_verified"

    order.refresh_from_db()
    position.refresh_from_db()
    account.refresh_from_db()
    assert order.filled_quantity == fill_quantity
    assert order.shares_consumed == fill_quantity
    assert order.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert position.quantity == Decimal("900.000000")
    assert position.available_quantity == Decimal("900.000000")
    net_proceeds = expected_fill.gross_amount - expected_fill.incremental_fees.total_fee
    assert account.current_cash == before[0] + net_proceeds

    cancelled = client.post(
        reverse(
            "api_simulated_trading:order-cancel",
            kwargs={"account_id": account_id, "order_id": order.pk},
        ),
        {"confirmed": True},
        format="json",
        secure=True,
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="https://testserver",
    )
    assert cancelled.status_code == 200, cancelled.data
    order.refresh_from_db()
    assert order.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert order.shares_released == Decimal("100.000000")
    assert order.shares_reserved == order.shares_consumed + order.shares_released

    readback = client.get(
        reverse(
            "api_simulated_trading:order-by-key",
            kwargs={"account_id": account_id, "order_key": order_key},
        ),
        {"market_purpose": CLOSE_SNAPSHOT_PURPOSE},
        secure=True,
    )
    assert readback.status_code == 200, readback.data
    assert readback.data["order_id"] == order.pk
    assert readback.data["purpose"] == CLOSE_SNAPSHOT_PURPOSE
    assert readback.data["market_purpose"] == CLOSE_SNAPSHOT_PURPOSE
    assert readback.data["order"]["filled_quantity"] == "100.000000"
    assert readback.data["order"]["shares_released"] == "100.000000"
    account.refresh_from_db()
    position.refresh_from_db()
    order.refresh_from_db()
    financial_after_cancel = (
        account.current_cash,
        position.quantity,
        position.available_quantity,
        order.status,
        order.shares_consumed,
        order.shares_released,
        SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account_id).count(),
    )
    replay = live_helpers._owner_post(
        client,
        csrf,
        "order-confirm",
        account_id=account_id,
        payload={
            "preview_token": token,
            "confirmed": True,
        },
        order_key=order_key,
    )
    assert replay.status_code == 200, replay.data
    assert replay.data["replayed"] is True
    assert replay.data["purpose"] == CLOSE_SNAPSHOT_PURPOSE
    assert replay.data["market_purpose"] == CLOSE_SNAPSHOT_PURPOSE
    assert len(evidence.routed_captures) == 1
    account.refresh_from_db()
    position.refresh_from_db()
    order.refresh_from_db()
    assert (
        account.current_cash,
        position.quantity,
        position.available_quantity,
        order.status,
        order.shares_consumed,
        order.shares_released,
        SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account_id).count(),
    ) == financial_after_cancel
    assert SimulatedOrderReservationModel.objects.filter(account_id=account_id).count() == 1
    assert SimulatedTradeModel.objects.filter(account_id=account_id).count() == 1


def test_live_close_snapshot_stop_loss_uses_exact_receipt_and_same_key_replay(
    monkeypatch: pytest.MonkeyPatch,
    live_owner_context: live_helpers._LiveOwnerContext,
) -> None:
    """Seal actual vendor close-snapshot evidence into the ordinary stop-loss receipt."""

    context = live_owner_context
    account = context.account
    account_id = cast(int, account.pk)
    evidence = _configure_close_snapshot_source(
        monkeypatch=monkeypatch,
        context=context,
        account_id=account_id,
        scenario="owner-stop-loss",
    )
    quote = evidence.preflight_capture.quote
    assert quote is not None and quote.last_price is not None
    position = auto_fixture._persist_stop_loss_position(account)
    position.avg_cost = (quote.last_price * Decimal("2")).quantize(Decimal("0.0001"))
    position.total_cost = (position.avg_cost * position.quantity).quantize(Decimal("0.01"))
    position.current_price = quote.last_price
    position.market_value = (quote.last_price * position.quantity).quantize(Decimal("0.01"))
    position.unrealized_pnl = position.market_value - position.total_cost
    position.unrealized_pnl_pct = float(
        (position.unrealized_pnl / position.total_cost) * Decimal("100")
    )
    position.save(
        update_fields=(
            "avg_cost",
            "total_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
        )
    )
    account.refresh_from_db()
    account.current_market_value = position.market_value
    account.total_value = account.current_cash + position.market_value
    account.save()
    assert account.auto_trading_enabled is True
    assert account.stop_loss_pct == 10.0
    auto_fixture._build_real_auto_caller(
        monkeypatch,
        include_buy_candidate=False,
        strategy_id=None,
        legacy_exit=False,
    )
    client, csrf = _owner_session_client(context.owner_id)
    invocation_key = f"ash03-close-snapshot-stop-loss-{uuid4().hex}"
    first = _post_close_stop_loss(
        client=client,
        csrf=csrf,
        account_id=account_id,
        trade_date=context.uow.market_session,
        invocation_key=invocation_key,
    )
    assert first.status_code == 200, first.content
    payload = first.json()
    result_map = cast(dict[str, Any], payload["results"])
    account_result = cast(dict[str, Any], result_map[str(account_id)])
    assert payload["outcome"] == "success"
    assert payload["stored"] == 1
    assert account_result["outcome"] == "success"
    assert account_result["sell_count"] == 1
    assert account_result["confirmed_trade_count"] == 1
    assert account_result["stored"] == 1
    assert account_result["issues"] == []

    assert len(evidence.routed_captures) == 1
    capture = evidence.routed_captures[0]
    actual_quote = capture.quote
    assert actual_quote is not None and actual_quote.last_price is not None
    assert actual_quote.last_price == quote.last_price
    trade = SimulatedTradeModel.objects.get(account_id=account_id, action="sell")
    assert trade.quantity == Decimal("1000.000000")
    assert trade.price == actual_quote.last_price.quantize(Decimal("0.0001"))
    assert trade.amount == (trade.quantity * trade.price).quantize(Decimal("0.01"))
    assert trade.order_date == context.uow.market_session
    assert trade.execution_date == context.uow.market_session
    assert trade.settlement_plan_binding_version == 3
    assert trade.fee_amounts_known is True

    fees = DjangoFeePolicyV2Repository(using="default").get_execution_fee_policy(
        account_id=account_id,
        user_id=context.owner_id,
        asset_type="equity",
        market=context.uow.rule_market,
        board=context.uow.board,
        side=SimulatedTradeSide.SELL,
        as_of=_utc(trade.created_at),
    )
    assert fees is not None
    expected_fees = fees.calculate_for(
        asset_type="equity",
        market=context.uow.rule_market,
        board=context.uow.board,
        side=SimulatedTradeSide.SELL,
        amount=trade.amount,
        as_of=_utc(trade.created_at),
    )
    assert trade.commission == expected_fees.commission
    assert trade.transfer_fee == expected_fees.transfer_fee
    assert trade.stamp_duty == expected_fees.stamp_duty
    assert trade.slippage == expected_fees.slippage
    assert trade.total_cost == expected_fees.total_fee

    receipt = build_simulated_trade_execution_receipt(trade)
    assert receipt.side is SimulatedTradeSide.SELL
    assert receipt.quantity == trade.quantity
    assert receipt.price == trade.price
    assert receipt.amount == trade.amount
    assert receipt.commission == expected_fees.commission
    assert receipt.transfer_fee == expected_fees.transfer_fee
    assert receipt.stamp_duty == expected_fees.stamp_duty
    assert receipt.slippage == expected_fees.slippage
    assert receipt.total_cost == expected_fees.total_fee
    assert receipt.replayed is False

    audit_payload, market_bundle = _trade_close_audit(trade)
    assert market_bundle["purpose"] == CLOSE_SNAPSHOT_PURPOSE
    audit_evidence = cast(dict[str, Any], audit_payload["evidence"])
    close_decision = cast(dict[str, Any], audit_evidence["close_qualification"])
    assert close_decision["status"] == "QUALIFIED"
    assert close_decision["order_id"] == trade.idempotency_key
    assert close_decision["account_id"] == account_id
    assert audit_payload["close_qualification_hash"] == close_decision["content_hash"]
    assert _parse_utc(audit_payload["close_evaluated_at"]) == _parse_utc(
        audit_evidence["close_evaluated_at"]
    )
    stop_loss_qualification = cast(dict[str, Any], audit_evidence["qualification"])
    assert stop_loss_qualification == {
        "purpose": CLOSE_SNAPSHOT_PURPOSE,
        "decision_scope": "automatic_account_stop_loss",
        "local_simulation_qualified": True,
        "freshness": "close_snapshot",
        "reliability": "vendor_reported_close_snapshot",
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "execution_authority": False,
        "global_identity_restrictions": {
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        },
        "local_market_permission": {
            "purpose": CLOSE_SNAPSHOT_PURPOSE,
            "qualified": True,
            "must_not_execute": True,
            "execution_authority": False,
        },
        "market_available_at_basis": "local_response_completed_at_not_vendor_published_at",
    }
    policy_payload = cast(dict[str, Any], market_bundle["policy"])
    assert policy_payload["policy_id"] == evidence.policy.policy_id
    assert policy_payload["policy_version"] == evidence.policy.policy_version
    assert policy_payload["content_hash"] == evidence.policy.content_hash
    market_evidence = cast(dict[str, Any], market_bundle["market"])
    market_v1 = cast(dict[str, Any], market_evidence["market_evidence_v1"])
    assert str(market_v1["session_state"]).casefold() == "closed"
    assert "vendor_last_quote_after_close_not_official_close" in json.dumps(
        market_bundle,
        ensure_ascii=False,
        sort_keys=True,
    )
    capture_payload = cast(dict[str, Any], market_bundle["capture"])
    assert capture_payload["body_sha256"] == capture.body_sha256
    assert _parse_utc(market_v1["market_observed_at"]) == _utc(
        cast(datetime, actual_quote.source_observed_at)
    )
    assert _parse_utc(market_v1["market_available_at"]) == _utc(capture.response_completed_at)
    assert CLOSE_SNAPSHOT_PURPOSE in json.dumps(audit_payload, ensure_ascii=False, sort_keys=True)
    _assert_capture_clocks(
        capture=capture,
        index_path=evidence.routed_indexes[0],
        expected_price=actual_quote.last_price,
        trade_date=context.uow.market_session,
        close_at=datetime.combine(
            context.uow.market_session,
            max(window.ends_at for window in context.policy.session_windows),
            SHANGHAI,
        ),
    )

    assert not PositionModel.objects.filter(account_id=account_id, asset_code=ASSET_CODE).exists()
    account.refresh_from_db()
    assert account.current_cash == Decimal("100000.00") + trade.amount - trade.total_cost
    assert account.current_market_value == Decimal("0.00")
    assert account.total_value == account.current_cash
    assert account.total_trades == 1
    invocation = AutomaticTradingInvocationModel.objects.get(
        namespace=f"http:user:{context.owner_id}",
        invocation_key=invocation_key,
    )
    assert invocation.state == AutomaticTradingInvocationModel.STATE_FINISHED
    assert invocation.request_payload["market_purpose"] == CLOSE_SNAPSHOT_PURPOSE
    assert invocation.request_payload["execution_scope"] == "account_stop_loss_only"
    assert invocation.request_payload["confirmed"] is True
    assert invocation.trade_date == context.uow.market_session
    assert invocation.account_ids == [account_id]

    account.refresh_from_db()
    financial_after_first = (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        account.total_trades,
        SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account_id).count(),
    )
    replay = _post_close_stop_loss(
        client=client,
        csrf=csrf,
        account_id=account_id,
        trade_date=context.uow.market_session,
        invocation_key=invocation_key,
    )
    assert replay.status_code == 200, replay.content
    assert replay.json() == payload
    assert len(evidence.routed_captures) == 1
    assert SimulatedTradeModel.objects.filter(account_id=account_id).count() == 1
    assert SimulatedOrderReservationModel.objects.filter(account_id=account_id).count() == 0
    trade.refresh_from_db()
    account.refresh_from_db()
    assert (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        account.total_trades,
        SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account_id).count(),
    ) == financial_after_first
    assert trade.quantity == Decimal("1000.000000")
