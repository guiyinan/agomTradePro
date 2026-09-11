"""Compete with actual actor and creation parent row locks during receipt issuance."""

from queue import Queue
from threading import Event, Thread

import pytest
from django.db import connections, transaction

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentUnavailable,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
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
from tests.component.account.test_receipt_v4_locked_composition import _command, _issuer


def test_actor_and_binding_for_update_exclude_issuance_and_replay(receipt_alias, monkeypatch):
    record = _seed_record(receipt_alias, monkeypatch)
    issuer = _issuer(receipt_alias, record)
    command = _command(record)
    for model in (
        AccountOwnerAssignmentActorAuthoritySourceV3Model,
        CanonicalAccountCreationBindingV2Model,
    ):
        ready: Queue[BaseException | None] = Queue()
        release = Event()
        table = model._meta.db_table

        def hold_parent(table: str, ready: Queue[BaseException | None], release: Event):
            connection = connections[receipt_alias]
            try:
                with transaction.atomic(using=receipt_alias):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"SELECT id FROM {connection.ops.quote_name(table)} FOR UPDATE"
                        )
                        assert len(cursor.fetchall()) == 1
                    ready.put(None)
                    if not release.wait(30):
                        raise RuntimeError("parent lock release timed out")
            except BaseException as error:
                ready.put(error)
            finally:
                connection.close()

        worker = Thread(target=hold_parent, args=(table, ready, release))
        worker.start()
        try:
            assert ready.get(timeout=30) is None
            with pytest.raises(AccountOwnerAssignmentUnavailable):
                issuer.execute(command)
        finally:
            release.set()
            worker.join(timeout=30)
        assert not worker.is_alive()
        assert ready.empty()

        def reject_default_query(execute, sql, params, many, context):
            raise AssertionError("receipt issuance queried the default alias")

        with connections["default"].execute_wrapper(reject_default_query):
            assert issuer.execute(command).claimant.is_staff is True
