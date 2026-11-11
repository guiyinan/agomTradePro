"""Compose cash-dividend stage boundaries with official and account evidence."""

from __future__ import annotations

from pathlib import Path

from django.db import DEFAULT_DB_ALIAS

from apps.simulated_trading.application.corporate_action_posting import (
    AuditedCorporateActionPostingRepositoryPort,
    AuditedCorporateActionPostingRepositoryProtocol,
    CorporateActionOwnershipProofVerifier,
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    CorporateActionPostingRepositoryProtocol,
    CorporateActionSourceQualificationVerifierProtocol,
    CorporateActionTaxBasisVerifierProtocol,
    PostCashDividendEntitlementUseCase,
    PostCashDividendPaymentUseCase,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionStageRequest,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    VerifiedSzseActionSourceQualifier,
)


class _AuditedPostingRepositoryAdapter(CorporateActionPostingRepositoryProtocol):
    """Adapt only the explicit same-alias audited posting port to the Application boundary."""

    def __init__(self, repository: AuditedCorporateActionPostingRepositoryPort) -> None:
        self._repository = repository

    def post_revision(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Delegate the revision to its required atomic Audit/Outbox transaction."""

        return self._repository.post_revision_with_audit(requests)


def build_corporate_action_posting_use_case(
    *,
    body_store_root: Path,
    runtime_environment: str,
    audited_repository: AuditedCorporateActionPostingRepositoryProtocol | None = None,
    using: str = DEFAULT_DB_ALIAS,
) -> PostCashDividendEntitlementUseCase:
    """Build a cash-entitlement entry only with a required same-alias Audit/Outbox factory.

    The injected repository factory must commit the ledger append and required Audit/Outbox
    observation atomically on ``using``. This composition never constructs the bare Django
    posting repository. Its tax verifier is deliberately ``None`` so withholding remains
    blocked until statutory rules and per-sale assessments are persisted and verified.
    """

    posting_repository = _build_audited_posting_repository(
        body_store_root=body_store_root,
        runtime_environment=runtime_environment,
        audited_repository=audited_repository,
        using=using,
    )
    return PostCashDividendEntitlementUseCase(posting_repository)


def build_corporate_action_payment_use_case(
    *,
    body_store_root: Path,
    runtime_environment: str,
    audited_repository: AuditedCorporateActionPostingRepositoryProtocol | None = None,
    using: str = DEFAULT_DB_ALIAS,
) -> PostCashDividendPaymentUseCase:
    """Build a payment-only entry with required same-alias Audit/Outbox posting."""

    posting_repository = _build_audited_posting_repository(
        body_store_root=body_store_root,
        runtime_environment=runtime_environment,
        audited_repository=audited_repository,
        using=using,
    )
    return PostCashDividendPaymentUseCase(posting_repository)


def _build_audited_posting_repository(
    *,
    body_store_root: Path,
    runtime_environment: str,
    audited_repository: AuditedCorporateActionPostingRepositoryProtocol | None,
    using: str,
) -> CorporateActionPostingRepositoryProtocol:
    """Build the shared qualified source and account-proof ports behind Audit/Outbox."""

    if (
        not isinstance(body_store_root, Path)
        or type(runtime_environment) is not str
        or not runtime_environment.strip()
        or type(using) is not str
        or not using
    ):
        raise CorporateActionPostingBlockedError(
            "corporate-action posting composition scope is invalid",
            code="CORPORATE_ACTION_INPUT_INVALID",
        )
    if audited_repository is None or not isinstance(
        audited_repository,
        AuditedCorporateActionPostingRepositoryProtocol,
    ):
        raise CorporateActionPostingBlockedError(
            "same-alias atomic Audit/Outbox posting is unavailable",
            code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
        )

    source_qualifier: CorporateActionSourceQualificationVerifierProtocol = (
        VerifiedSzseActionSourceQualifier(body_store_root=body_store_root, using=using)
    )
    ownership_history = build_corporate_action_ownership_history_repository(
        runtime_environment=runtime_environment,
        using=using,
    )
    ownership_verifier = CorporateActionOwnershipProofVerifier(ownership_history)
    tax_basis_verifier: CorporateActionTaxBasisVerifierProtocol | None = None
    posting_repository = audited_repository.build_posting_repository(
        source_qualifier=source_qualifier,
        ownership_verifier=ownership_verifier,
        tax_basis_verifier=tax_basis_verifier,
        using=using,
    )
    if (
        not isinstance(posting_repository, AuditedCorporateActionPostingRepositoryPort)
        or posting_repository.get_database_alias() != using
    ):
        raise CorporateActionPostingBlockedError(
            "atomic Audit/Outbox factory returned an invalid or wrong-alias repository",
            code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
        )
    return _AuditedPostingRepositoryAdapter(posting_repository)


__all__ = [
    "build_corporate_action_payment_use_case",
    "build_corporate_action_posting_use_case",
]
