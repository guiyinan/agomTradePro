from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.owner_tenant_authority_v1 import (
    GetCurrentOwnerTenantAuthorityV1Command,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
    root_claim_hash_for_actor_authority_source_v3,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.owner_tenant_authority_v1 import OwnerTenantAuthorityV1
from apps.account.system_audit_authority_composition import (
    AccountSystemAuditAuthorityReaders,
)
from core.integration import system_audit_authority as authority_module
from core.integration.system_audit_authority import (
    AccountSystemAuditActorAuthorityAdapter,
    AccountSystemAuditScopeAuthorityAdapter,
    SystemAuditAuthorityReaders,
    build_system_audit_authority_readers,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _actor_source(
    *,
    authority_state: str = "current",
    is_authenticated: bool = True,
    is_active: bool = True,
    valid_until: datetime = NOW + timedelta(minutes=30),
) -> AccountOwnerAssignmentActorAuthoritySourceV3:
    return AccountOwnerAssignmentActorAuthoritySourceV3(
        source_id="actor-source-41",
        source_version="v3",
        principal_id="principal-41",
        user_id=41,
        authentication_context_id="session-41",
        authentication_context_version="generation-2",
        authentication_context_identity_hash="a" * 64,
        authentication_context_content_hash="b" * 64,
        user_source_id="account-user-41",
        user_source_version="v7",
        user_source_content_hash="c" * 64,
        rbac_source_id="account-rbac-41",
        rbac_source_version="v5",
        rbac_source_content_hash="d" * 64,
        actor_id="django-user:41",
        is_authenticated=is_authenticated,
        is_active=is_active,
        is_staff=True,
        is_superuser=False,
        rbac_role="audit_reader",
        authority_state=authority_state,
        principal_authenticated_at=NOW - timedelta(minutes=12),
        principal_valid_until=valid_until,
        source_recorded_at=NOW - timedelta(minutes=10),
        source_valid_until=valid_until,
        issued_at=NOW - timedelta(minutes=9),
        recorded_at=NOW - timedelta(minutes=8),
        ttl_valid_until=valid_until,
        valid_until=valid_until,
        root_claim_hash=root_claim_hash_for_actor_authority_source_v3(
            source_id="actor-source-41",
            principal_id="principal-41",
            user_id=41,
            authentication_context_identity_hash="a" * 64,
            actor_id="django-user:41",
        ),
    )


def _scope_authority(
    *,
    status: str = "active",
    valid_until: datetime = NOW + timedelta(minutes=25),
) -> OwnerTenantAuthorityV1:
    return OwnerTenantAuthorityV1(
        authority_id="scope-authority-41",
        authority_version="v4",
        tenant_id="tenant-41",
        owner_id="owner-41",
        account_namespace="account",
        account_id="account-41",
        actor_id="django-user:41",
        actor_user_id=41,
        assignment_evidence_id="assignment-41",
        assignment_evidence_version="v3",
        assignment_evidence_content_hash="e" * 64,
        status=status,
        approved_by=AccountOwnerAssignmentActor(
            actor_id="approver-9",
            user_id=9,
            role="owner_tenant_authority_approver",
            is_staff=True,
        ),
        approved_at=NOW - timedelta(minutes=7),
        recorded_at=NOW - timedelta(minutes=6),
        valid_until=valid_until,
    )


@dataclass
class FakeActorReader:
    value: AccountOwnerAssignmentActorAuthoritySourceV3 | None
    command: GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command | None = field(
        default=None, init=False
    )

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3 | None:
        self.command = command
        return self.value


@dataclass
class FakeScopeReader:
    value: OwnerTenantAuthorityV1 | None
    command: GetCurrentOwnerTenantAuthorityV1Command | None = field(default=None, init=False)

    def execute(
        self, command: GetCurrentOwnerTenantAuthorityV1Command
    ) -> OwnerTenantAuthorityV1 | None:
        self.command = command
        return self.value


def test_actor_adapter_forwards_exact_selector_and_projects_all_facts() -> None:
    source = _actor_source()
    reader = FakeActorReader(source)
    facts = AccountSystemAuditActorAuthorityAdapter(reader).get_current(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
        as_of=NOW,
    )

    assert reader.command == GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command(
        source.source_id,
        source.source_version,
        source.content_hash,
        NOW,
    )
    assert facts is not None
    assert (
        facts.source_id,
        facts.source_version,
        facts.content_hash,
        facts.actor_id,
        facts.user_id,
        facts.is_authenticated,
        facts.is_staff,
        facts.role,
        facts.authority_state,
        facts.recorded_at,
        facts.valid_until,
    ) == (
        source.source_id,
        source.source_version,
        source.content_hash,
        source.actor_id,
        source.user_id,
        source.is_authenticated,
        source.is_staff,
        source.rbac_role,
        "active",
        source.recorded_at,
        source.valid_until,
    )


@pytest.mark.parametrize(
    "source",
    [
        None,
        _actor_source(valid_until=NOW),
        _actor_source(authority_state="revoked", is_authenticated=False, is_active=False),
        _actor_source(authority_state="deactivated", is_authenticated=False, is_active=False),
    ],
)
def test_actor_adapter_returns_none_for_absent_expired_or_terminal_source(
    source: AccountOwnerAssignmentActorAuthoritySourceV3 | None,
) -> None:
    assert (
        AccountSystemAuditActorAuthorityAdapter(FakeActorReader(source)).get_current(
            source_id="actor-source-41",
            source_version="v3",
            expected_content_hash="f" * 64,
            as_of=NOW,
        )
        is None
    )


def test_actor_adapter_rejects_type_substitution() -> None:
    reader = FakeActorReader(cast(AccountOwnerAssignmentActorAuthoritySourceV3, object()))
    with pytest.raises(TypeError, match="type substitution"):
        AccountSystemAuditActorAuthorityAdapter(reader).get_current(
            source_id="actor-source-41",
            source_version="v3",
            expected_content_hash="a" * 64,
            as_of=NOW,
        )


def test_scope_adapter_forwards_exact_selector_and_projects_all_facts() -> None:
    authority = _scope_authority()
    reader = FakeScopeReader(authority)
    facts = AccountSystemAuditScopeAuthorityAdapter(reader).get_current(
        source_id=authority.authority_id,
        source_version=authority.authority_version,
        expected_content_hash=authority.content_hash,
        as_of=NOW,
    )

    assert reader.command == GetCurrentOwnerTenantAuthorityV1Command(
        authority.authority_id,
        authority.authority_version,
        authority.content_hash,
        NOW,
    )
    assert facts is not None
    assert (
        facts.source_id,
        facts.source_version,
        facts.content_hash,
        facts.actor_id,
        facts.user_id,
        facts.tenant_id,
        facts.owner_id,
        facts.authority_state,
        facts.recorded_at,
        facts.valid_until,
    ) == (
        authority.authority_id,
        authority.authority_version,
        authority.content_hash,
        authority.actor_id,
        authority.actor_user_id,
        authority.tenant_id,
        authority.owner_id,
        "active",
        authority.recorded_at,
        authority.valid_until,
    )


@pytest.mark.parametrize(
    "authority",
    [None, _scope_authority(valid_until=NOW), _scope_authority(status="revoked")],
)
def test_scope_adapter_returns_none_for_absent_expired_or_terminal_authority(
    authority: OwnerTenantAuthorityV1 | None,
) -> None:
    assert (
        AccountSystemAuditScopeAuthorityAdapter(FakeScopeReader(authority)).get_current(
            source_id="scope-authority-41",
            source_version="v4",
            expected_content_hash="f" * 64,
            as_of=NOW,
        )
        is None
    )


def test_scope_adapter_rejects_type_substitution() -> None:
    reader = FakeScopeReader(cast(OwnerTenantAuthorityV1, object()))
    with pytest.raises(TypeError, match="type substitution"):
        AccountSystemAuditScopeAuthorityAdapter(reader).get_current(
            source_id="scope-authority-41",
            source_version="v4",
            expected_content_hash="a" * 64,
            as_of=NOW,
        )


@pytest.mark.parametrize("alias", ["", " bad ", "bad alias", "a" * 65])
def test_builder_rejects_invalid_alias(alias: str) -> None:
    with pytest.raises(ValueError, match="database alias"):
        build_system_audit_authority_readers(using=alias)


def test_builder_rejects_non_string_alias() -> None:
    with pytest.raises(ValueError, match="database alias"):
        build_system_audit_authority_readers(using=cast(str, 42))


def test_bundle_rejects_mismatched_child_aliases() -> None:
    actor = AccountSystemAuditActorAuthorityAdapter(FakeActorReader(None), "default")
    scope = AccountSystemAuditScopeAuthorityAdapter(FakeScopeReader(None), "other")
    with pytest.raises(ValueError, match="share one database alias"):
        SystemAuditAuthorityReaders(actor=actor, scope=scope, database_alias="default")


def test_builder_wires_every_reader_to_the_same_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.account import system_audit_authority_composition as authority_module

    calls: list[tuple[str, str]] = []
    actor_reader = FakeActorReader(None)
    scope_reader = FakeScopeReader(None)
    bundle_sentinel = object()
    repository_sentinel = object()

    def build_bundle(*, using: str) -> object:
        calls.append(("bundle", using))
        return bundle_sentinel

    def build_repository(*, using: str) -> object:
        calls.append(("repository", using))
        return repository_sentinel

    def build_actor(*, input_bundle_provider: object, repository: object) -> FakeActorReader:
        assert input_bundle_provider is bundle_sentinel
        assert repository is repository_sentinel
        calls.append(("actor", "audit-db"))
        return actor_reader

    def build_scope(*, using: str) -> FakeScopeReader:
        calls.append(("scope", using))
        return scope_reader

    monkeypatch.setattr(
        authority_module, "DjangoAccountActorAuthorityInputBundleProviderV3", build_bundle
    )
    monkeypatch.setattr(
        authority_module,
        "DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository",
        build_repository,
    )
    monkeypatch.setattr(
        authority_module, "GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3", build_actor
    )
    monkeypatch.setattr(authority_module, "build_owner_tenant_authority_v1_reader", build_scope)

    readers = build_system_audit_authority_readers(using="audit-db")

    assert calls == [
        ("bundle", "audit-db"),
        ("repository", "audit-db"),
        ("actor", "audit-db"),
        ("scope", "audit-db"),
    ]
    assert readers.database_alias == "audit-db"
    assert readers.actor.database_alias == "audit-db"
    assert readers.scope.database_alias == "audit-db"


def test_account_bundle_rejects_malformed_alias_and_reader_substitution() -> None:
    with pytest.raises(ValueError, match="database alias"):
        AccountSystemAuditAuthorityReaders(
            actor=cast(object, FakeActorReader(None)),
            scope=cast(object, FakeScopeReader(None)),
            database_alias="bad alias",
        )
    with pytest.raises(TypeError, match="actor authority reader"):
        AccountSystemAuditAuthorityReaders(
            actor=cast(object, object()),
            scope=cast(object, FakeScopeReader(None)),
            database_alias="default",
        )


def test_core_builder_rejects_account_bundle_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authority_module,
        "build_account_system_audit_authority_readers",
        lambda **kwargs: object(),
    )

    with pytest.raises(TypeError, match="bundle type was substituted"):
        build_system_audit_authority_readers()
