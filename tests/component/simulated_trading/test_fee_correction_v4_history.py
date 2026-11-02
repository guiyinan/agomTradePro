"""Prove fee correction preserves a real FeeV2 V4 fill prefix and history read."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import cast
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    OPERATOR_FEE_CSV_SCHEMA,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
)
from apps.simulated_trading.application.order_reservation_fill import (
    ApplySimulatedOrderFillCommand,
    ApplySimulatedOrderFillUseCase,
    LocalSimulatedFillSourceBinding,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
    DjangoFeeCorrectionEvidenceRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_django_fee_correction_repository,
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
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from shared.config.secrets import clear_secrets_cache, get_secrets
from shared.infrastructure.crypto import FieldEncryptionService
from tests.api.test_fee_correction_confirmation_api import _session_user_client
from tests.api.test_fee_correction_flow_api import _assert_json, _head_url
from tests.api.test_fee_correction_preview_api import _preview_url
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _READ_CUTOFF,
    _EventReader,
    _first_buy_rows,
    _FixedClock,
    _initial_position_mark,
    _InitialPositionMarkReader,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
)
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=[
            "apps.simulated_trading",
            "apps.account",
            "apps.config_center",
            "apps.data_center",
            "apps.risk_center",
            "apps.portfolio",
            "core",
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
        ],
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Fee correction V4 history requires Native PostgreSQL",
    ),
]


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Bind this module to the shared explicit TEST.NAME setup."""

    return native_postgres_test_database


_CSV_HEADERS = (
    "schema_version",
    "currency_code",
    "source_account_ref",
    "source_trade_ref",
    "asset_code",
    "side",
    "quantity",
    "price",
    "amount",
    "execution_at",
    "source_observed_at",
    "commission",
    "transfer_fee",
    "stamp_duty",
)


@dataclass(frozen=True, slots=True)
class _FixtureSettlementResolver:
    """Build a settlement proof from the fixture's published calendar evidence."""

    evidence: ExecutionCalendarEvidence
    read_cutoff: datetime

    def resolve(
        self,
        *,
        event_occurred_at: datetime,
        settlement_exchange: str,
        settlement_lag_sessions: int,
        sealed_calendar_evidence: ExecutionCalendarEvidence | None = None,
    ) -> OrderFillSettlementProof | None:
        """Resolve only the exact exchange and lag held by the sealed fixture."""

        if settlement_exchange != self.evidence.snapshot.exchange:
            return None
        return build_order_fill_settlement_proof(
            calendar_evidence=self.evidence,
            calendar_read_cutoff=self.read_cutoff,
            fill_occurred_at=event_occurred_at,
            settlement_exchange=settlement_exchange,
            settlement_lag_sessions=settlement_lag_sessions,
        )


def _json_object(value: object, label: str) -> dict[str, object]:
    """Narrow a persisted JSON object before asserting its sealed accrual fields."""

    if type(value) is not dict:
        raise AssertionError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _trade_rows_snapshot(account_id: int) -> tuple[dict[str, object], ...]:
    """Capture every persisted Trade column for an exact immutability comparison."""

    return tuple(
        cast(dict[str, object], row)
        for row in SimulatedTradeModel._base_manager.filter(account_id=account_id)
        .order_by("pk")
        .values()
    )


def _receipt_rows_snapshot(account_id: int) -> tuple[dict[str, object], ...]:
    """Capture every persisted receipt column, including JSON and all content seals."""

    return tuple(
        cast(dict[str, object], row)
        for row in SimulatedOrderFillReceiptModel._base_manager.filter(trade__account_id=account_id)
        .order_by("reservation_id", "fill_sequence", "pk")
        .values()
    )


def _operator_attested_csv(
    *,
    account_id: int,
    trade: SimulatedTradeModel,
    source_observed_at: datetime,
    revised_commission: Decimal,
    revised_transfer_fee: Decimal | None = None,
    revised_stamp_duty: Decimal | None = None,
    source_account_ref: str | None = None,
    source_trade_ref: str | None = None,
) -> bytes:
    """Encode one owner-attested fee scenario bound to this exact simulated Trade."""

    if trade.transfer_fee is None or trade.stamp_duty is None:
        raise AssertionError("V4 trade must preserve known transfer and stamp fees")
    retained_source_account_ref = (
        source_account_ref if source_account_ref is not None else f"account-{account_id}"
    )
    retained_source_trade_ref = (
        source_trade_ref if source_trade_ref is not None else f"trade-{trade.pk}"
    )
    retained_transfer_fee = (
        revised_transfer_fee if revised_transfer_fee is not None else trade.transfer_fee
    )
    retained_stamp_duty = revised_stamp_duty if revised_stamp_duty is not None else trade.stamp_duty
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_CSV_HEADERS)
    writer.writerow(
        (
            OPERATOR_FEE_CSV_SCHEMA,
            "CNY",
            retained_source_account_ref,
            retained_source_trade_ref,
            trade.asset_code,
            trade.action,
            format(trade.quantity, "f"),
            format(trade.price, "f"),
            format(trade.amount, "f"),
            trade.execution_time.isoformat(timespec="microseconds"),
            source_observed_at.isoformat(timespec="microseconds"),
            format(revised_commission, ".2f"),
            format(retained_transfer_fee, ".2f"),
            format(retained_stamp_duty, ".2f"),
        )
    )
    return output.getvalue().encode("utf-8")


def _confirmation_token_from_preview(
    payload: dict[str, object],
    *,
    account_id: int,
    trade_id: int,
) -> str:
    """Extract the exact encrypted owner continuation for this account and Trade."""

    continuation = _json_object(payload.get("continuation"), "confirmation continuation")
    token_input = _json_object(continuation.get("input"), "confirmation token input")
    token = token_input.get("confirmation_token")
    assert continuation.get("action_key") == "simulated-trading.fee-correction-confirm"
    assert set(token_input) == {"account_id", "trade_id", "confirmation_token"}
    assert token_input.get("account_id") == str(account_id)
    assert token_input.get("trade_id") == str(trade_id)
    assert type(token) is str and token.startswith(FieldEncryptionService.PREFIX)
    expires_at = continuation.get("expires_at")
    assert type(expires_at) is str
    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    assert expiry.tzinfo is not None and expiry.utcoffset() is not None
    return token


@pytest.fixture
def _fee_correction_session_encryption_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use a disposable encryption key for the real owner-session confirmation path."""

    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", FieldEncryptionService.generate_key())
    clear_secrets_cache()
    assert get_secrets(require_tushare_token=False).field_encryption_key
    yield
    clear_secrets_cache()


def test_fee_correction_preserves_nonempty_v4_fill_prefix_and_history_projection(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    django_db_setup: str,
    _fee_correction_session_encryption_key: None,
) -> None:
    """Recover and confirm explicit simulation fee corrections over a real V4 chain."""

    del persisted_receipt_schema, _fee_correction_session_encryption_key
    assert_native_postgres_test_database(expected_name=django_db_setup)
    harness = reservation_harness
    rows = _first_buy_rows(harness)
    # This typed fixture reader is synthetic; the real Application and ORM
    # writer create, seal, re-read, and later revalidate the persisted chain.
    reader = _EventReader(rows.event, [])
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    fill_repository = DjangoSimulatedOrderFillRepository(
        event_reader=reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    fill_clock = _FixedClock(_READ_CUTOFF)
    fill_use_case = ApplySimulatedOrderFillUseCase(
        repository=fill_repository,
        clock=fill_clock,
        source_binding=LocalSimulatedFillSourceBinding(
            reader=reader,
            source_namespace=rows.event.source_namespace,
            source_version=rows.event.source_version,
        ),
        settlement_resolver=_FixtureSettlementResolver(
            evidence=rows.proof.calendar_evidence,
            read_cutoff=_READ_CUTOFF,
        ),
    )

    first_event = rows.event
    first_result = fill_use_case.execute(
        ApplySimulatedOrderFillCommand(
            account_id=harness.account.pk,
            user_id=harness.user_id,
            order_idempotency_key=rows.reservation.idempotency_key,
            source_namespace=first_event.source_namespace,
            fill_event_id=first_event.source_event_id,
            expected_event_payload_hash=first_event.event_payload_hash,
        )
    )
    second_at = first_event.occurred_at + timedelta(seconds=30)
    second_event = replace(
        first_event,
        source_event_id="row-reader-event-0002",
        event_payload_hash="6" * 64,
        source_snapshot_id="row-reader-source-snapshot-002",
        source_snapshot_hash="7" * 64,
        quantity=Decimal("20.000000"),
        occurred_at=second_at,
        source_observed_at=second_at,
        source_available_at=second_at,
        recorded_at=second_at,
    )
    reader.event = second_event
    second_result = fill_use_case.execute(
        ApplySimulatedOrderFillCommand(
            account_id=harness.account.pk,
            user_id=harness.user_id,
            order_idempotency_key=rows.reservation.idempotency_key,
            source_namespace=second_event.source_namespace,
            fill_event_id=second_event.source_event_id,
            expected_event_payload_hash=second_event.event_payload_hash,
        )
    )
    assert first_result.replayed is False
    assert second_result.replayed is False
    assert first_result.reservation.status.value == "active"
    assert second_result.reservation.status.value == "active"

    receipts = tuple(
        SimulatedOrderFillReceiptModel._base_manager.filter(
            reservation_id=rows.reservation.pk
        ).order_by("fill_sequence", "pk")
    )
    assert len(receipts) == 2
    assert tuple(receipt.fill_sequence for receipt in receipts) == (1, 2)
    trades = tuple(
        SimulatedTradeModel._base_manager.filter(account_id=harness.account.pk).order_by("pk")
    )
    assert len(trades) == 2
    assert all(trade.settlement_plan_binding_version == 4 for trade in trades)
    assert all(trade.status == "executed" for trade in trades)
    prior = _json_object(receipts[1].economics_payload, "second receipt economics")
    prior_state = _json_object(prior["prior"], "second receipt prior accrual")
    cumulative_state = _json_object(prior["cumulative_state"], "second receipt cumulative accrual")
    assert prior_state["fill_count"] == 1
    assert Decimal(str(prior_state["cumulative_quantity"])) == Decimal("10.000000")
    assert cumulative_state["fill_count"] == 2
    assert Decimal(str(cumulative_state["cumulative_quantity"])) == Decimal("30.000000")

    cancel_use_case = CancelSimulatedOrderReservationUseCase(
        repository=harness.repository,
        clock=_FixedClock(_READ_CUTOFF + timedelta(seconds=1)),
    )
    cancelled = cancel_use_case.execute(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        idempotency_key=rows.reservation.idempotency_key,
    )
    assert cancelled.status.value == "cancelled"
    persisted_reservation = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    assert persisted_reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert persisted_reservation.filled_quantity == Decimal("30.000000")
    assert not SimulatedOrderReservationModel.objects.filter(
        account_id=harness.account.pk,
        status=SimulatedOrderReservationModel.STATUS_ACTIVE,
    ).exists()

    target_trade = SimulatedTradeModel.objects.get(pk=trades[0].pk)
    account_before = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    assert account_before.account_type == "simulated"
    assert account_before.user_id == harness.user_id
    assert target_trade.action == "buy"
    assert target_trade.status == "executed"
    assert target_trade.settlement_plan_binding_version == 4
    assert target_trade.fee_amounts_known is True
    position_before = PositionModel.objects.get(
        account_id=harness.account.pk,
        asset_code=target_trade.asset_code,
    )
    original_trade_rows = _trade_rows_snapshot(harness.account.pk)
    original_receipt_rows = _receipt_rows_snapshot(harness.account.pk)
    now = timezone.now()
    source_observed_at = now - timedelta(minutes=1)
    original_commission = target_trade.commission
    original_transfer_fee = target_trade.transfer_fee
    original_stamp_duty = target_trade.stamp_duty
    if original_transfer_fee is None or original_stamp_duty is None:
        raise AssertionError("the V4 trade must preserve known fee components")
    FeeCorrectionEvidencePolicyModel.objects.create(
        account_id=harness.account.pk,
        enabled=True,
        allow_operator_attested_upload=True,
        ledger_currency="CNY",
        version=1,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=30),
        updated_by_id=harness.user_id,
    )

    # CITIC's official P020250630 schedule and Caitong's 2025-06-30 notice
    # publish an A-share commission cap of 3‰ and a ¥5 minimum. Shanghai
    # transfer is separately listed at 0.001%; exchange/regulatory fees are
    # included or broker-borne, so this simulation does not add them again.
    # These published schedules are assumptions, not proof of actual charges.
    # CITIC: https://www.citics.com/newsite/xxgs/cgxm_21852/202311/P020250630561786625387.pdf
    # Caitong: https://www.ctsec.com/agedNews/detail/9316859
    simulated_public_commission = max(
        target_trade.amount * Decimal("0.003"),
        Decimal("5.00"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    simulated_public_transfer = (target_trade.amount * Decimal("0.00001")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN
    )
    # This fixture is a BUY; seller-only stamp duty remains zero. The
    # two-decimal half-even rounding is the explicit test assumption.
    simulated_buy_stamp = Decimal("0.00")
    expected_fee_delta = (
        simulated_public_commission
        - original_commission
        + simulated_public_transfer
        - original_transfer_fee
        + simulated_buy_stamp
        - original_stamp_duty
    )
    assert expected_fee_delta > Decimal("0.00")
    public_source_ref = "SIMULATION_ONLY_PUBLIC_TARIFF_CITIC_P020250630_CAITONG_20250630"
    public_trade_ref = f"SIMULATION_ONLY_V4_TRADE_{target_trade.pk}_PUBLIC_TARIFF"
    public_filename = "SIMULATION_ONLY_public_tariff_assumption.csv"
    public_evidence = _operator_attested_csv(
        account_id=harness.account.pk,
        trade=target_trade,
        source_observed_at=source_observed_at,
        revised_commission=simulated_public_commission,
        revised_transfer_fee=simulated_public_transfer,
        revised_stamp_duty=simulated_buy_stamp,
        source_account_ref=public_source_ref,
        source_trade_ref=public_trade_ref,
    )

    idempotency_key = f"simulation-public-fee-{uuid4().hex}"
    evidence_repository = DjangoFeeCorrectionEvidenceRepository()
    correction_repository = build_django_fee_correction_repository(
        evidence_repository=evidence_repository,
    )
    owner = get_user_model()._base_manager.get(pk=harness.user_id)
    client, csrf_token = _session_user_client(owner)
    account_id = harness.account.pk
    trade_id = target_trade.pk
    preview_url = _preview_url(account_id, trade_id)
    confirmation_url = (
        f"/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/"
        "fee-corrections/confirm/"
    )

    def post_preview(key: str, payload: dict[str, object]) -> dict[str, object]:
        return _assert_json(
            client.post(
                preview_url,
                payload,
                format="json",
                secure=True,
                HTTP_ORIGIN="https://testserver",
                HTTP_X_CSRFTOKEN=csrf_token,
                HTTP_IDEMPOTENCY_KEY=key,
            ),
            200,
        )

    def post_confirmation(key: str, token: str) -> dict[str, object]:
        return _assert_json(
            client.post(
                confirmation_url,
                {"confirmation_token": token},
                format="json",
                secure=True,
                HTTP_ORIGIN="https://testserver",
                HTTP_X_CSRFTOKEN=csrf_token,
                HTTP_IDEMPOTENCY_KEY=key,
            ),
            200,
        )

    artifacts_before = FeeCorrectionEvidenceArtifactModel.objects.filter(
        account_id=account_id
    ).count()
    bindings_before = FeeCorrectionEvidenceBindingModel.objects.filter(
        account_id=account_id
    ).count()
    public_preview_body = post_preview(
        idempotency_key,
        {
            "original_filename": public_filename,
            "csv_text": public_evidence.decode("utf-8"),
            "attestation_acknowledged": True,
        },
    )
    assert public_preview_body["status"] == "preview"
    assurance_notice = public_preview_body.get("assurance_notice")
    assert type(assurance_notice) is str
    assert "不代表券商或发行方认证" in assurance_notice
    public_preview = _json_object(public_preview_body.get("preview"), "public fee preview")
    assert public_preview["account_id"] == account_id
    assert public_preview["trade_id"] == trade_id
    assert public_preview["expected_revision"] == 0
    assert public_preview["expected_predecessor_id"] is None
    assert public_preview["assurance_class"] == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    previous = _json_object(public_preview.get("previous_fee_components"), "previous fees")
    revised = _json_object(public_preview.get("revised_fee_components"), "revised fees")
    delta = _json_object(public_preview.get("delta"), "public fee delta")
    assert Decimal(cast(str, previous["commission"])) == original_commission
    assert Decimal(cast(str, previous["transfer_fee"])) == original_transfer_fee
    assert Decimal(cast(str, previous["stamp_duty"])) == original_stamp_duty
    assert Decimal(cast(str, revised["commission"])) == simulated_public_commission
    assert Decimal(cast(str, revised["transfer_fee"])) == simulated_public_transfer
    assert Decimal(cast(str, revised["stamp_duty"])) == simulated_buy_stamp
    assert Decimal(cast(str, delta["commission"])) == (
        simulated_public_commission - original_commission
    )
    assert Decimal(cast(str, delta["transfer_fee"])) == (
        simulated_public_transfer - original_transfer_fee
    )
    assert Decimal(cast(str, delta["stamp_duty"])) == (simulated_buy_stamp - original_stamp_duty)
    assert Decimal(cast(str, delta["total_fee_delta"])) == expected_fee_delta
    assert Decimal(cast(str, delta["cash_delta"])) == -expected_fee_delta
    assert _trade_rows_snapshot(account_id) == original_trade_rows
    assert _receipt_rows_snapshot(account_id) == original_receipt_rows
    preview_account = SimulatedAccountModel.objects.get(pk=account_id)
    preview_position = PositionModel.objects.get(pk=position_before.pk)
    assert preview_account.current_cash == account_before.current_cash
    assert preview_account.total_value == account_before.total_value
    assert preview_position.total_cost == position_before.total_cost
    assert FeeCorrectionEvidenceArtifactModel.objects.filter(account_id=account_id).count() == (
        artifacts_before + 1
    )
    assert FeeCorrectionEvidenceBindingModel.objects.filter(account_id=account_id).count() == (
        bindings_before + 1
    )
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=account_id,
            trade_id=trade_id,
        ).count()
        == 0
    )

    source_locator = cast(str, public_preview["source_locator"])
    request = FeeCorrectionRequest(
        account_id=account_id,
        trade_id=trade_id,
        idempotency_key=idempotency_key,
        expected_revision=0,
        source_locator=source_locator,
    )
    verified_evidence = evidence_repository.verify(request)
    authorization = evidence_repository.authorize(
        account_id=account_id,
        principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, owner),
    )
    assert verified_evidence is not None
    assert authorization is not None

    real_account = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    real_account.account_type = "real"
    real_account.save(update_fields=("account_type",))
    with pytest.raises(FeeCorrectionBlockedError) as write_error:
        correction_repository.apply_fee_correction(
            request=request,
            principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, owner),
            evidence=verified_evidence,
            authorization=authorization,
            clock=_FixedClock(now + timedelta(minutes=5)),
        )
    assert write_error.value.code == "SIMULATED_ACCOUNT_UNAVAILABLE"
    assert not SimulatedFeeCorrectionEventModel.objects.filter(
        account_id=harness.account.pk
    ).exists()
    real_account.account_type = "simulated"
    real_account.save(update_fields=("account_type",))

    recovery_body = _assert_json(
        client.get(
            f"/api/simulated-trading/accounts/{account_id}/trades/{trade_id}/"
            "fee-corrections/recovery/",
            secure=True,
            HTTP_ORIGIN="https://testserver",
        ),
        200,
    )
    recovery = _json_object(recovery_body.get("recovery"), "pending recovery")
    items = recovery.get("items")
    assert type(items) is list and len(items) == 1
    pending_item = cast(dict[str, object], items[0])
    assert pending_item["source_locator"] == source_locator
    assert "original_filename" not in pending_item
    assert "idempotency_key" not in pending_item

    transport_key = f"simulation-recovery-{uuid4().hex}"
    recovered_preview_body = post_preview(transport_key, {"source_locator": source_locator})
    recovered_preview = _json_object(recovered_preview_body.get("preview"), "recovered preview")
    assert recovered_preview["source_locator"] == source_locator
    assert recovered_preview["content_sha256"] == public_preview["content_sha256"]
    assert recovered_preview["payload_sha256"] == public_preview["payload_sha256"]
    assert recovered_preview["expected_revision"] == 0
    assert recovered_preview["expected_predecessor_id"] is None
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=account_id,
            trade_id=trade_id,
        ).count()
        == 0
    )
    confirmation_token = _confirmation_token_from_preview(
        recovered_preview_body,
        account_id=account_id,
        trade_id=trade_id,
    )
    confirmation = post_confirmation(transport_key, confirmation_token)
    first_receipt = _json_object(confirmation.get("receipt"), "first confirmation receipt")
    first_event_id = cast(int, first_receipt["event_id"])
    assert first_receipt["revision"] == 1
    assert first_receipt["replayed"] is False
    event = SimulatedFeeCorrectionEventModel.objects.get(pk=first_event_id)
    assert event.trade_id == target_trade.pk
    assert event.idempotency_key == idempotency_key
    assert event.previous_commission == original_commission
    assert event.revised_commission == simulated_public_commission
    assert event.commission_delta == simulated_public_commission - original_commission
    assert event.transfer_fee_delta == simulated_public_transfer - original_transfer_fee
    assert event.stamp_duty_delta == simulated_buy_stamp - original_stamp_duty
    assert event.total_fee_delta == expected_fee_delta
    assert event.cash_delta == -expected_fee_delta
    assert event.receipt_snapshot_hash is not None
    assert event.source_observed_at == source_observed_at
    assert event.source_namespace == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert event.verifier_identity == "local.operator_attested_csv.v1"
    assert event.authority_identity == "local.owner_policy.v1"
    authority_snapshot = _json_object(event.authority_snapshot_json, "owner authority")
    assert authority_snapshot["account_type"] == "simulated"
    assert authority_snapshot["account_owner_user_id"] == harness.user_id
    assert event.source_record_id == source_locator

    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        public_id=source_locator
    )
    assert binding.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert binding.artifact.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert binding.account_id == account_id
    assert binding.trade_id == trade_id
    assert binding.artifact.original_filename == public_filename
    assert b"SIMULATION_ONLY" in bytes(binding.artifact.raw_bytes)
    retained_row = _json_object(binding.artifact.raw_row_json, "retained simulation fee row")
    assert retained_row["source_account_ref"] == public_source_ref
    assert retained_row["source_trade_ref"] == public_trade_ref
    assert bytes(binding.artifact.raw_bytes) == public_evidence

    # Fee corrections append an overlay; every original Trade and V4 receipt column stays fixed.
    assert _trade_rows_snapshot(harness.account.pk) == original_trade_rows
    assert _receipt_rows_snapshot(harness.account.pk) == original_receipt_rows
    charged_account = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    assert charged_account.current_cash == account_before.current_cash - expected_fee_delta
    assert charged_account.current_market_value == account_before.current_market_value
    assert charged_account.total_value == account_before.total_value - expected_fee_delta
    assert charged_account.cash_known is True
    assert charged_account.cash_reconciliation_status == "simulated_ledger"
    charged_position = PositionModel.objects.get(pk=position_before.pk)
    expected_cost = position_before.total_cost + expected_fee_delta
    with localcontext() as context:
        context.prec = 80
        expected_average_cost = (expected_cost / position_before.quantity).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_EVEN,
        )
    assert charged_position.quantity == position_before.quantity
    assert charged_position.available_quantity == position_before.available_quantity
    assert charged_position.current_price == position_before.current_price
    assert charged_position.market_value == position_before.market_value
    assert charged_position.total_cost == expected_cost
    assert charged_position.avg_cost == expected_average_cost
    assert charged_position.unrealized_pnl == position_before.unrealized_pnl - expected_fee_delta
    assert charged_position.cost_basis_known is True
    replayed_confirmation = post_confirmation(transport_key, confirmation_token)
    replayed_receipt = _json_object(
        replayed_confirmation.get("receipt"),
        "replayed first confirmation receipt",
    )
    assert replayed_receipt["event_id"] == first_event_id
    assert replayed_receipt["replayed"] is True
    assert (
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=account_id,
            trade_id=trade_id,
        ).count()
        == 1
    )
    first_head_body = _assert_json(
        client.get(
            _head_url(account_id, trade_id),
            secure=True,
            HTTP_ORIGIN="https://testserver",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        ),
        200,
    )
    first_head = _json_object(first_head_body.get("head"), "first original-key head")
    first_head_receipt = _json_object(
        first_head.get("request_receipt"),
        "first original-key receipt",
    )
    assert first_head["revision"] == 1
    assert first_head_receipt["event_id"] == first_event_id
    assert first_head_receipt["replayed"] is True

    # Refund the simulation-only assumption back to the immutable effective
    # V2 values saved on this Trade; this does not claim an actual broker refund.
    refund_key = f"simulation-refund-{uuid4().hex}"
    refund_observed_at = timezone.now()
    refund_filename = "SIMULATION_ONLY_configured_tier_refund.csv"
    refund_evidence = _operator_attested_csv(
        account_id=account_id,
        trade=target_trade,
        source_observed_at=refund_observed_at,
        revised_commission=original_commission,
        revised_transfer_fee=original_transfer_fee,
        revised_stamp_duty=original_stamp_duty,
        source_account_ref="SIMULATION_ONLY_CONFIGURED_V2_TIER_REFUND",
        source_trade_ref=f"SIMULATION_ONLY_V4_TRADE_{trade_id}_REFUND_REVISION",
    )
    refund_preview_body = post_preview(
        refund_key,
        {
            "original_filename": refund_filename,
            "csv_text": refund_evidence.decode("utf-8"),
            "attestation_acknowledged": True,
        },
    )
    refund_preview = _json_object(refund_preview_body.get("preview"), "refund preview")
    assert refund_preview["expected_revision"] == 1
    assert refund_preview["expected_predecessor_id"] == first_event_id
    refund_delta = _json_object(refund_preview.get("delta"), "refund fee delta")
    assert Decimal(cast(str, refund_delta["total_fee_delta"])) == -expected_fee_delta
    assert Decimal(cast(str, refund_delta["cash_delta"])) == expected_fee_delta
    assert (
        SimulatedAccountModel.objects.get(pk=account_id).current_cash
        == charged_account.current_cash
    )
    assert (
        PositionModel.objects.get(pk=position_before.pk).total_cost == charged_position.total_cost
    )
    refund_token = _confirmation_token_from_preview(
        refund_preview_body,
        account_id=account_id,
        trade_id=trade_id,
    )
    refund_confirmation = post_confirmation(refund_key, refund_token)
    refund_receipt = _json_object(refund_confirmation.get("receipt"), "refund receipt")
    refund_event_id = cast(int, refund_receipt["event_id"])
    assert refund_receipt["revision"] == 2
    assert refund_receipt["replayed"] is False
    refund_event = SimulatedFeeCorrectionEventModel.objects.get(pk=refund_event_id)
    assert refund_event.previous_event_id == first_event_id
    assert refund_event.idempotency_key == refund_key
    assert refund_event.commission_delta == original_commission - simulated_public_commission
    assert refund_event.transfer_fee_delta == original_transfer_fee - simulated_public_transfer
    assert refund_event.stamp_duty_delta == original_stamp_duty - simulated_buy_stamp
    assert refund_event.total_fee_delta == -expected_fee_delta
    assert refund_event.cash_delta == expected_fee_delta
    refund_replay = post_confirmation(refund_key, refund_token)
    replayed_refund = _json_object(refund_replay.get("receipt"), "replayed refund receipt")
    assert replayed_refund["event_id"] == refund_event_id
    assert replayed_refund["replayed"] is True
    all_events = tuple(
        SimulatedFeeCorrectionEventModel.objects.filter(
            account_id=account_id,
            trade_id=trade_id,
        ).order_by("revision")
    )
    assert len(all_events) == 2
    assert tuple(event.revision for event in all_events) == (1, 2)
    assert tuple(event.previous_event_id for event in all_events) == (None, first_event_id)
    assert tuple(event.cash_delta for event in all_events) == (
        -expected_fee_delta,
        expected_fee_delta,
    )
    assert tuple(event.idempotency_key for event in all_events) == (idempotency_key, refund_key)

    refund_binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        account_id=account_id,
        idempotency_key=refund_key,
    )
    assert refund_binding.trade_id == trade_id
    assert refund_binding.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert refund_binding.artifact.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert refund_binding.artifact.original_filename == refund_filename
    assert b"SIMULATION_ONLY" in bytes(refund_binding.artifact.raw_bytes)
    assert bytes(refund_binding.artifact.raw_bytes) == refund_evidence
    retained_refund_row = _json_object(
        refund_binding.artifact.raw_row_json,
        "retained simulation refund row",
    )
    assert retained_refund_row["source_account_ref"] == (
        "SIMULATION_ONLY_CONFIGURED_V2_TIER_REFUND"
    )
    assert retained_refund_row["source_trade_ref"] == (
        f"SIMULATION_ONLY_V4_TRADE_{trade_id}_REFUND_REVISION"
    )

    account_after = SimulatedAccountModel.objects.get(pk=account_id)
    position_after = PositionModel.objects.get(pk=position_before.pk)
    assert account_after.current_cash == account_before.current_cash
    assert account_after.current_market_value == account_before.current_market_value
    assert account_after.total_value == account_before.total_value
    assert position_after.total_cost == position_before.total_cost
    assert position_after.avg_cost == position_before.avg_cost
    assert _trade_rows_snapshot(account_id) == original_trade_rows
    assert _receipt_rows_snapshot(account_id) == original_receipt_rows
    assert FeeCorrectionEvidenceArtifactModel.objects.filter(account_id=account_id).count() == (
        artifacts_before + 2
    )
    assert FeeCorrectionEvidenceBindingModel.objects.filter(account_id=account_id).count() == (
        bindings_before + 2
    )
    refund_head_body = _assert_json(
        client.get(
            _head_url(account_id, trade_id),
            secure=True,
            HTTP_ORIGIN="https://testserver",
            HTTP_IDEMPOTENCY_KEY=refund_key,
        ),
        200,
    )
    refund_head = _json_object(refund_head_body.get("head"), "refund original-key head")
    refund_head_receipt = _json_object(
        refund_head.get("request_receipt"),
        "refund original-key receipt",
    )
    assert refund_head["revision"] == 2
    assert refund_head["expected_predecessor_id"] == refund_event_id
    assert refund_head_receipt["event_id"] == refund_event_id
    assert refund_head_receipt["replayed"] is True

    history = correction_repository.get_account_history(
        account_id=account_id,
        as_of=timezone.now() + timedelta(minutes=1),
    )
    projected_trade = next(item for item in history.trades if item.trade_id == trade_id)
    assert projected_trade.commission == float(original_commission)
    assert projected_trade.effective_commission == float(original_commission)
    assert projected_trade.current_commission == float(original_commission)
    assert projected_trade.effective_transfer_fee == float(original_transfer_fee)
    assert projected_trade.effective_stamp_duty == float(original_stamp_duty)
    assert projected_trade.fee_correction_revision == 2
    assert projected_trade.fee_correction_overlay_applied is True
    assert tuple(item.cash_delta for item in projected_trade.fee_correction_cash_events) == (
        -expected_fee_delta,
        expected_fee_delta,
    )
    assert len(history.cash_events) == 2
    assert tuple(item.account_revision for item in history.cash_events) == (1, 2)
    assert sum((item.cash_delta for item in history.cash_events), Decimal("0.00")) == Decimal(
        "0.00"
    )

    real_account = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    real_account.account_type = "real"
    real_account.save(update_fields=("account_type",))
    with pytest.raises(FeeCorrectionBlockedError) as history_error:
        correction_repository.get_account_history(
            account_id=account_id,
            as_of=timezone.now() + timedelta(minutes=1),
        )
    assert history_error.value.code == "FEE_CORRECTION_HISTORY_INVALID"
