"""Native PostgreSQL races for browser-session fee correction confirmation."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic, sleep
from typing import cast

import pytest
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import DEFAULT_DB_ALIAS, connection, transaction

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionBlockedError,
    FeeCorrectionReceipt,
)
from apps.simulated_trading.application.fee_correction_confirmation import (
    BrowserContext,
    FeeCorrectionConfirmationCommand,
)
from apps.simulated_trading.application.fee_correction_policy import (
    FeeCorrectionPolicyCommand,
)
from apps.simulated_trading.application.fee_correction_preview import (
    FeeCorrectionPreviewCommand,
)
from apps.simulated_trading.fee_correction_composition import (
    build_fee_correction_confirmation_use_case,
)
from apps.simulated_trading.fee_correction_policy_composition import (
    build_fee_correction_policy_use_case,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from shared.config.secrets import clear_secrets_cache
from shared.infrastructure.crypto import FieldEncryptionService
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_fee_correction_concurrency import (
    _csv_bytes as _csv_bytes,
)
from tests.component.simulated_trading.test_fee_correction_concurrency import (
    _FeeCorrectionFixture as _FeeCorrectionFixture,
)
from tests.component.simulated_trading.test_fee_correction_concurrency import (
    fee_correction_fixture as fee_correction_fixture,
)
from tests.component.simulated_trading.test_fee_correction_concurrency import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _lock_account_parent as _lock_account_parent,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _submit_worker as _submit_worker,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _wait_for_account_parent_lock as _wait_for_account_parent_lock,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _WorkerCall as _WorkerCall,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _WorkerOutcome as _WorkerOutcome,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
    ],
)

_REVISED_COMMISSION = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class _ConfirmationAttempt:
    """Keep a durable confirmation receipt or its stable application block code."""

    receipt: FeeCorrectionReceipt | None
    blocked_code: str | None


@dataclass(frozen=True, slots=True)
class _RelationRowLockWait:
    """Capture PostgreSQL activity and relation-lock evidence for one row waiter."""

    query: str
    blocker_pids: tuple[int, ...]
    wait_event_type: str
    relation_oid: int
    relation_lock_mode: str
    relation_lock_granted: bool
    relation_table: str


@pytest.fixture(autouse=True)
def _require_native_postgres_and_encryption_key(
    django_db_use_migrations: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep lock claims native-PostgreSQL-only and use a generated test key."""

    if not django_db_use_migrations:
        pytest.skip("confirmation row-lock races require the migrated PostgreSQL database")
    if connection.vendor != "postgresql":
        pytest.skip("confirmation row-lock races require PostgreSQL")
    assert_native_postgres_test_database()
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.db"
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", FieldEncryptionService.generate_key())
    clear_secrets_cache()
    yield
    clear_secrets_cache()


def _browser_context_for_owner(owner: AbstractBaseUser) -> BrowserContext:
    """Persist an actual Django database session and return its server-side claims."""

    owner_id = getattr(owner, "pk", None)
    assert type(owner_id) is int and owner_id > 0
    backend = settings.AUTHENTICATION_BACKENDS[0]
    assert isinstance(backend, str) and backend
    session_store = SessionStore()
    session_store[SESSION_KEY] = str(owner_id)
    session_store[BACKEND_SESSION_KEY] = backend
    session_store[HASH_SESSION_KEY] = owner.get_session_auth_hash()
    session_store.set_expiry(3600)
    session_store.create()
    session_key = session_store.session_key
    assert isinstance(session_key, str) and session_key
    stored_session = Session._default_manager.using(DEFAULT_DB_ALIAS).get(session_key=session_key)
    assert stored_session._state.db == DEFAULT_DB_ALIAS
    return BrowserContext(
        actor_user_id=owner_id,
        session_key=session_key,
        auth_backend=backend,
        auth_session_hash=owner.get_session_auth_hash(),
    )


def _prepare_confirmation(
    fixture: _FeeCorrectionFixture,
    browser_context: BrowserContext,
    *,
    idempotency_key: str,
) -> FeeCorrectionConfirmationCommand:
    """Persist the real owner CSV preview and bind its token to this session."""

    assert type(fixture.account.pk) is int
    assert type(fixture.trade.pk) is int
    command = FeeCorrectionPreviewCommand(
        account_id=fixture.account.pk,
        trade_id=fixture.trade.pk,
        idempotency_key=idempotency_key,
        original_filename=f"{idempotency_key}.csv",
        content=_csv_bytes(
            account=fixture.account,
            trade=fixture.trade,
            revised_commission=_REVISED_COMMISSION,
        ),
        attestation_acknowledged=True,
    )
    prepared = build_fee_correction_confirmation_use_case().prepare_preview(
        command,
        principal=fixture.owner,
        browser_context=browser_context,
    )
    assert prepared.preview.status == "preview"
    assert prepared.preview.preview is not None
    assert isinstance(prepared.confirmation_token, str) and prepared.confirmation_token
    return FeeCorrectionConfirmationCommand(
        account_id=fixture.account.pk,
        trade_id=fixture.trade.pk,
        idempotency_key=idempotency_key,
        confirmation_token=prepared.confirmation_token,
    )


def _attempt_confirmation(
    command: FeeCorrectionConfirmationCommand,
    *,
    owner: AbstractBaseUser,
    browser_context: BrowserContext,
) -> _ConfirmationAttempt:
    """Execute the real confirmation use case and retain its stable rejection."""

    try:
        receipt = build_fee_correction_confirmation_use_case().confirm(
            command,
            principal=owner,
            browser_context=browser_context,
        )
    except FeeCorrectionBlockedError as error:
        return _ConfirmationAttempt(receipt=None, blocked_code=error.code)
    return _ConfirmationAttempt(receipt=receipt, blocked_code=None)


def _attempt_from_worker(worker: _WorkerCall) -> _ConfirmationAttempt:
    """Require the fresh PostgreSQL worker to return the confirmation result."""

    outcome = worker.future.result(timeout=20)
    assert outcome.blocked_code is None
    assert isinstance(outcome.value, _ConfirmationAttempt)
    return cast(_ConfirmationAttempt, outcome.value)


def _lock_session_row(session_key: str) -> int:
    """Lock one persisted Django session row and return the holding backend PID."""

    assert connection.in_atomic_block
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
    assert row is not None and type(row[0]) is int
    Session._default_manager.using(DEFAULT_DB_ALIAS).select_for_update().get(
        session_key=session_key
    )
    return row[0]


def _lock_session_on_worker(session_key: str) -> bool:
    """Attempt a real session-row lock from another database connection."""

    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        Session._default_manager.using(DEFAULT_DB_ALIAS).select_for_update().get(
            session_key=session_key
        )
    return True


def _wait_for_relation_row_lock(
    *,
    waiter_pid: int,
    relation_table: str,
    allowed_blocker_pids: tuple[int, ...],
    future: Future[_WorkerOutcome],
) -> _RelationRowLockWait:
    """Require a live SELECT waiter and granted row-share relation lock in PostgreSQL."""

    deadline = monotonic() + 6.0
    last_query = ""
    last_blockers: tuple[int, ...] = ()
    last_wait_event: str | None = None
    last_relation_oid: int | None = None
    last_lock_mode: str | None = None
    last_lock_granted: bool | None = None
    normalized_table = relation_table.lower()
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT activity.wait_event_type, activity.query, "
                "pg_blocking_pids(activity.pid), relation_lock.relation, "
                "relation_lock.mode, relation_lock.granted "
                "FROM pg_stat_activity AS activity "
                "JOIN pg_locks AS relation_lock ON relation_lock.pid = activity.pid "
                "WHERE activity.pid = %s "
                "AND relation_lock.locktype = 'relation' "
                "AND relation_lock.database = ("
                "SELECT oid FROM pg_database WHERE datname = current_database()"
                ") "
                "AND relation_lock.relation = to_regclass(%s)::oid "
                "AND relation_lock.mode = 'RowShareLock' "
                "ORDER BY relation_lock.granted DESC",
                [waiter_pid, relation_table],
            )
            row = cursor.fetchone()
        if row is not None and len(row) == 6:
            wait_value, query_value, blockers_value, oid_value, mode_value, granted_value = row
            last_wait_event = wait_value if isinstance(wait_value, str) else None
            last_query = query_value if isinstance(query_value, str) else ""
            last_blockers = (
                tuple(int(pid) for pid in blockers_value)
                if isinstance(blockers_value, (list, tuple))
                else ()
            )
            last_relation_oid = oid_value if type(oid_value) is int else None
            last_lock_mode = mode_value if isinstance(mode_value, str) else None
            last_lock_granted = granted_value if type(granted_value) is bool else None
            query_prefix = last_query.lstrip().lower()[:512]
            relation_is_locked = (
                last_relation_oid is not None
                and last_lock_mode == "RowShareLock"
                and last_lock_granted is True
            )
            blocker_matches = any(pid in last_blockers for pid in allowed_blocker_pids)
            if (
                last_wait_event == "Lock"
                and query_prefix.startswith("select ")
                and normalized_table in query_prefix
                and relation_is_locked
                and blocker_matches
            ):
                assert last_relation_oid is not None
                assert last_lock_mode is not None
                assert last_lock_granted is True
                return _RelationRowLockWait(
                    query=last_query,
                    blocker_pids=last_blockers,
                    wait_event_type=last_wait_event,
                    relation_oid=last_relation_oid,
                    relation_lock_mode=last_lock_mode,
                    relation_lock_granted=last_lock_granted,
                    relation_table=relation_table,
                )
        if future.done():
            finished = future.result()
            raise AssertionError(
                "worker completed before PostgreSQL reported the expected row-lock wait: "
                f"{finished!r}"
            )
        sleep(0.02)
    raise AssertionError(
        "worker did not wait on the expected PostgreSQL row lock; "
        f"table={relation_table!r}, wait_event={last_wait_event!r}, "
        f"blockers={last_blockers!r}, relation_oid={last_relation_oid!r}, "
        f"lock_mode={last_lock_mode!r}, lock_granted={last_lock_granted!r}, "
        f"query={last_query!r}"
    )


def _assert_relation_row_lock_wait(
    wait: _RelationRowLockWait,
    *,
    relation_table: str,
    allowed_blocker_pids: tuple[int, ...],
) -> None:
    """Check that PostgreSQL reports the exact table and an allowed blocker."""

    assert wait.wait_event_type == "Lock"
    assert wait.relation_oid > 0
    assert wait.relation_lock_mode == "RowShareLock"
    assert wait.relation_lock_granted is True
    assert wait.relation_table.lower() == relation_table.lower()
    assert any(pid in wait.blocker_pids for pid in allowed_blocker_pids)
    assert relation_table.lower() in wait.query.lower()
    assert wait.query.lstrip().lower().startswith("select ")


def _assert_single_posting(
    fixture: _FeeCorrectionFixture,
    attempts: tuple[_ConfirmationAttempt, ...],
    *,
    initial_cash: Decimal,
    original_trade: tuple[tuple[str, object], ...],
    expect_replay: bool,
) -> None:
    """Verify exactly one event and one corresponding cash/position update."""

    receipts = tuple(attempt.receipt for attempt in attempts if attempt.receipt is not None)
    blocked = tuple(attempt for attempt in attempts if attempt.blocked_code is not None)
    assert len(receipts) == (2 if expect_replay else 1)
    if expect_replay:
        typed_receipts = tuple(cast(FeeCorrectionReceipt, receipt) for receipt in receipts)
        assert sorted(receipt.replayed for receipt in typed_receipts) == [False, True]
        assert typed_receipts[0].event_id == typed_receipts[1].event_id
        assert blocked == ()
    else:
        assert len(blocked) == 1
        assert blocked[0].blocked_code == "FEE_CORRECTION_REVISION_CONFLICT"

    assert (
        SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=fixture.account.pk)
        .count()
        == 1
    )
    event = SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS).get(
        account_id=fixture.account.pk
    )
    fixture.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    fixture.position.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert fixture.account.current_cash == initial_cash + event.cash_delta
    assert event.cash_delta == Decimal("-0.05")
    assert fixture.position.total_cost == Decimal("1000.12")
    assert (
        _model_snapshot(
            SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS).get(pk=fixture.trade.pk)
        )
        == original_trade
    )
    assert (
        not SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(trade_id=fixture.trade.pk)
        .exists()
    )


def _model_snapshot(
    row: SimulatedAccountModel | PositionModel | SimulatedTradeModel,
) -> tuple[tuple[str, object], ...]:
    """Capture all persisted financial fields for the no-write concurrency assertions."""

    return tuple(
        (field.attname, getattr(row, field.attname)) for field in row._meta.concrete_fields
    )


def test_postgres_same_session_same_key_serializes_on_session_row(
    fee_correction_fixture: _FeeCorrectionFixture,
) -> None:
    """Two exact confirms share one real session lock and post one cash delta."""

    fixture = fee_correction_fixture
    context = _browser_context_for_owner(fixture.owner)
    command = _prepare_confirmation(
        fixture,
        context,
        idempotency_key="pg-confirm-same-session-key",
    )
    initial_cash = fixture.account.current_cash
    original_trade = _model_snapshot(fixture.trade)
    session_table = Session._meta.db_table

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="fee-confirm-session") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            blocker_pid = _lock_session_row(context.session_key)
            first = _submit_worker(
                executor,
                lambda: _attempt_confirmation(
                    command, owner=fixture.owner, browser_context=context
                ),
            )
            first_wait = _wait_for_relation_row_lock(
                waiter_pid=first.backend_pids[0],
                relation_table=session_table,
                allowed_blocker_pids=(blocker_pid,),
                future=first.future,
            )
            _assert_relation_row_lock_wait(
                first_wait,
                relation_table=session_table,
                allowed_blocker_pids=(blocker_pid,),
            )
            second = _submit_worker(
                executor,
                lambda: _attempt_confirmation(
                    command, owner=fixture.owner, browser_context=context
                ),
            )
            second_wait = _wait_for_relation_row_lock(
                waiter_pid=second.backend_pids[0],
                relation_table=session_table,
                allowed_blocker_pids=(blocker_pid, first.backend_pids[0]),
                future=second.future,
            )
            _assert_relation_row_lock_wait(
                second_wait,
                relation_table=session_table,
                allowed_blocker_pids=(blocker_pid, first.backend_pids[0]),
            )
            assert first.backend_pids[0] != second.backend_pids[0]

        attempts = (_attempt_from_worker(first), _attempt_from_worker(second))

    _assert_single_posting(
        fixture,
        attempts,
        initial_cash=initial_cash,
        original_trade=original_trade,
        expect_replay=True,
    )


@pytest.mark.parametrize(
    ("second_key", "expect_replay"),
    [
        pytest.param("pg-confirm-cross-session-same", True, id="same-key-cross-session"),
        pytest.param("pg-confirm-cross-session-other", False, id="different-key-same-head"),
    ],
)
def test_postgres_two_sessions_compete_on_one_fee_correction_head(
    fee_correction_fixture: _FeeCorrectionFixture,
    second_key: str,
    expect_replay: bool,
) -> None:
    """Independent session tokens serialize by account and replay or conflict by key."""

    fixture = fee_correction_fixture
    first_context = _browser_context_for_owner(fixture.owner)
    second_context = _browser_context_for_owner(fixture.owner)
    assert first_context.session_key != second_context.session_key
    first_key = (
        "pg-confirm-cross-session-same" if expect_replay else "pg-confirm-cross-session-first"
    )
    first_command = _prepare_confirmation(
        fixture,
        first_context,
        idempotency_key=first_key,
    )
    second_command = _prepare_confirmation(
        fixture,
        second_context,
        idempotency_key=second_key,
    )
    assert (
        first_command.idempotency_key == second_command.idempotency_key
        if expect_replay
        else (first_command.idempotency_key != second_command.idempotency_key)
    )
    initial_cash = fixture.account.current_cash
    original_trade = _model_snapshot(fixture.trade)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="fee-confirm-head") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            blocker_pid = _lock_account_parent(fixture.account)
            first = _submit_worker(
                executor,
                lambda: _attempt_confirmation(
                    first_command,
                    owner=fixture.owner,
                    browser_context=first_context,
                ),
            )
            first_wait = _wait_for_account_parent_lock(
                waiter_pid=first.backend_pids[0],
                allowed_blocker_pids=(blocker_pid,),
                future=first.future,
            )
            second = _submit_worker(
                executor,
                lambda: _attempt_confirmation(
                    second_command,
                    owner=fixture.owner,
                    browser_context=second_context,
                ),
            )
            second_wait = _wait_for_account_parent_lock(
                waiter_pid=second.backend_pids[0],
                allowed_blocker_pids=(blocker_pid, first.backend_pids[0]),
                future=second.future,
            )
            assert blocker_pid in first_wait.blocker_pids
            assert any(
                pid in second_wait.blocker_pids for pid in (blocker_pid, first.backend_pids[0])
            )
            assert first.backend_pids[0] != second.backend_pids[0]

        attempts = (_attempt_from_worker(first), _attempt_from_worker(second))

    _assert_single_posting(
        fixture,
        attempts,
        initial_cash=initial_cash,
        original_trade=original_trade,
        expect_replay=expect_replay,
    )


def test_postgres_confirmation_rechecks_password_after_account_lock_wait(
    fee_correction_fixture: _FeeCorrectionFixture,
) -> None:
    """A password change while confirmation waits invalidates the old session token."""

    fixture = fee_correction_fixture
    context = _browser_context_for_owner(fixture.owner)
    command = _prepare_confirmation(
        fixture,
        context,
        idempotency_key="pg-confirm-password-revoked",
    )
    account_before = _model_snapshot(fixture.account)
    trade_before = _model_snapshot(fixture.trade)
    position_before = _model_snapshot(fixture.position)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="fee-confirm-revoke") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            blocker_pid = _lock_account_parent(fixture.account)
            confirm_worker = _submit_worker(
                executor,
                lambda: _attempt_confirmation(
                    command, owner=fixture.owner, browser_context=context
                ),
            )
            account_wait = _wait_for_account_parent_lock(
                waiter_pid=confirm_worker.backend_pids[0],
                allowed_blocker_pids=(blocker_pid,),
                future=confirm_worker.future,
            )
            assert blocker_pid in account_wait.blocker_pids

            session_observer = _submit_worker(
                executor,
                lambda: _lock_session_on_worker(context.session_key),
            )
            session_wait = _wait_for_relation_row_lock(
                waiter_pid=session_observer.backend_pids[0],
                relation_table=Session._meta.db_table,
                allowed_blocker_pids=(confirm_worker.backend_pids[0],),
                future=session_observer.future,
            )
            _assert_relation_row_lock_wait(
                session_wait,
                relation_table=Session._meta.db_table,
                allowed_blocker_pids=(confirm_worker.backend_pids[0],),
            )

            user = (
                get_user_model()
                ._default_manager.using(DEFAULT_DB_ALIAS)
                .get(pk=context.actor_user_id)
            )
            user.set_password("changed-during-confirmation-test")
            user.save(using=DEFAULT_DB_ALIAS, update_fields=("password",))

        attempt = _attempt_from_worker(confirm_worker)
        observer_outcome = session_observer.future.result(timeout=20)

    assert attempt.receipt is None
    assert attempt.blocked_code == "FEE_CORRECTION_CONFIRMATION_SESSION_INVALID"
    assert observer_outcome.value is True
    assert (
        not SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=fixture.account.pk)
        .exists()
    )
    fixture.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    fixture.trade.refresh_from_db(using=DEFAULT_DB_ALIAS)
    fixture.position.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert _model_snapshot(fixture.account) == account_before
    assert _model_snapshot(fixture.trade) == trade_before
    assert _model_snapshot(fixture.position) == position_before


def test_postgres_disabled_policy_blocks_confirmation_after_account_lock_wait(
    fee_correction_fixture: _FeeCorrectionFixture,
) -> None:
    """A committed owner policy disable wins over a queued fee confirmation."""

    fixture = fee_correction_fixture
    context = _browser_context_for_owner(fixture.owner)
    command = _prepare_confirmation(
        fixture,
        context,
        idempotency_key="pg-confirm-policy-revoked",
    )
    account_before = _model_snapshot(fixture.account)
    trade_before = _model_snapshot(fixture.trade)
    position_before = _model_snapshot(fixture.position)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="fee-confirm-policy") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            blocker_pid = _lock_account_parent(fixture.account)
            worker = _submit_worker(
                executor,
                lambda: _attempt_confirmation(
                    command, owner=fixture.owner, browser_context=context
                ),
            )
            wait = _wait_for_account_parent_lock(
                waiter_pid=worker.backend_pids[0],
                allowed_blocker_pids=(blocker_pid,),
                future=worker.future,
            )
            assert blocker_pid in wait.blocker_pids

            policy_use_case = build_fee_correction_policy_use_case()
            current = policy_use_case.get(fixture.account.pk, principal=fixture.owner)
            disabled = policy_use_case.save(
                FeeCorrectionPolicyCommand(
                    account_id=fixture.account.pk,
                    expected_version=current.version,
                    enabled=False,
                    allow_operator_attested_upload=False,
                    ledger_currency=current.ledger_currency,
                    valid_from=current.valid_from,
                    valid_until=current.valid_until,
                    attestation_acknowledged=False,
                ),
                principal=fixture.owner,
            )
            assert disabled.enabled is False

        attempt = _attempt_from_worker(worker)

    assert attempt.receipt is None
    assert attempt.blocked_code == "FEE_CORRECTION_SOURCE_UNAVAILABLE"
    assert (
        SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=fixture.account.pk)
        .count()
        == 0
    )
    policy = FeeCorrectionEvidencePolicyModel.objects.using(DEFAULT_DB_ALIAS).get(
        account_id=fixture.account.pk
    )
    assert policy.enabled is False
    assert policy.version == 2
    fixture.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    fixture.trade.refresh_from_db(using=DEFAULT_DB_ALIAS)
    fixture.position.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert _model_snapshot(fixture.account) == account_before
    assert _model_snapshot(fixture.trade) == trade_before
    assert _model_snapshot(fixture.position) == position_before
