"""Build audited share-action use cases from injected proof and owner-scope ports."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.simulated_trading.application.corporate_action_posting import (
    AuditedCorporateActionPostingRepositoryPort,
    AuditedCorporateActionPostingRepositoryProtocol,
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    CorporateActionPostingRepositoryProtocol,
    CorporateActionSourceQualificationVerifierProtocol,
    HistoricalAccountOwnershipVerifierProtocol,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_share_revision import (
    plan_corporate_action_share_revision,
)


class _AuditedShareRevisionRepositoryAdapter(CorporateActionPostingRepositoryProtocol):
    """Adapt the same-alias audited repository to the stage application boundary."""

    def __init__(
        self,
        repository: AuditedCorporateActionPostingRepositoryPort,
        *,
        expected_action_kind: CorporateActionKind,
    ) -> None:
        """Bind one action family to the exact ledger/Audit/Outbox repository."""

        self._repository = repository
        self._expected_action_kind = expected_action_kind

    def post_revision(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Delegate requests to the required atomic Audit/Outbox boundary."""

        try:
            plan = plan_corporate_action_share_revision(requests)
        except CorporateActionInputValidationError as error:
            raise CorporateActionPostingBlockedError(str(error), code=error.code) from error
        if any(request.action_kind is not self._expected_action_kind for request in plan.requests):
            raise CorporateActionPostingBlockedError(
                "audited action builder received another corporate-action family",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        return self._repository.post_revision_with_audit(requests)


def _build_audited_revision_use_case(
    *,
    audited_repository: AuditedCorporateActionPostingRepositoryProtocol,
    source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
    ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
    expected_action_kind: CorporateActionKind,
    using: str,
) -> PostCorporateActionStageUseCase:
    """Compose supplied proof ports only through same-alias audited persistence."""

    if (
        type(using) is not str
        or not using
        or not isinstance(audited_repository, AuditedCorporateActionPostingRepositoryProtocol)
        or source_qualifier is None
        or ownership_verifier is None
    ):
        raise CorporateActionPostingBlockedError(
            "share-action proof, owner or audited posting dependency is unavailable",
            code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
        )
    repository = audited_repository.build_posting_repository(
        source_qualifier=source_qualifier,
        ownership_verifier=ownership_verifier,
        tax_basis_verifier=None,
        using=using,
    )
    if (
        not isinstance(repository, AuditedCorporateActionPostingRepositoryPort)
        or repository.get_database_alias() != using
    ):
        raise CorporateActionPostingBlockedError(
            "share-action factory returned an invalid or wrong-alias audited repository",
            code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
        )
    return PostCorporateActionStageUseCase(
        _AuditedShareRevisionRepositoryAdapter(
            repository,
            expected_action_kind=expected_action_kind,
        )
    )


def build_audited_share_revision_use_case(
    *,
    audited_repository: AuditedCorporateActionPostingRepositoryProtocol,
    source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
    ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
    using: str = DEFAULT_DB_ALIAS,
) -> PostCorporateActionStageUseCase:
    """Build one audited share entitlement, delivery, release or revision entry.

    The supplied source and ownership verifiers must prove the current share-action
    facts. The configured owner gate must be the explicit V3 gate. This composition
    does not fabricate source proofs or infer registry quantities or sellable dates.
    """

    return _build_audited_revision_use_case(
        audited_repository=audited_repository,
        source_qualifier=source_qualifier,
        ownership_verifier=ownership_verifier,
        expected_action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        using=using,
    )


def build_audited_rights_no_effect_use_case(
    *,
    audited_repository: AuditedCorporateActionPostingRepositoryProtocol,
    source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
    ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
    using: str = DEFAULT_DB_ALIAS,
) -> PostCorporateActionStageUseCase:
    """Build one audited no-exercise rights entry with no exercise capability."""

    return _build_audited_revision_use_case(
        audited_repository=audited_repository,
        source_qualifier=source_qualifier,
        ownership_verifier=ownership_verifier,
        expected_action_kind=CorporateActionKind.RIGHTS_ISSUE,
        using=using,
    )


__all__ = [
    "build_audited_rights_no_effect_use_case",
    "build_audited_share_revision_use_case",
]
