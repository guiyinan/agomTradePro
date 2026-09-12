"""Real PostgreSQL owner decisions over durable local V4 provenance and actual auth."""

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connections, transaction

from apps.account.application.owner_tenant_authority_v2_contracts import (
    OwnerTenantAuthorityV2Conflict,
    OwnerTenantAuthorityV2Corruption,
    OwnerTenantAuthorityV2Unavailable,
    PersistedOwnerTenantAuthorityV2,
    PersistedOwnerTenantAuthorityV2Revocation,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    APPROVER_ROLE,
    REVOKER_ROLE,
    OwnerTenantAuthorityV2,
    OwnerTenantAuthorityV2Revocation,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_models import (
    AccountOwnerAssignmentEvidenceV4Model,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_repository import (
    DjangoAccountOwnerAssignmentEvidenceV4Repository,
)
from apps.account.infrastructure.owner_tenant_authority_v2_models import (
    OwnerTenantAuthorityV2Model,
    OwnerTenantAuthorityV2RevocationModel,
)
from apps.account.infrastructure.owner_tenant_authority_v2_repository import (
    DjangoOwnerTenantAuthorityV2Repository,
    lock_owner_tenant_authority_v2_sources,
)
from tests.component.account.test_account_owner_assignment_evidence_v4_repository import (
    _append_graph,
    _seed,
)

pytest_plugins = [
    "tests.component.account.test_account_owner_assignment_evidence_v4_repository",
]


@pytest.fixture
def owner_alias(assignment_alias: str) -> Iterator[str]:
    connection = connections[assignment_alias]
    models = (OwnerTenantAuthorityV2Model, OwnerTenantAuthorityV2RevocationModel)
    with connection.schema_editor() as editor:
        for model in models:
            editor.create_model(model)
    try:
        yield assignment_alias
    finally:
        with connection.schema_editor() as editor:
            for model in reversed(models):
                editor.delete_model(model)


def _owner_seed(alias, monkeypatch):
    parent = _seed(alias, monkeypatch)
    _append_graph(DjangoAccountOwnerAssignmentEvidenceV4Repository(using=alias), parent)
    evidence = parent.evidence
    root = OwnerTenantAuthorityV2(
        authority_id="local-owner-decision",
        authority_version="v2.1",
        assignment=evidence,
        policy=evidence.policy,
        approved_by=replace(evidence.claimant, role=APPROVER_ROLE),
        approved_at=evidence.recorded_at,
        recorded_at=evidence.recorded_at,
        valid_until=evidence.policy.valid_until,
    )
    return PersistedOwnerTenantAuthorityV2(root, parent.authority)


def _append_owner(repository, record):
    with repository.atomic():
        return repository.append_root(record, recorded_at=record.authority.recorded_at)


def _revocation(record, *, reason="owner-request"):
    root = record.authority
    clock = root.recorded_at + timedelta(seconds=1)
    return PersistedOwnerTenantAuthorityV2Revocation(
        OwnerTenantAuthorityV2Revocation(
            authority_content_hash=root.content_hash,
            policy_content_hash=root.policy.content_hash,
            revoked_by=replace(root.approved_by, role=REVOKER_ROLE),
            revoked_at=clock,
            recorded_at=clock,
            reason=reason,
        ),
        record.authentication,
    )


def _append_revocation(repository, record):
    with repository.atomic():
        return repository.append_revocation(
            record,
            expected_authority_content_hash=record.revocation.authority_content_hash,
            recorded_at=record.revocation.recorded_at,
        )


def _winner(repository, record, *, as_of=None):
    root = record.authority
    return repository.get_winner(
        authority_id=root.authority_id,
        authority_version=root.authority_version,
        as_of=as_of or root.recorded_at,
    )


def test_whole_graph_replay_cutoffs_and_same_alias_outer_rollback(owner_alias, monkeypatch):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV2Repository(using=owner_alias)
    root = record.authority
    revoked = _revocation(record)
    monkeypatch.setattr("django.utils.timezone.now", lambda: revoked.revocation.recorded_at)
    with pytest.raises(RuntimeError, match="rollback owner graph"):
        with transaction.atomic(using=owner_alias):
            assert _append_owner(repository, record) == record
            assert _append_revocation(repository, revoked) == revoked
            raise RuntimeError("rollback owner graph")
    assert OwnerTenantAuthorityV2Model.objects.using(owner_alias).count() == 0
    assert OwnerTenantAuthorityV2RevocationModel.objects.using(owner_alias).count() == 0
    assert AccountOwnerAssignmentEvidenceV4Model.objects.using(owner_alias).count() == 1

    def reject_default_query(execute, sql, params, many, context):
        raise AssertionError("owner repository queried default alias")

    with connections["default"].execute_wrapper(reject_default_query):
        assert _append_owner(repository, record) == _append_owner(repository, record) == record
        assert _winner(repository, record) == record
        assert (
            _winner(repository, record, as_of=root.recorded_at - timedelta(microseconds=1)) is None
        )
        monkeypatch.setattr(
            "django.utils.timezone.now", lambda: root.valid_until + timedelta(days=1)
        )
        assert repository.get_head(authority_id=root.authority_id, as_of=root.valid_until) == record
        assert (
            repository.get_assignment_head(
                assignment_content_hash=root.assignment.content_hash, as_of=root.valid_until
            )
            == record
        )
        assert root.valid_until > record.authentication.valid_until
        assert _append_revocation(repository, revoked) == _append_revocation(repository, revoked)
        assert (
            repository.get_revocation(
                authority_content_hash=root.content_hash, as_of=root.recorded_at
            )
            is None
        )
        assert (
            repository.get_revocation(
                authority_content_hash=root.content_hash, as_of=revoked.revocation.recorded_at
            )
            == revoked
        )
        assert _winner(repository, record, as_of=root.valid_until + timedelta(days=1)) == record
    assert OwnerTenantAuthorityV2Model.objects.using(owner_alias).get().status == "active"


def test_permanent_slots_revocation_cas_and_future_persistence_rejection(owner_alias, monkeypatch):
    record = _owner_seed(owner_alias, monkeypatch)
    record = replace(
        record,
        authority=replace(
            record.authority,
            valid_until=record.authority.recorded_at + timedelta(seconds=1),
            content_hash="",
        ),
    )
    repository = DjangoOwnerTenantAuthorityV2Repository(using=owner_alias)
    root = record.authority
    _append_owner(repository, record)
    for changed in (
        replace(root, authority_id="second-root", identity_hash="", content_hash=""),
        replace(root, authority_version="v2.2", identity_hash="", content_hash=""),
    ):
        with pytest.raises(OwnerTenantAuthorityV2Conflict):
            _append_owner(repository, replace(record, authority=changed))
    monkeypatch.setattr(
        "django.utils.timezone.now", lambda: root.recorded_at - timedelta(seconds=1)
    )
    with pytest.raises((OwnerTenantAuthorityV2Conflict, OwnerTenantAuthorityV2Corruption)):
        _append_owner(repository, record)
    revoked = _revocation(record)
    assert not root.is_current_at(revoked.revocation.recorded_at)
    monkeypatch.setattr("django.utils.timezone.now", lambda: revoked.revocation.recorded_at)
    _append_revocation(repository, revoked)
    with pytest.raises(OwnerTenantAuthorityV2Conflict):
        _append_revocation(repository, _revocation(record, reason="different-reason"))
    with pytest.raises((OwnerTenantAuthorityV2Conflict, OwnerTenantAuthorityV2Corruption)):
        with repository.atomic():
            repository.append_revocation(
                revoked,
                expected_authority_content_hash="f" * 64,
                recorded_at=revoked.revocation.recorded_at,
            )
    assert OwnerTenantAuthorityV2Model.objects.using(owner_alias).count() == 1
    assert OwnerTenantAuthorityV2RevocationModel.objects.using(owner_alias).count() == 1


def test_closed_world_detects_payload_headers_parent_and_revocation_tamper(
    owner_alias, monkeypatch
):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV2Repository(using=owner_alias)
    _append_owner(repository, record)
    revoked = _revocation(record)
    monkeypatch.setattr("django.utils.timezone.now", lambda: revoked.revocation.recorded_at)
    _append_revocation(repository, revoked)
    root_table = OwnerTenantAuthorityV2Model._meta.db_table
    revocation_table = OwnerTenantAuthorityV2RevocationModel._meta.db_table
    parent_table = AccountOwnerAssignmentEvidenceV4Model._meta.db_table
    attacks = (
        (root_table, "record_seal = %s", ["a" * 64]),
        (root_table, "ledger_seal = %s", ["b" * 64]),
        (root_table, "tenant_id = %s", ["other-tenant"]),
        (root_table, "policy_content_hash = %s", ["c" * 64]),
        (root_table, "assignment_id = %s", [999999]),
        (root_table, "policy_id = %s", [999999]),
        (root_table, "actor_source_id = %s", [999999]),
        (
            root_table,
            "canonical_payload = jsonb_set(canonical_payload, '{authentication,user_id}', '999')",
            [],
        ),
        (
            root_table,
            "canonical_payload = jsonb_set(canonical_payload, '{authority,assignment,content_hash}', '\"changed\"')",
            [],
        ),
        (parent_table, "ledger_seal = %s", ["d" * 64]),
        (revocation_table, "reason = %s", ["substituted-reason"]),
        (revocation_table, "ledger_seal = %s", ["e" * 64]),
        (revocation_table, "authority_id = %s", [999999]),
        (
            revocation_table,
            "canonical_payload = jsonb_set(canonical_payload, '{revocation,policy_content_hash}', '\"changed\"')",
            [],
        ),
    )
    for table, expression, params in attacks:
        with transaction.atomic(using=owner_alias):
            with connections[owner_alias].cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                cursor.execute(f'UPDATE "{table}" SET {expression}', params)
            with pytest.raises(OwnerTenantAuthorityV2Corruption):
                repository.get_winner(
                    authority_id="unrelated-selector",
                    authority_version="none",
                    as_of=revoked.revocation.recorded_at,
                )
            transaction.set_rollback(True, using=owner_alias)
    assert _winner(repository, record) == record


def test_append_only_guards_and_source_lock_isolation(owner_alias, monkeypatch):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV2Repository(using=owner_alias)
    _append_owner(repository, record)
    rows = OwnerTenantAuthorityV2Model.objects.using(owner_alias)
    row = rows.get()
    for operation in (
        lambda: rows.update(status="revoked"),
        lambda: rows.delete(),
        lambda: rows.bulk_create([OwnerTenantAuthorityV2Model()]),
        lambda: row.save(using=owner_alias),
        lambda: row.save_base(using=owner_alias),
        lambda: OwnerTenantAuthorityV2RevocationModel.objects.using(owner_alias).create(),
    ):
        with pytest.raises(ValidationError):
            operation()
    with repository.atomic():
        with pytest.raises(OwnerTenantAuthorityV2Conflict):
            with repository.atomic():
                pass
    with pytest.raises(OwnerTenantAuthorityV2Unavailable):
        lock_owner_tenant_authority_v2_sources(
            using=owner_alias, policy_id=record.authority.policy.policy_id
        )
    with transaction.atomic(using=owner_alias):
        with connections[owner_alias].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(OwnerTenantAuthorityV2Unavailable, match="READ COMMITTED"):
            _append_owner(repository, record)


def test_competing_decision_writer_and_parent_row_lock_fail_then_retry(owner_alias, monkeypatch):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV2Repository(using=owner_alias)
    competing = "evid07_owner_v2_competing"
    assert competing not in connections.databases
    connections.databases[competing] = deepcopy(connections.databases[owner_alias])
    try:
        other = DjangoOwnerTenantAuthorityV2Repository(using=competing)
        with transaction.atomic(using=owner_alias):
            assert _append_owner(repository, record) == record
            with pytest.raises(OwnerTenantAuthorityV2Unavailable):
                _append_owner(other, record)
        assert _append_owner(other, record) == record
        with transaction.atomic(using=competing):
            AccountOwnerAssignmentEvidenceV4Model.objects.using(competing).select_for_update().get()
            with pytest.raises(OwnerTenantAuthorityV2Unavailable):
                _append_owner(repository, record)
        assert _append_owner(repository, record) == record
        assert OwnerTenantAuthorityV2Model.objects.using(owner_alias).count() == 1
    finally:
        connections[competing].close()
        connections.databases.pop(competing)
