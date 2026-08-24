"""Authenticated Account authority bridge to Research Evidence scope v1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
    CurrentAccountOwnerClaimantProviderV3,
    ExactCurrentAccountActorAuthorityV3Reader,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
)
from apps.account.application.owner_tenant_authority_v1 import (
    GetCurrentOwnerTenantAuthorityV1,
    GetCurrentOwnerTenantAuthorityV1Command,
    OwnerTenantAuthorityV1Corruption,
    OwnerTenantAuthorityV1Unavailable,
)
from apps.account.domain.owner_tenant_authority_v1 import OwnerTenantAuthorityV1
from apps.research.application.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1Corruption,
    EvidenceScopeSourceV1Unavailable,
)
from apps.research.application.evidence_scope_source_v1_lifecycle import (
    EvidenceScopeSourceV1LifecycleRepository,
    EvidenceScopeSourceV1Observation,
    IssueEvidenceScopeSourceV1,
    IssueEvidenceScopeSourceV1Command,
)
from apps.research.application.evidence_scope_source_v1_provider import (
    EvidenceScopeSourceV1Selector,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import EvidenceScopeSourceV1
from apps.research.evidence_composition import (
    OwnerScopedEvidenceReadFacade,
    make_authorized_evidence_read_facade,
    make_evidence_scope_source_v1_lifecycle_repository,
)


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class OwnerTenantAuthorityArtifactBindingV1:
    """Server-owned exact authority binding for one Research artifact."""

    authority_id: str
    authority_version: str
    authority_content_hash: str
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        _token(self.authority_id, "authority_id")
        _token(self.authority_version, "authority_version")
        _digest(self.authority_content_hash, "authority_content_hash")
        if type(self.artifact) is not ArtifactRef:
            raise TypeError("artifact must be an exact ArtifactRef")
        self.artifact.__post_init__()


@dataclass(frozen=True, slots=True)
class OwnerTenantEvidenceReadBindingV1:
    """Server-owned exact authority/source binding for one artifact read."""

    authority: OwnerTenantAuthorityArtifactBindingV1
    source_id: str
    source_version: str
    source_content_hash: str

    def __post_init__(self) -> None:
        if type(self.authority) is not OwnerTenantAuthorityArtifactBindingV1:
            raise TypeError("authority must be an exact OwnerTenantAuthorityArtifactBindingV1")
        self.authority.__post_init__()
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.source_content_hash, "source_content_hash")

    @property
    def artifact(self) -> ArtifactRef:
        """Expose the exact artifact sealed by the authority binding."""

        return self.authority.artifact


@dataclass(frozen=True, slots=True)
class AuthenticatedOwnerTenantEvidenceSelectorProviderV1:
    """Issue a selector only after principal and final authority revalidation."""

    principal: AuthenticatedAccountPrincipalV3
    actor_authority_reader: ExactCurrentAccountActorAuthorityV3Reader
    owner_tenant_reader: GetCurrentOwnerTenantAuthorityV1
    binding: OwnerTenantEvidenceReadBindingV1
    using: str = "default"

    def __post_init__(self) -> None:
        _validate_provider_inputs(
            principal=self.principal,
            actor_reader=self.actor_authority_reader,
            authority_reader=self.owner_tenant_reader,
            authority_binding=self.binding.authority,
            using=self.using,
        )
        self.binding.__post_init__()

    @property
    def unit_of_work_key(self) -> str:
        """Return the same Django alias required by Evidence composition."""

        return f"django:{self.using}"

    def get_selector(
        self, *, artifact: ArtifactRef, as_of: datetime
    ) -> EvidenceScopeSourceV1Selector | None:
        """Return an exact selector or fail closed without mutable fallback."""

        if type(artifact) is not ArtifactRef:
            raise TypeError("artifact must be an exact ArtifactRef")
        artifact.__post_init__()
        if artifact != self.binding.artifact:
            return None
        authority = _current_authority(
            principal=self.principal,
            actor_reader=self.actor_authority_reader,
            authority_reader=self.owner_tenant_reader,
            binding=self.binding.authority,
            as_of=as_of,
        )
        if authority is None:
            return None
        return EvidenceScopeSourceV1Selector(
            source_id=self.binding.source_id,
            source_version=self.binding.source_version,
            expected_content_hash=self.binding.source_content_hash,
            owner_id=authority.owner_id,
            tenant_id=authority.tenant_id,
            account_id=authority.account_id,
            actor_id=authority.actor_id,
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedOwnerTenantScopeObservationProviderV1:
    """Project authenticated current authority into an immutable observation."""

    principal: AuthenticatedAccountPrincipalV3
    actor_authority_reader: ExactCurrentAccountActorAuthorityV3Reader
    owner_tenant_reader: GetCurrentOwnerTenantAuthorityV1
    binding: OwnerTenantAuthorityArtifactBindingV1
    using: str = "default"

    def __post_init__(self) -> None:
        _validate_provider_inputs(
            principal=self.principal,
            actor_reader=self.actor_authority_reader,
            authority_reader=self.owner_tenant_reader,
            authority_binding=self.binding,
            using=self.using,
        )

    @property
    def unit_of_work_key(self) -> str:
        """Return the Django alias shared with the scope-source repository."""

        return f"django:{self.using}"

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1Observation | None:
        """Return the deterministic observation for the exact current authority."""

        observation = self.build_current(as_of=as_of)
        if observation is None:
            return None
        if (
            observation.observation_id,
            observation.observation_version,
            observation.content_hash,
        ) != (observation_id, observation_version, expected_content_hash):
            return None
        return observation

    def build_current(self, *, as_of: datetime) -> EvidenceScopeSourceV1Observation | None:
        """Build the current content-addressed observation without persisting it."""

        authority = _current_authority(
            principal=self.principal,
            actor_reader=self.actor_authority_reader,
            authority_reader=self.owner_tenant_reader,
            binding=self.binding,
            as_of=as_of,
        )
        if authority is None:
            return None
        return EvidenceScopeSourceV1Observation(
            observation_id=_observation_id(authority, self.binding.artifact),
            observation_version=authority.authority_version,
            owner_id=authority.owner_id,
            tenant_id=authority.tenant_id,
            account_id=authority.account_id,
            actor_id=authority.actor_id,
            artifact=self.binding.artifact,
            status="active",
            recorded_at=authority.recorded_at,
            valid_until=authority.valid_until,
        )


class AuthenticatedOwnerTenantEvidenceScopeIssuerV1:
    """Automatically capture a scope source from authenticated current authority."""

    __slots__ = ("_lifecycle", "_observations", "_repository")

    def __init__(
        self,
        *,
        observation_provider: AuthenticatedOwnerTenantScopeObservationProviderV1,
        repository: EvidenceScopeSourceV1LifecycleRepository,
        validity_period: timedelta,
    ) -> None:
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        if observation_provider.unit_of_work_key != repository.unit_of_work_key:
            raise ValueError("authority observation and scope repository aliases differ")
        self._observations = observation_provider
        self._repository = repository
        self._lifecycle = IssueEvidenceScopeSourceV1(
            observation_provider=observation_provider,
            repository=repository,
            validity_period=validity_period,
        )

    def issue(self, *, source_id: str, source_version: str) -> EvidenceScopeSourceV1:
        """Issue one source using only server clock and current authority facts."""

        _token(source_id, "source_id")
        _token(source_version, "source_version")
        cutoff = self._repository.now()
        observation = self._observations.build_current(as_of=cutoff)
        if observation is None:
            raise EvidenceScopeSourceV1Unavailable(
                "current owner/tenant observation is unavailable"
            )
        return self._lifecycle.execute(
            IssueEvidenceScopeSourceV1Command(
                source_id=source_id,
                source_version=source_version,
                observation_id=observation.observation_id,
                observation_version=observation.observation_version,
                expected_observation_content_hash=observation.content_hash,
            )
        )


def _validate_provider_inputs(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    actor_reader: ExactCurrentAccountActorAuthorityV3Reader,
    authority_reader: GetCurrentOwnerTenantAuthorityV1,
    authority_binding: OwnerTenantAuthorityArtifactBindingV1,
    using: str,
) -> None:
    if type(principal) is not AuthenticatedAccountPrincipalV3:
        raise TypeError("principal must be an exact AuthenticatedAccountPrincipalV3")
    principal.__post_init__()
    if actor_reader is None:
        raise TypeError("actor_authority_reader is required")
    if type(authority_reader) is not GetCurrentOwnerTenantAuthorityV1:
        raise TypeError("owner_tenant_reader must be an exact GetCurrentOwnerTenantAuthorityV1")
    if type(authority_binding) is not OwnerTenantAuthorityArtifactBindingV1:
        raise TypeError("binding must be an exact OwnerTenantAuthorityArtifactBindingV1")
    authority_binding.__post_init__()
    if (
        type(using) is not str
        or not using
        or using.strip() != using
        or any(character.isspace() for character in using)
    ):
        raise ValueError("Evidence authority database alias is invalid")


def _current_authority(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    actor_reader: ExactCurrentAccountActorAuthorityV3Reader,
    authority_reader: GetCurrentOwnerTenantAuthorityV1,
    binding: OwnerTenantAuthorityArtifactBindingV1,
    as_of: datetime,
) -> OwnerTenantAuthorityV1 | None:
    try:
        claimant = CurrentAccountOwnerClaimantProviderV3(
            principal=principal,
            authority_reader=actor_reader,
        ).get_current(as_of=as_of)
    except AccountOwnerAssignmentCorruption as error:
        raise EvidenceScopeSourceV1Corruption("authenticated actor authority is corrupt") from error
    if claimant is None:
        return None
    try:
        authority = authority_reader.execute(
            GetCurrentOwnerTenantAuthorityV1Command(
                binding.authority_id,
                binding.authority_version,
                binding.authority_content_hash,
                as_of,
            )
        )
    except OwnerTenantAuthorityV1Unavailable as error:
        raise EvidenceScopeSourceV1Unavailable("owner/tenant authority is unavailable") from error
    except OwnerTenantAuthorityV1Corruption as error:
        raise EvidenceScopeSourceV1Corruption("owner/tenant authority is corrupt") from error
    if authority is None:
        return None
    if authority.actor_id != claimant.actor_id or authority.actor_user_id != claimant.user_id:
        return None
    return authority


def _observation_id(authority: OwnerTenantAuthorityV1, artifact: ArtifactRef) -> str:
    payload = {
        "artifact": artifact.to_payload(),
        "authority_content_hash": authority.content_hash,
        "authority_id": authority.authority_id,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "owner-tenant-observation-" + hashlib.sha256(encoded).hexdigest()


def build_authenticated_owner_scoped_evidence_read_facade(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    actor_authority_reader: ExactCurrentAccountActorAuthorityV3Reader,
    owner_tenant_reader: GetCurrentOwnerTenantAuthorityV1,
    binding: OwnerTenantEvidenceReadBindingV1,
    using: str = "default",
) -> OwnerScopedEvidenceReadFacade:
    """Compose authenticated owner scope and Evidence reads at the core root."""

    selector = AuthenticatedOwnerTenantEvidenceSelectorProviderV1(
        principal=principal,
        actor_authority_reader=actor_authority_reader,
        owner_tenant_reader=owner_tenant_reader,
        binding=binding,
        using=using,
    )
    return make_authorized_evidence_read_facade(
        selector_provider=selector,
        using=using,
    )


def build_authenticated_owner_scoped_evidence_scope_issuer(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    actor_authority_reader: ExactCurrentAccountActorAuthorityV3Reader,
    owner_tenant_reader: GetCurrentOwnerTenantAuthorityV1,
    binding: OwnerTenantAuthorityArtifactBindingV1,
    validity_period: timedelta,
    using: str = "default",
) -> AuthenticatedOwnerTenantEvidenceScopeIssuerV1:
    """Build authenticated scope capture at the core composition boundary."""

    observations = AuthenticatedOwnerTenantScopeObservationProviderV1(
        principal=principal,
        actor_authority_reader=actor_authority_reader,
        owner_tenant_reader=owner_tenant_reader,
        binding=binding,
        using=using,
    )
    repository = make_evidence_scope_source_v1_lifecycle_repository(using=using)
    return AuthenticatedOwnerTenantEvidenceScopeIssuerV1(
        observation_provider=observations,
        repository=repository,
        validity_period=validity_period,
    )


__all__ = [
    "AuthenticatedOwnerTenantEvidenceScopeIssuerV1",
    "AuthenticatedOwnerTenantEvidenceSelectorProviderV1",
    "AuthenticatedOwnerTenantScopeObservationProviderV1",
    "OwnerScopedEvidenceReadFacade",
    "OwnerTenantAuthorityArtifactBindingV1",
    "OwnerTenantEvidenceReadBindingV1",
    "build_authenticated_owner_scoped_evidence_read_facade",
    "build_authenticated_owner_scoped_evidence_scope_issuer",
]
