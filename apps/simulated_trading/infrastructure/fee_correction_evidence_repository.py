"""Django local artifact store and verifier for operator-attested fee evidence."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionRequest,
    VerifiedFeeCorrectionAuthorization,
    VerifiedFeeCorrectionEvidence,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    OPERATOR_ATTESTATION_VERSION,
    OPERATOR_FEE_CSV_SCHEMA,
    CorrectableFeeComponents,
    FeeCorrectionEvidencePersistedEventSnapshot,
    FeeCorrectionEvidencePredecessorSnapshot,
    FeeCorrectionEvidenceUploadCommand,
    FeeCorrectionEvidenceUploadReceipt,
    FeeCorrectionEvidenceVerificationSnapshot,
    FeeCorrectionPolicySnapshotJSON,
    FeeEvidenceParsedMetadataJSON,
    FeeEvidenceRawRowJSON,
    PersistedFeeCorrectionEventProof,
    TradeEconomicFingerprintInput,
    fee_correction_policy_sha256,
    fee_correction_policy_snapshot_json,
    operator_fee_evidence_row_matches_trade,
    trade_economic_fingerprint_sha256,
    verify_fee_correction_evidence_snapshot,
    verify_persisted_fee_correction_event_snapshot,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)

from .fee_correction_evidence_codec import (
    FeeEvidenceCsvParseError,
    parse_operator_fee_evidence_csv,
)
from .fee_correction_evidence_receipt_codec import (
    SimulatedFillReceiptSnapshotProtocol,
    receipt_snapshot_sha256,
)
from .fee_correction_recovery_support import classify_fee_correction_binding


class DjangoFeeCorrectionEvidenceRepository:
    """Persist local uploads and re-read every proof input at qualification time."""

    def authorize(
        self,
        *,
        account_id: int,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> VerifiedFeeCorrectionAuthorization | None:
        """Authorize a live request principal against locked owner and policy rows."""

        principal_user_id = _authenticated_principal_user_id(principal)
        if type(account_id) is not int or account_id <= 0 or principal_user_id is None:
            return None
        with transaction.atomic():
            account = (
                SimulatedAccountModel.objects.select_for_update().filter(pk=account_id).first()
            )
            if (
                account is None
                or account.account_type != "simulated"
                or account.is_active is not True
                or type(account.user_id) is not int
                or account.user_id != principal_user_id
            ):
                return None
            user_model = get_user_model()
            actor = (
                user_model._base_manager.select_for_update().filter(pk=principal_user_id).first()
            )
            if actor is None or getattr(actor, "is_active", None) is not True:
                return None
            policy = (
                FeeCorrectionEvidencePolicyModel.objects.select_for_update()
                .filter(account_id=account.pk)
                .first()
            )
            authorized_at = timezone.now()
            if (
                policy is None
                or not _policy_allows_operator_attested_upload(policy, authorized_at)
                or policy.updated_by_id != account.user_id
            ):
                return None
            policy_sha256 = _policy_hash(policy)
            return VerifiedFeeCorrectionAuthorization(
                account_id=account.pk,
                actor_user_id=principal_user_id,
                authority_identity="local.owner_policy.v1",
                authority_record_id=f"fee-correction-policy:{policy.pk}:v{policy.version}",
                authority_sha256=policy_sha256,
                policy_version=policy.version,
                policy_sha256=policy_sha256,
                policy_ledger_currency=policy.ledger_currency,
                policy_enabled=policy.enabled,
                policy_allows_operator_attested_upload=policy.allow_operator_attested_upload,
                policy_valid_from=policy.valid_from,
                policy_valid_until=policy.valid_until,
                policy_updated_by_id=policy.updated_by_id,
                principal_enabled=True,
                authorization_scope="simulated_fee_correction:operator_attested_upload",
            )

    def hash_trade(
        self,
        *,
        trade: SimulatedTradeModel,
        original_v4_receipt_hash: str | None,
    ) -> str:
        """Return the Application codec hash for one locked Trade and V4 seal."""

        receipt = _optional_fill_receipt(trade)
        current_receipt_hash = receipt.receipt_hash if receipt is not None else None
        if current_receipt_hash != original_v4_receipt_hash:
            raise ValueError("supplied V4 receipt hash differs from the Trade's receipt")
        account = trade.account
        owner_id = account.user_id
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError("Trade owner is not a persisted user")
        snapshot = _trade_fingerprint_input(
            trade,
            owner_id,
            original_v4_receipt_hash=current_receipt_hash,
        )
        return trade_economic_fingerprint_sha256(snapshot)

    def capture(
        self,
        command: FeeCorrectionEvidenceUploadCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionEvidenceUploadReceipt:
        """Store immutable bytes only for an authenticated current account owner."""

        command.__post_init__()
        principal_user_id = _authenticated_principal_user_id(principal)
        if principal_user_id is None:
            raise FeeCorrectionBlockedError(
                "费用材料上传需要有效的已认证账户主体",
                code="FEE_CORRECTION_PRINCIPAL_INVALID",
            )
        try:
            parsed = parse_operator_fee_evidence_csv(command.content)
        except FeeEvidenceCsvParseError as error:
            raise FeeCorrectionBlockedError(
                "费用材料不符合单行规范 CSV 契约",
                code="FEE_CORRECTION_EVIDENCE_INVALID",
            ) from error
        content_sha256 = _sha256(command.content)
        with transaction.atomic():
            account = (
                SimulatedAccountModel.objects.select_for_update()
                .filter(pk=command.account_id)
                .first()
            )
            if (
                account is None
                or account.account_type != "simulated"
                or account.is_active is not True
                or type(account.user_id) is not int
                or account.user_id != principal_user_id
            ):
                raise FeeCorrectionBlockedError(
                    "只有当前账户所有者可绑定费用材料到模拟账户",
                    code="FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
                )
            user_model = get_user_model()
            actor = (
                user_model._base_manager.select_for_update().filter(pk=principal_user_id).first()
            )
            if actor is None or getattr(actor, "is_active", None) is not True:
                raise FeeCorrectionBlockedError(
                    "费用材料上传主体已停用或不存在",
                    code="FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
                )
            policy = (
                FeeCorrectionEvidencePolicyModel.objects.select_for_update()
                .filter(account_id=account.pk)
                .first()
            )
            now = timezone.now()
            if policy is None or not _policy_allows_operator_attested_upload(policy, now):
                raise FeeCorrectionBlockedError(
                    "该账户当前没有允许操作者声明材料的有效业务策略",
                    code="FEE_CORRECTION_POLICY_DENIED",
                )
            if policy.updated_by_id != account.user_id:
                raise FeeCorrectionBlockedError(
                    "费用资格策略未由当前账户所有者确认",
                    code="FEE_CORRECTION_POLICY_DENIED",
                )
            if parsed.currency_code != policy.ledger_currency:
                raise FeeCorrectionBlockedError(
                    "费用材料币种与该账户明示账本币种不一致",
                    code="FEE_CORRECTION_CURRENCY_MISMATCH",
                )
            trade = (
                SimulatedTradeModel.objects.select_for_update()
                .filter(pk=command.trade_id, account_id=account.pk)
                .first()
            )
            if trade is None or trade.status != "executed":
                raise FeeCorrectionBlockedError(
                    "目标必须是该模拟账户内已执行的精确成交",
                    code="FEE_CORRECTION_TRADE_SCOPE_INVALID",
                )
            receipt = _optional_fill_receipt(trade)
            receipt_hash = receipt.receipt_hash if receipt is not None else None
            trade_snapshot = _trade_fingerprint_input(
                trade,
                account.user_id,
                original_v4_receipt_hash=receipt_hash,
            )
            try:
                trade_snapshot_hash = trade_economic_fingerprint_sha256(trade_snapshot)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise FeeCorrectionBlockedError(
                    "目标成交缺少可稳定绑定的经济身份字段",
                    code="FEE_CORRECTION_TRADE_SNAPSHOT_INVALID",
                ) from error
            if not operator_fee_evidence_row_matches_trade(parsed, trade_snapshot):
                raise FeeCorrectionBlockedError(
                    "上传行与用户选择的精确模拟成交经济字段不匹配",
                    code="FEE_CORRECTION_TRADE_SCOPE_MISMATCH",
                )
            policy_sha256 = _policy_hash(policy)
            policy_snapshot = _policy_snapshot(policy)
            existing = (
                FeeCorrectionEvidenceBindingModel.objects.select_for_update()
                .filter(account_id=account.pk, idempotency_key=command.idempotency_key)
                .select_related("artifact")
                .first()
            )
            if existing is not None:
                if (
                    existing.trade_id != trade.pk
                    or existing.attested_by_id != principal_user_id
                    or existing.attestation_version != OPERATOR_ATTESTATION_VERSION
                    or existing.attestation_acknowledged is not True
                    or existing.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
                    or existing.expected_revision != command.expected_revision
                    or existing.expected_predecessor_id != command.expected_predecessor_id
                    or existing.trade_snapshot_sha256 != trade_snapshot_hash
                    or existing.policy_version != policy.version
                    or existing.policy_sha256 != policy_sha256
                    or existing.artifact.original_filename != command.original_filename
                    or existing.artifact.content_sha256 != content_sha256
                    or existing.artifact.payload_sha256 != parsed.payload_sha256
                    or existing.artifact.uploaded_by_id != principal_user_id
                    or existing.artifact.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
                    or existing.artifact.schema_version != OPERATOR_FEE_CSV_SCHEMA
                    or existing.artifact.raw_row_json != parsed.raw_row
                    or existing.artifact.parsed_metadata_json != parsed.parsed_metadata
                    or existing.content_sha256 != content_sha256
                    or existing.payload_sha256 != parsed.payload_sha256
                    or existing.policy_snapshot_json != policy_snapshot
                    or bytes(existing.artifact.raw_bytes) != command.content
                ):
                    raise FeeCorrectionBlockedError(
                        "费用材料幂等键已绑定到不同内容或成交",
                        code="FEE_CORRECTION_EVIDENCE_IDEMPOTENCY_CONFLICT",
                    )
                return _upload_receipt(existing, existing.artifact)

            # The account lock serializes capture with policy writes. Inspect every
            # binding for this Trade; the display page limit is never a write guard.
            from .fee_correction_head_repository import DjangoFeeCorrectionHeadRepository

            history_reader = DjangoFeeCorrectionHeadRepository()

            existing_trade_bindings = (
                FeeCorrectionEvidenceBindingModel._base_manager.select_for_update()
                .filter(account_id=account.pk, trade_id=trade.pk)
                .select_related("artifact", "policy")
                .order_by("public_id")
            )
            for existing_binding in existing_trade_bindings.iterator(chunk_size=100):
                classification = classify_fee_correction_binding(
                    existing_binding,
                    account=account,
                    current_policy=policy,
                    principal=principal,
                    evidence_repository=self,
                    history_reader=history_reader,
                )
                if classification.state in ("unresolved", "unknown"):
                    raise FeeCorrectionBlockedError(
                        "该成交存在尚未处理或无法验证的费用材料，请先通过恢复流程核对",
                        code="FEE_CORRECTION_RECOVERY_REQUIRED",
                    )

            artifact = FeeCorrectionEvidenceArtifactModel.objects.create(
                account=account,
                uploaded_by_id=principal_user_id,
                original_filename=command.original_filename,
                assurance_class=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
                schema_version=OPERATOR_FEE_CSV_SCHEMA,
                raw_bytes=command.content,
                content_sha256=content_sha256,
                payload_sha256=parsed.payload_sha256,
                raw_row_json=parsed.raw_row,
                parsed_metadata_json=parsed.parsed_metadata,
                uploaded_at=now,
            )
            binding = FeeCorrectionEvidenceBindingModel.objects.create(
                account=account,
                trade=trade,
                artifact=artifact,
                policy=policy,
                idempotency_key=command.idempotency_key,
                attested_by_id=principal_user_id,
                attestation_version=OPERATOR_ATTESTATION_VERSION,
                attestation_acknowledged=True,
                assurance_class=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
                expected_revision=command.expected_revision,
                expected_predecessor_id=command.expected_predecessor_id,
                content_sha256=content_sha256,
                payload_sha256=parsed.payload_sha256,
                trade_snapshot_sha256=trade_snapshot_hash,
                policy_version=policy.version,
                policy_sha256=policy_sha256,
                policy_snapshot_json=policy_snapshot,
                created_at=now,
            )
            return _upload_receipt(binding, artifact)

    def verify(self, request: FeeCorrectionRequest) -> VerifiedFeeCorrectionEvidence | None:
        """Reread and validate the local artifact, current policy, and Trade proof."""

        return self._verify(request, historical_policy=False)

    def verify_historical_material(self, request: FeeCorrectionRequest) -> bool:
        """Validate only whether a stored source is intact under its captured policy."""

        return type(self._verify(request, historical_policy=True)) is VerifiedFeeCorrectionEvidence

    def _verify(
        self,
        request: FeeCorrectionRequest,
        *,
        historical_policy: bool,
    ) -> VerifiedFeeCorrectionEvidence | None:
        """Share exact source proof checks while selecting current or captured policy facts."""

        try:
            request.__post_init__()
            binding_uuid = UUID(request.source_locator)
        except (TypeError, ValueError, FeeCorrectionBlockedError):
            return None
        if str(binding_uuid) != request.source_locator:
            return None
        with transaction.atomic():
            binding = FeeCorrectionEvidenceBindingModel.objects.filter(
                public_id=binding_uuid
            ).first()
            if binding is None:
                return None
            if binding.account_id != request.account_id or binding.trade_id != request.trade_id:
                return None
            if binding.idempotency_key != request.idempotency_key:
                raise FeeCorrectionBlockedError(
                    "费用材料幂等键与更正请求编号不一致",
                    code="FEE_CORRECTION_IDEMPOTENCY_CONFLICT",
                )
            account = (
                SimulatedAccountModel.objects.select_for_update()
                .filter(pk=binding.account_id)
                .first()
            )
            if account is None:
                return None
            policy = (
                FeeCorrectionEvidencePolicyModel.objects.select_for_update()
                .filter(pk=binding.policy_id, account_id=account.pk)
                .first()
            )
            trade = (
                SimulatedTradeModel.objects.select_for_update()
                .filter(pk=binding.trade_id, account_id=account.pk)
                .first()
            )
            artifact = FeeCorrectionEvidenceArtifactModel.objects.filter(
                pk=binding.artifact_id
            ).first()
            if (
                policy is None
                or trade is None
                or artifact is None
                or artifact.account_id != request.account_id
                or account.account_type != "simulated"
                or account.is_active is not True
                or type(account.user_id) is not int
                or trade.status != "executed"
            ):
                return None
            raw_value = artifact.raw_bytes
            if not isinstance(raw_value, (bytes, bytearray, memoryview)):
                return None
            raw_bytes = bytes(raw_value)
            try:
                parsed = parse_operator_fee_evidence_csv(raw_bytes)
            except FeeEvidenceCsvParseError:
                return None
            raw_row = _narrow_raw_row(artifact.raw_row_json)
            if raw_row is None:
                return None
            parsed_metadata = _narrow_parsed_metadata(
                artifact.parsed_metadata_json,
                parsed.parsed_metadata,
            )
            policy_snapshot = _narrow_policy_snapshot(binding.policy_snapshot_json)
            if parsed_metadata is None or policy_snapshot is None:
                return None
            if historical_policy:
                created_at = binding.created_at
                now = timezone.now()
                if (
                    type(created_at) is not datetime
                    or created_at.tzinfo is None
                    or created_at.utcoffset() is None
                    or created_at > now
                ):
                    return None
                policy_values = _historical_policy_values(
                    policy_snapshot,
                    account_id=account.pk,
                    owner_id=account.user_id,
                    binding_version=binding.policy_version,
                    binding_actor_id=binding.attested_by_id,
                )
                if policy_values is None:
                    return None
                (
                    policy_version,
                    policy_enabled,
                    policy_allows_upload,
                    policy_ledger_currency,
                    policy_valid_from,
                    policy_valid_until,
                    policy_updated_by_id,
                ) = policy_values
                verified_at = created_at
            else:
                policy_version = policy.version
                policy_enabled = policy.enabled
                policy_allows_upload = policy.allow_operator_attested_upload
                policy_ledger_currency = policy.ledger_currency
                policy_valid_from = policy.valid_from
                policy_valid_until = policy.valid_until
                policy_updated_by_id = policy.updated_by_id
                verified_at = timezone.now()
            predecessor: FeeCorrectionEvidencePredecessorSnapshot | None = None
            if binding.expected_revision == 0:
                if binding.expected_predecessor_id is not None:
                    return None
            else:
                if (
                    type(binding.expected_revision) is not int
                    or binding.expected_revision <= 0
                    or type(binding.expected_predecessor_id) is not int
                    or binding.expected_predecessor_id <= 0
                ):
                    return None
                predecessor_row = SimulatedFeeCorrectionEventModel._base_manager.filter(
                    account_id=binding.account_id,
                    trade_id=binding.trade_id,
                    revision=binding.expected_revision,
                    pk=binding.expected_predecessor_id,
                ).first()
                if predecessor_row is None:
                    return None
                try:
                    predecessor = FeeCorrectionEvidencePredecessorSnapshot(
                        account_id=predecessor_row.account_id,
                        trade_id=predecessor_row.trade_id,
                        revision=predecessor_row.revision,
                        event_id=predecessor_row.pk,
                        revised_fee_components=CorrectableFeeComponents(
                            commission=predecessor_row.revised_commission,
                            transfer_fee=predecessor_row.revised_transfer_fee,
                            stamp_duty=predecessor_row.revised_stamp_duty,
                        ),
                    )
                except (ArithmeticError, TypeError, ValueError):
                    return None
            try:
                receipt = _optional_fill_receipt(trade)
                receipt_hash = receipt.receipt_hash if receipt is not None else None
                trade_snapshot = _trade_fingerprint_input(
                    trade,
                    account.user_id,
                    original_v4_receipt_hash=receipt_hash,
                )
            except (ArithmeticError, TypeError, ValueError):
                return None
            snapshot = FeeCorrectionEvidenceVerificationSnapshot(
                binding_locator=str(binding.public_id),
                artifact_account_id=artifact.account_id,
                artifact_uploaded_by_id=artifact.uploaded_by_id,
                artifact_bytes=raw_bytes,
                artifact_sha256=artifact.content_sha256,
                artifact_payload_sha256=artifact.payload_sha256,
                artifact_raw_row=raw_row,
                artifact_parsed_metadata=parsed_metadata,
                artifact_uploaded_at=artifact.uploaded_at,
                artifact_schema_version=artifact.schema_version,
                artifact_assurance_class=artifact.assurance_class,
                binding_account_id=binding.account_id,
                binding_trade_id=binding.trade_id,
                binding_attested_by_id=binding.attested_by_id,
                binding_attestation_version=binding.attestation_version,
                binding_attestation_acknowledged=binding.attestation_acknowledged,
                binding_assurance_class=binding.assurance_class,
                binding_content_sha256=binding.content_sha256,
                binding_payload_sha256=binding.payload_sha256,
                binding_created_at=binding.created_at,
                binding_idempotency_key=binding.idempotency_key,
                binding_expected_revision=binding.expected_revision,
                binding_expected_predecessor_id=binding.expected_predecessor_id,
                binding_trade_snapshot_sha256=binding.trade_snapshot_sha256,
                binding_policy_version=binding.policy_version,
                binding_policy_sha256=binding.policy_sha256,
                policy_ledger_currency=policy_ledger_currency,
                binding_policy_snapshot=policy_snapshot,
                current_account_id=account.pk,
                current_account_owner_id=account.user_id,
                policy_account_id=policy.account_id,
                policy_version=policy_version,
                policy_enabled=policy_enabled,
                policy_allows_operator_attested_upload=policy_allows_upload,
                policy_valid_from=policy_valid_from,
                policy_valid_until=policy_valid_until,
                policy_updated_by_id=policy_updated_by_id,
                trade=trade_snapshot,
                predecessor=predecessor,
                parsed_upload=parsed,
            )
            return verify_fee_correction_evidence_snapshot(
                snapshot,
                request,
                verified_at=verified_at,
            )

    def verify_persisted_event(
        self,
        proof: PersistedFeeCorrectionEventProof,
    ) -> bool | None:
        """Revalidate historical source bytes and policy snapshot for one event.

        This method checks only evidence provenance and binding. The caller
        must validate the event's persisted authority record separately.
        """

        if type(proof) is not PersistedFeeCorrectionEventProof:
            return False
        try:
            proof.__post_init__()
            binding_uuid = UUID(proof.source_record_id)
        except (TypeError, ValueError):
            return False
        if str(binding_uuid) != proof.source_record_id:
            return False
        binding = FeeCorrectionEvidenceBindingModel.objects.filter(public_id=binding_uuid).first()
        if binding is None:
            return None
        if binding.account_id != proof.account_id or binding.trade_id != proof.trade_id:
            return False
        artifact = FeeCorrectionEvidenceArtifactModel.objects.filter(pk=binding.artifact_id).first()
        trade = SimulatedTradeModel.objects.filter(
            pk=binding.trade_id,
            account_id=binding.account_id,
        ).first()
        account_exists = SimulatedAccountModel.objects.filter(pk=binding.account_id).exists()
        if artifact is None or trade is None or not account_exists:
            return False
        raw_value = artifact.raw_bytes
        if not isinstance(raw_value, (bytes, bytearray, memoryview)):
            return False
        raw_bytes = bytes(raw_value)
        try:
            parsed = parse_operator_fee_evidence_csv(raw_bytes)
            receipt = _optional_fill_receipt(trade)
            receipt_hash = receipt.receipt_hash if receipt is not None else None
            receipt_snapshot = receipt_snapshot_sha256(receipt) if receipt is not None else None
            trade_snapshot = _trade_fingerprint_input(
                trade,
                binding.attested_by_id,
                original_v4_receipt_hash=receipt_hash,
            )
        except (ArithmeticError, TypeError, ValueError, FeeEvidenceCsvParseError):
            return False
        raw_row = _narrow_raw_row(artifact.raw_row_json)
        parsed_metadata = _narrow_parsed_metadata(
            artifact.parsed_metadata_json,
            parsed.parsed_metadata,
        )
        policy_snapshot = _narrow_policy_snapshot(binding.policy_snapshot_json)
        if raw_row is None or parsed_metadata is None or policy_snapshot is None:
            return False
        snapshot = FeeCorrectionEvidencePersistedEventSnapshot(
            binding_locator=str(binding.public_id),
            binding_account_id=binding.account_id,
            binding_trade_id=binding.trade_id,
            binding_attested_by_id=binding.attested_by_id,
            binding_attestation_version=binding.attestation_version,
            binding_attestation_acknowledged=binding.attestation_acknowledged,
            binding_assurance_class=binding.assurance_class,
            binding_expected_revision=binding.expected_revision,
            binding_expected_predecessor_id=binding.expected_predecessor_id,
            binding_content_sha256=binding.content_sha256,
            binding_payload_sha256=binding.payload_sha256,
            binding_created_at=binding.created_at,
            binding_trade_snapshot_sha256=binding.trade_snapshot_sha256,
            binding_policy_version=binding.policy_version,
            binding_policy_sha256=binding.policy_sha256,
            binding_policy_snapshot=policy_snapshot,
            artifact_account_id=artifact.account_id,
            artifact_uploaded_by_id=artifact.uploaded_by_id,
            artifact_bytes=raw_bytes,
            artifact_sha256=artifact.content_sha256,
            artifact_payload_sha256=artifact.payload_sha256,
            artifact_raw_row=raw_row,
            artifact_parsed_metadata=parsed_metadata,
            artifact_uploaded_at=artifact.uploaded_at,
            artifact_schema_version=artifact.schema_version,
            artifact_assurance_class=artifact.assurance_class,
            trade=trade_snapshot,
            receipt_snapshot_hash=receipt_snapshot,
            parsed_upload=parsed,
        )
        return verify_persisted_fee_correction_event_snapshot(snapshot, proof)


def _authenticated_principal_user_id(principal: object) -> int | None:
    """Narrow an authenticated Django request user, including lazy request.user."""

    if principal is None or not isinstance(principal, get_user_model()):
        return None
    authenticated = getattr(principal, "is_authenticated", None)
    user_id = getattr(principal, "pk", None)
    if (
        type(authenticated) is not bool
        or authenticated is not True
        or type(user_id) is not int
        or user_id <= 0
    ):
        return None
    return user_id


def _currency_token(value: object) -> bool:
    """Require a configured uppercase code without guessing or converting units."""

    return (
        type(value) is str
        and len(value) == 3
        and all("A" <= character <= "Z" for character in value)
    )


def _policy_allows_operator_attested_upload(
    policy: FeeCorrectionEvidencePolicyModel,
    now: datetime,
) -> bool:
    """Require explicit current owner-scoped policy enablement and an updater."""

    if (
        policy.enabled is not True
        or policy.allow_operator_attested_upload is not True
        or type(policy.version) is not int
        or policy.version <= 0
        or not _currency_token(policy.ledger_currency)
        or type(policy.updated_by_id) is not int
        or policy.updated_by_id <= 0
    ):
        return False
    if policy.valid_from is not None:
        if policy.valid_from.tzinfo is None or policy.valid_from.utcoffset() is None:
            return False
        if now < policy.valid_from:
            return False
    if policy.valid_until is not None:
        if policy.valid_until.tzinfo is None or policy.valid_until.utcoffset() is None:
            return False
        if now >= policy.valid_until:
            return False
    return True


def _policy_hash(policy: FeeCorrectionEvidencePolicyModel) -> str:
    """Digest the exact business qualification policy version."""

    return fee_correction_policy_sha256(
        account_id=policy.account_id,
        version=policy.version,
        enabled=policy.enabled,
        allows_operator_attested_upload=policy.allow_operator_attested_upload,
        ledger_currency=policy.ledger_currency,
        valid_from=policy.valid_from,
        valid_until=policy.valid_until,
        updated_by_id=policy.updated_by_id,
    )


def _policy_snapshot(
    policy: FeeCorrectionEvidencePolicyModel,
) -> FeeCorrectionPolicySnapshotJSON:
    """Build the exact JSON-safe policy snapshot stored with a binding."""

    return fee_correction_policy_snapshot_json(
        account_id=policy.account_id,
        version=policy.version,
        enabled=policy.enabled,
        allows_operator_attested_upload=policy.allow_operator_attested_upload,
        ledger_currency=policy.ledger_currency,
        valid_from=policy.valid_from,
        valid_until=policy.valid_until,
        updated_by_id=policy.updated_by_id,
    )


def _trade_fingerprint_input(
    trade: SimulatedTradeModel,
    account_owner_id: int,
    *,
    original_v4_receipt_hash: str | None,
) -> TradeEconomicFingerprintInput:
    """Narrow current ORM Trade and its immutable V4 receipt hash."""
    return TradeEconomicFingerprintInput(
        account_id=trade.account_id,
        account_owner_id=account_owner_id,
        trade_id=trade.pk,
        asset_code=trade.asset_code,
        asset_name=trade.asset_name,
        asset_type=trade.asset_type,
        action=trade.action,
        quantity=trade.quantity,
        price=trade.price,
        amount=trade.amount,
        commission=trade.commission,
        transfer_fee=trade.transfer_fee,
        stamp_duty=trade.stamp_duty,
        slippage=trade.slippage,
        total_cost=trade.total_cost,
        fee_amounts_known=trade.fee_amounts_known,
        cost_basis_known=trade.cost_basis_known,
        realized_pnl=trade.realized_pnl,
        realized_pnl_pct=trade.realized_pnl_pct,
        order_date=trade.order_date,
        execution_date=trade.execution_date,
        execution_time=trade.execution_time,
        status=trade.status,
        idempotency_key=trade.idempotency_key,
        request_payload_hash=trade.request_payload_hash,
        fee_config_id=trade.fee_config_id,
        fee_schedule_hash=trade.fee_schedule_hash,
        fee_precision_basis=trade.fee_precision_basis,
        fee_calculation_purpose=trade.fee_calculation_purpose,
        fee_rounding_policy=trade.fee_rounding_policy,
        settlement_security_id=trade.settlement_security_id,
        settlement_market=trade.settlement_market,
        settlement_exchange=trade.settlement_exchange,
        settlement_board=trade.settlement_board,
        settlement_market_session=trade.settlement_market_session,
        settlement_lag_sessions=trade.settlement_lag_sessions,
        settlement_plan_binding_version=trade.settlement_plan_binding_version,
        settlement_plan_binding_hash=trade.settlement_plan_binding_hash,
        settlement_bundle_id=trade.settlement_bundle_id,
        settlement_bundle_version=trade.settlement_bundle_version,
        settlement_bundle_hash=trade.settlement_bundle_hash,
        settlement_policy_id=trade.settlement_policy_id,
        settlement_policy_version=trade.settlement_policy_version,
        settlement_policy_hash=trade.settlement_policy_hash,
        execution_rule_v2_hash=trade.execution_rule_v2_hash,
        original_v4_receipt_hash=original_v4_receipt_hash,
    )


def _optional_fill_receipt(
    trade: SimulatedTradeModel,
) -> SimulatedFillReceiptSnapshotProtocol | None:
    """Read a Trade's optional immutable V4 receipt without fabricating one."""

    try:
        receipt_value = getattr(trade, "fill_receipt", None)
    except ObjectDoesNotExist:
        return None
    if receipt_value is None:
        return None
    return cast(SimulatedFillReceiptSnapshotProtocol, receipt_value)


def _narrow_raw_row(value: object) -> FeeEvidenceRawRowJSON | None:
    """Narrow JSONField contents to the exact persisted raw CSV shape."""

    expected_keys = (
        "schema_version",
        "currency_code",
        "source_account_ref",
        "source_trade_ref",
        "asset_code",
        "side",
        "quantity",
        "price",
        "amount",
        "execution_at",
        "source_observed_at",
        "commission",
        "transfer_fee",
        "stamp_duty",
    )
    if not isinstance(value, dict) or set(value) != set(expected_keys):
        return None
    if any(type(value[key]) is not str for key in expected_keys):
        return None
    return cast(FeeEvidenceRawRowJSON, value)


def _narrow_parsed_metadata(
    value: object,
    expected: FeeEvidenceParsedMetadataJSON,
) -> FeeEvidenceParsedMetadataJSON | None:
    """Require the persisted parser precision/null record to match the bytes."""

    if not isinstance(value, dict) or value != expected:
        return None
    return cast(FeeEvidenceParsedMetadataJSON, value)


def _narrow_policy_snapshot(value: object) -> FeeCorrectionPolicySnapshotJSON | None:
    """Narrow an immutable policy snapshot JSON object to its exact schema."""

    keys = {
        "schema",
        "account_id",
        "version",
        "enabled",
        "allows_operator_attested_upload",
        "ledger_currency",
        "valid_from",
        "valid_until",
        "updated_by_id",
    }
    if not isinstance(value, dict) or set(value) != keys:
        return None
    if (
        type(value["schema"]) is not str
        or type(value["account_id"]) is not int
        or type(value["version"]) is not int
        or type(value["enabled"]) is not bool
        or type(value["allows_operator_attested_upload"]) is not bool
        or type(value["ledger_currency"]) is not str
        or not _currency_token(value["ledger_currency"])
        or (value["valid_from"] is not None and type(value["valid_from"]) is not str)
        or (value["valid_until"] is not None and type(value["valid_until"]) is not str)
        or (value["updated_by_id"] is not None and type(value["updated_by_id"]) is not int)
    ):
        return None
    return cast(FeeCorrectionPolicySnapshotJSON, value)


def _historical_policy_values(
    snapshot: FeeCorrectionPolicySnapshotJSON,
    *,
    account_id: int,
    owner_id: int,
    binding_version: int,
    binding_actor_id: int,
) -> tuple[int, bool, bool, str, datetime | None, datetime | None, int | None] | None:
    """Narrow a binding's historical policy without borrowing mutable row fields."""

    version = snapshot["version"]
    updated_by_id = snapshot["updated_by_id"]
    if (
        snapshot["schema"] != "simulated-fee-correction-policy.v2"
        or snapshot["account_id"] != account_id
        or version != binding_version
        or updated_by_id != owner_id
        or updated_by_id != binding_actor_id
    ):
        return None
    valid_from = _parse_policy_timestamp(snapshot["valid_from"])
    valid_until = _parse_policy_timestamp(snapshot["valid_until"])
    if (snapshot["valid_from"] is not None and valid_from is None) or (
        snapshot["valid_until"] is not None and valid_until is None
    ):
        return None
    if valid_from is not None and valid_until is not None and valid_until <= valid_from:
        return None
    return (
        version,
        snapshot["enabled"],
        snapshot["allows_operator_attested_upload"],
        snapshot["ledger_currency"],
        valid_from,
        valid_until,
        updated_by_id,
    )


def _parse_policy_timestamp(value: str | None) -> datetime | None:
    """Parse one JSON policy timestamp only when it is explicitly timezone-aware."""

    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _sha256(content: bytes) -> str:
    """Return the server-computed lowercase SHA-256 for immutable upload bytes."""

    import hashlib

    return hashlib.sha256(content).hexdigest()


def _upload_receipt(
    binding: FeeCorrectionEvidenceBindingModel,
    artifact: FeeCorrectionEvidenceArtifactModel,
) -> FeeCorrectionEvidenceUploadReceipt:
    """Build a storage receipt that remains explicitly unverified."""

    return FeeCorrectionEvidenceUploadReceipt(
        source_locator=str(binding.public_id),
        content_sha256=artifact.content_sha256,
        payload_sha256=artifact.payload_sha256,
        assurance_class=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
        stored_at=artifact.uploaded_at,
    )


__all__ = ["DjangoFeeCorrectionEvidenceRepository"]
