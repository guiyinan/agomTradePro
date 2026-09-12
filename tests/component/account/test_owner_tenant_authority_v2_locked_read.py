"""Verify callback source locks using two actual local PostgreSQL connections."""

from copy import deepcopy

import pytest
from django.db import DatabaseError, connections, transaction

from apps.account.application.owner_tenant_authority_v2 import (
    GetCurrentOwnerTenantAuthorityV2Command,
    IssueOwnerTenantAuthorityV2Command,
)
from apps.account.infrastructure.owner_tenant_authority_v2_models import (
    OwnerTenantAuthorityV2Model,
)
from tests.component.account.test_owner_tenant_authority_v2_composition import (
    _facade,
    _physical_fixture,
    _seed_live_compatible,
)

pytest_plugins = ["tests.component.account.test_owner_tenant_authority_v2_composition"]


def test_callback_keeps_actual_owner_locks_until_materialized_read_returns(
    owner_physical_alias, monkeypatch
):
    alias = owner_physical_alias
    record = _seed_live_compatible(alias, monkeypatch)
    _physical_fixture(alias, record)
    facade = _facade(alias, record)
    assignment = record.authority.assignment
    root = facade.issue(
        IssueOwnerTenantAuthorityV2Command(
            "locked-read-root",
            "v2.1",
            assignment.evidence_id,
            assignment.evidence_version,
            assignment.content_hash,
        )
    )
    competing = "evid07_owner_callback_competing"
    assert competing not in connections.databases
    connections.databases[competing] = deepcopy(connections.databases[alias])

    def competing_lock():
        with transaction.atomic(using=competing):
            with connections[competing].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '250ms'")
            return (
                OwnerTenantAuthorityV2Model.objects.using(competing)
                .select_for_update(nowait=True)
                .get()
                .content_hash
            )

    def read(current):
        assert connections[alias].in_atomic_block
        assert facade.unit_of_work_key == f"django:{alias}"
        with pytest.raises(DatabaseError) as blocked:
            competing_lock()
        assert getattr(blocked.value.__cause__, "sqlstate", None) == "55P03"
        # Eager same-alias query is completed before returning the immutable result.
        return tuple(
            OwnerTenantAuthorityV2Model.objects.using(alias).values_list("content_hash", flat=True)
        )

    try:
        result = facade.with_current(
            GetCurrentOwnerTenantAuthorityV2Command(
                root.authority_id, root.authority_version, root.content_hash
            ),
            read,
        )
        assert result == (root.content_hash,)
        assert competing_lock() == root.content_hash
    finally:
        connections[competing].close()
        connections.databases.pop(competing)
