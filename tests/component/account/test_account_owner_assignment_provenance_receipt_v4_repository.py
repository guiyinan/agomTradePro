"""Receipt persistence against real PG writers with synthetic creation facts and test clocks.

The actor sources are published from an actual local User/Profile/Session. The
creation Domain graph is a test fixture, not a captured real account creation.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from importlib import import_module
from queue import Queue
from threading import Thread
from time import monotonic, sleep

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.db.migrations.state import ProjectState

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_request_reader,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Recorder,
    PersistedAllocatedPhysicalAccountRowObservationV3,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_models import (
    AccountOwnerAssignmentProvenanceReceiptV4Model,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _gateway,
    _session_for_user,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    evid06_alias as evid06_alias,
)
from tests.component.account.test_canonical_account_creation_consumption_repository import (
    _append_pair,
    _pair,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4 import _at, _receipt

_CREATION_MODELS = (
    CanonicalAccountCreationAllocationModel,
    AllocatedPhysicalAccountRowObservationV3Model,
    CanonicalAccountCreationConsumptionClaimModel,
    CanonicalAccountCreationBindingModel,
    CanonicalAccountCreationBindingV2Model,
    SingleOwnerAuthorityPolicyV1Model,
)


@pytest.fixture
def creation_alias(evid06_alias: str) -> Iterator[str]:
    connection = connections[evid06_alias]
    with connection.schema_editor() as editor:
        for model in _CREATION_MODELS:
            editor.create_model(model)
    try:
        yield evid06_alias
    finally:
        with connection.schema_editor() as editor:
            for model in reversed(_CREATION_MODELS):
                editor.delete_model(model)


@pytest.fixture
def receipt_alias(creation_alias: str) -> Iterator[str]:
    connection = connections[creation_alias]
    with connection.schema_editor() as editor:
        editor.create_model(AccountOwnerAssignmentProvenanceReceiptV4Model)
    try:
        yield creation_alias
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(AccountOwnerAssignmentProvenanceReceiptV4Model)


def _seed_record(
    alias: str, monkeypatch: pytest.MonkeyPatch
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
    observation = _at(8, 12, 30)
    monkeypatch.setattr("django.utils.timezone.now", lambda: observation)
    binding, claim = _pair()
    allocation_repository = DjangoCanonicalAccountCreationRepository(using=alias)
    with allocation_repository.atomic():
        allocation_repository.append_allocation(
            binding.allocation, recorded_at=binding.allocation.allocated_at
        )
    root_repository = DjangoAllocatedPhysicalAccountRowObservationV3Repository(using=alias)
    with root_repository.atomic():
        root_repository.append(
            PersistedAllocatedPhysicalAccountRowObservationV3(
                binding.creation_root,
                AllocatedPhysicalAccountRowObservationV3Recorder("receipt-v4-test"),
            ),
            expected_predecessor_hash=None,
            recorded_at=binding.creation_root.recorded_at,
        )
    consumption = DjangoCanonicalAccountCreationConsumptionRepository(using=alias)
    with consumption.atomic():
        _append_pair(consumption, binding, claim)
    user = User(
        id=binding.allocation.requested_row_user_id,
        username="receipt-v4-test-owner",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    user.set_password("receipt-v4-local-test-password")
    user.save(using=alias)
    AccountProfileModel(
        user=user,
        display_name="Receipt V4 test",
        rbac_role="owner",
        mcp_enabled=True,
        approval_status="pending",
    ).save(using=alias)
    session = _session_for_user(alias, user, expires_at=observation + timedelta(hours=1))
    publication = _gateway(alias, user, session).publish()
    authority = build_account_actor_authority_request_reader(
        source_id=publication.actor.source_id,
        source_version=publication.actor.source_version,
        expected_content_hash=publication.actor.content_hash,
        using=alias,
    ).get_exact_current(
        principal_id=publication.principal_id,
        user_id=publication.user_id,
        expected_authentication_context_hash=publication.authentication_context.content_hash,
        as_of=observation,
    )
    assert authority is not None
    receipt = _receipt(
        binding=binding,
        issued_at=observation,
        recorded_at=observation,
        valid_until=publication.valid_until,
    )
    policy_repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=alias)
    with policy_repository.atomic():
        policy_repository.append(policy=receipt.policy, expected_previous_content_hash=None)
    actor = receipt.claimant
    return PersistedAccountOwnerAssignmentProvenanceReceiptV4(
        receipt,
        AccountOwnerAssignmentServerActor(
            actor.actor_id, actor.user_id, actor.role, actor.kind, actor.is_staff
        ),
        authority,
    )


def _append(
    repository: DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository,
    record: PersistedAccountOwnerAssignmentProvenanceReceiptV4,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
    with repository.atomic():
        return repository.append(
            record,
            expected_predecessor_hash=record.receipt.supersedes_content_hash,
            recorded_at=record.receipt.recorded_at,
        )


def test_real_parent_roundtrip_replay_and_outer_rollback(
    receipt_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _seed_record(receipt_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=receipt_alias)
    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic(using=receipt_alias):
            assert _append(repository, record) == record
            raise RuntimeError("outer rollback")
    assert AccountOwnerAssignmentProvenanceReceiptV4Model.objects.using(receipt_alias).count() == 0
    assert _append(repository, record) == _append(repository, record) == record
    assert AccountOwnerAssignmentProvenanceReceiptV4Model.objects.using(receipt_alias).count() == 1
    assert (
        repository.get_exact_by_hash(
            receipt_id=record.receipt.receipt_id,
            receipt_version=record.receipt.receipt_version,
            expected_content_hash=record.receipt.content_hash,
            as_of=record.receipt.recorded_at,
        )
        == record
    )


def test_parent_tamper_breaks_even_unrelated_selector(
    receipt_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _seed_record(receipt_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=receipt_alias)
    _append(repository, record)
    connection = connections[receipt_alias]
    table = connection.ops.quote_name(SingleOwnerAuthorityPolicyV1Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET authorization_content_hash=%s", ["e" * 64])
    with pytest.raises(AccountOwnerAssignmentCorruption):
        repository.get_winner(
            receipt_id="missing", receipt_version="missing", as_of=record.receipt.recorded_at
        )


def test_successor_cas_and_expired_head_never_falls_back(
    receipt_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _seed_record(receipt_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=receipt_alias)
    _append(repository, first)
    second_time = first.receipt.recorded_at + timedelta(seconds=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: second_time)
    second = replace(
        first,
        receipt=replace(
            first.receipt,
            receipt_version="v4.2",
            issued_at=second_time,
            recorded_at=second_time,
            valid_until=second_time + timedelta(seconds=1),
            supersedes_content_hash=first.receipt.content_hash,
            identity_hash="",
            content_hash="",
        ),
    )
    assert _append(repository, second) == second
    cutoff = second.receipt.valid_until
    assert repository.get_current_head(receipt_id=first.receipt.receipt_id, as_of=cutoff) == second
    assert second.receipt.is_current_at(cutoff) is False
    assert first.receipt.is_current_at(cutoff) is True
    assert _append(repository, first) == first
    with pytest.raises(AccountOwnerAssignmentConflict):
        with repository.atomic():
            repository.append(
                second, expected_predecessor_hash=None, recorded_at=second.receipt.recorded_at
            )


def test_record_ledger_seal_tampering_cannot_restore(
    receipt_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _seed_record(receipt_alias, monkeypatch)
    repository = DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=receipt_alias)
    _append(repository, record)
    connection = connections[receipt_alias]
    table = connection.ops.quote_name(AccountOwnerAssignmentProvenanceReceiptV4Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET ledger_seal=%s", ["0" * 64])
    with pytest.raises(AccountOwnerAssignmentCorruption):
        repository.get_current_head(
            receipt_id=record.receipt.receipt_id, as_of=record.receipt.recorded_at
        )


def test_all_parent_writes_use_selected_alias_and_public_orm_bypasses_fail(
    receipt_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_default(*args: object, **kwargs: object) -> None:
        raise AssertionError("receipt graph attempted a default-alias query")

    with connections["default"].execute_wrapper(reject_default):
        record = _seed_record(receipt_alias, monkeypatch)
        repository = DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=receipt_alias)
        assert _append(repository, record) == record
        query = AccountOwnerAssignmentProvenanceReceiptV4Model._default_manager.using(receipt_alias)
        row = query.get()
        with pytest.raises(ValidationError):
            query.create(receipt_id="bypass")
        with pytest.raises(ValidationError):
            query.bulk_create([])
        with pytest.raises(ValidationError):
            query.update(status="active")
        with pytest.raises(ValidationError):
            query.bulk_update([row], ["status"])
        with pytest.raises(ValidationError):
            query.delete()
        with pytest.raises(ValidationError):
            row.delete(using=receipt_alias)
        with pytest.raises(ValidationError):
            AccountOwnerAssignmentProvenanceReceiptV4Model().save_base(using=receipt_alias)


def test_receipt_waits_for_policy_writer_then_rejects_committed_revocation(
    receipt_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _seed_record(receipt_alias, monkeypatch)
    policy = record.receipt.policy
    revoked = replace(
        policy,
        policy_version="revoked",
        status="revoked",
        observed_at=record.receipt.recorded_at,
        identity_hash="",
        content_hash="",
    )
    policy_repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=receipt_alias)
    worker_pid: Queue[int] = Queue()
    outcome: Queue[object] = Queue()

    def issue_in_other_connection() -> None:
        connection = connections[receipt_alias]
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                worker_pid.put(cursor.fetchone()[0])
            repository = DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(
                using=receipt_alias
            )
            outcome.put(_append(repository, record))
        except Exception as error:
            outcome.put(error)
        finally:
            connection.close()

    worker = Thread(target=issue_in_other_connection, daemon=True)
    try:
        with policy_repository.atomic():
            policy_repository.append(
                policy=revoked, expected_previous_content_hash=policy.content_hash
            )
            worker.start()
            pid = worker_pid.get(timeout=10)
            deadline = monotonic() + 10
            waiting = False
            while monotonic() < deadline:
                with connections[receipt_alias].cursor() as cursor:
                    cursor.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=%s "
                        "AND locktype='advisory' AND NOT granted) "
                        "AND pg_backend_pid() = ANY(pg_blocking_pids(%s))",
                        [pid, pid],
                    )
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                sleep(0.02)
            assert waiting, "receipt must wait on the policy writer's exact advisory key"
    finally:
        if worker.ident is not None:
            worker.join(timeout=15)
            assert not worker.is_alive(), "receipt append did not finish after policy lock release"
    assert isinstance(outcome.get(timeout=1), AccountOwnerAssignmentCorruption)
    assert (
        AccountOwnerAssignmentProvenanceReceiptV4Model._default_manager.using(receipt_alias).count()
        == 0
    )


def test_receipt_migration_ddl_roundtrip_with_all_real_parent_tables(creation_alias: str) -> None:
    module = import_module(
        "apps.account.migrations.0057_account_owner_assignment_provenance_receipt_v4"
    )
    migration = module.Migration("0057_account_owner_assignment_provenance_receipt_v4", "account")
    connection = connections[creation_alias]
    table = AccountOwnerAssignmentProvenanceReceiptV4Model._meta.db_table
    from django.apps import apps

    before = ProjectState.from_apps(apps)
    before.remove_model("account", "accountownerassignmentprovenancereceiptv4model")
    for _ in range(2):
        with connection.schema_editor() as editor:
            migration.apply(before.clone(), editor)
        try:
            with connection.cursor() as cursor:
                constraints = connection.introspection.get_constraints(cursor, table)
            assert {
                c.name for c in AccountOwnerAssignmentProvenanceReceiptV4Model._meta.constraints
            } <= set(constraints)
            assert len([c for c in constraints.values() if c["foreign_key"]]) == 4
        finally:
            with connection.schema_editor() as editor:
                migration.unapply(before.clone(), editor)
        assert table not in connection.introspection.table_names()
