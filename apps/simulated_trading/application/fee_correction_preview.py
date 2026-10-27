"""Owner-scoped preview contracts for operator-attested fee corrections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionReceipt,
)
from apps.simulated_trading.application.fee_correction_evidence_contracts import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    FeeCorrectionEvidenceUploadCommand,
)
from apps.simulated_trading.domain.fee_correction import (
    CorrectableFeeComponents,
    FeeCorrectionDelta,
    calculate_fee_correction_delta,
)


@dataclass(frozen=True, slots=True)
class FeeCorrectionPreviewCommand:
    """Owner input for previewing one exact CSV without client revision fields."""

    account_id: int
    trade_id: int
    idempotency_key: str
    original_filename: str
    content: bytes
    attestation_acknowledged: bool

    def __post_init__(self) -> None:
        """Reuse the upload contract's strict input checks without selecting a head."""

        self.to_upload_command(expected_revision=0, expected_predecessor_id=None)

    def to_upload_command(
        self,
        *,
        expected_revision: int,
        expected_predecessor_id: int | None,
    ) -> FeeCorrectionEvidenceUploadCommand:
        """Attach a server-selected revision to the existing evidence command."""

        return FeeCorrectionEvidenceUploadCommand(
            account_id=self.account_id,
            trade_id=self.trade_id,
            expected_revision=expected_revision,
            expected_predecessor_id=expected_predecessor_id,
            idempotency_key=self.idempotency_key,
            original_filename=self.original_filename,
            content=self.content,
            attestation_acknowledged=self.attestation_acknowledged,
        )


@dataclass(frozen=True, slots=True)
class FeeCorrectionPreview:
    """Validated fee comparison and source clocks; this is not an apply approval."""

    account_id: int
    trade_id: int
    asset_code: str
    ledger_currency: str
    expected_revision: int
    expected_predecessor_id: int | None
    source_locator: str
    content_sha256: str
    payload_sha256: str
    assurance_class: str
    source_observed_at: datetime
    verified_at: datetime
    stored_at: datetime
    as_of: datetime
    previous_fee_components: CorrectableFeeComponents
    revised_fee_components: CorrectableFeeComponents
    delta: FeeCorrectionDelta

    def __post_init__(self) -> None:
        """Keep the preview's identity, assurance, clocks, and exact math coherent."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.trade_id) is not int
            or self.trade_id <= 0
            or type(self.asset_code) is not str
            or not self.asset_code
            or self.asset_code.strip() != self.asset_code
            or any(character.isspace() for character in self.asset_code)
            or type(self.ledger_currency) is not str
            or len(self.ledger_currency) != 3
            or any(character < "A" or character > "Z" for character in self.ledger_currency)
            or type(self.expected_revision) is not int
            or self.expected_revision < 0
            or (
                self.expected_predecessor_id is not None
                and (
                    type(self.expected_predecessor_id) is not int
                    or self.expected_predecessor_id <= 0
                )
            )
            or (self.expected_revision == 0) != (self.expected_predecessor_id is None)
            or type(self.source_locator) is not str
            or not self.source_locator
            or self.source_locator.strip() != self.source_locator
            or self.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or type(self.previous_fee_components) is not CorrectableFeeComponents
            or type(self.revised_fee_components) is not CorrectableFeeComponents
            or type(self.delta) is not FeeCorrectionDelta
        ):
            raise FeeCorrectionBlockedError(
                "费用更正预览身份或范围无效", code="FEE_CORRECTION_PREVIEW_INVALID"
            )
        for digest in (self.content_sha256, self.payload_sha256):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise FeeCorrectionBlockedError(
                    "费用更正预览摘要无效", code="FEE_CORRECTION_PREVIEW_INVALID"
                )
        for value in (
            self.source_observed_at,
            self.verified_at,
            self.stored_at,
            self.as_of,
        ):
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise FeeCorrectionBlockedError(
                    "费用更正预览时钟必须带时区", code="FEE_CORRECTION_PREVIEW_INVALID"
                )
        if self.source_observed_at > self.verified_at or self.stored_at > self.verified_at:
            raise FeeCorrectionBlockedError(
                "费用更正预览证据时序无效", code="FEE_CORRECTION_PREVIEW_INVALID"
            )
        if (
            calculate_fee_correction_delta(
                self.previous_fee_components,
                self.revised_fee_components,
            )
            != self.delta
        ):
            raise FeeCorrectionBlockedError(
                "费用更正预览差额与费用组成不一致",
                code="FEE_CORRECTION_PREVIEW_INVALID",
            )


@dataclass(frozen=True, slots=True)
class FeeCorrectionPreviewResult:
    """A pending preview or an exact receipt for an already-applied request."""

    status: Literal["preview", "already_applied"]
    preview: FeeCorrectionPreview | None
    receipt: FeeCorrectionReceipt | None

    def __post_init__(self) -> None:
        """Require disjoint response forms for preview and completed-key recovery."""

        if self.status == "preview":
            if type(self.preview) is not FeeCorrectionPreview or self.receipt is not None:
                raise FeeCorrectionBlockedError(
                    "费用更正预览响应无效", code="FEE_CORRECTION_PREVIEW_INVALID"
                )
            return
        if self.status == "already_applied":
            if (
                self.preview is not None
                or type(self.receipt) is not FeeCorrectionReceipt
                or self.receipt.replayed is not True
            ):
                raise FeeCorrectionBlockedError(
                    "费用更正原请求回执无效", code="FEE_CORRECTION_IDEMPOTENCY_CONFLICT"
                )
            return
        raise FeeCorrectionBlockedError(
            "费用更正预览状态无效", code="FEE_CORRECTION_PREVIEW_INVALID"
        )


class FeeCorrectionPreviewRepositoryProtocol(Protocol):
    """Prepare or recover a preview inside one account-scoped transaction."""

    def preview(
        self,
        command: FeeCorrectionPreviewCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPreviewResult:
        """Return a qualified comparison or the original completed receipt."""
        ...


class FeeCorrectionPreviewUseCase:
    """Validate the authenticated preview request before repository orchestration."""

    def __init__(self, repository: FeeCorrectionPreviewRepositoryProtocol) -> None:
        """Use the supplied owner-scoped preview boundary."""

        self._repository = repository

    def execute(
        self,
        command: FeeCorrectionPreviewCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPreviewResult:
        """Preview an owner-attested CSV without applying a cash or position change."""

        if type(command) is not FeeCorrectionPreviewCommand:
            raise FeeCorrectionBlockedError(
                "费用更正预览命令无效", code="FEE_CORRECTION_PREVIEW_INVALID"
            )
        command.__post_init__()
        principal_id = getattr(principal, "pk", None)
        if (
            getattr(principal, "is_authenticated", None) is not True
            or type(principal_id) is not int
            or principal_id <= 0
        ):
            raise FeeCorrectionBlockedError(
                "费用更正预览需要有效的已认证账户主体",
                code="FEE_CORRECTION_PRINCIPAL_INVALID",
            )
        return self._repository.preview(command, principal=principal)


__all__ = [
    "FeeCorrectionPreview",
    "FeeCorrectionPreviewCommand",
    "FeeCorrectionPreviewRepositoryProtocol",
    "FeeCorrectionPreviewResult",
    "FeeCorrectionPreviewUseCase",
]
