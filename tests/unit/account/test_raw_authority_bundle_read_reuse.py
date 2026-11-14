"""Exact raw worlds are reused only inside a stable native bundle read."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.infrastructure import (
    account_owner_assignment_actor_authority_bundle_provider as bundle,
)
from apps.account.infrastructure import account_user_authority_source_v3_repository as users
from apps.account.infrastructure.account_actor_authority_capture_snapshot import (
    DjangoAccountActorAuthorityCaptureBundleProviderV3,
)
from apps.account.infrastructure.account_system_audit_actor_authority_bundle_provider import (
    DjangoAccountSystemAuditActorAuthorityBundleProviderV3,
)
from apps.account.infrastructure.owner_tenant_authority_v3_read_context import (
    OwnerTenantAuthorityV3OperationReadContext,
)
from shared.infrastructure.immutable_read_snapshot import immutable_read_snapshot
from tests.unit.account.test_account_system_audit_actor_authority_bundle_provider import _Connection


@pytest.mark.parametrize("scope", ("held", "phase_only", "wrong_policy", "not_phase"))
def test_capture_raw_lock_reuse_requires_the_exact_outer_lock_scope(scope):
    connection = _Connection()
    context = OwnerTenantAuthorityV3OperationReadContext(
        using="default", connection_provider=lambda: connection.connection
    )
    provider = DjangoAccountActorAuthorityCaptureBundleProviderV3(
        require_capture_transaction=lambda: None,
        read_context=context,
        source_lock_policy_id="policy-42",
    )
    with (
        context.source_locks(
            policy_id="other" if scope == "wrong_policy" else "policy-42", acquire=lambda: None
        )
        if scope != "phase_only"
        else nullcontext()
    ):
        with context.phase() if scope != "not_phase" else nullcontext():
            with provider._snapshot(connection):
                pass
    statements = connection.cursor_value.statements
    if scope == "held":
        assert statements == []
    else:
        assert statements[0] == "SHOW transaction_isolation"
        assert statements[1].count('"account_') == 6


def test_capture_inherited_locks_never_replace_the_private_actor_uow():
    connection = _Connection()
    context = OwnerTenantAuthorityV3OperationReadContext(
        using="default", connection_provider=lambda: connection.connection
    )

    def unavailable():
        from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
        )

        raise AccountOwnerAssignmentActorAuthoritySourceV3Unavailable("no actor UOW")

    provider = DjangoAccountActorAuthorityCaptureBundleProviderV3(
        require_capture_transaction=unavailable,
        read_context=context,
        source_lock_policy_id="policy-42",
    )
    with context.source_locks(policy_id="policy-42", acquire=lambda: None), context.phase():
        with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable):
            provider._snapshot(connection)
    assert connection.cursor_value.statements == []


@pytest.fixture(params=("audit", "capture", "standalone"))
def raw_scope(request, monkeypatch):
    standalone = request.param == "standalone"
    connection = _Connection(in_atomic_block=not standalone, autocommit=standalone)
    connection.connection = object()
    if request.param == "audit":
        provider = DjangoAccountSystemAuditActorAuthorityBundleProviderV3()
    elif request.param == "capture":
        provider = DjangoAccountActorAuthorityCaptureBundleProviderV3(
            require_capture_transaction=lambda: None,
        )
    else:
        monkeypatch.setattr(bundle, "_atomic_for_alias", lambda using: nullcontext())
        provider = bundle.DjangoAccountActorAuthorityInputBundleProviderV3()
    reads = []
    state = {"broken": False}

    class Query:
        def using(self, alias):
            assert alias == "default"
            return self

        def all(self):
            return self

        def select_related(self, *fields):
            return self

        def order_by(self, key):
            assert key == "pk"
            reads.append(key)
            if state["broken"]:
                raise AccountActorAuthorityRawSourceV3Corruption("changed raw ledger")
            return ()

    for name in ("AccountUserAuthoritySourceV3AnchorModel", "AccountUserAuthoritySourceV3Model"):
        monkeypatch.setattr(users, name, SimpleNamespace(_base_manager=Query()))
    return provider, connection, users.DjangoAccountUserAuthoritySourceV3Repository(), reads, state


def test_raw_bundle_reuses_exact_world_and_restarts_at_the_next_snapshot(raw_scope):
    provider, connection, repository, reads, _ = raw_scope
    with provider._snapshot(connection):
        repository._closed_world(lock=False)
        repository._closed_world(lock=False)
    assert len(reads) == 2
    with provider._snapshot(connection):
        repository._closed_world(lock=False)
        repository._closed_world(lock=False)
    assert len(reads) == 4


def test_next_bundle_observes_raw_corruption_without_reusing_prior_success(raw_scope):
    provider, connection, repository, _, state = raw_scope
    with provider._snapshot(connection):
        repository._closed_world(lock=False)
    state["broken"] = True
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        with provider._snapshot(connection):
            repository._closed_world(lock=False)
    if type(provider) is bundle.DjangoAccountActorAuthorityInputBundleProviderV3:
        state["broken"] = False
        with immutable_read_snapshot():
            repository._closed_world(lock=False)
            state["broken"] = True
            with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
                with provider._snapshot(connection):
                    repository._closed_world(lock=False)


def test_bundle_rejects_replaced_physical_connection_before_returning_cached_work(raw_scope):
    provider, connection, repository, _, _ = raw_scope
    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable, match="connection"):
        with provider._snapshot(connection):
            repository._closed_world(lock=False)
            connection.connection = object()
            repository._closed_world(lock=False)


@pytest.mark.parametrize("capture", (False, True))
def test_raw_lock_connection_cannot_be_replaced_before_the_bundle_phase(capture):
    connection = _Connection()
    provider = (
        DjangoAccountActorAuthorityCaptureBundleProviderV3(require_capture_transaction=lambda: None)
        if capture
        else DjangoAccountSystemAuditActorAuthorityBundleProviderV3()
    )
    scope = provider._snapshot(connection)
    connection.connection = object()
    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable, match="connection"):
        with scope:
            pytest.fail("old connection locks cannot authorize reads on a new connection")
