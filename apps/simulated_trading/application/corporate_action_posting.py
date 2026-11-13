"""Application contract for appending qualified corporate-action stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from apps.data_center.domain.security_disclosure_event import SecurityDisclosureExchange
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxExchange,
)
from core.exceptions import BusinessLogicError


class CorporateActionPostingBlockedError(BusinessLogicError):
    """Raised when identity, evidence, or locked simulated-ledger state is unsafe."""

    default_message = "模拟公司行动账本条件不足"
    default_code = "CORPORATE_ACTION_POSTING_BLOCKED"


class CorporateActionPostingConflictError(CorporateActionPostingBlockedError):
    """Raised when an event-stage key is reused with different facts."""

    default_message = "公司行动阶段身份已绑定不同账本事实"
    default_code = "CORPORATE_ACTION_IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True, slots=True)
class CorporateActionPostingReceipt:
    """Immutable confirmation returned for each inserted or replayed ledger row."""

    entry_id: int
    account_revision: int
    stage_key: str
    request_payload_sha256: str
    replayed: bool


class CorporateActionSourceQualificationVerifierProtocol(Protocol):
    """Verify official-source bytes, revision identity, dates, and corporate-action terms."""

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        """Return true only for a qualified official exchange disclosure snapshot."""


class HistoricalAccountOwnershipVerifierProtocol(Protocol):
    """Verify account ownership as of the action record date from retained history."""

    def verify_ownership(self, request: CorporateActionStageRequest) -> bool:
        """Confirm the immutable snapshot belongs to this account and record date."""


class RecordDateOwnershipProofReaderProtocol(Protocol):
    """Read persisted account history and replay one exact record-date ownership proof."""

    def read_record_date_ownership_proof(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        security_id: str,
        asset_code: str,
        record_date: date,
        evidence_cutoff_at: datetime,
    ) -> RecordDateOwnershipProof:
        """Return the immutable ownership replay for the requested exact scope."""


class CorporateActionOwnershipProofVerifier(HistoricalAccountOwnershipVerifierProtocol):
    """Compare caller terms with a fresh persisted replay at the qualified cutoff."""

    def __init__(self, reader: RecordDateOwnershipProofReaderProtocol) -> None:
        """Bind the verifier to the read-only ownership history port."""

        self._reader = reader

    def verify_ownership(self, request: CorporateActionStageRequest) -> bool:
        """Accept only supported entitlement or no-exercise rows with an exact proof."""

        if type(request) is not CorporateActionStageRequest:
            return False
        ordinary_entry = request.entry_kind in {
            CorporateActionEntryKind.POSTING,
            CorporateActionEntryKind.SUCCESSOR,
        }
        supported_entitlement = ordinary_entry and (
            (
                request.action_kind is CorporateActionKind.CASH_DIVIDEND
                and request.stage is CorporateActionStage.CASH_ENTITLEMENT
            )
            or (
                request.action_kind is CorporateActionKind.SHARE_DISTRIBUTION
                and request.stage is CorporateActionStage.SHARE_ENTITLEMENT
            )
        )
        supported_unexercised_rights = (
            request.action_kind is CorporateActionKind.RIGHTS_ISSUE
            and request.stage is CorporateActionStage.RIGHTS_NOT_EXERCISED
            and request.entry_kind is CorporateActionEntryKind.NO_EFFECT
        )
        if (
            not (supported_entitlement or supported_unexercised_rights)
            or request.ownership_snapshot_observed_at != request.qualified_at
        ):
            return False
        try:
            proof = self._reader.read_record_date_ownership_proof(
                account_id=request.account_id,
                owner_user_id=request.owner_user_id,
                security_id=request.security_id,
                asset_code=request.asset_code,
                record_date=request.record_date,
                evidence_cutoff_at=request.qualified_at,
            )
        except SimulatedTradeExecutionBlocked:
            return False
        if type(proof) is not RecordDateOwnershipProof:
            return False
        return (
            proof.account_id == request.account_id
            and proof.owner_user_id == request.owner_user_id
            and proof.security_id == request.security_id
            and proof.asset_code == request.asset_code
            and proof.exchange
            in {SecurityDisclosureExchange.SZSE.value, SimulatedDividendTaxExchange.SZ.value}
            and proof.record_date == request.record_date
            and proof.ownership_snapshot_as_of_date == request.record_date
            and proof.ownership_snapshot_id == request.ownership_snapshot_id
            and proof.ownership_snapshot_sha256 == request.ownership_snapshot_sha256
            and proof.eligible_quantity == request.eligible_quantity
            and proof.ownership_snapshot_observed_at == request.ownership_snapshot_observed_at
            and proof.ownership_snapshot_observed_at == request.qualified_at
        )


class CorporateActionTaxBasisVerifierProtocol(Protocol):
    """Verify the source-qualified tax basis for a deferred withholding stage."""

    def verify_tax_basis(self, request: CorporateActionStageRequest) -> bool:
        """Confirm the tax amount and basis record match the retained tax evidence."""


@runtime_checkable
class CorporateActionPostingRepositoryProtocol(Protocol):
    """Persistence boundary for atomic account-scoped stage posting."""

    def post_revision(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Append one initial stage or one complete correction revision atomically."""


@runtime_checkable
class AuditedCorporateActionPostingRepositoryPort(Protocol):
    """Same-alias posting port that atomically appends the ledger and required Audit/Outbox."""

    def get_database_alias(self) -> str:
        """Return the database alias used by the ledger, Audit, and Outbox transaction."""

    def post_revision_with_audit(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Append stages and required Audit/Outbox observation in one database transaction."""


@runtime_checkable
class AuditedCorporateActionPostingRepositoryProtocol(Protocol):
    """Factory for a same-alias repository that atomically posts Audit and Outbox evidence."""

    def build_posting_repository(
        self,
        *,
        source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
        ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
        tax_basis_verifier: CorporateActionTaxBasisVerifierProtocol | None,
        using: str,
    ) -> AuditedCorporateActionPostingRepositoryPort:
        """Build the atomic ledger/Audit/Outbox adapter on the requested database alias."""


class PostCorporateActionStageUseCase:
    """Validate and append explicit source-qualified account-action stage rows."""

    def __init__(self, repository: CorporateActionPostingRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Post one stage or an atomic set of reversals and successor stages."""

        if type(requests) is not tuple or not requests:
            raise CorporateActionPostingBlockedError(
                "corporate-action revision must contain at least one explicit stage",
                code="CORPORATE_ACTION_INPUT_INVALID",
            )
        try:
            for request in requests:
                if type(request) is not CorporateActionStageRequest:
                    raise CorporateActionInputValidationError(
                        "corporate-action stage request type is invalid"
                    )
                request.__post_init__()
        except CorporateActionInputValidationError as error:
            raise CorporateActionPostingBlockedError(str(error), code=error.code) from error
        return self._repository.post_revision(requests)


class PostCashDividendEntitlementUseCase:
    """Post only one verified cash-dividend entitlement through an injected repository."""

    def __init__(self, repository: CorporateActionPostingRepositoryProtocol) -> None:
        """Bind the cash-entitlement-only posting boundary."""

        self._delegate = PostCorporateActionStageUseCase(repository)

    def execute(
        self,
        request: CorporateActionStageRequest,
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Reject all settlement or non-cash stages before forwarding one entitlement."""

        if (
            type(request) is not CorporateActionStageRequest
            or request.action_kind is not CorporateActionKind.CASH_DIVIDEND
            or request.stage is not CorporateActionStage.CASH_ENTITLEMENT
            or request.entry_kind
            not in {CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR}
        ):
            raise CorporateActionPostingBlockedError(
                "this production entry only accepts cash-dividend entitlement stages",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        return self._delegate.execute((request,))


class PostCashDividendPaymentUseCase:
    """Post only one official-date cash-dividend payment through an injected repository."""

    def __init__(self, repository: CorporateActionPostingRepositoryProtocol) -> None:
        """Bind the cash-payment-only posting boundary."""

        self._delegate = PostCorporateActionStageUseCase(repository)

    def execute(
        self,
        request: CorporateActionStageRequest,
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Reject entitlement, tax, share, and correction-reversal stages before forwarding."""

        if (
            type(request) is not CorporateActionStageRequest
            or request.action_kind is not CorporateActionKind.CASH_DIVIDEND
            or request.stage is not CorporateActionStage.CASH_PAYMENT
            or request.entry_kind
            not in {CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR}
        ):
            raise CorporateActionPostingBlockedError(
                "this production entry only accepts cash-dividend payment stages",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        return self._delegate.execute((request,))


__all__ = [
    "AuditedCorporateActionPostingRepositoryPort",
    "AuditedCorporateActionPostingRepositoryProtocol",
    "CorporateActionOwnershipProofVerifier",
    "CorporateActionPostingBlockedError",
    "CorporateActionPostingConflictError",
    "CorporateActionPostingReceipt",
    "CorporateActionPostingRepositoryProtocol",
    "PostCashDividendEntitlementUseCase",
    "PostCashDividendPaymentUseCase",
    "PostCorporateActionStageUseCase",
    "RecordDateOwnershipProofReaderProtocol",
]
