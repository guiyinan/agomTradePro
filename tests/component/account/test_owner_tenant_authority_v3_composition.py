"""Component contracts for the authenticated Authority V3 composition root."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from django.db import connections

from apps.account import owner_tenant_authority_v3_composition as composition
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    GetCurrentAccountOwnerAssignmentEvidenceV5,
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
    GetExactOwnerTenantAuthorityV3Command,
    IssueOwnerTenantAuthorityV3Command,
    RevokeOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Unavailable,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from apps.account.domain.validation_graph import reuse_validated_decode
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.immutable_read_snapshot import reuse_immutable_read
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    DjangoOwnerTenantAuthorityV3Repository,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from tests.component.account.test_owner_tenant_authority_v3_repository import (
    owner_alias as owner_alias,
)

pytest_plugins = [
    "tests.component.account.test_owner_tenant_authority_v3_repository",
]

_AS_OF = datetime(2026, 8, 30, 11, tzinfo=UTC)
_HASH = "a" * 64


def _principal() -> AuthenticatedAccountPrincipalV3:
    """Return valid server-owned principal facts for composition tests."""

    return AuthenticatedAccountPrincipalV3(
        principal_id="principal-42",
        user_id=42,
        authentication_context_hash=_HASH,
        authenticated_at=datetime(2026, 8, 30, 10, tzinfo=UTC),
        valid_until=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )


def _binding() -> SingleOwnerPolicyBinding:
    """Return a valid server-owned single-owner policy binding."""

    return SingleOwnerPolicyBinding(
        policy_id="policy-42",
        policy_version="v1",
        expected_content_hash="b" * 64,
        tenant_id="tenant-42",
        owner_id="owner-42",
        account_namespace="account",
        account_id="account-42",
    )


class _PostgreSQLConnection:
    """Minimal connection view used to isolate facade transaction ordering."""

    def __init__(self, vendor: str = "postgresql") -> None:
        self.vendor = vendor


class _ConnectionRegistry:
    """Resolve exactly one fake PostgreSQL alias without touching Django state."""

    def __init__(self, vendor: str = "postgresql") -> None:
        self._connection = _PostgreSQLConnection(vendor)

    def __getitem__(self, alias: str) -> _PostgreSQLConnection:
        """Return the fake connection for the requested alias."""

        assert alias == "authority-v3"
        return self._connection


@contextmanager
def _record_context(events: list[str], name: str) -> Iterator[None]:
    """Record entry, rollback, and exit for one injected context manager."""

    events.append(f"{name}.enter")
    try:
        yield
    except BaseException:
        events.append(f"{name}.rollback")
        raise
    finally:
        events.append(f"{name}.exit")


class _FakeActors:
    """Inject the actor UOW boundary required by the facade."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def atomic(self) -> AbstractContextManager[None]:
        """Return a context manager that records actor UOW ordering."""

        return _record_context(self._events, "actors")


class _FakeService:
    """Record one facade call and return configured values."""

    def __init__(self, events: list[str], current: object = "current") -> None:
        self._events = events
        self._current = current
        self.current_values: list[object] = []

    def issue(self, command: object) -> object:
        """Record the root use case call."""

        del command
        self._events.append("issue")
        return "issued"

    def supersede(self, command: object) -> object:
        """Record the supersede use case call."""

        del command
        self._events.append("supersede")
        return "superseded"

    def successor(self, command: object) -> object:
        """Record the successor use case call."""

        del command
        self._events.append("successor")
        return "successor"

    def get_current(self, command: object) -> object:
        """Record a current read and return its next configured observation."""

        del command
        self._events.append("current")
        if self.current_values:
            return self.current_values.pop(0)
        return self._current

    def get_exact(self, command: object) -> object:
        """Record an exact historical read."""

        del command
        self._events.append("exact")
        return "exact"

    def revoke(self, command: object) -> object:
        """Record the immutable revocation use case call."""

        del command
        self._events.append("revoke")
        return "revoked"


class _LifecycleValidationProbeService(_FakeService):
    """Run one validation-graph probe before each Authority lifecycle call."""

    def __init__(
        self,
        events: list[str],
        probe: Callable[[], None],
        *,
        fail: bool = False,
    ) -> None:
        """Bind a probe and optionally fail after it has executed."""

        super().__init__(events)
        self._probe = probe
        self._fail = fail

    def _before(self) -> None:
        """Run the probe and optionally raise a lifecycle failure."""

        self._probe()
        if self._fail:
            raise RuntimeError("authority lifecycle probe failure")

    def issue(self, command: object) -> object:
        """Probe the root issue route."""

        self._before()
        return super().issue(command)

    def successor(self, command: object) -> object:
        """Probe the successor route."""

        self._before()
        return super().successor(command)

    def revoke(self, command: object) -> object:
        """Probe the revocation route."""

        self._before()
        return super().revoke(command)


@dataclass(frozen=True)
class _AuthorityProjection:
    """Small comparable authority projection for callback contract tests."""

    assignment: object = "assignment"
    policy: object = "policy"


@dataclass(frozen=True)
class _AuthenticationProjection:
    """Small comparable actor projection for callback contract tests."""

    source_content_hash: str = _HASH


@dataclass(frozen=True)
class _CurrentProjection:
    """Small current observation accepted through the typed facade seam."""

    observed_at: datetime
    valid_until: datetime
    authority: _AuthorityProjection
    authentication: _AuthenticationProjection


def _facade(
    events: list[str],
    *,
    vendor: str = "postgresql",
    service: _FakeService | None = None,
) -> composition.OwnerTenantAuthorityV3Facade:
    """Build an injectable facade for transaction and callback tests."""

    return composition.OwnerTenantAuthorityV3Facade(
        using="authority-v3",
        policy_id="policy-42",
        actors=cast(
            DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
            _FakeActors(events),
        ),
        service=cast(
            composition.OwnerTenantAuthorityV3Service,
            service or _FakeService(events),
        ),
        lock_current_physical_sources=lambda: events.append("lock-physical"),
    )


def _source_v2_for_physical(
    physical: PhysicalAccountRowObservationV2,
) -> SimulatedAccountRowSourceV2:
    """Rebuild the exact source-v2 row already sealed by the V5 parent graph."""

    return SimulatedAccountRowSourceV2(
        source_id=physical.source_id,
        source_version=physical.source_version,
        account_namespace=physical.account_namespace,
        account_id=physical.account_id,
        underlying_unified_account_namespace=physical.underlying_unified_account_namespace,
        underlying_unified_account_id=physical.underlying_unified_account_id,
        row_user_id=physical.row_user_id,
        raw_account_type=physical.raw_account_type,
        is_active=physical.is_active,
        row_created_at=physical.row_created_at,
        row_updated_at=physical.row_updated_at,
        is_present=physical.is_present,
        is_tombstone=physical.is_tombstone,
        observed_at=physical.source_observed_at,
        recorded_at=physical.source_recorded_at,
        source_valid_until=physical.source_valid_until,
        ttl_valid_until=physical.source_ttl_valid_until,
        valid_until=physical.source_effective_valid_until,
        raw_observation_id=physical.raw_observation_id,
        raw_observation_version=physical.raw_observation_version,
        raw_observation_identity_hash=physical.raw_observation_identity_hash,
        raw_observation_content_hash=physical.raw_observation_content_hash,
        raw_observation_observed_at=physical.raw_observation_observed_at,
        raw_observation_valid_until=physical.raw_observation_valid_until,
        raw_observation_supersedes_content_hash=physical.raw_observation_supersedes_content_hash,
        supersedes_content_hash=physical.source_supersedes_content_hash,
    )


def _append_source_v2_for_physical(
    alias: str,
    physical: PhysicalAccountRowObservationV2,
) -> SimulatedAccountRowSourceV2:
    """Populate the real provider ledger with the source sealed by Physical V2."""

    source = _source_v2_for_physical(physical)
    assert source.content_hash == physical.source_content_hash
    assert source.raw_observation_content_hash == physical.raw_observation_content_hash
    repository = DjangoSimulatedAccountRowSourceV2Repository(using=alias)
    with repository.atomic():
        persisted = repository.append(
            PersistedSimulatedAccountRowSourceV2(source),
            expected_predecessor_hash=None,
            recorded_at=source.recorded_at,
        )
    assert persisted.source == source
    return source


@pytest.mark.parametrize("method_name", ["issue", "successor", "revoke"])
def test_lifecycle_validation_cache_reuses_exact_decode_only_inside_operation(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    """Reuse one exact decode during each Authority lifecycle operation only."""

    events: list[str] = []
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry())

    @contextmanager
    def outer_atomic(*, using: str) -> Iterator[None]:
        """Record the outer same-alias transaction."""

        assert using == "authority-v3"
        yield

    monkeypatch.setattr(composition.transaction, "atomic", outer_atomic)
    monkeypatch.setattr(
        composition,
        "lock_owner_tenant_authority_v3_sources",
        lambda **kwargs: events.append("lock"),
    )

    calls = 0

    @reuse_validated_decode("authority-v3-lifecycle-test")
    def decode(payload: object) -> object:
        """Count exact payload decodes for one facade operation."""

        nonlocal calls
        del payload
        calls += 1
        return object()

    read_calls = 0

    class _ReadProbe:
        """Expose an immutable-read decorated method for write-path checks."""

        @reuse_immutable_read("authority-v3-write-read-test")
        def read(self) -> object:
            """Count immutable reads without activating their snapshot context."""

            nonlocal read_calls
            read_calls += 1
            return object()

    reader = _ReadProbe()

    def probe() -> None:
        """Probe validation reuse and immutable-read snapshot boundaries."""

        first = decode({"payload": "same"})
        second = decode({"payload": "same"})
        assert first is second
        first_read = reader.read()
        second_read = reader.read()
        assert first_read is not second_read

    facade = _facade(
        events,
        service=_LifecycleValidationProbeService(events, probe),
    )
    getattr(facade, method_name)(cast(object, object()))

    assert calls == 1
    assert read_calls == 2
    decode({"payload": "same"})
    assert calls == 2


def test_lifecycle_validation_cache_is_cleared_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not reuse a validation result after a failed Authority operation."""

    events: list[str] = []
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry())

    @contextmanager
    def outer_atomic(*, using: str) -> Iterator[None]:
        """Record the outer same-alias transaction."""

        assert using == "authority-v3"
        yield

    monkeypatch.setattr(composition.transaction, "atomic", outer_atomic)
    monkeypatch.setattr(
        composition,
        "lock_owner_tenant_authority_v3_sources",
        lambda **kwargs: events.append("lock"),
    )

    calls = 0

    @reuse_validated_decode("authority-v3-failing-lifecycle-test")
    def decode(payload: object) -> object:
        """Count exact payload decodes for the failing operation."""

        nonlocal calls
        del payload
        calls += 1
        return object()

    def probe() -> None:
        """Decode one exact JSON tree twice before the injected failure."""

        decode({"payload": "same"})
        decode({"payload": "same"})

    facade = _facade(
        events,
        service=_LifecycleValidationProbeService(events, probe, fail=True),
    )
    with pytest.raises(RuntimeError, match="probe failure"):
        facade.issue(cast(IssueOwnerTenantAuthorityV3Command, object()))

    assert calls == 1
    decode({"payload": "same"})
    assert calls == 2


def test_lifecycle_validation_cache_does_not_cross_changed_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require a second decode when an exact payload changes."""

    events: list[str] = []
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry())

    @contextmanager
    def outer_atomic(*, using: str) -> Iterator[None]:
        """Record the outer same-alias transaction."""

        assert using == "authority-v3"
        yield

    monkeypatch.setattr(composition.transaction, "atomic", outer_atomic)
    monkeypatch.setattr(
        composition,
        "lock_owner_tenant_authority_v3_sources",
        lambda **kwargs: events.append("lock"),
    )

    calls = 0

    @reuse_validated_decode("authority-v3-changed-payload-test")
    def decode(payload: object) -> object:
        """Count decodes for distinct exact JSON trees."""

        nonlocal calls
        del payload
        calls += 1
        return object()

    def probe() -> None:
        """Decode two different exact JSON trees."""

        first = decode({"payload": "same"})
        second = decode({"payload": "changed"})
        assert first is not second

    facade = _facade(
        events,
        service=_LifecycleValidationProbeService(events, probe),
    )
    facade.issue(cast(IssueOwnerTenantAuthorityV3Command, object()))

    assert calls == 2


def test_builder_binds_v3_service_evidence_facade_and_sources_to_one_alias() -> None:
    """Build the complete Authority V3 graph without opening a database."""

    alias = "authority-v3-composition-contract"
    assert alias not in connections.databases

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

    assert isinstance(facade, composition.OwnerTenantAuthorityV3Facade)
    assert facade._using == alias
    assert facade._policy_id == "policy-42"
    assert facade._actors._using == alias

    service = facade._service
    assert isinstance(service._repository, DjangoOwnerTenantAuthorityV3Repository)
    assert service._repository._using == alias
    assert service._current_assignments._facade._using == alias
    assert service._historical_assignments._facade._using == alias
    assert isinstance(
        service._current_assignments._facade, composition.AccountOwnerAssignmentEvidenceV5Facade
    )
    assert isinstance(
        service._current_assignments._facade._current, GetCurrentAccountOwnerAssignmentEvidenceV5
    )
    assert isinstance(
        service._current_assignments._facade._exact, GetExactAccountOwnerAssignmentEvidenceV5
    )

    participants = service._participants
    assert participants.binding == _binding()
    assert participants.policies._using == alias
    assert participants.actors.current_reader._repository._using == alias
    assert participants.actors.current_reader._inputs._using == alias
    assert alias not in connections.databases


def test_facade_orders_v5_v3_lock_then_actor_uow_for_every_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the outer lock order and all public lifecycle methods."""

    events: list[str] = []
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry())

    @contextmanager
    def outer_atomic(*, using: str) -> Iterator[None]:
        """Record the outer same-alias transaction."""

        assert using == "authority-v3"
        with _record_context(events, "outer"):
            yield

    def lock_sources(*, using: str, policy_id: str) -> None:
        """Record the combined V5 then Authority V3 source lock."""

        assert using == "authority-v3"
        assert policy_id == "policy-42"
        events.append("lock-v5-v3")

    monkeypatch.setattr(composition.transaction, "atomic", outer_atomic)
    monkeypatch.setattr(composition, "lock_owner_tenant_authority_v3_sources", lock_sources)
    facade = _facade(events)
    command = cast(object, object())

    assert facade.issue(cast(IssueOwnerTenantAuthorityV3Command, command)) == "issued"
    assert events == [
        "outer.enter",
        "lock-v5-v3",
        "actors.enter",
        "issue",
        "actors.exit",
        "outer.exit",
    ]

    for method, expected_call, expected_result in (
        (facade.supersede, "supersede", "superseded"),
        (facade.successor, "successor", "successor"),
        (facade.get_current, "current", "current"),
        (facade.get_exact, "exact", "exact"),
        (facade.revoke, "revoke", "revoked"),
    ):
        events.clear()
        result = method(cast(object, command))
        assert result == expected_result
        assert events == [
            "outer.enter",
            "lock-v5-v3",
            "actors.enter",
            *(["lock-physical"] if expected_call == "current" else []),
            expected_call,
            "actors.exit",
            "outer.exit",
        ]


def test_with_current_rechecks_authority_authentication_and_source_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discard a callback result when the second observation drifts."""

    events: list[str] = []
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry())

    @contextmanager
    def outer_atomic(*, using: str) -> Iterator[None]:
        """Record the callback transaction."""

        del using
        yield

    monkeypatch.setattr(composition.transaction, "atomic", outer_atomic)
    monkeypatch.setattr(
        composition,
        "lock_owner_tenant_authority_v3_sources",
        lambda **kwargs: events.append("lock"),
    )
    now = datetime(2026, 8, 30, 11, tzinfo=UTC)
    valid_until = now + timedelta(minutes=5)
    authority = _AuthorityProjection()
    authentication = _AuthenticationProjection()
    initial = _CurrentProjection(now, valid_until, authority, authentication)
    final = _CurrentProjection(now + timedelta(seconds=1), valid_until, authority, authentication)
    service = _FakeService(events)
    service.current_values = [initial, final]
    facade = _facade(events, service=service)

    result = facade.with_current(
        cast(GetCurrentOwnerTenantAuthorityV3Command, object()),
        lambda observation: (
            observation.authority.account_id
            if hasattr(observation.authority, "account_id")
            else "materialized-read"
        ),
    )
    assert result == "materialized-read"
    assert events == ["lock", "actors.enter", "current", "current", "actors.exit"]

    events.clear()
    drifted = _CurrentProjection(
        now + timedelta(seconds=1),
        valid_until,
        _AuthorityProjection(policy="drifted-policy"),
        authentication,
    )
    service.current_values = [initial, drifted]
    assert (
        facade.with_current(
            cast(GetCurrentOwnerTenantAuthorityV3Command, object()),
            lambda observation: observation,
        )
        is None
    )
    assert events == ["lock", "actors.enter", "current", "current", "actors.exit"]


def test_facade_rolls_back_outer_context_and_rejects_non_postgresql_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep callback failures atomic and reject unsupported aliases early."""

    events: list[str] = []
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry())

    @contextmanager
    def outer_atomic(*, using: str) -> Iterator[None]:
        """Record rollback of the injected outer transaction."""

        del using
        with _record_context(events, "outer"):
            yield

    monkeypatch.setattr(composition.transaction, "atomic", outer_atomic)
    monkeypatch.setattr(
        composition,
        "lock_owner_tenant_authority_v3_sources",
        lambda **kwargs: events.append("lock"),
    )
    facade = _facade(events)
    with pytest.raises(RuntimeError, match="composition rollback"):
        facade.with_current(
            cast(GetCurrentOwnerTenantAuthorityV3Command, object()),
            lambda observation: (_ for _ in ()).throw(RuntimeError("composition rollback")),
        )
    assert events == [
        "outer.enter",
        "lock",
        "actors.enter",
        "current",
        "actors.rollback",
        "actors.exit",
        "outer.rollback",
        "outer.exit",
    ]

    events.clear()
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry(vendor="sqlite"))
    monkeypatch.setattr(
        composition,
        "lock_owner_tenant_authority_v3_sources",
        lambda **kwargs: events.append("lock"),
    )
    with pytest.raises(OwnerTenantAuthorityV3Unavailable, match="PostgreSQL"):
        facade.issue(cast(IssueOwnerTenantAuthorityV3Command, object()))
    assert events == []


@pytest.mark.skipif(
    os.environ.get("AGOM_EVID06_POSTGRES_TEST") != "1",
    reason="opt-in disposable PostgreSQL Authority V3 composition test",
)
def test_opt_in_postgres_facade_issues_reads_and_revokes(
    owner_alias: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the complete authenticated facade against the disposable PG graph."""

    from tests.component.account.test_owner_tenant_authority_v3_repository import _owner_seed
    from tests.support.owner_authority_current_sources import seed_current_actor_source
    from tests.unit.account.test_account_owner_assignment_evidence_v5 import _evidence

    capture_at = datetime(2026, 8, 15, 14, 20, tzinfo=UTC)
    monkeypatch.setattr("django.utils.timezone.now", lambda: capture_at)
    actor_source = seed_current_actor_source(
        owner_alias, capture_at, _evidence().approval_valid_until + timedelta(minutes=1)
    )
    persisted = _owner_seed(owner_alias, monkeypatch, actor_source=actor_source)
    authority = persisted.authority
    authentication = persisted.authentication
    policy = authority.policy
    assignment = authority.assignment
    physical = assignment.reobservation.current_physical
    source = _append_source_v2_for_physical(owner_alias, physical)
    now = assignment.recorded_at + timedelta(minutes=1)
    assert now + timedelta(minutes=1) < min(
        assignment.valid_until, policy.valid_until, authentication.valid_until
    )
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    physical_provider = build_account_physical_row_v2_provider(using=owner_alias)
    facade = composition.build_owner_tenant_authority_v3_facade(
        principal=AuthenticatedAccountPrincipalV3(
            principal_id=authentication.principal_id,
            user_id=authentication.user_id,
            authentication_context_hash=authentication.authentication_context_hash,
            authenticated_at=actor_source.principal_authenticated_at,
            valid_until=actor_source.principal_valid_until,
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
        actor_source_id=authentication.source_id,
        actor_source_version=authentication.source_version,
        actor_source_content_hash=authentication.source_content_hash,
        validity_period=timedelta(hours=1),
        physical_row_provider=physical_provider,
        using=owner_alias,
    )
    assert source.is_current_at(now)
    current_source = physical_provider.get_exact_current(
        source_id=physical.source_id,
        source_version=physical.source_version,
        expected_content_hash=physical.source_content_hash,
        account_namespace=physical.account_namespace,
        account_id=physical.account_id,
        underlying_unified_account_namespace=physical.underlying_unified_account_namespace,
        underlying_unified_account_id=physical.underlying_unified_account_id,
        as_of=now,
    )
    assert current_source is not None
    assert current_source.content_hash == physical.source_content_hash
    assert current_source.account_id == physical.account_id
    assert current_source.underlying_unified_account_id == physical.underlying_unified_account_id
    current_evidence = facade._service._current_assignments._facade.get_current(
        GetCurrentAccountOwnerAssignmentEvidenceV5Command(
            assignment.evidence_id,
            assignment.evidence_version,
            assignment.content_hash,
            now,
        )
    )
    assert current_evidence == assignment
    issue = facade.issue(
        IssueOwnerTenantAuthorityV3Command(
            "composition-owner-root",
            "v3.1",
            assignment.evidence_id,
            assignment.evidence_version,
            assignment.content_hash,
        )
    )
    selector = GetCurrentOwnerTenantAuthorityV3Command(
        issue.authority_id,
        issue.authority_version,
        issue.content_hash,
    )
    observed = facade.get_current(selector)
    assert observed is not None and observed.authority == issue
    assert (
        facade.with_current(selector, lambda value: value.authority.content_hash)
        == issue.content_hash
    )
    facade.revoke(
        RevokeOwnerTenantAuthorityV3Command(
            issue.authority_id,
            issue.authority_version,
            issue.content_hash,
            "composition-test",
        )
    )
    assert facade.get_current(selector) is None
    historical = facade.get_exact(
        GetExactOwnerTenantAuthorityV3Command(
            issue.authority_id,
            issue.authority_version,
            issue.content_hash,
            now,
        )
    )
    assert historical == issue


def test_composition_source_has_no_v4_domain_http_or_execution_boundary() -> None:
    """Keep Authority V3 rooted in public Evidence V5 and read authority only."""

    source = Path(composition.__file__).read_text(encoding="utf-8")

    assert "account_owner_assignment_evidence_v4" not in source
    assert "apps.account.interface" not in source
    assert "broker_execution" not in source
    assert "lock_owner_tenant_authority_v3_sources" in source
    assert "build_account_owner_assignment_evidence_v5_facade" in source
