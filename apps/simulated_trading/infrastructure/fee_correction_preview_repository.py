"""Transactional owner preview orchestration for simulated fee corrections."""

from __future__ import annotations

import hashlib
from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionReceipt,
    FeeCorrectionRequest,
    VerifiedFeeCorrectionAuthorization,
    VerifiedFeeCorrectionEvidence,
)
from apps.simulated_trading.application.fee_correction_evidence_contracts import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    OPERATOR_ATTESTATION_VERSION,
    OPERATOR_FEE_CSV_SCHEMA,
    FeeCorrectionEvidenceUploadReceipt,
)
from apps.simulated_trading.application.fee_correction_head import (
    FeeCorrectionHeadRepositoryProtocol,
)
from apps.simulated_trading.application.fee_correction_preview import (
    FeeCorrectionPreview,
    FeeCorrectionPreviewCommand,
    FeeCorrectionPreviewRepositoryProtocol,
    FeeCorrectionPreviewResult,
)
from apps.simulated_trading.domain.fee_correction import calculate_fee_correction_delta
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceBindingModel,
)

from .fee_correction_evidence_repository import DjangoFeeCorrectionEvidenceRepository
from .fee_correction_head_repository import DjangoFeeCorrectionHeadRepository


class DjangoFeeCorrectionPreviewRepository(FeeCorrectionPreviewRepositoryProtocol):
    """Keep head selection, evidence capture, and qualification in one transaction."""

    def __init__(
        self,
        *,
        head_repository: FeeCorrectionHeadRepositoryProtocol | None = None,
        evidence_repository: DjangoFeeCorrectionEvidenceRepository | None = None,
    ) -> None:
        """Use existing head and evidence repositories unless tests inject replacements."""

        self._head_repository = (
            head_repository if head_repository is not None else DjangoFeeCorrectionHeadRepository()
        )
        self._evidence_repository = (
            evidence_repository
            if evidence_repository is not None
            else DjangoFeeCorrectionEvidenceRepository()
        )

    def preview(
        self,
        command: FeeCorrectionPreviewCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPreviewResult:
        """Persist or recover one immutable upload and return a validated fee delta."""

        if type(command) is not FeeCorrectionPreviewCommand:
            raise _blocked("费用更正预览命令无效", "FEE_CORRECTION_PREVIEW_INVALID")
        command.__post_init__()
        principal_user_id = _authenticated_principal_user_id(principal)
        if principal_user_id is None:
            raise _blocked(
                "费用更正预览需要有效的已认证账户主体",
                "FEE_CORRECTION_PRINCIPAL_INVALID",
            )

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            head = self._head_repository.get_head(
                command.account_id,
                command.trade_id,
                principal=principal,
                request_key=command.idempotency_key,
            )
            if head.request_receipt is not None:
                self._validate_applied_request_binding(
                    command=command,
                    principal_user_id=principal_user_id,
                    receipt=head.request_receipt,
                )
                return FeeCorrectionPreviewResult(
                    status="already_applied",
                    preview=None,
                    receipt=head.request_receipt,
                )

            binding = self._find_binding(command)
            if binding is not None:
                self._validate_pending_binding_identity(
                    binding=binding,
                    command=command,
                    principal_user_id=principal_user_id,
                )
                if (
                    binding.expected_revision != head.revision
                    or binding.expected_predecessor_id != head.expected_predecessor_id
                ):
                    raise _blocked(
                        "费用更正 head 已变化，原材料不能绑定到新版本",
                        "FEE_CORRECTION_REVISION_CONFLICT",
                    )
                expected_revision = binding.expected_revision
                expected_predecessor_id = binding.expected_predecessor_id
            else:
                expected_revision = head.revision
                expected_predecessor_id = head.expected_predecessor_id

            upload_command = command.to_upload_command(
                expected_revision=expected_revision,
                expected_predecessor_id=expected_predecessor_id,
            )
            upload_receipt = self._evidence_repository.capture(
                upload_command,
                principal=principal,
            )
            request = FeeCorrectionRequest(
                account_id=command.account_id,
                trade_id=command.trade_id,
                idempotency_key=command.idempotency_key,
                expected_revision=expected_revision,
                source_locator=upload_receipt.source_locator,
            )
            evidence = self._evidence_repository.verify(request)
            if type(evidence) is not VerifiedFeeCorrectionEvidence:
                raise _blocked(
                    "上传材料无法通过费用来源验证",
                    "FEE_CORRECTION_SOURCE_UNAVAILABLE",
                )
            evidence.__post_init__()
            self._validate_evidence_binding(
                evidence=evidence,
                upload_receipt=upload_receipt,
                command=command,
                expected_revision=expected_revision,
                expected_predecessor_id=expected_predecessor_id,
            )

            authorization = self._evidence_repository.authorize(
                account_id=command.account_id,
                principal=principal,
            )
            if type(authorization) is not VerifiedFeeCorrectionAuthorization:
                raise _blocked(
                    "没有可验证的账户费用材料权限",
                    "FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
                )
            authorization.__post_init__()
            if (
                authorization.account_id != command.account_id
                or authorization.actor_user_id != principal_user_id
                or authorization.policy_ledger_currency == ""
            ):
                raise _blocked(
                    "费用预览权限与请求账户或主体不匹配",
                    "FEE_CORRECTION_AUTHORITY_SCOPE_MISMATCH",
                )

            delta = calculate_fee_correction_delta(
                evidence.previous_fee_components,
                evidence.revised_fee_components,
            )
            preview = FeeCorrectionPreview(
                account_id=command.account_id,
                trade_id=command.trade_id,
                asset_code=evidence.asset_code,
                ledger_currency=authorization.policy_ledger_currency,
                expected_revision=expected_revision,
                expected_predecessor_id=expected_predecessor_id,
                source_locator=upload_receipt.source_locator,
                content_sha256=upload_receipt.content_sha256,
                payload_sha256=upload_receipt.payload_sha256,
                assurance_class=upload_receipt.assurance_class,
                source_observed_at=evidence.source_observed_at,
                verified_at=evidence.verified_at,
                stored_at=upload_receipt.stored_at,
                as_of=head.as_of,
                previous_fee_components=evidence.previous_fee_components,
                revised_fee_components=evidence.revised_fee_components,
                delta=delta,
            )
            return FeeCorrectionPreviewResult(
                status="preview",
                preview=preview,
                receipt=None,
            )

    @staticmethod
    def _find_binding(
        command: FeeCorrectionPreviewCommand,
    ) -> FeeCorrectionEvidenceBindingModel | None:
        """Read the account-local immutable binding for the submitted key."""

        return (
            FeeCorrectionEvidenceBindingModel._base_manager.using(DEFAULT_DB_ALIAS)
            .select_related("artifact")
            .filter(account_id=command.account_id, idempotency_key=command.idempotency_key)
            .first()
        )

    @staticmethod
    def _validate_pending_binding_identity(
        *,
        binding: FeeCorrectionEvidenceBindingModel,
        command: FeeCorrectionPreviewCommand,
        principal_user_id: int,
    ) -> None:
        """Reject a pending key bound to another trade or owner's attestation."""

        if (
            binding.account_id != command.account_id
            or binding.trade_id != command.trade_id
            or binding.idempotency_key != command.idempotency_key
            or binding.attested_by_id != principal_user_id
            or binding.attestation_version != OPERATOR_ATTESTATION_VERSION
            or binding.attestation_acknowledged is not True
            or binding.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
        ):
            raise _idempotency_conflict()

    @staticmethod
    def _validate_applied_request_binding(
        *,
        command: FeeCorrectionPreviewCommand,
        principal_user_id: int,
        receipt: FeeCorrectionReceipt,
    ) -> None:
        """Require the completed event and original upload to share one exact binding."""

        binding = (
            FeeCorrectionEvidenceBindingModel._base_manager.using(DEFAULT_DB_ALIAS)
            .select_related("artifact")
            .filter(account_id=command.account_id, idempotency_key=command.idempotency_key)
            .first()
        )
        if binding is None:
            raise _idempotency_conflict()
        try:
            artifact = binding.artifact
            raw_bytes_value = artifact.raw_bytes
            raw_bytes = bytes(raw_bytes_value)
        except (ObjectDoesNotExist, TypeError, ValueError):
            raise _idempotency_conflict() from None

        event = (
            SimulatedFeeCorrectionEventModel._base_manager.using(DEFAULT_DB_ALIAS)
            .filter(pk=receipt.event_id)
            .first()
        )
        content_sha256 = hashlib.sha256(command.content).hexdigest()
        if (
            event is None
            or receipt.replayed is not True
            or receipt.account_id != command.account_id
            or receipt.trade_id != command.trade_id
            or event.account_id != command.account_id
            or event.trade_id != command.trade_id
            or event.actor_user_id != principal_user_id
            or event.idempotency_key != command.idempotency_key
            or event.revision != receipt.revision
            or event.request_payload_hash != receipt.payload_hash
            or event.source_namespace != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or event.source_record_id != str(binding.public_id)
            or binding.account_id != command.account_id
            or binding.trade_id != command.trade_id
            or binding.idempotency_key != command.idempotency_key
            or binding.attested_by_id != principal_user_id
            or binding.attestation_version != OPERATOR_ATTESTATION_VERSION
            or binding.attestation_acknowledged is not True
            or binding.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or binding.expected_revision + 1 != event.revision
            or binding.expected_predecessor_id != event.previous_event_id
            or artifact.account_id != command.account_id
            or artifact.uploaded_by_id != principal_user_id
            or artifact.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or artifact.schema_version != OPERATOR_FEE_CSV_SCHEMA
            or artifact.content_sha256 != content_sha256
            or binding.content_sha256 != content_sha256
            or bytes(raw_bytes) != command.content
            or binding.payload_sha256 != artifact.payload_sha256
            or binding.content_sha256 != artifact.content_sha256
        ):
            raise _idempotency_conflict()

    @staticmethod
    def _validate_evidence_binding(
        *,
        evidence: VerifiedFeeCorrectionEvidence,
        upload_receipt: FeeCorrectionEvidenceUploadReceipt,
        command: FeeCorrectionPreviewCommand,
        expected_revision: int,
        expected_predecessor_id: int | None,
    ) -> None:
        """Keep verified source and persisted receipt aligned to this exact upload."""

        if (
            evidence.account_id != command.account_id
            or evidence.trade_id != command.trade_id
            or evidence.expected_revision != expected_revision
            or evidence.expected_predecessor_id != expected_predecessor_id
            or evidence.source_record_id != upload_receipt.source_locator
            or evidence.source_namespace != upload_receipt.assurance_class
            or evidence.evidence_sha256 != upload_receipt.content_sha256
            or evidence.source_payload_sha256 != upload_receipt.payload_sha256
            or upload_receipt.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or upload_receipt.content_sha256 != hashlib.sha256(command.content).hexdigest()
            or type(upload_receipt.stored_at) is not datetime
            or upload_receipt.stored_at.tzinfo is None
            or upload_receipt.stored_at.utcoffset() is None
            or upload_receipt.stored_at > evidence.verified_at
        ):
            raise _blocked(
                "费用验证结果与原始上传绑定不一致",
                "FEE_CORRECTION_SOURCE_SCOPE_MISMATCH",
            )


def _authenticated_principal_user_id(
    principal: AuthenticatedFeeCorrectionPrincipalProtocol,
) -> int | None:
    """Narrow the request principal without accepting a body-supplied actor."""

    user_id = getattr(principal, "pk", None)
    if (
        getattr(principal, "is_authenticated", None) is not True
        or type(user_id) is not int
        or user_id <= 0
    ):
        return None
    return user_id


def _idempotency_conflict() -> FeeCorrectionBlockedError:
    """Return the stable denial for a reused key with a different binding."""

    return _blocked(
        "费用更正幂等键已绑定到其他材料、主体或成交",
        "FEE_CORRECTION_EVIDENCE_IDEMPOTENCY_CONFLICT",
    )


def _blocked(message: str, code: str) -> FeeCorrectionBlockedError:
    """Construct the application's recognized fee-correction error."""

    return FeeCorrectionBlockedError(message, code=code)


__all__ = ["DjangoFeeCorrectionPreviewRepository"]
