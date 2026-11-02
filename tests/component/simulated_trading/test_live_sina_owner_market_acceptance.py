"""Opt-in live Sina acceptance through owner paper-order and stop-loss paths.

These tests require an explicitly enabled, migrated Native PostgreSQL test DB
and a genuinely eligible public quote in the current continuous session. They
never change system clocks, write broker configuration, or persist auth tokens.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import apps.simulated_trading.owner_order_submission_composition as owner_market_composition
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center.application.instrument_reference_snapshot import (
    SaveInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.application.sina_quote_capture import SinaQuoteCapture
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotContent,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.risk_center.application.local_simulated_market import (
    LocalSimulatedMarketBundle,
    build_submission_market,
)
from apps.risk_center.domain.execution_trading_constraints import SessionState
from apps.risk_center.domain.local_simulated_market_policy import (
    LocalSimulatedCalendarContext,
    LocalSimulatedMarketPolicy,
)
from apps.simulated_trading.domain.execution_current_reference import (
    SimulatedSettlementPlanBindingV3,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.infrastructure.automatic_trading_invocation_models import (
    AutomaticTradingInvocationModel,
)
from apps.simulated_trading.infrastructure.execution_settlement_plan_binding_repository import (
    build_simulated_trade_execution_receipt,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.owner_order_submission_composition import (
    SINA_SUBMISSION_POLICIES_KEY,
)
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.component.simulated_trading import (
    test_auto_trading_current_reference_t1 as auto_fixture,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _build_real_auto_caller,
    _create_account,
    _owner_session_client,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.ash03_auto_calendar_fixture import (
    FormalCalendarFixture,
    persist_auto_uow_formal_calendar,
)
from tests.support.ash03_auto_uow_fixture import (
    AutoCurrentReferenceUowFixture,
    build_auto_current_reference_uow_fixture,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.unit.risk_center.test_local_simulated_market_provider import _policy

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        os.environ.get("AGOM_RUN_LIVE_SINA_ACCEPTANCE") != "1",
        reason="set AGOM_RUN_LIVE_SINA_ACCEPTANCE=1 for public Sina live acceptance",
    ),
]

ASSET_CODE = "600000.SH"
ASSET_NAME = "Fixture bank"
SECURITY_ID = "SH.ASH03.AUTO.CALLER"
SOURCE_CODE = "600000.SH"
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class _LiveOwnerContext:
    """Hold test-owned account, local calendar/rules, and explicit paper policy."""

    account: SimulatedAccountModel
    owner_id: int
    policy: LocalSimulatedMarketPolicy
    calendar: FormalCalendarFixture
    uow: AutoCurrentReferenceUowFixture


@pytest.fixture(autouse=True)
def _require_native_live_test_database(django_db_use_migrations: bool) -> None:
    """Refuse opt-in live calls outside a migrated isolated Native PostgreSQL DB."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.fail("live Sina acceptance requires the migrated Native PostgreSQL test DB")
    if str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip().endswith(".production"):
        pytest.fail("live Sina acceptance is permitted only under non-production Django settings")
    assert_native_postgres_test_database()


@pytest.fixture
def live_owner_context(
    monkeypatch: pytest.MonkeyPatch,
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
) -> _LiveOwnerContext:
    """Compose fresh local test identity/calendar/rule/fee rows without a frozen clock."""

    repository, content = persisted_source_snapshot
    source = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    # The shared synthetic source fixture seals its two records up to six
    # seconds ahead. Let real time reach that declared knowledge boundary.
    # No quote has been requested and no system clock is changed here.
    known_at = max(source.recorded_at, source.mapping_record.recorded_at)
    wait_seconds = (known_at - timezone.now().astimezone(UTC)).total_seconds()
    if wait_seconds > 10:
        pytest.fail("synthetic identity knowledge cutoff is unexpectedly far in the future")
    if wait_seconds > 0:
        time.sleep(wait_seconds + 0.01)
    classification = content.classify_security(SOURCE_CODE)
    assert classification is not None
    assert classification.blocked_reason is None
    assert classification.rule_market is not None
    assert classification.board is not None
    account = _create_account()
    assert type(account.pk) is int and type(account.user_id) is int
    calendar = persist_auto_uow_formal_calendar(
        as_of=timezone.now().astimezone(UTC),
        exchange=classification.source_exchange,
        timezone_name="Asia/Shanghai",
        live_clock=True,
    )
    trade_date = calendar.market_session
    risk_cutoff = timezone.now().astimezone(UTC) - timedelta(seconds=2)
    monkeypatch.setattr(auto_fixture, "AS_OF", risk_cutoff)
    monkeypatch.setattr(auto_fixture, "KNOWLEDGE_AT", risk_cutoff - timedelta(seconds=10))
    bundle = auto_fixture._seed_rule_bundle(
        security_id=SECURITY_ID,
        market=classification.rule_market,
        board=classification.board,
    )
    monkeypatch.setattr(
        auto_fixture, "AS_OF", timezone.now().astimezone(UTC) + timedelta(minutes=1)
    )
    auto_fixture._seed_fee_policy(
        account_id=account.pk,
        market=classification.rule_market,
        board=classification.board,
    )
    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    runtime_environment = "production" if settings_module.endswith(".production") else "development"
    uow = build_auto_current_reference_uow_fixture(
        source_snapshot=source,
        account_id=account.pk,
        user_id=account.user_id,
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
        source_code=SOURCE_CODE,
        runtime_environment=runtime_environment,
        exchange_timezone="Asia/Shanghai",
        live_clock=True,
        actor="ash03-live-sina-test",
    )
    assert uow.market_session == trade_date
    assert uow.rule_bundle.content_hash == bundle.content_hash
    assert uow.as_of.utcoffset() == timedelta(0)
    policy = replace(
        _policy(),
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
        market=uow.rule_market,
        board=uow.board,
        effective_from=trade_date,
        effective_until=trade_date,
        content_hash="",
    )
    activate_runtime_profile_patch(
        environment=runtime_environment,
        patch={SINA_SUBMISSION_POLICIES_KEY: {"policies": [policy.to_payload()]}},
        actor="ash03-live-sina-test",
        reason="explicit local-only policy for opt-in public quote acceptance",
    )
    return _LiveOwnerContext(
        account=account,
        owner_id=account.user_id,
        policy=policy,
        calendar=calendar,
        uow=uow,
    )


def _install_capture_recorder(
    monkeypatch: pytest.MonkeyPatch,
    *,
    scenario: str,
) -> tuple[list[SinaQuoteCapture], list[Path]]:
    """Record exact public Sina bodies without storing owner or preview secrets."""

    original_capture = owner_market_composition.capture_sina_quote
    captures: list[SinaQuoteCapture] = []
    paths: list[Path] = []
    artifact_dir = Path(__file__).resolve().parents[3] / ".tmp" / "ash03-live-sina-acceptance"
    artifact_dir = artifact_dir / f"{scenario}-{timezone.now().astimezone(UTC):%Y%m%d}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    def recording_capture(asset_code: str) -> SinaQuoteCapture:
        """Delegate one actual request and retain its exact response bytes/index."""

        capture = original_capture(asset_code)
        captures.append(capture)
        paths.append(_retain_capture(capture, artifact_dir=artifact_dir))
        return capture

    monkeypatch.setattr(owner_market_composition, "capture_sina_quote", recording_capture)
    return captures, paths


def _retain_capture(capture: SinaQuoteCapture, *, artifact_dir: Path) -> Path:
    """Write exact body bytes and a small safe clock/hash index under ignored .tmp."""

    if type(capture) is not SinaQuoteCapture:
        raise TypeError("the recorder requires the exact Sina capture type")
    capture.__post_init__()
    suffix = uuid4().hex
    body_path = artifact_dir / f"{suffix}-{capture.body_sha256}.body"
    index_path = artifact_dir / f"{suffix}-{capture.body_sha256}.json"
    body_path.write_bytes(capture.body)
    quote = capture.quote
    index: dict[str, object] = {
        "schema": "ash03-live-sina-capture-index.v1",
        "purpose": "test_only_public_source_capture",
        "asset_code": capture.asset_code,
        "requested_url": capture.requested_url,
        "final_url": capture.final_url,
        "request_started_at_utc": _utc_text(capture.request_started_at),
        "response_completed_at_utc": _utc_text(capture.response_completed_at),
        "http_date": capture.http_date,
        "http_status": capture.http_status,
        "content_type": capture.content_type,
        "charset": capture.charset,
        "content_encoding": capture.content_encoding,
        "body_bytes": capture.body_size_bytes,
        "body_sha256": capture.body_sha256,
        "raw_body_path": body_path.name,
        "parse_issue": capture.parse_issue.value if capture.parse_issue is not None else None,
        "quote": (
            None
            if quote is None
            else {
                "source_date": quote.source_date_text,
                "source_time": quote.source_time_text,
                "source_observed_at": (
                    _utc_text(quote.source_observed_at)
                    if quote.source_observed_at is not None
                    else None
                ),
                "source_clock_status": quote.source_clock_status.value,
                "vendor_status_code": quote.vendor_status_code,
                "reported_trading_state": quote.reported_trading_state.value,
                "previous_close": _decimal_text(quote.previous_close),
                "last_price": _decimal_text(quote.last_price),
                "bid_price": _decimal_text(quote.bid_price),
                "ask_price": _decimal_text(quote.ask_price),
            }
        ),
    }
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return index_path


def _verify_capture_artifact(capture: SinaQuoteCapture, index_path: Path) -> None:
    """Verify persisted raw bytes, hash, URL, and actual response clocks."""

    index_value = json.loads(index_path.read_text(encoding="utf-8"))
    if type(index_value) is not dict:
        raise AssertionError("capture evidence index must be a JSON object")
    index = cast(dict[str, object], index_value)
    body_name = index.get("raw_body_path")
    if type(body_name) is not str:
        raise AssertionError("capture evidence index has no raw body path")
    body = (index_path.parent / body_name).read_bytes()
    assert body == capture.body
    assert sha256(body).hexdigest() == capture.body_sha256
    assert index["body_sha256"] == capture.body_sha256
    assert index["body_bytes"] == len(capture.body)
    assert index["requested_url"] == capture.requested_url
    assert index["final_url"] == capture.final_url
    assert index["request_started_at_utc"] == _utc_text(capture.request_started_at)
    assert index["response_completed_at_utc"] == _utc_text(capture.response_completed_at)
    assert index["http_date"] == capture.http_date
    assert index["http_status"] == capture.http_status


def _qualify_capture(
    capture: SinaQuoteCapture,
    *,
    context: _LiveOwnerContext,
    as_of: datetime,
) -> tuple[LocalSimulatedMarketBundle | None, str]:
    """Apply the same paper market qualification before accepting live evidence."""

    quote = capture.quote
    if not capture.usable_parse or quote is None:
        return None, "Sina response did not parse into a usable quote"
    if quote.source_clock_status.value != "valid" or quote.source_observed_at is None:
        return None, f"Sina source clock is {quote.source_clock_status.value}"
    if quote.vendor_status_code not in context.policy.trusted_vendor_status_codes:
        return (
            None,
            f"Sina vendor status {quote.vendor_status_code!r} is not trusted by the test policy",
        )
    if quote.reported_trading_state.value != "trading":
        return None, f"Sina reports state {quote.reported_trading_state.value}"
    if quote.last_price is None or quote.previous_close is None:
        return None, "Sina quote lacks last or same-day previous-close price"
    if quote.source_observed_at.astimezone(SHANGHAI).date() != context.uow.market_session:
        return None, "Sina source date differs from the current test calendar session"
    age = as_of.astimezone(UTC) - quote.source_observed_at.astimezone(UTC)
    if age < timedelta(0) or age >= timedelta(seconds=context.policy.quote_ttl_seconds):
        return None, "Sina source quote is future-dated or outside the configured test TTL"
    if not context.policy.is_same_continuous_window(
        observed_at=quote.source_observed_at,
        as_of=as_of,
    ):
        return None, "Sina source observation is outside the current configured continuous window"
    local_now = as_of.astimezone(SHANGHAI)
    if local_now.date() != context.uow.market_session:
        return None, "the current system date is outside the test calendar session"
    if not any(
        window.starts_at <= local_now.timetz().replace(tzinfo=None) < window.ends_at
        for window in context.policy.session_windows
    ):
        return None, "the current system clock is outside configured continuous trading hours"
    try:
        lower, upper = context.policy.derive_price_boundaries(
            previous_close=quote.previous_close,
            price_tick=context.uow.rule_bundle.execution_submission_v2.execution_rule_v1.price_tick,
        )
    except ValueError as error:
        return None, f"test paper price boundary could not be derived: {error}"
    if lower is not None and quote.last_price < lower:
        return None, "Sina last price is below the configured paper boundary"
    if upper is not None and quote.last_price > upper:
        return None, "Sina last price is above the configured paper boundary"
    calendar = _local_calendar_context(context=context, as_of=as_of)
    bundle = build_submission_market(
        policy=context.policy,
        capture=capture,
        calendar=calendar,
        rule=context.uow.rule_bundle.execution_submission_v2,
        as_of=as_of,
    )
    if bundle is None:
        return None, "the qualified Sina capture did not form a complete V2 paper market"
    return bundle, ""


def _local_calendar_context(
    *,
    context: _LiveOwnerContext,
    as_of: datetime,
) -> LocalSimulatedCalendarContext:
    """Adapt the persisted synthetic Native-test calendar to the paper policy."""

    evidence = context.uow.calendar_evidence
    evidence.validate_for(as_of)
    publication = evidence.publication
    if publication is None:
        raise AssertionError("the Native test calendar publication is missing")
    day = evidence.current_open_session(as_of)
    if day != context.uow.market_session:
        raise AssertionError("current test calendar session changed during acceptance")
    windows = context.policy.session_windows
    zone = ZoneInfo(context.policy.session_timezone)
    return LocalSimulatedCalendarContext(
        calendar_id=publication.publication_id,
        calendar_version=publication.publication_hash,
        calendar_source_hash=evidence.evidence_hash,
        calendar_observed_at=evidence.snapshot.raw_reference.response_completed_at,
        calendar_available_at=max(
            evidence.snapshot.recorded_at,
            publication.recorded_at,
            evidence.snapshot.raw_reference.response_completed_at,
        ),
        calendar_valid_until=publication.reference_valid_until,
        trading_date=day,
        session_id=f"{evidence.snapshot.exchange}:{day.isoformat()}",
        session_timezone=context.policy.session_timezone,
        session_open_at=datetime.combine(day, min(window.starts_at for window in windows), zone),
        session_close_at=datetime.combine(day, max(window.ends_at for window in windows), zone),
        session_state=SessionState.OPEN,
    )


def _require_live_qualified(
    capture: SinaQuoteCapture,
    *,
    context: _LiveOwnerContext,
    evidence_path: Path,
) -> LocalSimulatedMarketBundle:
    """Skip rather than pass when the actual current source is not eligible."""

    bundle, reason = _qualify_capture(
        capture,
        context=context,
        as_of=timezone.now().astimezone(UTC),
    )
    if bundle is None:
        pytest.skip(f"not a live positive acceptance: {reason}; retained evidence: {evidence_path}")
    return bundle


def _skip_outside_current_session(context: _LiveOwnerContext) -> None:
    """Do not request source data outside the current actual continuous session."""

    now = timezone.now().astimezone(SHANGHAI)
    if now.date() != context.uow.market_session:
        pytest.skip("not a live positive acceptance: system date is not the current open session")
    if not any(
        window.starts_at <= now.timetz().replace(tzinfo=None) < window.ends_at
        for window in context.policy.session_windows
    ):
        pytest.skip(
            "not a live positive acceptance: actual system clock is outside continuous hours"
        )


def _owner_post(
    client: APIClient,
    csrf: str,
    operation: str,
    *,
    account_id: int,
    payload: dict[str, object],
    order_key: str | None = None,
) -> Any:
    """Post one owner operation through the real Session and CSRF checks."""

    route_values: dict[str, object] = {"account_id": account_id}
    if order_key is not None:
        route_values["order_key"] = order_key
    response = client.post(
        reverse(f"api_simulated_trading:{operation}", kwargs=route_values),
        payload,
        format="json",
        secure=True,
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="https://testserver",
    )
    assert response["Content-Type"].startswith("application/json")
    return response


def _post_auto_stop_loss(
    client: APIClient,
    csrf: str,
    *,
    account_id: int,
    trade_date: date,
    invocation_key: str,
) -> Any:
    """Submit the existing automatic trade endpoint with one exact retry key."""

    response = client.post(
        reverse("api_simulated_trading:auto-trading-run"),
        {"trade_date": trade_date.isoformat(), "account_ids": [account_id]},
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY=invocation_key,
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="https://testserver",
    )
    assert response["Content-Type"].startswith("application/json")
    return response


def _safe_account_result(payload: object, account_id: int) -> dict[str, Any]:
    """Select one account result without including response secrets in failures."""

    if type(payload) is not dict:
        raise AssertionError("owner response must be a JSON object")
    results = cast(dict[str, object], payload).get("results")
    if type(results) is not dict:
        raise AssertionError("automatic owner response has no result map")
    result = cast(dict[str, object], results).get(str(account_id))
    if type(result) is not dict:
        raise AssertionError("automatic owner response omitted the selected account")
    return cast(dict[str, Any], result)


def _seed_live_stop_loss_position(
    account: SimulatedAccountModel,
    *,
    reference_price: Decimal,
    trade_date: date,
) -> PositionModel:
    """Create an explicit test-only held position whose chosen cost can trigger."""

    quantity = Decimal("1000.000000")
    avg_cost = (reference_price * Decimal("2")).quantize(Decimal("0.0001"))
    total_cost = (avg_cost * quantity).quantize(Decimal("0.01"))
    market_value = (reference_price * quantity).quantize(Decimal("0.01"))
    account.stop_loss_pct = 40.0
    account.current_market_value = market_value
    account.total_value = account.current_cash + market_value
    account.save(update_fields=("stop_loss_pct", "current_market_value", "total_value"))
    return PositionModel._default_manager.create(
        account=account,
        asset_code=ASSET_CODE,
        asset_name=ASSET_NAME,
        asset_type="equity",
        quantity=quantity,
        available_quantity=quantity,
        available_quantity_known=True,
        avg_cost=avg_cost,
        total_cost=total_cost,
        cost_basis_known=True,
        current_price=reference_price,
        market_value=market_value,
        valuation_known=True,
        unrealized_pnl=market_value - total_cost,
        unrealized_pnl_pct=-50.0,
        first_buy_date=trade_date - timedelta(days=1),
        first_buy_date_known=True,
    )


def _assert_sell_trade_evidence(
    *,
    context: _LiveOwnerContext,
    capture: SinaQuoteCapture,
    invocation_key: str,
) -> SimulatedTradeModel:
    """Bind actual source clocks, local purpose, exact fees, cash, and V4 receipt."""

    account = context.account
    account_id = cast(int, account.pk)
    quote = capture.quote
    assert quote is not None and quote.last_price is not None
    invocation = AutomaticTradingInvocationModel._default_manager.get(
        namespace=f"http:user:{context.owner_id}",
        invocation_key=invocation_key,
    )
    assert invocation.state == AutomaticTradingInvocationModel.STATE_FINISHED
    assert invocation.trade_date == context.uow.market_session
    assert invocation.account_ids == [account_id]
    trade = SimulatedTradeModel._default_manager.get(
        account_id=account_id,
        asset_code=ASSET_CODE,
        action="sell",
    )
    assert trade.status == "executed"
    assert trade.quantity == Decimal("1000.000000")
    assert trade.price == quote.last_price.quantize(Decimal("0.0001"))
    assert trade.amount == (trade.price * trade.quantity).quantize(Decimal("0.01"))
    assert trade.order_date == context.uow.market_session
    assert trade.execution_date == context.uow.market_session
    assert trade.idempotency_key == f"auto:{invocation.invocation_id.hex}:1:sell"
    assert trade.request_payload_hash is not None
    assert trade.fee_amounts_known is True
    assert trade.commission is not None
    assert trade.transfer_fee is not None
    assert trade.stamp_duty is not None
    assert trade.slippage is not None
    assert trade.total_cost == (
        trade.commission + trade.transfer_fee + trade.stamp_duty + trade.slippage
    )
    assert trade.settlement_plan_binding_version == 3
    receipt = build_simulated_trade_execution_receipt(trade)
    assert receipt.trade_id == trade.pk
    assert receipt.account_id == account_id
    assert receipt.idempotency_key == trade.idempotency_key
    assert receipt.request_payload_hash == trade.request_payload_hash
    assert receipt.side is SimulatedTradeSide.SELL
    assert receipt.quantity == trade.quantity
    assert receipt.price == trade.price
    assert receipt.amount == trade.amount
    assert receipt.commission == trade.commission
    assert receipt.transfer_fee == trade.transfer_fee
    assert receipt.stamp_duty == trade.stamp_duty
    assert receipt.slippage == trade.slippage
    assert receipt.total_cost == trade.total_cost
    assert receipt.replayed is False
    binding = SimulatedSettlementPlanBindingV3.from_payload(trade.settlement_plan_binding_payload)
    assert binding.content_hash == trade.settlement_plan_binding_hash
    assert binding.identity_evidence.source_evidence.must_not_use_for_decision is True
    assert binding.identity_evidence.source_evidence.must_not_execute is True
    audit = binding.local_market_audit
    assert audit is not None
    audit_payload = audit.to_payload()
    evidence = cast(dict[str, Any], audit_payload["evidence"])
    retained = cast(dict[str, Any], evidence["retained_source"])
    capture_payload = cast(dict[str, Any], retained["capture"])
    assert capture_payload["body_sha256"] == capture.body_sha256
    assert capture_payload["request_started_at"] == _utc_text(capture.request_started_at)
    assert capture_payload["response_completed_at"] == _utc_text(capture.response_completed_at)
    market_bundle = cast(dict[str, Any], evidence["market_bundle"])
    assert market_bundle["purpose"] == "local_simulation_only"
    assert market_bundle["market_available_at_basis"] == (
        "local_response_completed_at_not_vendor_published_at"
    )
    qualification = cast(dict[str, Any], evidence["qualification"])
    assert qualification["decision_scope"] == "automatic_account_stop_loss"
    assert qualification["must_not_use_for_decision"] is True
    assert qualification["must_not_execute"] is True
    assert qualification["execution_authority"] is False
    assert qualification["global_identity_restrictions"] == {
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    assert qualification["local_market_permission"]["purpose"] == "local_simulation_only"
    assert qualification["local_market_permission"]["must_not_execute"] is True
    assert qualification["local_market_permission"]["execution_authority"] is False
    return trade


def test_live_sina_owner_sell_preview_confirm_readback_and_same_key_recovery(
    monkeypatch: pytest.MonkeyPatch,
    live_owner_context: _LiveOwnerContext,
) -> None:
    """Seed a local holding after quote qualification, reserve shares once, and recover it."""

    context = live_owner_context
    _skip_outside_current_session(context)
    captures, evidence_paths = _install_capture_recorder(monkeypatch, scenario="owner-order")
    preflight = owner_market_composition.capture_sina_quote(ASSET_CODE)
    _verify_capture_artifact(preflight, evidence_paths[-1])
    preflight_bundle = _require_live_qualified(
        preflight,
        context=context,
        evidence_path=evidence_paths[-1],
    )
    quote = preflight_bundle.market.market_evidence_v1.reference_price
    assert quote is not None
    position = _seed_live_stop_loss_position(
        context.account,
        reference_price=quote,
        trade_date=context.uow.market_session,
    )
    context.account.refresh_from_db()
    position.refresh_from_db()
    client, csrf = _owner_session_client(context.owner_id)
    account_id = cast(int, context.account.pk)
    before_cash = context.account.current_cash
    before_position_quantity = position.quantity
    before_available_quantity = position.available_quantity
    before_trades = SimulatedTradeModel._default_manager.filter(account_id=account_id).count()
    before_reservations = SimulatedOrderReservationModel._default_manager.filter(
        account_id=account_id
    ).count()

    preview = _owner_post(
        client,
        csrf,
        "order-preview",
        account_id=account_id,
        payload={
            "asset_code": ASSET_CODE,
            "asset_name": ASSET_NAME,
            "side": "sell",
            "quantity": "100",
            "limit_price": str(quote),
        },
    )
    assert len(captures) == 2
    preview_capture = captures[-1]
    _verify_capture_artifact(preview_capture, evidence_paths[-1])
    preview_bundle, preview_reason = _qualify_capture(
        preview_capture,
        context=context,
        as_of=timezone.now().astimezone(UTC),
    )
    context.account.refresh_from_db()
    position.refresh_from_db()
    assert context.account.current_cash == before_cash
    assert position.quantity == before_position_quantity
    assert position.available_quantity == before_available_quantity
    assert (
        SimulatedTradeModel._default_manager.filter(account_id=account_id).count() == before_trades
    )
    assert (
        SimulatedOrderReservationModel._default_manager.filter(account_id=account_id).count()
        == before_reservations
    )
    if preview.status_code != 200:
        if preview_bundle is None:
            pytest.skip(
                "not a live positive acceptance: owner preview capture became unqualified; "
                f"reason={preview_reason}, evidence={evidence_paths[-1]}"
            )
        pytest.fail(f"qualified owner preview returned unexpected HTTP {preview.status_code}")
    if preview_bundle is None:
        pytest.skip(
            "not a live positive acceptance: owner preview capture became unqualified; "
            f"reason={preview_reason}, evidence={evidence_paths[-1]}"
        )
    assert preview.status_code == 200
    payload = cast(dict[str, Any], preview.data)
    assert payload["read_only"] is True
    assert payload["execution_submitted"] is False
    preview_order = cast(dict[str, Any], payload["order"])
    assert preview_order["side"] == "sell"
    assert Decimal(str(preview_order["quantity"])) == Decimal("100")
    assert Decimal(str(preview_order["shares_reserved"])) == Decimal("100")
    assert Decimal(str(preview_order["cash_reserved"])) == Decimal("0")
    assert preview_order["status"] == "active"
    qualification = cast(dict[str, Any], payload["market_qualification"])
    assert qualification["decision_scope"] == "local_simulation_only"
    assert qualification["freshness"] == "fresh"
    assert qualification["must_not_use_for_decision"] is False
    assert qualification["must_not_execute"] is True
    assert qualification["market_available_at_basis"] == (
        "local_response_completed_at_not_vendor_published_at"
    )
    assert "preview_token" not in payload
    continuation = cast(dict[str, Any], payload["continuation"])
    inputs = cast(dict[str, Any], continuation["input"])
    token = inputs["preview_token"]
    order_key = inputs["order_key"]
    assert type(token) is str and token
    assert type(order_key) is str and order_key

    confirmation = _owner_post(
        client,
        csrf,
        "order-confirm",
        account_id=account_id,
        order_key=order_key,
        payload={"preview_token": token, "confirmed": True},
    )
    assert confirmation.status_code == 200
    confirmed_payload = cast(dict[str, Any], confirmation.data)
    assert confirmed_payload["read_only"] is False
    assert confirmed_payload["execution_submitted"] is False
    assert confirmed_payload["success"] is True
    assert confirmed_payload["outcome"] == "success"
    order_id = confirmed_payload["order_id"]
    order = SimulatedOrderReservationModel._default_manager.get(pk=order_id)
    assert order.account_id == account_id
    assert order.asset_code == ASSET_CODE
    assert order.idempotency_key == order_key
    assert order.status == "active"
    assert order.side == "sell"
    assert order.quantity == Decimal("100")
    assert order.shares_reserved == Decimal("100")
    assert order.cash_reserved == Decimal("0")
    assert order.filled_quantity == Decimal("0")
    assert order.cash_consumed == Decimal("0")
    assert order.shares_consumed == Decimal("0")
    assert order.fee_estimate == (
        order.commission_estimate
        + order.transfer_fee_estimate
        + order.stamp_duty_estimate
        + order.slippage_estimate
    )
    assert order.notional == (order.quantity * order.limit_price).quantize(Decimal("0.01"))
    confirmed_order = cast(dict[str, Any], confirmed_payload["order"])
    assert confirmed_order["side"] == "sell"
    assert Decimal(str(confirmed_order["shares_reserved"])) == Decimal("100")
    assert Decimal(str(confirmed_order["cash_reserved"])) == Decimal("0")
    assert confirmed_order["status"] == "active"
    context.account.refresh_from_db()
    position.refresh_from_db()
    assert context.account.current_cash == before_cash
    assert position.quantity == before_position_quantity
    assert position.available_quantity == before_available_quantity
    assert (
        SimulatedTradeModel._default_manager.filter(account_id=account_id).count() == before_trades
    )
    order_snapshot = cast(dict[str, Any], order.plan_snapshot)
    submission_snapshot = cast(dict[str, Any], order_snapshot["submission_market"])
    serialized_submission_snapshot = json.dumps(
        submission_snapshot,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
    )
    assert preview_capture.body_sha256 in serialized_submission_snapshot
    assert _utc_text(preview_capture.response_completed_at) in serialized_submission_snapshot

    readback = client.get(
        reverse(
            "api_simulated_trading:order-by-key",
            kwargs={"account_id": account_id, "order_key": order_key},
        ),
        secure=True,
    )
    assert readback.status_code == 200
    readback_payload = cast(dict[str, Any], readback.data)
    assert readback_payload["read_only"] is True
    assert readback_payload["order_id"] == order_id
    assert readback_payload["order_key"] == order_key
    readback_order = cast(dict[str, Any], readback_payload["order"])
    assert readback_order["side"] == "sell"
    assert Decimal(str(readback_order["quantity"])) == Decimal("100")
    assert Decimal(str(readback_order["shares_reserved"])) == Decimal("100")
    assert Decimal(str(readback_order["cash_reserved"])) == Decimal("0")
    assert readback_order["status"] == "active"
    assert Decimal(str(readback_order["filled_quantity"])) == Decimal("0")

    replay = _owner_post(
        client,
        csrf,
        "order-confirm",
        account_id=account_id,
        order_key=order_key,
        payload={"preview_token": token, "confirmed": True},
    )
    assert replay.status_code == 200
    assert replay.data["order_id"] == order_id
    assert replay.data["replayed"] is True
    assert len(captures) == 2
    assert (
        SimulatedTradeModel._default_manager.filter(account_id=account_id).count() == before_trades
    )
    assert (
        SimulatedOrderReservationModel._default_manager.filter(account_id=account_id).count()
        == before_reservations + 1
    )


def test_live_sina_account_stop_loss_sell_replays_without_a_second_capture(
    monkeypatch: pytest.MonkeyPatch,
    live_owner_context: _LiveOwnerContext,
) -> None:
    """Use a real qualified Sina quote for the ordinary stop-loss SELL and exact replay."""

    context = live_owner_context
    _skip_outside_current_session(context)
    captures, evidence_paths = _install_capture_recorder(monkeypatch, scenario="account-stop-loss")
    preflight = owner_market_composition.capture_sina_quote(ASSET_CODE)
    _verify_capture_artifact(preflight, evidence_paths[-1])
    preflight_bundle = _require_live_qualified(
        preflight,
        context=context,
        evidence_path=evidence_paths[-1],
    )
    reference_price = preflight_bundle.market.market_evidence_v1.reference_price
    assert reference_price is not None
    trade_date = context.uow.market_session
    position = _seed_live_stop_loss_position(
        context.account,
        reference_price=reference_price,
        trade_date=trade_date,
    )
    account_id = cast(int, context.account.pk)
    initial_cash = context.account.current_cash
    initial_market_value = context.account.current_market_value
    initial_total_value = context.account.total_value
    monkeypatch.setattr(auto_fixture, "TRADE_DATE", trade_date)
    _build_real_auto_caller(
        monkeypatch,
        include_buy_candidate=False,
        strategy_id=None,
        legacy_exit=False,
    )
    client, csrf = _owner_session_client(context.owner_id)
    invocation_key = f"ash03-live-stop-loss-{uuid4().hex}"
    first = _post_auto_stop_loss(
        client,
        csrf,
        account_id=account_id,
        trade_date=trade_date,
        invocation_key=invocation_key,
    )
    assert first.status_code == 200
    assert len(captures) == 2
    route_capture = captures[-1]
    _verify_capture_artifact(route_capture, evidence_paths[-1])
    route_bundle, route_reason = _qualify_capture(
        route_capture,
        context=context,
        as_of=timezone.now().astimezone(UTC),
    )
    if route_bundle is None:
        assert SimulatedTradeModel._default_manager.filter(account_id=account_id).count() == 0
        position.refresh_from_db()
        context.account.refresh_from_db()
        assert position.quantity == Decimal("1000.000000")
        assert position.available_quantity == Decimal("1000.000000")
        assert context.account.current_cash == initial_cash
        assert context.account.current_market_value == initial_market_value
        assert context.account.total_value == initial_total_value
        pytest.skip(
            "not a live positive acceptance: stop-loss route quote became unqualified; "
            f"reason={route_reason}, evidence={evidence_paths[-1]}"
        )
    route_quote = route_capture.quote
    assert route_quote is not None and route_quote.last_price is not None
    stop_price = (position.avg_cost * Decimal("0.60")).quantize(Decimal("0.0001"))
    result = _safe_account_result(first.data, account_id)
    if result.get("sell_count") != 1:
        if route_quote.last_price > stop_price:
            assert SimulatedTradeModel._default_manager.filter(account_id=account_id).count() == 0
            position.refresh_from_db()
            context.account.refresh_from_db()
            assert position.quantity == Decimal("1000.000000")
            assert position.available_quantity == Decimal("1000.000000")
            assert context.account.current_cash == initial_cash
            assert context.account.current_market_value == initial_market_value
            assert context.account.total_value == initial_total_value
            pytest.skip(
                "not a live positive acceptance: actual quote recovered above the test stop price; "
                f"quote={route_quote.last_price}, evidence={evidence_paths[-1]}"
            )
        pytest.fail("qualified source quote crossed the explicit test stop but no SELL was stored")
    assert first.data["outcome"] == "success"
    assert result["outcome"] == "success"
    assert result["confirmed_trade_count"] == 1
    assert result["stored"] == 1

    trade = _assert_sell_trade_evidence(
        context=context,
        capture=route_capture,
        invocation_key=invocation_key,
    )
    assert trade.price == route_quote.last_price.quantize(Decimal("0.0001"))
    assert not PositionModel._default_manager.filter(
        account_id=account_id,
        asset_code=ASSET_CODE,
    ).exists()
    context.account.refresh_from_db()
    assert context.account.current_cash == initial_cash + trade.amount - trade.total_cost
    assert context.account.current_market_value == Decimal("0.00")
    assert context.account.total_value == context.account.current_cash
    assert context.account.total_trades == 1

    replay = _post_auto_stop_loss(
        client,
        csrf,
        account_id=account_id,
        trade_date=trade_date,
        invocation_key=invocation_key,
    )
    assert replay.status_code == 200
    assert len(captures) == 2
    assert _safe_account_result(replay.data, account_id)["sell_count"] == 1
    assert SimulatedTradeModel._default_manager.filter(account_id=account_id).count() == 1
    assert not PositionModel._default_manager.filter(
        account_id=account_id,
        asset_code=ASSET_CODE,
    ).exists()
    context.account.refresh_from_db()
    assert context.account.current_cash == initial_cash + trade.amount - trade.total_cost
    assert context.account.total_trades == 1


def _utc_text(value: datetime | None) -> str | None:
    """Return source clocks as stable UTC text without inventing missing times."""

    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Decimal | None) -> str | None:
    """Return exact source decimal text while retaining missing values as null."""

    return None if value is None else str(value)
