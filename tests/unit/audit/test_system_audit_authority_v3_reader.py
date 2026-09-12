from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    root_claim_hash_for_actor_authority_source_v3,
)
from apps.account.system_audit_authority_v3_composition import (
    AccountSystemAuditOwnerTenantAuthorityV3Reader,
)
from tests.unit.account.test_account_owner_assignment_actor_authority_source_v3 import (
    _source,
)
from tests.unit.account.test_owner_tenant_authority_v3 import _authority
from tests.unit.account.test_owner_tenant_authority_v3_application import _authority_source


class _PhysicalProvider:
    def get_exact_final(self, **kwargs: object) -> None:
        return None

    def get_exact_current(self, **kwargs: object) -> None:
        return None


def test_v3_reader_derives_facade_inputs_only_from_exact_immutable_sources(
    monkeypatch,
) -> None:
    from apps.account import system_audit_authority_v3_composition as module

    authority = _authority()
    cutoff = authority.recorded_at + timedelta(microseconds=1)
    authentication = _authority_source(authority.assignment, valid_until=authority.valid_until)
    record = PersistedOwnerTenantAuthorityV3(authority, authentication)
    actor = _source(
        source_id="audit-actor-v3",
        source_version="v1",
        principal_id="principal-42",
        user_id=authority.actor_user_id,
        actor_id=authority.actor_id,
        is_staff=True,
        is_superuser=True,
        rbac_role="admin",
        principal_authenticated_at=authority.approved_at - timedelta(minutes=1),
        principal_valid_until=authority.valid_until,
        source_recorded_at=authority.approved_at - timedelta(minutes=1),
        source_valid_until=authority.valid_until,
        issued_at=authority.approved_at,
        recorded_at=authority.approved_at,
        ttl_valid_until=authority.valid_until,
        valid_until=authority.valid_until,
        root_claim_hash=root_claim_hash_for_actor_authority_source_v3(
            source_id="audit-actor-v3",
            principal_id="principal-42",
            user_id=authority.actor_user_id,
            authentication_context_identity_hash="a" * 64,
            actor_id=authority.actor_id,
        ),
    )

    class _AuthorityRepository:
        @contextmanager
        def atomic(self) -> Iterator[None]:
            yield

        def now(self):
            return cutoff

        def get_winner(self, **kwargs: object):
            return record

        def get_head(self, **kwargs: object):
            return record

        def get_revocation(self, **kwargs: object):
            return None

    class _ActorRepository:
        def now(self):
            return cutoff

    class _ActorReader:
        def __init__(self, **kwargs: object) -> None:
            pass

        def execute(self, command: object):
            return actor

    observation = CurrentOwnerTenantAuthorityV3(
        authority=authority,
        authentication=authentication,
        observed_at=cutoff,
        valid_until=min(
            authority.valid_until,
            authority.assignment.valid_until,
            authority.policy.valid_until,
            authentication.valid_until,
        ),
    )
    facade_inputs: list[dict[str, object]] = []

    class _Facade:
        def get_current(self, command: object):
            return observation

    def build_facade(**kwargs: object) -> _Facade:
        facade_inputs.append(kwargs)
        return _Facade()

    monkeypatch.setattr(
        module, "DjangoOwnerTenantAuthorityV3Repository", lambda **kwargs: _AuthorityRepository()
    )
    monkeypatch.setattr(
        module,
        "DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository",
        lambda **kwargs: _ActorRepository(),
    )
    monkeypatch.setattr(
        module, "DjangoAccountActorAuthorityInputBundleProviderV3", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        module, "GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3", _ActorReader
    )
    monkeypatch.setattr(module, "build_owner_tenant_authority_v3_facade", build_facade)

    command = GetCurrentOwnerTenantAuthorityV3Command(
        authority.authority_id,
        authority.authority_version,
        authority.content_hash,
    )
    result = AccountSystemAuditOwnerTenantAuthorityV3Reader(
        actor_source_id=actor.source_id,
        actor_source_version=actor.source_version,
        actor_content_hash=actor.content_hash,
        physical_row_provider=_PhysicalProvider(),
        database_alias="audit",
    ).execute(command)

    assert result is observation
    assert len(facade_inputs) == 1
    inputs = facade_inputs[0]
    assert inputs["actor_source_id"] == actor.source_id
    assert inputs["actor_source_version"] == actor.source_version
    assert inputs["actor_source_content_hash"] == actor.content_hash
    assert inputs["using"] == "audit"
    assert inputs["principal"].principal_id == actor.principal_id
    assert (
        inputs["principal"].authentication_context_hash == actor.authentication_context_content_hash
    )
    assert inputs["policy_binding"].policy_id == authority.policy.policy_id
    assert inputs["policy_binding"].expected_content_hash == authority.policy.content_hash


def test_v3_reader_rejects_scope_hash_mismatch_without_building_facade(monkeypatch) -> None:
    from apps.account import system_audit_authority_v3_composition as module

    authority = _authority()
    authentication = _authority_source(authority.assignment, valid_until=authority.valid_until)
    record = PersistedOwnerTenantAuthorityV3(authority, authentication)

    class _Repository:
        @contextmanager
        def atomic(self) -> Iterator[None]:
            yield

        def now(self):
            return authority.recorded_at + timedelta(microseconds=1)

        def get_winner(self, **kwargs: object):
            return record

        def get_head(self, **kwargs: object):
            return record

        def get_revocation(self, **kwargs: object):
            return None

    monkeypatch.setattr(
        module, "DjangoOwnerTenantAuthorityV3Repository", lambda **kwargs: _Repository()
    )
    monkeypatch.setattr(
        module,
        "build_owner_tenant_authority_v3_facade",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("facade must not be built")),
    )
    reader = AccountSystemAuditOwnerTenantAuthorityV3Reader(
        actor_source_id="audit-actor-v3",
        actor_source_version="v1",
        actor_content_hash="a" * 64,
        physical_row_provider=_PhysicalProvider(),
    )

    assert (
        reader.execute(
            GetCurrentOwnerTenantAuthorityV3Command(
                authority.authority_id,
                authority.authority_version,
                "f" * 64,
            )
        )
        is None
    )
