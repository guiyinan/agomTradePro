"""Migration and database-constraint contract for V4 fill release proofs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from importlib import import_module

import pytest
from django.db import DataError, IntegrityError, connection, connections, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from tests.component.simulated_trading import (
    test_order_reservation_fill_migration as _migration_fixtures,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_migration import (
    _create_reservation,
    _create_v3_trade,
    _promote_to_v4,
    _read_table_with_short_lock_timeout,
)
from tests.component.simulated_trading.test_order_reservation_repository import _Harness

_full_app_registry_for_migration_loader = (
    _migration_fixtures._full_app_registry_for_migration_loader
)
_isolated_receipts_after_parent_ledger = _migration_fixtures._isolated_receipts_after_parent_ledger
reservation_harness = _migration_fixtures.reservation_harness

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)
pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)

_BEFORE = ("simulated_trading", "0038_simulated_order_fill_initial_mark")
_AFTER = ("simulated_trading", "0039_simulated_order_fill_release_proof")
_RELEASE_TIME = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)
_RELEASE_DATE = date(2026, 10, 20)
_HASH_RELEASE = "a" * 64
_HASH_RELEASE_CALENDAR = "sha256:" + "b" * 64
_HASH_RELEASE_RECORD = "sha256:" + "c" * 64
_HASH_RELEASE_PUBLICATION = "d" * 64
_HASH_RELEASE_POLICY = "e" * 64
_HASH_RELEASE_EVIDENCE = "f" * 64
_RELEASE_PROOF_PAYLOAD = {"proof": "schema-only migration fixture"}


@pytest.fixture(autouse=True)
def _reuse_migration_registry_and_receipt_cleanup(
    _full_app_registry_for_migration_loader: None,
    _isolated_receipts_after_parent_ledger: None,
) -> None:
    """Reuse the existing full migration graph and child-receipt cleanup fixtures."""

    del _full_app_registry_for_migration_loader, _isolated_receipts_after_parent_ledger


def _trade_values(trade_id: int) -> dict[str, object]:
    """Return the complete current trade row for no-rewrite comparisons."""

    return dict(
        SimulatedTradeModel._base_manager.using(connection.alias).filter(pk=trade_id).values().get()
    )


def _state_trade_values(target: tuple[str, str], trade_id: int) -> dict[str, object]:
    """Read a row through the model state at one exact migration target."""

    historical_model = (
        MigrationExecutor(connection)
        .loader.project_state([target])
        .apps.get_model(
            "simulated_trading",
            "SimulatedTradeModel",
        )
    )
    return dict(
        historical_model._base_manager.using(connection.alias).filter(pk=trade_id).values().get()
    )


def _migrate(target: tuple[str, str] | list[tuple[str, str]]) -> None:
    """Use a fresh executor so applied-migration state is never stale."""

    targets = [target] if isinstance(target, tuple) else target
    MigrationExecutor(connection).migrate(targets)


def _released_values(trade: SimulatedTradeModel) -> dict[str, object]:
    """Build required existing release columns for a schema-only V4 fixture."""

    release_date = trade.settlement_release_date or _RELEASE_DATE
    return {
        "settlement_status": "released",
        "settlement_release_date": release_date,
        "settlement_released_at": _RELEASE_TIME,
        "settlement_release_session": release_date,
        "settlement_release_calendar_snapshot_id": "550e8400-e29b-41d4-a716-446655440000",
        "settlement_release_calendar_content_hash": _HASH_RELEASE_CALENDAR,
        "settlement_release_calendar_record_digest": _HASH_RELEASE_RECORD,
        "settlement_release_calendar_publication_id": "release-proof-migration-publication",
        "settlement_release_calendar_publication_hash": _HASH_RELEASE_PUBLICATION,
        "settlement_release_calendar_policy_hash": _HASH_RELEASE_POLICY,
        "settlement_release_calendar_evidence_hash": _HASH_RELEASE_EVIDENCE,
        "settlement_release_calendar_timezone": "Asia/Shanghai",
    }


def _create_v4_released_trade(
    harness: _Harness,
    *,
    key: str,
) -> SimulatedTradeModel:
    """Create a V4 BUY row with a paired, schema-only release-proof payload."""

    trade = _create_v3_trade(harness, key=key)
    reservation = _create_reservation(harness, key=f"{key}-order")
    _promote_to_v4(
        trade,
        reservation,
        namespace="release-proof-migration",
        event_id=f"{key}-fill",
    )
    updated = (
        SimulatedTradeModel._base_manager.using(connection.alias)
        .filter(pk=trade.pk)
        .update(
            **_released_values(trade),
            settlement_release_proof_payload=_RELEASE_PROOF_PAYLOAD,
            settlement_release_proof_hash=_HASH_RELEASE,
        )
    )
    assert updated == 1
    trade.refresh_from_db()
    assert trade.action == "buy"
    assert trade.settlement_plan_binding_version == 4
    assert trade.settlement_status == "released"
    return trade


def _expect_proof_write_rejected(trade_id: int) -> None:
    """Assert the database rejects one proof-pair write without retaining it."""

    with pytest.raises(IntegrityError):
        with transaction.atomic(using=connection.alias):
            SimulatedTradeModel._base_manager.using(connection.alias).filter(pk=trade_id).update(
                settlement_release_proof_payload=_RELEASE_PROOF_PAYLOAD,
                settlement_release_proof_hash=_HASH_RELEASE,
            )
    row = _trade_values(trade_id)
    assert row["settlement_release_proof_payload"] is None
    assert row["settlement_release_proof_hash"] is None


def test_0039_defaults_preserve_legacy_trade_and_empty_proof_history_is_reversible(
    reservation_harness: _Harness,
) -> None:
    """V3 ledger values survive 0038→0039 and an empty-proof reversal unchanged."""

    trade = _create_v3_trade(reservation_harness, key="release-proof-v1-roundtrip")
    trade_id = int(trade.pk)
    current_before = _trade_values(trade_id)
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        _migrate(_BEFORE)
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
        before_state = _state_trade_values(_BEFORE, trade_id)
        assert {key: value for key, value in current_before.items() if key in before_state} == (
            before_state
        )
        assert "settlement_release_proof_payload" not in before_state
        assert "settlement_release_proof_hash" not in before_state

        _migrate(_AFTER)
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        upgraded = _trade_values(trade_id)
        assert upgraded["settlement_release_proof_payload"] is None
        assert upgraded["settlement_release_proof_hash"] is None
        assert upgraded == current_before

        _migrate(_BEFORE)
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
        downgraded = _state_trade_values(_BEFORE, trade_id)
        assert downgraded == before_state

        _migrate(_AFTER)
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        assert _trade_values(trade_id) == current_before
    finally:
        _migrate(leaf_nodes)


def test_release_proof_fields_and_constraint_match_registered_migration_state() -> None:
    """Runtime and 0039 field/constraint deconstructs remain exactly aligned."""

    payload_field = SimulatedTradeModel._meta.get_field("settlement_release_proof_payload")
    hash_field = SimulatedTradeModel._meta.get_field("settlement_release_proof_hash")
    assert payload_field.null is True and payload_field.default is None
    assert hash_field.null is True and hash_field.default is None and hash_field.max_length == 64
    runtime_constraints = tuple(
        constraint
        for constraint in SimulatedTradeModel._meta.constraints
        if constraint.name == "sim_trade_release_proof_ck"
    )
    assert len(runtime_constraints) == 1

    historical_model = (
        MigrationExecutor(connection)
        .loader.project_state([_AFTER])
        .apps.get_model(
            "simulated_trading",
            "SimulatedTradeModel",
        )
    )
    assert (
        historical_model._meta.get_field("settlement_release_proof_payload").deconstruct()
        == payload_field.deconstruct()
    )
    assert (
        historical_model._meta.get_field("settlement_release_proof_hash").deconstruct()
        == hash_field.deconstruct()
    )
    historical_constraints = tuple(
        constraint
        for constraint in historical_model._meta.constraints
        if constraint.name == "sim_trade_release_proof_ck"
    )
    assert len(historical_constraints) == 1
    assert historical_constraints[0].deconstruct() == runtime_constraints[0].deconstruct()


def test_release_proof_pair_is_accepted_only_for_a_released_v4_buy(
    reservation_harness: _Harness,
) -> None:
    """A complete paired proof is valid on the specifically permitted V4 BUY state."""

    trade = _create_v4_released_trade(reservation_harness, key="release-proof-v4-valid")
    row = _trade_values(int(trade.pk))
    assert row["settlement_release_proof_payload"] == _RELEASE_PROOF_PAYLOAD
    assert row["settlement_release_proof_hash"] == _HASH_RELEASE


@pytest.mark.parametrize(
    "proof_hash",
    [
        pytest.param("A" * 64, id="uppercase-hex"),
        pytest.param("g" * 64, id="non-hex"),
        pytest.param("a" * 64 + "\n", id="trailing-newline"),
    ],
)
def test_release_proof_hash_must_be_lowercase_sha256(
    reservation_harness: _Harness,
    proof_hash: str,
) -> None:
    """Only lowercase 64-character hexadecimal proof hashes may be stored."""

    trade = _create_v4_released_trade(
        reservation_harness,
        key=f"release-proof-hash-{proof_hash[0]}",
    )
    expected_error = (
        DataError
        if connection.vendor == "postgresql" and proof_hash.endswith("\n")
        else IntegrityError
    )
    with pytest.raises(expected_error):
        with transaction.atomic(using=connection.alias):
            SimulatedTradeModel._base_manager.using(connection.alias).filter(pk=trade.pk).update(
                settlement_release_proof_hash=proof_hash,
            )
    trade.refresh_from_db()
    assert trade.settlement_release_proof_hash == _HASH_RELEASE


@pytest.mark.parametrize(
    ("payload", "proof_hash"),
    [
        pytest.param(_RELEASE_PROOF_PAYLOAD, None, id="payload-without-hash"),
        pytest.param(None, _HASH_RELEASE, id="hash-without-payload"),
    ],
)
def test_release_proof_requires_both_sql_columns_to_be_present_or_absent(
    reservation_harness: _Harness,
    payload: dict[str, object] | None,
    proof_hash: str | None,
) -> None:
    """A half-populated SQL pair cannot be persisted on a legacy trade."""

    trade = _create_v3_trade(reservation_harness, key=f"release-proof-half-{payload is None}")
    with pytest.raises(IntegrityError):
        with transaction.atomic(using=connection.alias):
            SimulatedTradeModel._base_manager.using(connection.alias).filter(pk=trade.pk).update(
                settlement_release_proof_payload=payload,
                settlement_release_proof_hash=proof_hash,
            )
    row = _trade_values(int(trade.pk))
    assert row["settlement_release_proof_payload"] is None
    assert row["settlement_release_proof_hash"] is None


@pytest.mark.parametrize(
    "state",
    ["v3-released", "v4-pending", "sell-action"],
)
def test_paired_proof_is_rejected_outside_buy_v4_released_state(
    reservation_harness: _Harness,
    state: str,
) -> None:
    """Proof presence cannot be attached to V3, pending, or SELL trade states."""

    trade = _create_v3_trade(reservation_harness, key=f"release-proof-invalid-{state}")
    if state == "v4-pending":
        reservation = _create_reservation(
            reservation_harness, key=f"release-proof-invalid-{state}-order"
        )
        _promote_to_v4(
            trade,
            reservation,
            namespace="release-proof-invalid-state",
            event_id=f"{state}-fill",
        )
        changed = (
            SimulatedTradeModel._base_manager.using(connection.alias)
            .filter(pk=trade.pk)
            .update(
                settlement_status="pending",
                settlement_release_date=_RELEASE_DATE,
                settlement_released_at=None,
                settlement_release_session=None,
                settlement_release_calendar_snapshot_id=None,
                settlement_release_calendar_content_hash=None,
                settlement_release_calendar_record_digest=None,
                settlement_release_calendar_publication_id=None,
                settlement_release_calendar_publication_hash=None,
                settlement_release_calendar_policy_hash=None,
                settlement_release_calendar_evidence_hash=None,
                settlement_release_calendar_timezone=None,
            )
        )
    elif state == "v3-released":
        changed = (
            SimulatedTradeModel._base_manager.using(connection.alias)
            .filter(pk=trade.pk)
            .update(**_released_values(trade))
        )
    else:
        changed = (
            SimulatedTradeModel._base_manager.using(connection.alias)
            .filter(pk=trade.pk)
            .update(
                action="sell",
                settlement_status=None,
                settlement_release_date=None,
                settlement_released_at=None,
                settlement_release_session=None,
                settlement_release_calendar_snapshot_id=None,
                settlement_release_calendar_content_hash=None,
                settlement_release_calendar_record_digest=None,
                settlement_release_calendar_publication_id=None,
                settlement_release_calendar_publication_hash=None,
                settlement_release_calendar_policy_hash=None,
                settlement_release_calendar_evidence_hash=None,
                settlement_release_calendar_timezone=None,
            )
        )
    assert changed == 1
    _expect_proof_write_rejected(int(trade.pk))


def test_json_null_is_not_treated_as_sql_null_for_the_release_proof_pair(
    reservation_harness: _Harness,
) -> None:
    """JSON null is SQL-nonnull and therefore cannot masquerade as an empty pair."""

    trade = _create_v3_trade(reservation_harness, key="release-proof-json-null")
    table = connection.ops.quote_name(SimulatedTradeModel._meta.db_table)
    payload_column = connection.ops.quote_name(
        SimulatedTradeModel._meta.get_field("settlement_release_proof_payload").column
    )
    trade_id_column = connection.ops.quote_name(SimulatedTradeModel._meta.pk.column)
    if connection.vendor == "sqlite":
        statement = (
            f"UPDATE {table} SET {payload_column} = json('null'), "
            f"settlement_release_proof_hash = NULL WHERE {trade_id_column} = %s"
        )
        parameters: tuple[object, ...] = (trade.pk,)
    elif connection.vendor == "postgresql":
        statement = (
            f"UPDATE {table} SET {payload_column} = %s::jsonb, "
            f"settlement_release_proof_hash = NULL WHERE {trade_id_column} = %s"
        )
        parameters = ("null", trade.pk)
    else:
        pytest.fail(f"Release-proof JSON-null test does not support {connection.vendor}")

    with pytest.raises(IntegrityError):
        with transaction.atomic(using=connection.alias):
            with connection.cursor() as cursor:
                cursor.execute(statement, parameters)
    trade.refresh_from_db()
    assert trade.settlement_release_proof_payload is None
    assert trade.settlement_release_proof_hash is None
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {payload_column} IS NULL FROM {table} WHERE {trade_id_column} = %s",
            [trade.pk],
        )
        assert cursor.fetchone() == (True,)


def test_0039_reverse_refuses_any_proof_history_and_preserves_trade(
    reservation_harness: _Harness,
) -> None:
    """Any populated proof prevents reversing 0039 without changing its trade row."""

    trade = _create_v4_released_trade(reservation_harness, key="release-proof-reverse")
    trade_id = int(trade.pk)
    before = _trade_values(trade_id)
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        with pytest.raises(IrreversibleError, match="release proof while proof evidence exists"):
            _migrate(_BEFORE)
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        assert _trade_values(trade_id) == before
    finally:
        _migrate(leaf_nodes)


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="The release-proof reverse guard's ACCESS EXCLUSIVE fence is PostgreSQL-specific.",
)
def test_0039_reverse_guard_holds_the_trade_table_fence(
    reservation_harness: _Harness,
) -> None:
    """An independent connection cannot read trades before the proof scan completes."""

    _create_v4_released_trade(reservation_harness, key="release-proof-reverse-lock")
    migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    migration = import_module(
        "apps.simulated_trading.migrations.0039_simulated_order_fill_release_proof"
    )
    trade_table = SimulatedTradeModel._meta.db_table

    with transaction.atomic(using=connection.alias):
        with connections[connection.alias].schema_editor(atomic=False) as schema_editor:
            with pytest.raises(IrreversibleError):
                migration.refuse_to_drop_order_fill_release_proof(migration_apps, schema_editor)
        with ThreadPoolExecutor(max_workers=1) as executor:
            outcome = executor.submit(
                _read_table_with_short_lock_timeout,
                connection.alias,
                trade_table,
            ).result(timeout=5)

    assert outcome == ("database_error", "55P03")
