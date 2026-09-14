"""Contracts for the composition-owned Authority V3 read context."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from apps.account import account_owner_assignment_evidence_v5_composition as evidence_composition
from apps.account import owner_tenant_authority_v3_composition as composition
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
)
from apps.account.infrastructure.owner_tenant_authority_v3_read_context import (
    OwnerTenantAuthorityV3OperationReadContext,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from core.exceptions import ExternalServiceError
from shared.infrastructure.immutable_read_snapshot import reuse_immutable_read

_HASH = "a" * 64


def _principal() -> AuthenticatedAccountPrincipalV3:
    """Return one valid authenticated principal for composition construction."""

    return AuthenticatedAccountPrincipalV3(
        principal_id="principal-42",
        user_id=42,
        authentication_context_hash=_HASH,
        authenticated_at=datetime(2026, 8, 30, 10, tzinfo=UTC),
        valid_until=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )


def _binding() -> SingleOwnerPolicyBinding:
    """Return one valid server-owned policy binding."""

    return SingleOwnerPolicyBinding(
        policy_id="policy-42",
        policy_version="v1",
        expected_content_hash="b" * 64,
        tenant_id="tenant-42",
        owner_id="owner-42",
        account_namespace="account",
        account_id="account-42",
    )


@dataclass(frozen=True)
class _Connection:
    """Stable connection identity supplied to the operation context."""

    vendor = "postgresql"


class _ReadProbe:
    """Count exact reads while the production cache decorator is active."""

    def __init__(self) -> None:
        self.calls = 0

    @reuse_immutable_read("authority-v3-operation-context-test")
    def read(self, *, cutoff: datetime) -> object:
        """Return a distinct value for each uncached exact cutoff read."""

        del cutoff
        self.calls += 1
        return object()


def test_operation_context_reuses_one_cutoff_but_isolates_cutoffs_and_phases() -> None:
    """Reuse only exact reads inside one connection-bound operation phase."""

    connection = _Connection()
    current_connection = [connection]
    context = OwnerTenantAuthorityV3OperationReadContext(
        using="authority-v3",
        connection_provider=lambda: current_connection[0],
    )
    probe = _ReadProbe()
    cutoff = datetime(2026, 8, 30, 11, tzinfo=UTC)
    later = cutoff + timedelta(microseconds=1)

    assert context.is_active("authority-v3") is False
    with context.phase():
        first = probe.read(cutoff=cutoff)
        assert context.is_active("authority-v3") is True
        assert context.is_active("other-alias") is False
        assert probe.read(cutoff=cutoff) is first
        assert probe.read(cutoff=later) is not first
        current_connection[0] = _Connection()
        assert context.is_active("authority-v3") is False
        current_connection[0] = connection
        assert context.is_active("authority-v3") is True
    assert context.is_active("authority-v3") is False

    with context.phase():
        assert probe.read(cutoff=cutoff) is not first

    assert probe.calls == 3


def test_nested_evidence_facade_keeps_the_outer_operation_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nested V5 reads must not clear the V3 phase or its exact cache entries."""

    connection = _Connection()
    context = OwnerTenantAuthorityV3OperationReadContext(
        using="authority-v3",
        connection_provider=lambda: connection,
    )
    probe = _ReadProbe()

    class _Connections:
        """Resolve the one fake PostgreSQL connection used by this unit test."""

        def __getitem__(self, alias: str) -> _Connection:
            """Return the connection bound to the operation context."""

            assert alias == "authority-v3"
            return connection

    monkeypatch.setattr(evidence_composition, "connections", _Connections())
    source_locks: list[str] = []
    physical_locks: list[str] = []
    transactions: list[str] = []

    def atomic(*, using: str) -> object:
        transactions.append(using)
        return nullcontext()

    def lock_sources(**options: object) -> None:
        source_locks.append(str(options["using"]))

    monkeypatch.setattr(evidence_composition, "transaction", SimpleNamespace(atomic=atomic))
    monkeypatch.setattr(
        evidence_composition, "lock_account_owner_assignment_evidence_v5_sources", lock_sources
    )
    facade = evidence_composition.AccountOwnerAssignmentEvidenceV5Facade(
        using="authority-v3",
        policy_id="policy-42",
        actors=cast(object, SimpleNamespace(_uow=object())),
        approve=cast(object, object()),
        exact=cast(object, object()),
        current=cast(object, object()),
        physical_row_provider=cast(
            object, SimpleNamespace(lock_current_sources=lambda: physical_locks.append("physical"))
        ),
        repository=cast(DjangoAccountOwnerAssignmentEvidenceV5Repository, object()),
        read_context=context,
    )
    cutoff = datetime(2026, 8, 30, 11, tzinfo=UTC)

    with context.phase():
        first = facade._locked(lambda: probe.read(cutoff=cutoff))
        second = facade._locked(lambda: probe.read(cutoff=cutoff))

    assert second is first
    assert probe.calls == 1
    assert source_locks == ["authority-v3", "authority-v3"]
    assert physical_locks == ["physical", "physical"]
    assert transactions == ["authority-v3", "authority-v3"]


def test_closed_native_connection_cannot_start_a_reusable_phase() -> None:
    """An absent native connection cannot own immutable source reuse."""

    context = OwnerTenantAuthorityV3OperationReadContext(
        using="authority-v3", connection_provider=lambda: None
    )
    with pytest.raises(ExternalServiceError):
        with context.phase():
            pytest.fail("closed native connection entered a reusable phase")
    assert context.is_active("authority-v3") is False


def test_native_connection_change_cannot_return_a_successful_phase() -> None:
    """Even cached work is rejected if its physical connection changes."""

    wrapper = SimpleNamespace(connection=object())
    context = OwnerTenantAuthorityV3OperationReadContext(
        using="authority-v3", connection_provider=lambda: wrapper.connection
    )
    with pytest.raises(ExternalServiceError):
        with context.phase():
            assert context.is_active("authority-v3") is True
            wrapper.connection = object()
            assert context.is_active("authority-v3") is False
    assert context.is_active("authority-v3") is False


def test_composition_injects_one_shared_v5_graph_for_authority_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Share V5 parent repositories while keeping the public facade unchanged."""

    alias = "authority-v3-shared-operation-contract"
    facade = composition.build_owner_tenant_authority_v3_facade(
        principal=_principal(),
        policy_binding=_binding(),
        actor_source_id="actor-source-42",
        actor_source_version="v3",
        actor_source_content_hash="c" * 64,
        validity_period=timedelta(minutes=30),
        physical_row_provider=build_account_physical_row_v2_provider(using=alias),
        using=alias,
    )

    service = facade._service
    v3_repository = service._repository
    v5_facade = service._current_assignments._facade
    assert v3_repository._assignments is v5_facade._repository
    assert v3_repository._actors is v5_facade._actors
    assert v3_repository._policies is v5_facade._policies
    assert facade._actors is v5_facade._actors
    assert getattr(service._read_phase, "__self__", None) is v5_facade._read_context

    wrapper = SimpleNamespace(connection=object())
    monkeypatch.setattr(composition, "connections", {alias: wrapper})
    context = v5_facade._read_context
    assert context is not None
    assert context._connection_provider() is wrapper.connection
