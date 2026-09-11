"""Component contract coverage for the authenticated Evidence V5 composition."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from django.db import connections

from apps.account import account_owner_assignment_evidence_v5_composition as composition
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5Unavailable,
    ApproveAccountOwnerAssignmentEvidenceV5,
    ApproveAccountOwnerAssignmentEvidenceV5Command,
    GetCurrentAccountOwnerAssignmentEvidenceV5,
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5,
    GetExactAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    GetCurrentAccountOwnerAssignmentSubjectV5,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    GetCurrentCanonicalAccountOwnershipReobservationV1,
)
from apps.account.application.physical_account_row_observation_v2 import (
    GetCurrentPhysicalAccountRowObservationV2,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
)

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


def _approve_command() -> ApproveAccountOwnerAssignmentEvidenceV5Command:
    """Return the ID/hash-only approval command accepted by the facade."""

    return ApproveAccountOwnerAssignmentEvidenceV5Command(
        evidence_id="evidence-42",
        evidence_version="v5.1",
        subject_id="subject-42",
        subject_version="v5.1",
        expected_subject_content_hash=_HASH,
    )


def _exact_command() -> GetExactAccountOwnerAssignmentEvidenceV5Command:
    """Return an exact historical selector for facade orchestration tests."""

    return GetExactAccountOwnerAssignmentEvidenceV5Command(
        evidence_id="evidence-42",
        evidence_version="v5.1",
        expected_content_hash=_HASH,
        as_of=_AS_OF,
    )


def _current_command() -> GetCurrentAccountOwnerAssignmentEvidenceV5Command:
    """Return an exact current selector for facade orchestration tests."""

    return GetCurrentAccountOwnerAssignmentEvidenceV5Command(
        evidence_id="evidence-42",
        evidence_version="v5.1",
        expected_content_hash=_HASH,
        as_of=_AS_OF,
    )


def test_builder_binds_every_v5_reader_and_repository_to_one_alias() -> None:
    """Build the complete V5 graph without opening or falling back to a database."""

    alias = "evidence-v5-composition-contract"
    assert alias not in connections.databases

    facade = composition.build_account_owner_assignment_evidence_v5_facade(
        principal=_principal(),
        policy_binding=_binding(),
        actor_source_id="actor-source-42",
        actor_source_version="v3",
        actor_source_content_hash="c" * 64,
        validity_period=timedelta(minutes=30),
        using=alias,
    )

    assert isinstance(facade, composition.AccountOwnerAssignmentEvidenceV5Facade)
    assert facade._using == alias
    assert facade._policy_id == "policy-42"
    assert isinstance(
        facade._actors,
        DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
    )
    assert facade._actors._using == alias
    assert isinstance(facade._approve, ApproveAccountOwnerAssignmentEvidenceV5)
    assert isinstance(facade._exact, GetExactAccountOwnerAssignmentEvidenceV5)
    assert isinstance(facade._current, GetCurrentAccountOwnerAssignmentEvidenceV5)
    assert isinstance(facade._approve._repository, DjangoAccountOwnerAssignmentEvidenceV5Repository)

    participants = facade._approve._participants
    assert participants.policies._using == alias
    assert participants.actors.current_reader._repository._using == alias
    assert participants.actors.current_reader._inputs._using == alias

    subject_reader = facade._approve._subjects
    assert isinstance(subject_reader, GetCurrentAccountOwnerAssignmentSubjectV5)
    assert subject_reader._repository._using == alias
    receipt_reader = subject_reader._current_receipt_reader
    assert isinstance(receipt_reader, GetCurrentAccountOwnerAssignmentProvenanceReceiptV5)
    assert receipt_reader._repository._using == alias
    assert isinstance(receipt_reader._binding_reader, GetExactCanonicalAccountCreationBindingV2)
    assert receipt_reader._binding_reader._repository._using == alias
    assert isinstance(
        receipt_reader._reobservation_reader,
        GetCurrentCanonicalAccountOwnershipReobservationV1,
    )
    assert receipt_reader._reobservation_reader._repository._using == alias
    physical_reader = receipt_reader._reobservation_reader._current_physical_reader
    assert isinstance(physical_reader, GetCurrentPhysicalAccountRowObservationV2)
    assert physical_reader._repository._using == alias
    assert alias not in connections.databases


class _PostgreSQLConnection:
    """Minimal connection view used to isolate facade transaction ordering."""

    vendor = "postgresql"


class _ConnectionRegistry:
    """Resolve exactly one fake PostgreSQL alias without touching Django DB state."""

    def __init__(self, vendor: str = "postgresql") -> None:
        self._connection = _PostgreSQLConnection()
        self._connection.vendor = vendor

    def __getitem__(self, alias: str) -> _PostgreSQLConnection:
        """Return the fake connection for the requested alias."""

        assert alias == "evidence-v5"
        return self._connection


@contextmanager
def _record_context(events: list[str], name: str) -> Iterator[None]:
    """Record entry and exit for one injected context manager."""

    events.append(f"{name}.enter")
    try:
        yield
    finally:
        events.append(f"{name}.exit")


class _FakeActors:
    """Inject the actor UOW boundary required by the V5 facade."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def atomic(self) -> AbstractContextManager[None]:
        """Return a context manager that records the actor UOW."""

        return _record_context(self._events, "actors")


class _FakeUseCase:
    """Record one Application call and return its configured result."""

    def __init__(self, events: list[str], name: str, result: object = None) -> None:
        self._events = events
        self._name = name
        self._result = result

    def execute(self, command: object) -> object:
        """Record the immutable command passed through the facade."""

        del command
        self._events.append(self._name)
        return self._result


def test_facade_orders_outer_transaction_lock_actor_uow_and_leaves_exact_unlocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove current/approve use one outer lock while exact remains historical."""

    events: list[str] = []
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry())

    @contextmanager
    def outer_atomic(*, using: str) -> Iterator[None]:
        assert using == "evidence-v5"
        with _record_context(events, "outer"):
            yield

    def lock_sources(*, using: str, policy_id: str) -> None:
        assert using == "evidence-v5"
        assert policy_id == "policy-42"
        events.append("lock")

    monkeypatch.setattr(composition.transaction, "atomic", outer_atomic)
    monkeypatch.setattr(
        composition, "lock_account_owner_assignment_evidence_v5_sources", lock_sources
    )

    facade = composition.AccountOwnerAssignmentEvidenceV5Facade(
        using="evidence-v5",
        policy_id="policy-42",
        actors=cast(
            DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
            _FakeActors(events),
        ),
        approve=cast(
            ApproveAccountOwnerAssignmentEvidenceV5,
            _FakeUseCase(events, "approve", "approved"),
        ),
        exact=cast(
            GetExactAccountOwnerAssignmentEvidenceV5,
            _FakeUseCase(events, "exact", "historical"),
        ),
        current=cast(
            GetCurrentAccountOwnerAssignmentEvidenceV5,
            _FakeUseCase(events, "current", "current"),
        ),
    )

    assert facade.approve(_approve_command()) == "approved"
    assert events == [
        "outer.enter",
        "lock",
        "actors.enter",
        "approve",
        "actors.exit",
        "outer.exit",
    ]

    events.clear()
    assert facade.get_current(_current_command()) == "current"
    assert events == [
        "outer.enter",
        "lock",
        "actors.enter",
        "current",
        "actors.exit",
        "outer.exit",
    ]

    events.clear()
    assert facade.get_exact(_exact_command()) == "historical"
    assert events == ["exact"]


def test_facade_rejects_non_postgresql_alias_before_opening_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject unsupported aliases before lock or actor UOW acquisition."""

    events: list[str] = []
    monkeypatch.setattr(composition, "connections", _ConnectionRegistry(vendor="sqlite"))
    monkeypatch.setattr(
        composition,
        "lock_account_owner_assignment_evidence_v5_sources",
        lambda **kwargs: events.append("lock"),
    )
    facade = composition.AccountOwnerAssignmentEvidenceV5Facade(
        using="evidence-v5",
        policy_id="policy-42",
        actors=cast(
            DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
            _FakeActors(events),
        ),
        approve=cast(
            ApproveAccountOwnerAssignmentEvidenceV5,
            _FakeUseCase(events, "approve"),
        ),
        exact=cast(
            GetExactAccountOwnerAssignmentEvidenceV5,
            _FakeUseCase(events, "exact"),
        ),
        current=cast(
            GetCurrentAccountOwnerAssignmentEvidenceV5,
            _FakeUseCase(events, "current"),
        ),
    )

    with pytest.raises(AccountOwnerAssignmentEvidenceV5Unavailable, match="PostgreSQL"):
        facade.approve(_approve_command())
    assert events == []


def test_composition_source_has_no_v4_domain_or_execution_boundary() -> None:
    """Keep the V5 composition rooted in Subject V5 without execution authority."""

    source = Path(composition.__file__).read_text(encoding="utf-8")

    assert "account_owner_assignment_evidence_v4" not in source
    assert "AccountOwnerAssignmentSubjectV4" not in source
    assert "apps.account.interface" not in source
    assert "broker_execution" not in source
    assert "lock_account_owner_assignment_evidence_v5_sources" in source
    assert "DjangoAccountOwnerAssignmentEvidenceV5Repository" in source
