"""Component contracts for R7 result lifecycle persistence and audit paging."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from queue import Queue
from threading import Event, Lock
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.models.deletion import Collector
from django.test import override_settings

from apps.research.application.r7_research_result_lifecycle import (
    ApplyR7ResultLifecycleCommand,
    R7ResultLifecycleAuthorizationRef,
    R7ResultLifecycleConflict,
    R7ResultLifecycleCorruption,
    R7ResultLifecycleUnavailable,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
    R7ResultLifecycleStatus,
    R7ResultPromotionAuthorization,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
)
from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResearchResultAuditSnapshotModel,
    R7ResultLifecycleAuthorizationModel,
    R7ResultLifecycleEventModel,
)
from apps.research.infrastructure.r7_research_result_lifecycle_repository import (
    _authorization_values,
    _DjangoR7ResultLifecycleStore,
)
from apps.research.infrastructure.r7_research_result_models import R7ResearchResultModel
from apps.research.r7_research_result_lifecycle_composition import (
    DjangoR7ResultLifecycleRuntime,
    build_django_r7_result_lifecycle_runtime,
)
from tests.component.research.test_r7_research_result_repository import (
    FixedClock,
    _command,
    _runtime,
)


class AuthorizationProvider:
    """Exact in-memory owner port used only at the component boundary."""

    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.authorization: R7ResultPromotionAuthorization | None = None
        self.calls: list[tuple[object, ...]] = []

    def get_exact(
        self,
        *,
        authorization_ref: R7ResultLifecycleAuthorizationRef,
        result_ref: R7ResearchResultRef,
        action: R7ResultLifecycleAction,
        as_of: datetime,
    ) -> R7ResultPromotionAuthorization | None:
        self.calls.append((authorization_ref, result_ref, action, as_of))
        authorization = self.authorization
        if authorization is None:
            return None
        if (
            authorization.authorization_id != authorization_ref.authorization_id
            or authorization.authorization_version != authorization_ref.authorization_version
            or authorization.result_ref != result_ref
            or authorization.action is not action
            or authorization.recorded_at > as_of
        ):
            return None
        return authorization


@dataclass(frozen=True)
class LifecycleFixture:
    runtime: DjangoR7ResultLifecycleRuntime
    repository: _DjangoR7ResultLifecycleStore
    provider: AuthorizationProvider
    clock: FixedClock


def _lifecycle_runtime(clock: FixedClock) -> LifecycleFixture:
    provider = AuthorizationProvider()
    runtime = build_django_r7_result_lifecycle_runtime(
        authorization_provider=provider,
        clock=clock,
    )
    repository = _DjangoR7ResultLifecycleStore(clock=clock)
    return LifecycleFixture(runtime, repository, provider, clock)


def _result_ref(result: PersistedR7ResearchResult) -> R7ResearchResultRef:
    return R7ResearchResultRef(
        result.result_id,
        result.result_version,
        result.content_hash,
    )


def _authorization(
    *,
    result_ref: R7ResearchResultRef,
    action: R7ResultLifecycleAction,
    sequence: int,
    recorded_at: datetime,
) -> R7ResultPromotionAuthorization:
    return R7ResultPromotionAuthorization(
        authorization_id=f"component-r7-result-auth:{result_ref.result_id}:{sequence}",
        authorization_version="r7-result-authorization.v1",
        result_ref=result_ref,
        event_id=f"component-r7-result-event:{result_ref.result_id}:{sequence}",
        event_version="r7-result-lifecycle-event.v1",
        action=action,
        expected_sequence=sequence,
        owner="research",
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(days=1),
        reason_codes=("research-owner-reviewed",),
        evidence_ref=f"research://r7-result-review/{sequence}",
    )


def _apply_command(
    authorization: R7ResultPromotionAuthorization,
) -> ApplyR7ResultLifecycleCommand:
    return ApplyR7ResultLifecycleCommand(
        result_ref=authorization.result_ref,
        action=authorization.action,
        authorization_ref=R7ResultLifecycleAuthorizationRef(
            authorization.authorization_id,
            authorization.authorization_version,
        ),
    )


@pytest.mark.django_db
def test_exact_owner_promotion_retirement_and_idempotent_replay_are_pit_safe() -> None:
    result_fixture = _runtime()
    result = result_fixture.runtime.register.execute(_command())
    result_fixture.clock.value += timedelta(hours=1)
    fixture = _lifecycle_runtime(result_fixture.clock)
    result_ref = _result_ref(result)
    assert not hasattr(fixture.runtime, "repository")

    promotion = _authorization(
        result_ref=result_ref,
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=fixture.clock.value - timedelta(minutes=1),
    )
    fixture.provider.authorization = promotion
    promotion_event = fixture.runtime.apply.execute(_apply_command(promotion))
    assert promotion_event.recorded_at == fixture.clock.value
    assert promotion_event.publishes_model_probability is False
    assert promotion_event.produces_decision is False
    assert promotion_event.executes_orders is False

    fixture.clock.value += timedelta(minutes=10)
    retirement = _authorization(
        result_ref=result_ref,
        action=R7ResultLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=fixture.clock.value - timedelta(minutes=1),
    )
    fixture.provider.authorization = retirement
    retirement_event = fixture.runtime.apply.execute(_apply_command(retirement))
    assert retirement_event.previous_event_hash == promotion_event.content_hash

    fixture.provider.authorization = promotion
    assert fixture.runtime.apply.execute(_apply_command(promotion)) == promotion_event
    page = fixture.runtime.audit.execute(as_of=fixture.clock.value)
    assert page.entries[0].lifecycle_status is R7ResultLifecycleStatus.RETIRED
    assert page.entries[0].lifecycle_sequence == 2
    assert page.entries[0].must_not_use_for_decision is True
    assert page.entries[0].must_not_execute is True
    assert R7ResultLifecycleAuthorizationModel._default_manager.count() == 2
    assert R7ResultLifecycleEventModel._default_manager.count() == 2


@pytest.mark.django_db
def test_direct_bulk_related_update_base_and_delete_paths_are_rejected() -> None:
    result_fixture = _runtime()
    result = result_fixture.runtime.register.execute(_command())
    result_fixture.clock.value += timedelta(hours=1)
    fixture = _lifecycle_runtime(result_fixture.clock)
    authorization = _authorization(
        result_ref=_result_ref(result),
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=fixture.clock.value - timedelta(minutes=1),
    )
    fixture.provider.authorization = authorization
    fixture.runtime.apply.execute(_apply_command(authorization))
    authorization_row = R7ResultLifecycleAuthorizationModel._default_manager.get()
    event_row = R7ResultLifecycleEventModel._default_manager.get()

    authorization_row.owner = "strategy"
    with pytest.raises(ValidationError, match="append-only"):
        authorization_row.save()
    with pytest.raises(ValidationError, match="append-only"):
        authorization_row.save_base(force_update=True)
    with pytest.raises(ValidationError, match="append-only"):
        event_row.save_base(raw=True)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        event_row.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        R7ResultLifecycleEventModel._default_manager.update(sequence=99)
    with pytest.raises(ValidationError, match="repository appends"):
        R7ResultLifecycleAuthorizationModel._default_manager.bulk_create(
            [
                R7ResultLifecycleAuthorizationModel(
                    result=authorization_row.result,
                    **_authorization_values(authorization),
                )
            ]
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        authorization_row.result.lifecycle_authorizations.create(
            **_authorization_values(authorization)
        )
    private_queryset = R7ResultLifecycleEventModel._base_manager.filter(pk=event_row.pk)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        private_queryset._raw_delete("default")
    with pytest.raises(ValidationError, match="cannot be updated"):
        private_queryset._update([])
    with pytest.raises(ValidationError, match="private insert"):
        private_queryset._insert([], [])
    with pytest.raises(ValidationError, match="private bulk insert"):
        private_queryset._batched_insert([], [], 1)
    collector = Collector(using="default")
    collector.collect([event_row])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        with transaction.atomic():
            collector.delete()
    assert R7ResultLifecycleEventModel._default_manager.count() == 1


@pytest.mark.django_db
def test_raw_header_and_authorization_result_fk_substitution_are_detected() -> None:
    result_fixture = _runtime()
    first = result_fixture.runtime.register.execute(_command())
    result_fixture.clock.value += timedelta(minutes=1)
    second = result_fixture.runtime.register.execute(
        replace(_command(), result_id="r7-result:scenario-probability:2")
    )
    result_fixture.clock.value += timedelta(hours=1)
    fixture = _lifecycle_runtime(result_fixture.clock)
    authorization = _authorization(
        result_ref=_result_ref(first),
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=fixture.clock.value - timedelta(minutes=1),
    )
    fixture.provider.authorization = authorization
    fixture.runtime.apply.execute(_apply_command(authorization))
    event_row = R7ResultLifecycleEventModel._default_manager.get()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_result_lifecycle_event " "SET authorization_id = %s WHERE id = %s",
            ["tampered-authorization", event_row.pk],
        )
    with (
        fixture.repository.atomic(),
        pytest.raises(R7ResultLifecycleCorruption, match="header mismatch"),
    ):
        fixture.repository.load_lifecycle_stream(result_ref=_result_ref(first))

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_result_lifecycle_event " "SET authorization_id = %s WHERE id = %s",
            [authorization.authorization_id, event_row.pk],
        )
        second_row = R7ResearchResultModel._default_manager.get(result_id=second.result_id)
        cursor.execute(
            "UPDATE research_r7_result_lifecycle_authorization " "SET result_id = %s WHERE id = %s",
            [second_row.pk, event_row.authorization_record_id],
        )
    with (
        fixture.repository.atomic(),
        pytest.raises(
            R7ResultLifecycleCorruption,
            match="relation substitution|set is incomplete",
        ),
    ):
        fixture.repository.load_lifecycle_stream(result_ref=_result_ref(first))


@pytest.mark.django_db
def test_raw_canonical_payload_tamper_is_detected() -> None:
    result_fixture = _runtime()
    result = result_fixture.runtime.register.execute(_command())
    result_fixture.clock.value += timedelta(hours=1)
    fixture = _lifecycle_runtime(result_fixture.clock)
    authorization = _authorization(
        result_ref=_result_ref(result),
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=fixture.clock.value - timedelta(minutes=1),
    )
    fixture.provider.authorization = authorization
    fixture.runtime.apply.execute(_apply_command(authorization))
    event_row = R7ResultLifecycleEventModel._default_manager.get()
    payload = dict(event_row.canonical_payload)
    payload["action"] = R7ResultLifecycleAction.RETIRE.value
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_result_lifecycle_event " "SET canonical_payload = %s WHERE id = %s",
            [json.dumps(payload), event_row.pk],
        )
    with (
        fixture.repository.atomic(),
        pytest.raises(R7ResultLifecycleCorruption, match="payload is invalid"),
    ):
        fixture.repository.load_lifecycle_stream(result_ref=_result_ref(result))


@pytest.mark.django_db
def test_raw_event_delete_cannot_silently_revert_audit_to_unpromoted() -> None:
    result_fixture = _runtime()
    result = result_fixture.runtime.register.execute(_command())
    result_fixture.clock.value += timedelta(hours=1)
    fixture = _lifecycle_runtime(result_fixture.clock)
    authorization = _authorization(
        result_ref=_result_ref(result),
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=fixture.clock.value - timedelta(minutes=1),
    )
    fixture.provider.authorization = authorization
    fixture.runtime.apply.execute(_apply_command(authorization))
    event_row = R7ResultLifecycleEventModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM research_r7_result_lifecycle_event WHERE id = %s",
            [event_row.pk],
        )

    with pytest.raises(R7ResultLifecycleCorruption, match="authorization/event set"):
        fixture.runtime.audit.execute(as_of=fixture.clock.value)


@pytest.mark.django_db(transaction=True)
def test_event_insert_failure_rolls_back_authorization_and_reports_conflict() -> None:
    result_fixture = _runtime()
    result = result_fixture.runtime.register.execute(_command())
    result_fixture.clock.value += timedelta(hours=1)
    fixture = _lifecycle_runtime(result_fixture.clock)
    authorization = _authorization(
        result_ref=_result_ref(result),
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=fixture.clock.value - timedelta(minutes=1),
    )
    fixture.provider.authorization = authorization

    with (
        patch.object(
            R7ResultLifecycleEventModel,
            "save",
            side_effect=IntegrityError("event race"),
        ),
        pytest.raises(R7ResultLifecycleConflict, match="race lost"),
    ):
        fixture.runtime.apply.execute(_apply_command(authorization))

    assert R7ResultLifecycleAuthorizationModel._default_manager.count() == 0
    assert R7ResultLifecycleEventModel._default_manager.count() == 0


@pytest.mark.django_db
def test_audit_cursor_is_snapshot_bound_tamper_evident_and_has_no_duplicates() -> None:
    result_fixture = _runtime()
    first = result_fixture.runtime.register.execute(_command())
    for suffix in ("2", "3"):
        result_fixture.clock.value += timedelta(minutes=1)
        result_fixture.runtime.register.execute(
            replace(
                _command(),
                result_id=f"r7-result:scenario-probability:{suffix}",
            )
        )
    snapshot = result_fixture.clock.value
    fixture = _lifecycle_runtime(result_fixture.clock)
    first_page = fixture.runtime.audit.execute(as_of=snapshot, limit=1)
    assert first_page.next_cursor is not None
    assert R7ResearchResultAuditSnapshotModel._default_manager.count() == 1
    snapshot_row = R7ResearchResultAuditSnapshotModel._default_manager.get()
    assert snapshot_row.entry_count == 3
    assert all(
        "result_persisted_at" in entry for entry in snapshot_row.canonical_payload["entries"]
    )

    result_fixture.clock.value = snapshot - timedelta(seconds=30)
    result_fixture.runtime.register.execute(
        replace(_command(), result_id="r7-result:scenario-probability:late")
    )
    result_fixture.clock.value = snapshot + timedelta(minutes=1)
    seen = [first_page.entries[0].result_ref.result_id]
    cursor = first_page.next_cursor
    while cursor is not None:
        page = fixture.runtime.audit.execute(as_of=snapshot, cursor=cursor, limit=1)
        seen.extend(item.result_ref.result_id for item in page.entries)
        cursor = page.next_cursor
    assert len(seen) == len(set(seen)) == 3
    assert "r7-result:scenario-probability:late" not in seen

    with pytest.raises(R7ResultLifecycleUnavailable, match="different snapshot"):
        fixture.runtime.audit.execute(
            as_of=snapshot + timedelta(microseconds=1),
            cursor=first_page.next_cursor,
            limit=1,
        )
    assert first_page.next_cursor is not None
    tampered = first_page.next_cursor[:-1] + ("A" if first_page.next_cursor[-1] != "A" else "B")
    with pytest.raises(ValueError, match="cursor"):
        fixture.runtime.audit.execute(as_of=snapshot, cursor=tampered, limit=1)
    with (
        override_settings(SECRET_KEY="attacker-does-not-have-the-signing-key"),
        pytest.raises(ValueError, match="signature"),
    ):
        fixture.runtime.audit.execute(
            as_of=snapshot,
            cursor=first_page.next_cursor,
            limit=1,
        )

    fixture.clock.value += timedelta(minutes=10)
    promotion = _authorization(
        result_ref=_result_ref(first),
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=fixture.clock.value - timedelta(minutes=1),
    )
    fixture.provider.authorization = promotion
    event = fixture.runtime.apply.execute(_apply_command(promotion))
    before = fixture.runtime.audit.execute(as_of=event.recorded_at - timedelta(microseconds=1))
    after = fixture.runtime.audit.execute(as_of=event.recorded_at)
    before_entry = next(item for item in before.entries if item.result_ref == promotion.result_ref)
    after_entry = next(item for item in after.entries if item.result_ref == promotion.result_ref)
    assert before_entry.lifecycle_status is R7ResultLifecycleStatus.UNPROMOTED
    assert after_entry.lifecycle_status is R7ResultLifecycleStatus.PROMOTED


@pytest.mark.django_db
def test_audit_snapshot_is_append_only_and_result_persistence_tamper_evident() -> None:
    result_fixture = _runtime()
    result_fixture.runtime.register.execute(_command())
    result_fixture.clock.value += timedelta(minutes=1)
    result_fixture.runtime.register.execute(
        replace(_command(), result_id="r7-result:scenario-probability:2")
    )
    snapshot = result_fixture.clock.value
    fixture = _lifecycle_runtime(result_fixture.clock)
    page = fixture.runtime.audit.execute(as_of=snapshot, limit=1)
    assert page.next_cursor is not None
    row = R7ResearchResultAuditSnapshotModel._default_manager.get()

    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        R7ResearchResultAuditSnapshotModel._default_manager.update(entry_count=99)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    collector = Collector(using="default")
    collector.collect([row])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        with transaction.atomic():
            collector.delete()

    payload = deepcopy(row.canonical_payload)
    entries = payload["entries"]
    entries[0]["result_persisted_at"] = (
        datetime.fromisoformat(entries[0]["result_persisted_at"]) + timedelta(seconds=1)
    ).isoformat()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_result_audit_snapshot " "SET canonical_payload = %s WHERE id = %s",
            [json.dumps(payload), row.pk],
        )
    with pytest.raises(R7ResultLifecycleCorruption, match="content_hash mismatch"):
        fixture.runtime.audit.execute(
            as_of=snapshot,
            cursor=page.next_cursor,
            limit=1,
        )


@pytest.mark.django_db(transaction=True)
def test_postgresql_snapshot_lock_serializes_concurrent_lifecycle_append() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row-lock visibility across two connections")

    result_fixture = _runtime()
    target = result_fixture.runtime.register.execute(_command())
    result_fixture.clock.value += timedelta(minutes=1)
    result_fixture.runtime.register.execute(
        replace(_command(), result_id="r7-result:scenario-probability:2")
    )
    snapshot = result_fixture.clock.value
    fixture = _lifecycle_runtime(result_fixture.clock)
    promotion = _authorization(
        result_ref=_result_ref(target),
        action=R7ResultLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=snapshot - timedelta(seconds=1),
    )
    fixture.provider.authorization = promotion

    locks_acquired = Event()
    release_audit = Event()
    first_entry_lock = Lock()
    first_entry_pending = True
    original_audit_entry = fixture.repository._audit_entry

    def hold_after_manifest_locks(*, model: R7ResearchResultModel, as_of: datetime):
        nonlocal first_entry_pending
        with first_entry_lock:
            should_hold = first_entry_pending
            first_entry_pending = False
        if should_hold:
            locks_acquired.set()
            assert release_audit.wait(timeout=10)
        return original_audit_entry(model=model, as_of=as_of)

    append_pid: Queue[int] = Queue(maxsize=1)

    def materialize_snapshot():
        close_old_connections()
        try:
            return fixture.repository.list_audit(as_of=snapshot, cursor=None, limit=1)
        finally:
            connections["default"].close()

    def append_promotion():
        close_old_connections()
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                append_pid.put(int(cursor.fetchone()[0]))
            return fixture.runtime.apply.execute(_apply_command(promotion))
        finally:
            connections["default"].close()

    with (
        patch.object(fixture.repository, "_audit_entry", side_effect=hold_after_manifest_locks),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        audit_future = executor.submit(materialize_snapshot)
        assert locks_acquired.wait(timeout=10)
        append_future = executor.submit(append_promotion)
        pid = append_pid.get(timeout=10)
        deadline = time.monotonic() + 10
        observed_lock_wait = False
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                    [pid],
                )
                row = cursor.fetchone()
            if row is not None and row[0] == "Lock":
                observed_lock_wait = True
                break
            time.sleep(0.05)
        release_audit.set()
        first_page = audit_future.result(timeout=10)
        append_future.result(timeout=10)

    assert observed_lock_wait is True
    assert first_page.next_cursor is not None
    frozen_entries = list(first_page.entries)
    frozen_cursor = first_page.next_cursor
    while frozen_cursor is not None:
        page = fixture.runtime.audit.execute(
            as_of=snapshot,
            cursor=frozen_cursor,
            limit=1,
        )
        frozen_entries.extend(page.entries)
        frozen_cursor = page.next_cursor
    frozen_target = next(
        entry for entry in frozen_entries if entry.result_ref == _result_ref(target)
    )
    assert frozen_target.lifecycle_status is R7ResultLifecycleStatus.UNPROMOTED

    fresh_page = fixture.runtime.audit.execute(as_of=snapshot)
    fresh_target = next(
        entry for entry in fresh_page.entries if entry.result_ref == _result_ref(target)
    )
    assert fresh_target.lifecycle_status is R7ResultLifecycleStatus.PROMOTED
