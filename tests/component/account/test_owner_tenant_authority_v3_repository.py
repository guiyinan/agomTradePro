"""Real PostgreSQL owner decisions over durable local V5 provenance and actual auth."""

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connections, transaction

from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Conflict,
    OwnerTenantAuthorityV3Corruption,
    OwnerTenantAuthorityV3Unavailable,
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    APPROVER_ROLE,
    REVOKER_ROLE,
    OwnerTenantAuthorityV3,
    OwnerTenantAuthorityV3Revocation,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentEvidenceV5Model,
)
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
)
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    DjangoOwnerTenantAuthorityV3Repository,
    lock_owner_tenant_authority_v3_sources,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_models import (
    SimulatedAccountRowSourceV2Model,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from tests.component.account.test_account_owner_assignment_evidence_v5_repository import (
    _seed,
)
from tests.component.simulated_trading.test_simulated_account_row_source_v2_repository import (
    _source as _simulated_source,
)

pytest_plugins = [
    "tests.component.account.test_account_owner_assignment_evidence_v5_repository",
]


@pytest.fixture
def owner_alias(evidence_v5_alias: str) -> Iterator[str]:
    connection = connections[evidence_v5_alias]
    models = (
        OwnerTenantAuthorityV3Model,
        OwnerTenantAuthorityV3RevocationModel,
        SimulatedAccountRowSourceV2Model,
    )
    with connection.schema_editor() as editor:
        for model in models:
            editor.create_model(model)
    try:
        yield evidence_v5_alias
    finally:
        with connection.schema_editor() as editor:
            for model in reversed(models):
                editor.delete_model(model)


def _owner_seed(
    alias: str,
    monkeypatch: object,
    *,
    actor_source: AccountOwnerAssignmentActorAuthoritySourceV3 | None = None,
) -> PersistedOwnerTenantAuthorityV3:
    """Persist V5 parents and select either historical or real current actor facts."""
    del monkeypatch
    parent = _seed(alias, actor_source=actor_source)
    assignments = DjangoAccountOwnerAssignmentEvidenceV5Repository(using=alias)
    with assignments.atomic():
        assignments.append_root(
            parent,
            expected_account_head_hash=None,
            expected_underlying_head_hash=None,
            recorded_at=parent.evidence.recorded_at,
        )
    evidence = parent.evidence
    root = OwnerTenantAuthorityV3(
        authority_id="local-owner-decision",
        authority_version="v3.1",
        assignment=evidence,
        policy=evidence.policy,
        approved_by=replace(evidence.claimant, role=APPROVER_ROLE),
        approved_at=evidence.recorded_at,
        recorded_at=evidence.recorded_at,
        valid_until=evidence.policy.valid_until,
    )
    return PersistedOwnerTenantAuthorityV3(root, parent.authority)


def _append_owner(
    repository: DjangoOwnerTenantAuthorityV3Repository,
    record: PersistedOwnerTenantAuthorityV3,
) -> PersistedOwnerTenantAuthorityV3:
    with repository.atomic():
        return repository.append(
            record,
            expected_predecessor_hash=record.authority.supersedes_content_hash,
            recorded_at=record.authority.recorded_at,
        )


def _successor(
    record: PersistedOwnerTenantAuthorityV3,
    *,
    version: str = "v3.2",
) -> PersistedOwnerTenantAuthorityV3:
    """Build one immutable Authority V3 successor over the exact predecessor."""

    predecessor = record.authority
    successor_clock = predecessor.recorded_at + timedelta(seconds=1)
    successor = replace(
        predecessor,
        authority_version=version,
        approved_at=successor_clock,
        recorded_at=successor_clock,
        supersedes_content_hash=predecessor.content_hash,
        identity_hash="",
        content_hash="",
    )
    return PersistedOwnerTenantAuthorityV3(successor, record.authentication)


def _revocation(
    record: PersistedOwnerTenantAuthorityV3,
    *,
    reason: str = "owner-request",
) -> PersistedOwnerTenantAuthorityV3Revocation:
    root = record.authority
    clock = root.recorded_at + timedelta(seconds=1)
    return PersistedOwnerTenantAuthorityV3Revocation(
        OwnerTenantAuthorityV3Revocation(
            authority_content_hash=root.content_hash,
            policy_content_hash=root.policy.content_hash,
            revoked_by=replace(root.approved_by, role=REVOKER_ROLE),
            revoked_at=clock,
            recorded_at=clock,
            reason=reason,
        ),
        record.authentication,
    )


def _append_revocation(
    repository: DjangoOwnerTenantAuthorityV3Repository,
    record: PersistedOwnerTenantAuthorityV3Revocation,
) -> PersistedOwnerTenantAuthorityV3Revocation:
    with repository.atomic():
        return repository.append_revocation(
            record,
            expected_authority_content_hash=record.revocation.authority_content_hash,
            recorded_at=record.revocation.recorded_at,
        )


def _winner(
    repository: DjangoOwnerTenantAuthorityV3Repository,
    record: PersistedOwnerTenantAuthorityV3,
    *,
    as_of: datetime | None = None,
) -> PersistedOwnerTenantAuthorityV3 | None:
    root = record.authority
    return repository.get_winner(
        authority_id=root.authority_id,
        authority_version=root.authority_version,
        as_of=as_of or root.recorded_at,
    )


def test_whole_graph_replay_cutoffs_and_same_alias_outer_rollback(owner_alias, monkeypatch):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV3Repository(using=owner_alias)
    root = record.authority
    revoked = _revocation(record)
    monkeypatch.setattr("django.utils.timezone.now", lambda: revoked.revocation.recorded_at)
    with pytest.raises(RuntimeError, match="rollback owner graph"):
        with transaction.atomic(using=owner_alias):
            assert _append_owner(repository, record) == record
            assert _append_revocation(repository, revoked) == revoked
            raise RuntimeError("rollback owner graph")
    assert OwnerTenantAuthorityV3Model.objects.using(owner_alias).count() == 0
    assert OwnerTenantAuthorityV3RevocationModel.objects.using(owner_alias).count() == 0
    assert AccountOwnerAssignmentEvidenceV5Model.objects.using(owner_alias).count() == 1

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
        assert root.valid_until <= record.authentication.valid_until
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
    assert OwnerTenantAuthorityV3Model.objects.using(owner_alias).get().status == "active"


def test_successor_chain_cas_heads_historical_winner_and_final_head_revocation(
    owner_alias: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist one root and successor, then revoke only the final chain head."""

    root_record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV3Repository(using=owner_alias)
    root = _append_owner(repository, root_record)
    successor = _successor(root)

    assert (
        repository.get_provisional_winner(
            authority_id=root.authority.authority_id,
            authority_version=root.authority.authority_version,
            expected_content_hash=root.authority.content_hash,
            as_of=root.authority.recorded_at,
        )
        == root
    )
    assert (
        repository.get_provisional_winner(
            authority_id=root.authority.authority_id,
            authority_version=root.authority.authority_version,
            expected_content_hash="f" * 64,
            as_of=root.authority.recorded_at,
        )
        is None
    )

    with repository.atomic():
        with pytest.raises(OwnerTenantAuthorityV3Conflict, match="selector"):
            repository.append(
                successor,
                expected_predecessor_hash="f" * 64,
                recorded_at=successor.authority.recorded_at,
            )
    assert _append_owner(repository, successor) == successor
    assert _append_owner(repository, successor) == successor
    assert OwnerTenantAuthorityV3Model.objects.using(owner_alias).count() == 2

    root_clock = root.authority.recorded_at
    successor_clock = successor.authority.recorded_at
    assert repository.get_head(authority_id=root.authority.authority_id, as_of=root_clock) == root
    assert (
        repository.get_head(
            authority_id=root.authority.authority_id,
            as_of=successor_clock,
        )
        == successor
    )
    assert (
        repository.get_assignment_head(
            assignment_content_hash=root.authority.assignment.content_hash,
            as_of=successor_clock,
        )
        == successor
    )
    assert _winner(repository, root, as_of=successor_clock) == root

    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="final head"):
        _append_revocation(repository, _revocation(root))
    revoked = _revocation(successor)
    monkeypatch.setattr("django.utils.timezone.now", lambda: revoked.revocation.recorded_at)
    assert _append_revocation(repository, revoked) == revoked

    with pytest.raises(OwnerTenantAuthorityV3Conflict, match="revoked head"):
        _append_owner(repository, _successor(successor, version="v3.3"))
    assert (
        repository.get_revocation(
            authority_content_hash=successor.authority.content_hash,
            as_of=revoked.revocation.recorded_at,
        )
        == revoked
    )


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
    repository = DjangoOwnerTenantAuthorityV3Repository(using=owner_alias)
    root = record.authority
    _append_owner(repository, record)
    for changed in (
        replace(root, authority_id="second-root", identity_hash="", content_hash=""),
        replace(root, authority_version="v3.2", identity_hash="", content_hash=""),
    ):
        with pytest.raises(OwnerTenantAuthorityV3Conflict):
            _append_owner(repository, replace(record, authority=changed))
    monkeypatch.setattr(
        "django.utils.timezone.now", lambda: root.recorded_at - timedelta(seconds=1)
    )
    with pytest.raises((OwnerTenantAuthorityV3Conflict, OwnerTenantAuthorityV3Corruption)):
        _append_owner(repository, record)
    revoked = _revocation(record)
    assert not root.is_current_at(revoked.revocation.recorded_at)
    monkeypatch.setattr("django.utils.timezone.now", lambda: revoked.revocation.recorded_at)
    _append_revocation(repository, revoked)
    with pytest.raises(OwnerTenantAuthorityV3Conflict):
        _append_revocation(repository, _revocation(record, reason="different-reason"))
    with pytest.raises((OwnerTenantAuthorityV3Conflict, OwnerTenantAuthorityV3Corruption)):
        with repository.atomic():
            repository.append_revocation(
                revoked,
                expected_authority_content_hash="f" * 64,
                recorded_at=revoked.revocation.recorded_at,
            )
    assert OwnerTenantAuthorityV3Model.objects.using(owner_alias).count() == 1
    assert OwnerTenantAuthorityV3RevocationModel.objects.using(owner_alias).count() == 1


def test_closed_world_detects_payload_headers_parent_and_revocation_tamper(
    owner_alias, monkeypatch
):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV3Repository(using=owner_alias)
    _append_owner(repository, record)
    revoked = _revocation(record)
    monkeypatch.setattr("django.utils.timezone.now", lambda: revoked.revocation.recorded_at)
    _append_revocation(repository, revoked)
    root_table = OwnerTenantAuthorityV3Model._meta.db_table
    revocation_table = OwnerTenantAuthorityV3RevocationModel._meta.db_table
    parent_table = AccountOwnerAssignmentEvidenceV5Model._meta.db_table
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
            with pytest.raises(OwnerTenantAuthorityV3Corruption):
                repository.get_winner(
                    authority_id="unrelated-selector",
                    authority_version="none",
                    as_of=revoked.revocation.recorded_at,
                )
            transaction.set_rollback(True, using=owner_alias)
    assert _winner(repository, record) == record


def test_closed_world_rejects_successor_predecessor_substitution(owner_alias, monkeypatch):
    """Reject a self-linked successor before a forged chain can become a head."""

    root = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV3Repository(using=owner_alias)
    _append_owner(repository, root)
    successor = _successor(root)
    _append_owner(repository, successor)
    successor_row = OwnerTenantAuthorityV3Model.objects.using(owner_alias).get(
        content_hash=successor.authority.content_hash
    )
    table = OwnerTenantAuthorityV3Model._meta.db_table

    with transaction.atomic(using=owner_alias):
        with connections[owner_alias].cursor() as cursor:
            cursor.execute(
                f'UPDATE "{table}" SET predecessor_id = %s WHERE id = %s',
                [successor_row.pk, successor_row.pk],
            )
        with pytest.raises(
            OwnerTenantAuthorityV3Corruption,
            match="ledger_seal|predecessor|successor",
        ):
            repository.get_head(
                authority_id=root.authority.authority_id,
                as_of=successor.authority.recorded_at,
            )
        transaction.set_rollback(True, using=owner_alias)

    assert (
        repository.get_head(
            authority_id=root.authority.authority_id,
            as_of=successor.authority.recorded_at,
        )
        == successor
    )


def test_append_only_guards_and_source_lock_isolation(owner_alias, monkeypatch):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV3Repository(using=owner_alias)
    _append_owner(repository, record)
    rows = OwnerTenantAuthorityV3Model.objects.using(owner_alias)
    row = rows.get()
    for operation in (
        lambda: rows.update(status="revoked"),
        lambda: rows.delete(),
        lambda: rows.bulk_create([OwnerTenantAuthorityV3Model()]),
        lambda: row.save(using=owner_alias),
        lambda: row.save_base(using=owner_alias),
        lambda: OwnerTenantAuthorityV3RevocationModel.objects.using(owner_alias).create(),
    ):
        with pytest.raises(ValidationError):
            operation()
    with repository.atomic():
        with pytest.raises(OwnerTenantAuthorityV3Conflict):
            with repository.atomic():
                pass
    with pytest.raises(OwnerTenantAuthorityV3Unavailable):
        lock_owner_tenant_authority_v3_sources(
            using=owner_alias, policy_id=record.authority.policy.policy_id
        )
    with transaction.atomic(using=owner_alias):
        with connections[owner_alias].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(OwnerTenantAuthorityV3Unavailable, match="READ COMMITTED"):
            _append_owner(repository, record)


def test_competing_decision_writer_and_parent_row_lock_fail_then_retry(owner_alias, monkeypatch):
    record = _owner_seed(owner_alias, monkeypatch)
    repository = DjangoOwnerTenantAuthorityV3Repository(using=owner_alias)
    competing = "evid07_owner_v3_competing"
    assert competing not in connections.databases
    connections.databases[competing] = deepcopy(connections.databases[owner_alias])
    try:
        other = DjangoOwnerTenantAuthorityV3Repository(using=competing)
        with transaction.atomic(using=owner_alias):
            assert _append_owner(repository, record) == record
            with pytest.raises(OwnerTenantAuthorityV3Unavailable):
                _append_owner(other, record)
        assert _append_owner(other, record) == record
        with transaction.atomic(using=competing):
            AccountOwnerAssignmentEvidenceV5Model.objects.using(competing).select_for_update().get()
            with pytest.raises(OwnerTenantAuthorityV3Unavailable):
                _append_owner(repository, record)
        assert _append_owner(repository, record) == record
        assert OwnerTenantAuthorityV3Model.objects.using(owner_alias).count() == 1
    finally:
        connections[competing].close()
        connections.databases.pop(competing)


def test_current_source_lock_blocks_competing_simulated_successor(owner_alias):
    """Keep cached Account projections bound to one stable simulated source head."""

    root = _simulated_source()
    successor = _simulated_source(
        source_version="mutation-2",
        row_updated_at=root.row_updated_at + timedelta(minutes=1),
        observed_at=root.observed_at + timedelta(minutes=2),
        recorded_at=root.recorded_at + timedelta(minutes=3),
        raw_observation_supersedes_content_hash=root.raw_observation_content_hash,
        supersedes_content_hash=root.content_hash,
    )
    repository = DjangoSimulatedAccountRowSourceV2Repository(using=owner_alias)
    with repository.atomic():
        repository.append(
            PersistedSimulatedAccountRowSourceV2(root),
            expected_predecessor_hash=None,
            recorded_at=root.recorded_at,
        )
    competing = "evid07_owner_v3_simulated_competing"
    connections.databases[competing] = deepcopy(connections.databases[owner_alias])
    try:
        other = DjangoSimulatedAccountRowSourceV2Repository(using=competing)
        with transaction.atomic(using=owner_alias):
            repository.lock_current_sources()
            with pytest.raises(DatabaseError) as blocked:
                with other.atomic():
                    with connections[competing].cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '250ms'")
                    other.append(
                        PersistedSimulatedAccountRowSourceV2(successor),
                        expected_predecessor_hash=root.content_hash,
                        recorded_at=successor.recorded_at,
                    )
            assert getattr(blocked.value.__cause__, "sqlstate", None) == "55P03"
        with other.atomic():
            assert (
                other.append(
                    PersistedSimulatedAccountRowSourceV2(successor),
                    expected_predecessor_hash=root.content_hash,
                    recorded_at=successor.recorded_at,
                ).source
                == successor
            )
    finally:
        connections[competing].close()
        connections.databases.pop(competing)
