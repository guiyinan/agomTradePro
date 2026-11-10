"""Application contract for appending qualified corporate-action stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionInputValidationError,
    CorporateActionStageRequest,
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


class CorporateActionTaxBasisVerifierProtocol(Protocol):
    """Verify the source-qualified tax basis for a deferred withholding stage."""

    def verify_tax_basis(self, request: CorporateActionStageRequest) -> bool:
        """Confirm the tax amount and basis record match the retained tax evidence."""


class CorporateActionPostingRepositoryProtocol(Protocol):
    """Persistence boundary for atomic account-scoped stage posting."""

    def post_revision(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Append one initial stage or one complete correction revision atomically."""


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


__all__ = [
    "CorporateActionPostingBlockedError",
    "CorporateActionPostingConflictError",
    "CorporateActionPostingReceipt",
    "CorporateActionPostingRepositoryProtocol",
    "PostCorporateActionStageUseCase",
]
