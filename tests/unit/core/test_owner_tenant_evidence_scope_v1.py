from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.owner_tenant_authority_v1 import (
    GetCurrentOwnerTenantAuthorityV1,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import EvidenceScopeSourceV1
from core.integration.owner_tenant_evidence_scope_v1 import (
    AuthenticatedOwnerTenantEvidenceScopeIssuerV1,
    AuthenticatedOwnerTenantEvidenceSelectorProviderV1,
    AuthenticatedOwnerTenantScopeObservationProviderV1,
    OwnerTenantAuthorityArtifactBindingV1,
    OwnerTenantEvidenceReadBindingV1,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import _at
from tests.unit.account.test_owner_tenant_authority_v1 import (
    _Assignments,
    _authority,
    _Repository,
)


class _ActorReader:
    def __init__(self, actor_id: str = "human-42") -> None:
        self.actor_id = actor_id

    def get_exact_current(
        self,
        *,
        principal_id: str,
        user_id: int,
        expected_authentication_context_hash: str,
        as_of: datetime,
    ) -> CurrentAccountActorAuthorityV3 | None:
        return CurrentAccountActorAuthorityV3(
            principal_id=principal_id,
            user_id=user_id,
            authentication_context_hash=expected_authentication_context_hash,
            actor_id=self.actor_id,
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
            rbac_role="user",
            source_id="actor-source-42",
            source_version="v3",
            source_content_hash="2" * 64,
            recorded_at=_at(8),
            valid_until=_at(12),
        )


class _ScopeRepository:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.rows: list[EvidenceScopeSourceV1] = []

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield

    def now(self) -> datetime:
        return _at(9)

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> EvidenceScopeSourceV1 | None:
        return next(
            (
                value
                for value in self.rows
                if value.source_id == source_id
                and value.source_version == source_version
                and value.recorded_at <= as_of
            ),
            None,
        )

    def get_current_head(self, *, source_id: str, as_of: datetime) -> EvidenceScopeSourceV1 | None:
        known = [
            value
            for value in self.rows
            if value.source_id == source_id and value.recorded_at <= as_of
        ]
        return known[-1] if known else None

    def append(
        self,
        source: EvidenceScopeSourceV1,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> EvidenceScopeSourceV1:
        assert source.supersedes_content_hash == expected_predecessor_hash
        assert source.recorded_at == recorded_at
        self.rows.append(source)
        return source


class _OtherAliasRepository(_Repository):
    """Authority repository sentinel bound to a different Django alias."""

    unit_of_work_key = "django:other"


def _provider(
    *, actor_reader: _ActorReader | None = None
) -> tuple[AuthenticatedOwnerTenantEvidenceSelectorProviderV1, ArtifactRef]:
    authority = _authority()
    repository = _Repository()
    repository.rows.append(authority)
    artifact = ArtifactRef("research", "alpha_report", "report-7", "v4", "3" * 64)
    principal = AuthenticatedAccountPrincipalV3(
        principal_id="principal-42",
        user_id=42,
        authentication_context_hash="1" * 64,
        authenticated_at=_at(8),
        valid_until=_at(12),
    )
    authority_binding = OwnerTenantAuthorityArtifactBindingV1(
        authority_id=authority.authority_id,
        authority_version=authority.authority_version,
        authority_content_hash=authority.content_hash,
        artifact=artifact,
    )
    binding = OwnerTenantEvidenceReadBindingV1(
        authority=authority_binding,
        source_id="scope-source-7",
        source_version="v1",
        source_content_hash="4" * 64,
    )
    return (
        AuthenticatedOwnerTenantEvidenceSelectorProviderV1(
            principal=principal,
            actor_authority_reader=actor_reader or _ActorReader(),
            owner_tenant_reader=GetCurrentOwnerTenantAuthorityV1(
                repository, assignment_reader=_Assignments()
            ),
            binding=binding,
        ),
        artifact,
    )


def test_authenticated_principal_and_authority_issue_exact_selector() -> None:
    provider, artifact = _provider()
    selector = provider.get_selector(artifact=artifact, as_of=_at(9))
    assert selector is not None
    assert (
        selector.owner_id,
        selector.tenant_id,
        selector.account_id,
        selector.actor_id,
    ) == ("owner-agom-42", "tenant-cn-1", "acct-0007", "human-42")
    assert provider.unit_of_work_key == "django:default"


def test_authority_reader_alias_mismatch_fails_closed() -> None:
    """The Account authority reader must share the requested Evidence alias."""

    provider, _ = _provider()
    with pytest.raises(ValueError, match="share the requested unit of work"):
        AuthenticatedOwnerTenantEvidenceSelectorProviderV1(
            principal=provider.principal,
            actor_authority_reader=provider.actor_authority_reader,
            owner_tenant_reader=GetCurrentOwnerTenantAuthorityV1(
                _OtherAliasRepository(), assignment_reader=_Assignments()
            ),
            binding=provider.binding,
            using="default",
        )


def test_artifact_or_authenticated_actor_substitution_fails_closed() -> None:
    provider, artifact = _provider(actor_reader=_ActorReader("human-other"))
    assert provider.get_selector(artifact=artifact, as_of=_at(9)) is None
    other = ArtifactRef("research", "alpha_report", "report-8", "v4", "3" * 64)
    valid_provider, _ = _provider()
    assert valid_provider.get_selector(artifact=other, as_of=_at(9)) is None


def test_authenticated_authority_is_auto_captured_as_scope_source() -> None:
    selector, artifact = _provider()
    observation_provider = AuthenticatedOwnerTenantScopeObservationProviderV1(
        principal=selector.principal,
        actor_authority_reader=selector.actor_authority_reader,
        owner_tenant_reader=selector.owner_tenant_reader,
        binding=selector.binding.authority,
    )
    repository = _ScopeRepository()
    issuer = AuthenticatedOwnerTenantEvidenceScopeIssuerV1(
        observation_provider=observation_provider,
        repository=repository,
        validity_period=timedelta(hours=12),
    )
    source = issuer.issue(source_id="scope-source-7", source_version="v1")
    assert source.artifact == artifact
    assert (source.owner_id, source.tenant_id, source.actor_id) == (
        "owner-agom-42",
        "tenant-cn-1",
        "human-42",
    )
    assert issuer.issue(source_id="scope-source-7", source_version="v1") == source
    assert len(repository.rows) == 1
