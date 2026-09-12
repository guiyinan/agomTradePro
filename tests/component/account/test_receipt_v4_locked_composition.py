"""Exercise locked issuance with real local actor publication and synthetic creation facts."""

from dataclasses import replace
from datetime import timedelta
from queue import Queue
from threading import Event, Thread

import pytest
from django.db import connections, transaction

from apps.account.account_owner_assignment_provenance_receipt_v4_composition import (
    build_account_owner_assignment_provenance_receipt_v4_issuer,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    IssueAccountOwnerAssignmentProvenanceReceiptV4Command,
    PersistedAccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_models import (
    AccountOwnerAssignmentProvenanceReceiptV4Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    _seed_record,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    creation_alias as creation_alias,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    evid06_alias as evid06_alias,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    receipt_alias as receipt_alias,
)


def _issuer(alias: str, record: PersistedAccountOwnerAssignmentProvenanceReceiptV4):
    authority = record.authority
    policy = record.receipt.policy
    return build_account_owner_assignment_provenance_receipt_v4_issuer(
        principal=AuthenticatedAccountPrincipalV3(
            authority.principal_id,
            authority.user_id,
            authority.authentication_context_hash,
            authority.recorded_at,
            authority.valid_until,
        ),
        policy_binding=SingleOwnerPolicyBinding(
            policy.policy_id,
            policy.policy_version,
            policy.content_hash,
            policy.tenant_id,
            policy.owner_id,
            policy.account_namespace,
            policy.account_id,
        ),
        actor_source_id=authority.source_id,
        actor_source_version=authority.source_version,
        actor_source_content_hash=authority.source_content_hash,
        validity_period=timedelta(minutes=4),
        using=alias,
    )


def _command(record: PersistedAccountOwnerAssignmentProvenanceReceiptV4):
    receipt = record.receipt
    return IssueAccountOwnerAssignmentProvenanceReceiptV4Command(
        receipt.receipt_id,
        receipt.receipt_version,
        receipt.binding.binding_id,
        receipt.binding.binding_version,
        receipt.binding.content_hash,
        receipt.binding.creation_root.content_hash,
    )


def test_locked_issue_replay_and_outer_rollback(receipt_alias, monkeypatch):
    record = _seed_record(receipt_alias, monkeypatch)
    issuer = _issuer(receipt_alias, record)
    command = _command(record)
    with pytest.raises(RuntimeError, match="rollback issuance"):
        with transaction.atomic(using=receipt_alias):
            issued = issuer.execute(command)
            assert issued.claimant.is_staff is True
            assert issued.policy == record.receipt.policy
            assert issued.valid_until == issued.issued_at + timedelta(minutes=4)
            raise RuntimeError("rollback issuance")
    assert AccountOwnerAssignmentProvenanceReceiptV4Model.objects.using(receipt_alias).count() == 0
    issued = issuer.execute(command)
    assert issuer.execute(command) == issued
    assert AccountOwnerAssignmentProvenanceReceiptV4Model.objects.using(receipt_alias).count() == 1


def test_locked_replay_rechecks_committed_policy_revocation(receipt_alias, monkeypatch):
    record = _seed_record(receipt_alias, monkeypatch)
    issuer = _issuer(receipt_alias, record)
    command = _command(record)
    issued = issuer.execute(command)
    now = issued.recorded_at + timedelta(seconds=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    revoked = replace(
        issued.policy,
        policy_version="revoked",
        observed_at=now,
        status="revoked",
        identity_hash="",
        content_hash="",
    )
    repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=receipt_alias)
    with repository.atomic():
        repository.append(policy=revoked, expected_previous_content_hash=issued.policy.content_hash)
    with pytest.raises(AccountOwnerAssignmentConflict, match="no longer"):
        issuer.execute(command)
    assert AccountOwnerAssignmentProvenanceReceiptV4Model.objects.using(receipt_alias).count() == 1


def test_parent_row_lock_competition_fails_without_waiting_and_retry_succeeds(
    receipt_alias, monkeypatch
):
    record = _seed_record(receipt_alias, monkeypatch)
    issuer = _issuer(receipt_alias, record)
    command = _command(record)
    # ROW SHARE is acquired by SELECT FOR UPDATE: SHARE alone would not exclude it.
    table = AccountOwnerAssignmentProvenanceReceiptV4Model._meta.db_table
    ready: Queue[BaseException | None] = Queue()
    release = Event()

    def hold_row_share():
        connection = connections[receipt_alias]
        try:
            with transaction.atomic(using=receipt_alias):
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"LOCK TABLE {connection.ops.quote_name(table)} IN ROW SHARE MODE"
                    )
                ready.put(None)
                if not release.wait(30):
                    raise RuntimeError("test lock release timed out")
        except BaseException as error:
            ready.put(error)
        finally:
            connection.close()

    worker = Thread(target=hold_row_share)
    worker.start()
    try:
        assert ready.get(timeout=30) is None
        with pytest.raises(AccountOwnerAssignmentUnavailable):
            issuer.execute(command)
        assert (
            AccountOwnerAssignmentProvenanceReceiptV4Model.objects.using(receipt_alias).count() == 0
        )
    finally:
        release.set()
        worker.join(timeout=30)
    assert not worker.is_alive()
    assert ready.empty()
    assert issuer.execute(command).claimant.is_staff is True


def test_repeatable_read_is_rejected_before_issuance(receipt_alias, monkeypatch):
    record = _seed_record(receipt_alias, monkeypatch)
    issuer = _issuer(receipt_alias, record)
    with transaction.atomic(using=receipt_alias):
        with connections[receipt_alias].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(AccountOwnerAssignmentUnavailable, match="READ COMMITTED"):
            issuer.execute(_command(record))
    assert AccountOwnerAssignmentProvenanceReceiptV4Model.objects.using(receipt_alias).count() == 0
