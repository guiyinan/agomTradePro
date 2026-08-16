"""Risk Center-owned composition for operator-spec approval writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.risk_center.application.evidence_operator_spec_approval import (
    ApproveEvidenceOperatorSpec,
    EvidenceOperatorSpecApprovalUnavailable,
    ExactEvidenceOperatorSpecApprovalDefinitionProvider,
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
    definition_provider: ExactEvidenceOperatorSpecApprovalDefinitionProvider | None = None,
    using: str = "default",
) -> EvidenceOperatorSpecApprovalWriteRuntime:
    """Build commands with injected exact definitions and a human staff actor.

    Research owns the definition ledger, so the provider must be supplied by a
    higher-level composition root.  Omitting it is a deliberate fail-closed
    state rather than a hidden Risk Center → Research import.
    """

    actor = _actor_from_authenticated_user(authenticated_user)
    if definition_provider is None:
        raise EvidenceOperatorSpecApprovalUnavailable(
            "trusted operator specification definition provider is not wired"
        )
    repository = DjangoEvidenceOperatorSpecApprovalRepository(using=using)
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


__all__ = [
    "EvidenceOperatorSpecApprovalWriteRuntime",
    "build_evidence_operator_spec_approval_write_runtime",
]
