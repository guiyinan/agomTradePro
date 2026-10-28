"""Shared classification for exact fee material bindings during recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionRequest,
    VerifiedFeeCorrectionEvidence,
)
from apps.simulated_trading.application.fee_correction_evidence_fingerprint import (
    fee_correction_policy_sha256,
)
from apps.simulated_trading.application.fee_correction_head import FeeCorrectionHead
from apps.simulated_trading.application.fee_correction_recovery import (
    FeeCorrectionRecoveryState,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)


class FeeCorrectionMaterialEvidenceVerifierProtocol(Protocol):
    """Expose current and immutable-snapshot source validation to recovery."""

    def verify(self, request: FeeCorrectionRequest) -> VerifiedFeeCorrectionEvidence | None:
        """Verify one source against the live policy version."""
        ...

    def verify_historical_material(self, request: FeeCorrectionRequest) -> bool:
        """Check whether a newer policy can safely fence the stored material."""
        ...


class FeeCorrectionMaterialHistoryReaderProtocol(Protocol):
    """Read a locator through the existing complete history and authority guard."""

    def get_head(
        self,
        account_id: int,
        trade_id: int,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        request_key: str | None = None,
        source_locator: str | None = None,
    ) -> FeeCorrectionHead:
        """Return a fully validated head and exact-locator receipt, if present."""
        ...


@dataclass(frozen=True, slots=True)
class FeeCorrectionMaterialClassification:
    """State and stable reason for one exact immutable material binding."""

    state: FeeCorrectionRecoveryState
    reason_code: str
    head: FeeCorrectionHead | None = None


def classify_fee_correction_binding(
    binding: FeeCorrectionEvidenceBindingModel,
    *,
    account: SimulatedAccountModel,
    current_policy: FeeCorrectionEvidencePolicyModel | None,
    principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    evidence_repository: FeeCorrectionMaterialEvidenceVerifierProtocol,
    history_reader: FeeCorrectionMaterialHistoryReaderProtocol,
) -> FeeCorrectionMaterialClassification:
    """Classify one binding with the existing history and source proof contracts."""

    owner_id = getattr(principal, "pk", None)
    if (
        type(owner_id) is not int
        or owner_id <= 0
        or account.account_type != "simulated"
        or account.is_active is not True
        or account.user_id != owner_id
        or binding.account_id != account.pk
        or binding.attested_by_id != owner_id
        or binding.public_id is None
    ):
        return _unknown()

    locator = str(binding.public_id)
    try:
        head = history_reader.get_head(
            account.pk,
            binding.trade_id,
            principal=principal,
            source_locator=locator,
        )
    except (FeeCorrectionBlockedError, ArithmeticError, TypeError, ValueError):
        return _unknown()
    if head.request_receipt is not None:
        return FeeCorrectionMaterialClassification(
            state="completed",
            reason_code="FEE_CORRECTION_RECOVERY_COMPLETED",
            head=head,
        )

    if current_policy is None:
        return _unknown(head=head)
    current_version = current_policy.version
    if (
        type(current_version) is not int
        or current_version <= 0
        or type(binding.policy_version) is not int
        or binding.policy_version <= 0
        or current_policy.account_id != account.pk
        or current_policy.updated_by_id != owner_id
    ):
        return _unknown(head=head)

    try:
        request = FeeCorrectionRequest(
            account_id=account.pk,
            trade_id=binding.trade_id,
            idempotency_key=binding.idempotency_key,
            expected_revision=binding.expected_revision,
            source_locator=locator,
        )
        request.__post_init__()
    except (FeeCorrectionBlockedError, TypeError, ValueError):
        return _unknown(head=head)

    if current_version == binding.policy_version:
        try:
            verified = evidence_repository.verify(request)
        except (FeeCorrectionBlockedError, ArithmeticError, TypeError, ValueError):
            return _unknown(head=head)
        if type(verified) is VerifiedFeeCorrectionEvidence:
            return FeeCorrectionMaterialClassification(
                state="unresolved",
                reason_code="FEE_CORRECTION_RECOVERY_CONFIRMATION_REQUIRED",
                head=head,
            )
        return _unknown(head=head)

    if current_version < binding.policy_version:
        return _unknown(head=head)
    try:
        fee_correction_policy_sha256(
            account_id=current_policy.account_id,
            version=current_policy.version,
            enabled=current_policy.enabled,
            allows_operator_attested_upload=current_policy.allow_operator_attested_upload,
            ledger_currency=current_policy.ledger_currency,
            valid_from=current_policy.valid_from,
            valid_until=current_policy.valid_until,
            updated_by_id=current_policy.updated_by_id,
        )
        historically_verified = evidence_repository.verify_historical_material(request)
    except (FeeCorrectionBlockedError, ArithmeticError, TypeError, ValueError):
        return _unknown(head=head)
    if historically_verified is True:
        return FeeCorrectionMaterialClassification(
            state="fenced",
            reason_code="FEE_CORRECTION_RECOVERY_POLICY_SUPERSEDED",
            head=head,
        )
    return _unknown(head=head)


def _unknown(*, head: FeeCorrectionHead | None = None) -> FeeCorrectionMaterialClassification:
    """Fail closed when neither exact completion nor source qualification is proven."""

    return FeeCorrectionMaterialClassification(
        state="unknown",
        reason_code="FEE_CORRECTION_RECOVERY_MATERIAL_UNKNOWN",
        head=head,
    )


__all__ = [
    "FeeCorrectionMaterialClassification",
    "FeeCorrectionMaterialEvidenceVerifierProtocol",
    "FeeCorrectionMaterialHistoryReaderProtocol",
    "classify_fee_correction_binding",
]
