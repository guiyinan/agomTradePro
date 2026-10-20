"""Database tests for immutable persisted simulated-order fill evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, cast

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS, IntegrityError, connections, models, transaction
from django.db.models.deletion import ProtectedError

from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _Clock,
    _current_v3_plan,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

_FILL_BINDING_SCHEMA = "simulated-order-fill-binding.v4"
_HASH_SOURCE = "a" * 64
_HASH_SOURCE_SNAPSHOT = "5" * 64
_HASH_REQUEST = "b" * 64
_HASH_ECONOMICS = "c" * 64
_HASH_RECEIPT = "d" * 64
_HASH_BINDING = "e" * 64
_EVENT_TIME = datetime(2026, 10, 16, 2, 1, tzinfo=UTC)


class _FillReceiptView(Protocol):
    """Expose the receipt fields inspected by tests without importing a missing model."""

    pk: int
    source_namespace: str
    source_version: str
    source_event_id: str
    source_event_payload: dict[str, object]
    source_event_payload_hash: str
    source_event_snapshot_hash: str
    economic_request_hash: str
    economics_snapshot_hash: str
    receipt_hash: str


def _receipt_model() -> type[models.Model]:
    """Resolve the new model at test time so the pre-change test fails clearly."""

    try:
        model = django_apps.get_model(
            "simulated_trading",
            "SimulatedOrderFillReceiptModel",
        )
    except LookupError:
        pytest.fail("SimulatedOrderFillReceiptModel is not registered")
    return cast(type[models.Model], model)


def _create_trade(
    harness: _Harness,
    *,
    key: str,
) -> SimulatedTradeModel:
    """Create a real V3 ledger row through the existing current-purpose UoW."""

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    plan, bundle, _ = _current_v3_plan(
        repository=repository,
        intent=_intent_for(harness, key=key),
        as_of=AS_OF,
        source_exchange="SH",
    )
    result = repository.execute_trade(plan=plan, execution_bundle=bundle, clock=_Clock(AS_OF))
    row = SimulatedTradeModel.objects.get(pk=result.trade_id)
    assert row.settlement_plan_binding_version == 3
    return row


def _create_reservation(
    harness: _Harness,
    *,
    key: str,
) -> SimulatedOrderReservationModel:
    """Create one actual G1 order reservation through its application service."""

    intent = _intent_for(harness, key=key)
    harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=AS_OF)
    return SimulatedOrderReservationModel.objects.get(
        account=harness.account,
        idempotency_key=key,
    )


def _source_payload(
    reservation: SimulatedOrderReservationModel,
    *,
    namespace: str,
    version: str,
    event_id: str,
    event_kind: str,
) -> dict[str, object]:
    """Build a complete typed-shape source fixture without representing a live fill."""

    return {
        "source_namespace": namespace,
        "source_version": version,
        "source_event_id": event_id,
        "event_payload_hash": _HASH_SOURCE,
        "source_snapshot_id": "matcher-snapshot-001",
        "source_snapshot_hash": "f" * 64,
        "reservation_id": reservation.pk,
        "account_id": reservation.account_id,
        "user_id": reservation.owner_user_id,
        "order_idempotency_key": reservation.idempotency_key,
        "intent_payload_hash": reservation.intent_payload_hash,
        "reservation_request_hash": reservation.reservation_request_hash,
        "plan_snapshot_hash": reservation.plan_snapshot_hash,
        "security_id": reservation.security_id,
        "asset_code": reservation.asset_code,
        "side": SimulatedTradeSide.BUY.value,
        "event_kind": event_kind,
        "quantity": "1.000000",
        "price": "10.0000",
        "occurred_at": _EVENT_TIME.isoformat(),
        "source_observed_at": _EVENT_TIME.isoformat(),
        "source_available_at": _EVENT_TIME.isoformat(),
        "recorded_at": _EVENT_TIME.isoformat(),
    }


def _economics_payload(
    reservation: SimulatedOrderReservationModel,
    *,
    event_id: str,
) -> dict[str, object]:
    """Represent the full Domain result shape with independent request hash."""

    zero_fees = {
        "commission": "0.00",
        "transfer_fee": "0.00",
        "stamp_duty": "0.00",
        "slippage": "0.00",
        "total_fee": "0.00",
    }
    zero_state = {
        "fill_count": 0,
        "cumulative_quantity": "0.000000",
        "cumulative_gross": "0.00",
        "cumulative_fees": zero_fees,
    }
    return {
        "schema": "simulated-order-reservation-fill.v1",
        "fill_event_id": event_id,
        "reservation_identity": {
            "account_id": reservation.account_id,
            "security_id": reservation.security_id,
            "idempotency_key": reservation.idempotency_key,
            "request_payload_hash": reservation.reservation_request_hash,
        },
        "user_id": reservation.owner_user_id,
        "intent_payload_hash": reservation.intent_payload_hash,
        "fee_policy_hash": reservation.fee_policy_hash,
        "side": SimulatedTradeSide.BUY.value,
        "asset_code": reservation.asset_code,
        "asset_type": reservation.asset_type,
        "market": reservation.market,
        "board": reservation.board,
        "limit_price": "10.0000",
        "fill_occurred_at": _EVENT_TIME.isoformat(),
        "close_order": False,
        "quantity": "1.000000",
        "price": "10.0000",
        "gross_amount": "10.00",
        "prior": zero_state,
        "cumulative_state": {
            "fill_count": 1,
            "cumulative_quantity": "1.000000",
            "cumulative_gross": "10.00",
            "cumulative_fees": zero_fees,
        },
        "incremental_fees": zero_fees,
        "payload_hash": _HASH_REQUEST,
    }


def _binding_payload(
    reservation: SimulatedOrderReservationModel,
    *,
    namespace: str,
    version: str,
    event_id: str,
    fill_sequence: int,
) -> dict[str, object]:
    """Create a nonempty V4 envelope whose independent digests remain distinct."""

    return {
        "schema": _FILL_BINDING_SCHEMA,
        "reservation_id": reservation.pk,
        "intent_payload_hash": reservation.intent_payload_hash,
        "reservation_request_hash": reservation.reservation_request_hash,
        "plan_snapshot_hash": reservation.plan_snapshot_hash,
        "fee_policy_hash": reservation.fee_policy_hash,
        "source_namespace": namespace,
        "source_version": version,
        "source_event_id": event_id,
        "fill_sequence": fill_sequence,
        "side": reservation.side,
        "source_event_payload_hash": _HASH_SOURCE,
        "source_event_snapshot_hash": _HASH_SOURCE_SNAPSHOT,
        "economic_request_hash": _HASH_REQUEST,
        "economics_snapshot_hash": _HASH_ECONOMICS,
        "receipt_hash": _HASH_RECEIPT,
    }


def _promote_trade_to_v4(
    trade: SimulatedTradeModel,
    reservation: SimulatedOrderReservationModel,
    *,
    namespace: str,
    version: str = "parser-v1",
    event_id: str,
    fill_sequence: int = 1,
    binding_changes: dict[str, object] | None = None,
    remove_binding_key: str | None = None,
) -> SimulatedTradeModel:
    """Set the complete V4 structural envelope through the controlled test fixture."""

    binding_payload = _binding_payload(
        reservation,
        namespace=namespace,
        version=version,
        event_id=event_id,
        fill_sequence=fill_sequence,
    )
    if remove_binding_key is not None:
        binding_payload.pop(remove_binding_key, None)
    binding_payload.update(binding_changes or {})
    updated = SimulatedTradeModel.objects.filter(pk=trade.pk).update(
        request_payload_hash=_HASH_RECEIPT,
        settlement_plan_binding_version=4,
        settlement_plan_binding_payload=binding_payload,
        settlement_plan_binding_hash=_HASH_BINDING,
    )
    assert updated == 1
    trade.refresh_from_db()
    return trade


def _create_receipt(
    reservation: SimulatedOrderReservationModel,
    trade: SimulatedTradeModel,
    *,
    namespace: str = "local-matcher",
    version: str = "parser-v1",
    event_id: str = "event-001",
    event_kind: str = "fill",
    fill_sequence: int = 1,
    changes: dict[str, object] | None = None,
) -> models.Model:
    """Insert one actual ORM receipt row with separately named digest layers."""

    values: dict[str, object] = {
        "reservation": reservation,
        "trade": trade,
        "fill_sequence": fill_sequence,
        "source_namespace": namespace,
        "source_version": version,
        "source_event_id": event_id,
        "event_kind": event_kind,
        "source_event_payload": _source_payload(
            reservation,
            namespace=namespace,
            version=version,
            event_id=event_id,
            event_kind=event_kind,
        ),
        "source_event_payload_hash": _HASH_SOURCE,
        "source_event_snapshot_hash": _HASH_SOURCE_SNAPSHOT,
        "economic_request_hash": _HASH_REQUEST,
        "economics_snapshot_hash": _HASH_ECONOMICS,
        "plan_snapshot_hash": reservation.plan_snapshot_hash,
        "economics_payload": _economics_payload(reservation, event_id=event_id),
        "receipt_hash": _HASH_RECEIPT,
    }
    values.update(changes or {})
    return _receipt_model().objects.create(**values)


def _unique_constraint_name_for_columns(columns: tuple[str, ...]) -> str:
    """Read the database's unique constraint name for an exact column tuple."""

    receipt_model = _receipt_model()
    connection = connections[DEFAULT_DB_ALIAS]
    with connection.cursor() as cursor:
        raw_constraints = connection.introspection.get_constraints(
            cursor,
            receipt_model._meta.db_table,
        )
    matches: list[str] = []
    for name, metadata in raw_constraints.items():
        raw_columns = metadata.get("columns")
        if (
            metadata.get("unique") is True
            and isinstance(raw_columns, (list, tuple))
            and tuple(raw_columns) == columns
        ):
            matches.append(name)
    assert len(matches) == 1, f"Expected one unique constraint for {columns!r}: {matches!r}"
    return matches[0]


def _assert_unique_constraint_violation(
    error: pytest.ExceptionInfo[IntegrityError],
    *,
    expected_constraint: str,
    sqlite_columns: tuple[str, ...],
) -> None:
    """Prove an insert failed on the intended unique relation, not another key."""

    cause = error.value.__cause__
    assert cause is not None
    diagnostic = getattr(cause, "diag", None)
    if diagnostic is not None:
        assert getattr(diagnostic, "constraint_name", None) == expected_constraint
        return

    message = str(cause)
    assert "unique constraint failed" in message.lower()
    assert all(column in message for column in sqlite_columns)


def test_database_rejects_duplicate_fill_sequence_on_one_reservation(
    reservation_harness: _Harness,
) -> None:
    """Distinct complete receipts for distinct Trades cannot reuse a sequence."""

    with isolated_schema((_receipt_model(),)):
        first_trade = _create_trade(reservation_harness, key="fill-sequence-trade-a")
        second_trade = _create_trade(reservation_harness, key="fill-sequence-trade-b")
        reservation = _create_reservation(
            reservation_harness,
            key="fill-sequence-order",
        )
        _promote_trade_to_v4(
            first_trade,
            reservation,
            namespace="sequence-test",
            event_id="sequence-event-a",
            fill_sequence=1,
        )
        _create_receipt(
            reservation,
            first_trade,
            namespace="sequence-test",
            event_id="sequence-event-a",
            fill_sequence=1,
        )

        _promote_trade_to_v4(
            second_trade,
            reservation,
            namespace="sequence-test",
            event_id="sequence-event-b",
            fill_sequence=1,
        )
        expected_constraint = _unique_constraint_name_for_columns(
            ("reservation_id", "fill_sequence")
        )
        with pytest.raises(IntegrityError) as error:
            with transaction.atomic():
                _create_receipt(
                    reservation,
                    second_trade,
                    namespace="sequence-test",
                    event_id="sequence-event-b",
                    fill_sequence=1,
                )

        _assert_unique_constraint_violation(
            error,
            expected_constraint=expected_constraint,
            sqlite_columns=(
                "simulated_order_fill_receipt.reservation_id",
                "simulated_order_fill_receipt.fill_sequence",
            ),
        )
        assert _receipt_model().objects.filter(reservation=reservation).count() == 1
        assert not _receipt_model().objects.filter(source_event_id="sequence-event-b").exists()


def test_database_enforces_one_receipt_per_trade(
    reservation_harness: _Harness,
) -> None:
    """A second structurally complete locator cannot attach to an existing Trade."""

    with isolated_schema((_receipt_model(),)):
        trade = _create_trade(reservation_harness, key="one-receipt-trade")
        reservation = _create_reservation(
            reservation_harness,
            key="one-receipt-order",
        )
        _promote_trade_to_v4(
            trade,
            reservation,
            namespace="one-to-one-test",
            event_id="trade-event-a",
            fill_sequence=1,
        )
        _create_receipt(
            reservation,
            trade,
            namespace="one-to-one-test",
            event_id="trade-event-a",
            fill_sequence=1,
        )

        expected_constraint = _unique_constraint_name_for_columns(("trade_id",))
        with pytest.raises(IntegrityError) as error:
            with transaction.atomic():
                # Distinct locator/sequence isolate the trade_id relation. The
                # test does not claim one Trade can match both receipt payloads.
                _create_receipt(
                    reservation,
                    trade,
                    namespace="one-to-one-test",
                    event_id="trade-event-b",
                    fill_sequence=2,
                )

        _assert_unique_constraint_violation(
            error,
            expected_constraint=expected_constraint,
            sqlite_columns=("simulated_order_fill_receipt.trade_id",),
        )
        assert _receipt_model().objects.filter(trade=trade).count() == 1
        assert not _receipt_model().objects.filter(source_event_id="trade-event-b").exists()


def test_fill_receipt_is_append_only_and_protects_its_parent_rows(
    reservation_harness: _Harness,
) -> None:
    """A receipt row cannot be rewritten or detached from its reservation and trade."""

    with isolated_schema((_receipt_model(),)):
        trade = _create_trade(reservation_harness, key="fill-storage-trade-immutable")
        reservation = _create_reservation(
            reservation_harness,
            key="fill-storage-order-immutable",
        )
        _promote_trade_to_v4(
            trade,
            reservation,
            namespace="local-matcher",
            event_id="event-immutable",
        )
        receipt_row = _create_receipt(
            reservation,
            trade,
            event_id="event-immutable",
        )
        receipt = cast(_FillReceiptView, receipt_row)

        assert receipt.source_namespace == "local-matcher"
        assert receipt.source_version == "parser-v1"
        assert receipt.economic_request_hash == _HASH_REQUEST
        assert receipt.economics_snapshot_hash == _HASH_ECONOMICS
        assert receipt.source_event_payload_hash == _HASH_SOURCE
        assert receipt.source_event_snapshot_hash == _HASH_SOURCE_SNAPSHOT
        assert receipt.source_event_payload["event_payload_hash"] == _HASH_SOURCE
        assert receipt.receipt_hash == trade.request_payload_hash
        assert "fill_receipt_id" not in trade.settlement_plan_binding_payload

        receipt.source_version = "parser-v2"
        with pytest.raises(ValidationError):
            receipt.save()
        with pytest.raises(ValidationError):
            _receipt_model().objects.filter(pk=receipt.pk).update(source_version="parser-v2")
        with pytest.raises(ValidationError):
            _receipt_model().objects.filter(pk=receipt.pk).delete()
        with pytest.raises(ValidationError):
            receipt.delete()
        with pytest.raises(ValidationError):
            _receipt_model().objects.bulk_update([receipt_row], ["source_version"])
        with pytest.raises(ValidationError):
            _receipt_model().objects.bulk_create([receipt_row])

        with pytest.raises(ProtectedError):
            trade.delete()
        reservation_rows = SimulatedOrderReservationModel.objects.filter(pk=reservation.pk)
        with pytest.raises(ProtectedError):
            models.QuerySet.delete(reservation_rows)


def test_fill_receipt_unique_identity_uses_namespace_and_stable_event_id_not_version(
    reservation_harness: _Harness,
) -> None:
    """Different namespaces partition IDs, but parser versions cannot duplicate one event."""

    with isolated_schema((_receipt_model(),)):
        first_trade = _create_trade(reservation_harness, key="fill-storage-trade-source-a")
        second_trade = _create_trade(reservation_harness, key="fill-storage-trade-source-b")
        third_trade = _create_trade(
            reservation_harness,
            key="fill-storage-trade-version-conflict",
        )
        reservation = _create_reservation(
            reservation_harness,
            key="fill-storage-order-source-key",
        )
        _promote_trade_to_v4(
            first_trade,
            reservation,
            namespace="matcher-a",
            event_id="shared-event-id",
            fill_sequence=1,
        )
        first = _create_receipt(
            reservation,
            first_trade,
            namespace="matcher-a",
            version="parser-v1",
            event_id="shared-event-id",
            fill_sequence=1,
        )

        _promote_trade_to_v4(
            second_trade,
            reservation,
            namespace="matcher-b",
            event_id="shared-event-id",
            fill_sequence=2,
        )
        second = _create_receipt(
            reservation,
            second_trade,
            namespace="matcher-b",
            version="parser-v1",
            event_id="shared-event-id",
            fill_sequence=2,
        )
        assert first.pk != second.pk
        assert first.source_event_id == second.source_event_id
        assert first.source_namespace != second.source_namespace

        _promote_trade_to_v4(
            third_trade,
            reservation,
            namespace="matcher-a",
            version="parser-v2",
            event_id="shared-event-id",
            fill_sequence=3,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _create_receipt(
                    reservation,
                    third_trade,
                    namespace="matcher-a",
                    version="parser-v2",
                    event_id="shared-event-id",
                    fill_sequence=3,
                )

        assert (
            _receipt_model()
            .objects.filter(
                reservation=reservation,
                source_namespace="matcher-a",
                source_event_id="shared-event-id",
            )
            .count()
            == 1
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"fill_sequence": 0},
        {"source_namespace": ""},
        {"source_version": ""},
        {"source_event_id": ""},
        {"event_kind": "unknown"},
        {"source_event_payload_hash": "not-a-hash"},
        {"source_event_snapshot_hash": "not-a-hash"},
        {"economic_request_hash": "not-a-hash"},
        {"economics_snapshot_hash": "not-a-hash"},
        {"receipt_hash": "not-a-hash"},
        {"source_event_payload": {}},
        {"economics_payload": {}},
    ],
    ids=[
        "zero-sequence",
        "empty-namespace",
        "empty-version",
        "empty-event-id",
        "unknown-event-kind",
        "bad-source-hash",
        "bad-source-snapshot-hash",
        "bad-request-hash",
        "bad-snapshot-hash",
        "bad-receipt-hash",
        "empty-source-payload",
        "empty-economics-payload",
    ],
)
def test_database_rejects_malformed_fill_receipt_storage_rows(
    reservation_harness: _Harness,
    changes: dict[str, object],
) -> None:
    """The database rejects empty identities, unknown kinds, incomplete envelopes and hashes."""

    with isolated_schema((_receipt_model(),)):
        trade_key = f"fill-storage-trade-invalid-{tuple(changes)[0]}"
        trade = _create_trade(reservation_harness, key=trade_key)
        reservation = _create_reservation(
            reservation_harness,
            key=f"fill-storage-order-invalid-{len(changes)}-{tuple(changes)[0]}",
        )
        _promote_trade_to_v4(
            trade,
            reservation,
            namespace="local-matcher",
            event_id=f"invalid-{tuple(changes)[0]}",
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _create_receipt(
                    reservation,
                    trade,
                    event_id=f"invalid-{tuple(changes)[0]}",
                    changes=changes,
                )


def test_trade_binding_v4_requires_nonempty_fill_receipt_markers(
    reservation_harness: _Harness,
) -> None:
    """An empty JSON object cannot satisfy the dedicated V4 fill binding branch."""

    trade = _create_trade(reservation_harness, key="fill-storage-v4-empty-marker")
    reservation = _create_reservation(
        reservation_harness,
        key="fill-storage-v4-empty-order",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SimulatedTradeModel.objects.filter(pk=trade.pk).update(
                request_payload_hash=_HASH_RECEIPT,
                settlement_plan_binding_version=4,
                settlement_plan_binding_payload={},
                settlement_plan_binding_hash=_HASH_BINDING,
            )

    trade.refresh_from_db()
    assert trade.settlement_plan_binding_version == 3
    assert trade.request_payload_hash is not None
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE


@pytest.mark.parametrize(
    "top_level_change",
    [
        {"settlement_plan_binding_payload": None},
        {"settlement_plan_binding_hash": None},
    ],
    ids=["sql-null-payload", "sql-null-binding-digest"],
)
def test_trade_binding_v4_rejects_sql_null_top_level_envelope_fields(
    reservation_harness: _Harness,
    top_level_change: dict[str, object],
) -> None:
    """SQL NULL cannot make a V4 CHECK expression pass through UNKNOWN."""

    trade = _create_trade(
        reservation_harness,
        key=f"fill-storage-v4-sql-null-{tuple(top_level_change)}",
    )
    reservation = _create_reservation(
        reservation_harness,
        key=f"fill-storage-v4-sql-null-order-{tuple(top_level_change)}",
    )
    values: dict[str, object] = {
        "idempotency_key": trade.idempotency_key,
        "request_payload_hash": _HASH_RECEIPT,
        "settlement_plan_binding_version": 4,
        "settlement_plan_binding_payload": _binding_payload(
            reservation,
            namespace="local-matcher",
            version="parser-v1",
            event_id="sql-null-envelope-event",
            fill_sequence=1,
        ),
        "settlement_plan_binding_hash": _HASH_BINDING,
    }
    values.update(top_level_change)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SimulatedTradeModel.objects.filter(pk=trade.pk).update(**values)

    trade.refresh_from_db()
    assert trade.settlement_plan_binding_version == 3


@pytest.mark.parametrize(
    ("binding_changes", "remove_key"),
    [
        ({"source_namespace": None}, None),
        ({"source_namespace": ""}, None),
        ({"source_version": None}, None),
        ({"source_version": ""}, None),
        ({"source_event_id": None}, None),
        ({"source_event_id": ""}, None),
        ({"schema": None}, None),
        ({"schema": ""}, None),
        ({}, "schema"),
        ({"receipt_hash": None}, None),
        ({"receipt_hash": ""}, None),
        ({"economic_request_hash": None}, None),
        ({"economic_request_hash": ""}, None),
        ({"economic_request_hash": "z" * 64}, None),
        ({"side": "unknown"}, None),
        ({}, "side"),
        ({"reservation_id": None}, None),
        ({"reservation_id": ""}, None),
        ({"reservation_id": 0}, None),
        ({"fill_sequence": None}, None),
        ({"fill_sequence": ""}, None),
        ({"fill_sequence": 0}, None),
        ({}, "source_event_id"),
    ],
    ids=[
        "null-namespace",
        "empty-namespace",
        "null-version",
        "empty-version",
        "null-event-id",
        "empty-event-id",
        "null-schema",
        "empty-schema",
        "missing-schema",
        "null-receipt-digest",
        "empty-receipt-digest",
        "null-economic-digest",
        "empty-economic-digest",
        "malformed-economic-digest",
        "unknown-side",
        "missing-side",
        "null-reservation-id",
        "empty-reservation-id",
        "zero-reservation-id",
        "null-sequence",
        "empty-sequence",
        "zero-sequence",
        "missing-event-id",
    ],
)
def test_trade_binding_v4_rejects_empty_null_or_malformed_receipt_values(
    reservation_harness: _Harness,
    binding_changes: dict[str, object],
    remove_key: str | None,
) -> None:
    """A version marker cannot carry missing, empty, null, or malformed receipt fields."""

    trade = _create_trade(
        reservation_harness,
        key=f"fill-storage-v4-invalid-{tuple(binding_changes)}",
    )
    reservation = _create_reservation(
        reservation_harness,
        key=f"fill-storage-v4-invalid-order-{tuple(binding_changes)}-{remove_key}",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _promote_trade_to_v4(
                trade,
                reservation,
                namespace="local-matcher",
                event_id="invalid-v4-event",
                binding_changes=binding_changes,
                remove_binding_key=remove_key,
            )

    trade.refresh_from_db()
    assert trade.settlement_plan_binding_version == 3
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE


def test_trade_binding_v4_accepts_complete_structural_envelope_and_keeps_legacy_v3(
    reservation_harness: _Harness,
) -> None:
    """A valid V4 row is admitted while a normal UoW trade remains V3."""

    trade = _create_trade(reservation_harness, key="fill-storage-v4-complete-trade")
    assert trade.settlement_plan_binding_version == 3
    reservation = _create_reservation(
        reservation_harness,
        key="fill-storage-v4-complete-order",
    )
    _promote_trade_to_v4(
        trade,
        reservation,
        namespace="local-matcher",
        event_id="valid-v4-event",
    )
    assert trade.settlement_plan_binding_version == 4
    assert trade.settlement_plan_binding_payload["schema"] == _FILL_BINDING_SCHEMA
    assert "fill_receipt_id" not in trade.settlement_plan_binding_payload
    assert trade.settlement_plan_binding_payload["source_namespace"] == "local-matcher"
    assert trade.settlement_plan_binding_payload["source_event_id"] == "valid-v4-event"
    assert (
        trade.settlement_plan_binding_payload["source_event_snapshot_hash"] == _HASH_SOURCE_SNAPSHOT
    )
    assert trade.settlement_plan_binding_payload["receipt_hash"] == trade.request_payload_hash


def test_receipt_model_is_registered_after_trade_and_reservation_models() -> None:
    """The schema import order keeps both referenced ledger models registered first."""

    registered = django_apps.get_models("simulated_trading")
    labels = [model.__name__ for model in registered]
    assert "SimulatedTradeModel" in labels
    assert "SimulatedOrderReservationModel" in labels
    assert "SimulatedOrderFillReceiptModel" in labels
    assert labels.index("SimulatedTradeModel") < labels.index("SimulatedOrderReservationModel")
    assert labels.index("SimulatedOrderReservationModel") < labels.index(
        "SimulatedOrderFillReceiptModel"
    )
