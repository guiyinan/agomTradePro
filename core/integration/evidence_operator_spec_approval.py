"""Server-side composition for Risk Center operator-spec approval writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.evidence_operator_spec_lifecycle import (
    EvidenceOperatorSpecCorruption,
    EvidenceOperatorSpecUnavailable,
    ExactEvidenceOperatorSpecDefinitionProvider,
)
from apps.research.domain.evidence_operator_spec_lifecycle import (
    EvidenceOperatorSpecDefinition,
)
from apps.research.infrastructure.evidence_operator_spec_definition_provider import (
    DjangoEvidenceOperatorSpecDefinitionProvider,
)
from apps.risk_center.application.evidence_operator_spec_approval import (
    ApproveEvidenceOperatorSpec,
    EvidenceOperatorSpecApprovalCorruption,
    EvidenceOperatorSpecApprovalDefinition,
    EvidenceOperatorSpecApprovalUnavailable,
    RegisterEvidenceOperatorSpecApprovalSubject,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalActor,
    EvidenceOperatorSpecApprovalActorKind,
    EvidenceOperatorSpecApprovalSubject,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_repository import (
    DjangoEvidenceOperatorSpecApprovalRepository,
)


@dataclass(frozen=True, slots=True)
class EvidenceOperatorSpecApprovalWriteRuntime:
    """Human registration and approval commands bound to one authenticated user."""

    register_subject: RegisterEvidenceOperatorSpecApprovalSubject
    approve: ApproveEvidenceOperatorSpec


class _RiskCenterDefinitionProvider:
    """Translate trusted Research definitions at the cross-app composition root."""

    __slots__ = ("_provider",)

    def __init__(self, provider: ExactEvidenceOperatorSpecDefinitionProvider) -> None:
        self._provider = provider

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalDefinition | None:
        """Return a Risk Center projection without accepting definition payloads."""

        try:
            definition = self._provider.get_exact(
                operator_id=operator_id,
                operator_version=operator_version,
                as_of=as_of,
            )
        except EvidenceOperatorSpecUnavailable as error:
            raise EvidenceOperatorSpecApprovalUnavailable(
                "trusted Research operator specification definition is unavailable"
            ) from error
        except EvidenceOperatorSpecCorruption as error:
            raise EvidenceOperatorSpecApprovalCorruption(
                "trusted Research operator specification definition failed integrity checks"
            ) from error
        if definition is None:
            return None
        return _definition_projection(definition)


class _RegisteredSubjectProvider:
    """Expose only registered Risk Center subjects to the approval command."""

    __slots__ = ("_repository",)

    def __init__(self, repository: DjangoEvidenceOperatorSpecApprovalRepository) -> None:
        self._repository = repository

    def get_exact(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecApprovalSubject | None:
        """Return a persisted exact subject, never a request-body projection."""

        return self._repository.get_subject_winner(
            subject_id=subject_id,
            subject_version=subject_version,
            as_of=as_of,
        )


def build_evidence_operator_spec_approval_write_runtime(
    *,
    authenticated_user: object,
    using: str = "default",
) -> EvidenceOperatorSpecApprovalWriteRuntime:
    """Build commands with a human staff actor derived only from Django auth state."""

    actor = _actor_from_authenticated_user(authenticated_user)
    repository = DjangoEvidenceOperatorSpecApprovalRepository(using=using)
    definition_provider = _RiskCenterDefinitionProvider(
        DjangoEvidenceOperatorSpecDefinitionProvider(using=using)
    )
    return EvidenceOperatorSpecApprovalWriteRuntime(
        register_subject=RegisterEvidenceOperatorSpecApprovalSubject(
            definition_provider=definition_provider,
            repository=repository,
            actor=actor,
        ),
        approve=ApproveEvidenceOperatorSpec(
            subject_provider=_RegisteredSubjectProvider(repository),
            repository=repository,
            actor=actor,
        ),
    )


def _actor_from_authenticated_user(user: object) -> EvidenceOperatorSpecApprovalActor:
    """Create an immutable human actor without trusting request payload fields."""

    if getattr(user, "is_authenticated", False) is not True:
        raise EvidenceOperatorSpecApprovalUnavailable(
            "operator specification approval requires an authenticated human staff actor"
        )
    if getattr(user, "is_staff", False) is not True:
        raise EvidenceOperatorSpecApprovalUnavailable(
            "operator specification approval requires a human staff actor"
        )
    user_id = getattr(user, "pk", None)
    if type(user_id) is not int or user_id <= 0:
        raise EvidenceOperatorSpecApprovalUnavailable(
            "operator specification approval actor has no stable user identity"
        )
    return EvidenceOperatorSpecApprovalActor(
        actor_id=f"django-user:{user_id}",
        kind=EvidenceOperatorSpecApprovalActorKind.HUMAN,
        is_staff=True,
        user_id=user_id,
    )


def _definition_projection(
    definition: EvidenceOperatorSpecDefinition,
) -> EvidenceOperatorSpecApprovalDefinition:
    spec = definition.operator_spec
    return EvidenceOperatorSpecApprovalDefinition(
        operator_id=spec.operator_id,
        operator_version=spec.operator_version,
        definition_hash=definition.content_hash,
        supersedes_activation_hash=definition.supersedes_activation_hash,
        activated_at=spec.activated_at,
        valid_until=spec.valid_until,
    )


__all__ = [
    "EvidenceOperatorSpecApprovalWriteRuntime",
    "build_evidence_operator_spec_approval_write_runtime",
]
