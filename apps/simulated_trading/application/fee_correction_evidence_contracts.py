"""Typed Application contracts for operator-attested fee evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, TypedDict

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
)
from apps.simulated_trading.domain.execution_settlement_primitives import validate_ledger_money
from apps.simulated_trading.domain.fee_correction import CorrectableFeeComponents

from .fee_correction_evidence_values import (
    _valid_sha256,
)

ASSURANCE_OPERATOR_ATTESTED_UPLOAD = "operator_attested_upload"


OPERATOR_FEE_CSV_SCHEMA = "operator-fee-evidence.v2"


OPERATOR_ATTESTATION_VERSION = "operator-fee-attestation.v1"


MAX_UPLOAD_BYTES = 1_048_576


class FeeEvidenceRawRowJSON(TypedDict):
    """Original CSV cell lexemes in the finite v2 schema's canonical order."""

    schema_version: str
    currency_code: str
    source_account_ref: str
    source_trade_ref: str
    asset_code: str
    side: str
    quantity: str
    price: str
    amount: str
    execution_at: str
    source_observed_at: str
    commission: str
    transfer_fee: str
    stamp_duty: str


class FeeEvidenceFeeMetadataJSON(TypedDict):
    """One fee's original lexeme, known status, precision, and parsed value."""

    field: str
    raw: str
    known: bool
    precision: int | None
    value: str | None


class FeeEvidenceParsedMetadataJSON(TypedDict):
    """Canonical typed values kept beside the immutable original CSV bytes."""

    schema: str
    currency_code: str
    quantity: str
    price: str
    amount: str
    execution_at_utc: str
    source_observed_at_utc: str
    fees: list[FeeEvidenceFeeMetadataJSON]


class FeeCorrectionPolicySnapshotJSON(TypedDict):
    """Immutable policy values captured by the owner-attested binding."""

    schema: str
    account_id: int
    version: int
    enabled: bool
    allows_operator_attested_upload: bool
    ledger_currency: str
    valid_from: str | None
    valid_until: str | None
    updated_by_id: int | None


class FeeCorrectionFeeComponentsJSON(TypedDict):
    """Exact fixed-scale monetary fields sealed into a correction event."""

    commission: str
    transfer_fee: str
    stamp_duty: str


class FeeCorrectionAuthorityEventSnapshotJSON(TypedDict):
    """Server-recorded authorization facts bound to one committed fee event."""

    schema: str
    account_id: int
    account_owner_user_id: int
    account_type: str
    account_active: bool
    actor_user_id: int
    actor_authenticated: bool
    principal_enabled: bool
    authority_identity: str
    authority_record_id: str
    authority_sha256: str
    authorization_scope: str
    policy_version: int
    policy_sha256: str
    policy_ledger_currency: str
    policy_enabled: bool
    policy_allows_operator_attested_upload: bool
    policy_valid_from: str | None
    policy_valid_until: str | None
    policy_updated_by_id: int | None
    trade_id: int
    trade_snapshot_hash: str
    original_v4_receipt_hash: str | None
    receipt_snapshot_hash: str | None
    source_namespace: str
    source_record_id: str
    verifier_identity: str
    source_evidence_hash: str
    source_payload_hash: str
    source_observed_at: str
    evidence_verified_at: str
    idempotency_key: str
    request_payload_hash: str
    revision: int
    previous_event_id: int | None
    account_revision: int
    account_predecessor_hash: str
    previous_fees: FeeCorrectionFeeComponentsJSON
    revised_fees: FeeCorrectionFeeComponentsJSON
    original_slippage: str
    posting_time: str
    posting_date: str


@dataclass(frozen=True, slots=True)
class OperatorAttestedFeeEvidenceRow:
    """Strictly parsed operator-attested CSV data, retaining fee uncertainty."""

    schema_version: str
    source_account_ref: str
    source_trade_ref: str
    currency_code: str
    asset_code: str
    side: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    execution_at: datetime
    source_observed_at: datetime
    fee_lexemes: tuple[str, str, str]
    fee_amounts: tuple[Decimal | None, Decimal | None, Decimal | None]
    fee_precisions: tuple[int | None, int | None, int | None]
    fee_known: tuple[bool, bool, bool]
    raw_row: FeeEvidenceRawRowJSON
    parsed_metadata: FeeEvidenceParsedMetadataJSON
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class TradeEconomicFingerprintInput:
    """Immutable economic and identity fields used to bind one exact Trade.

    The original V4 receipt hash is included when a Trade has one. Mutable
    settlement release state is deliberately excluded so a later T+1 release
    does not invalidate an otherwise unchanged economic correction binding.
    """

    account_id: int
    account_owner_id: int
    trade_id: int
    asset_code: str
    asset_name: str
    asset_type: str
    action: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    commission: Decimal
    transfer_fee: Decimal | None
    stamp_duty: Decimal | None
    slippage: Decimal
    total_cost: Decimal
    fee_amounts_known: bool | None
    cost_basis_known: bool | None
    realized_pnl: Decimal | None
    realized_pnl_pct: float | None
    order_date: date
    execution_date: date
    execution_time: datetime
    status: str
    idempotency_key: str | None
    request_payload_hash: str | None
    fee_config_id: int | None
    fee_schedule_hash: str | None
    fee_precision_basis: str | None
    fee_calculation_purpose: str | None
    fee_rounding_policy: str | None
    settlement_security_id: str | None
    settlement_market: str | None
    settlement_exchange: str | None
    settlement_board: str | None
    settlement_market_session: date | None
    settlement_lag_sessions: int | None
    settlement_plan_binding_version: int
    settlement_plan_binding_hash: str | None
    settlement_bundle_id: str | None
    settlement_bundle_version: str | None
    settlement_bundle_hash: str | None
    settlement_policy_id: str | None
    settlement_policy_version: str | None
    settlement_policy_hash: str | None
    execution_rule_v2_hash: str | None
    original_v4_receipt_hash: str | None


@dataclass(frozen=True, slots=True)
class FeeCorrectionEvidencePredecessorSnapshot:
    """Exact prior event identity and revised fees bound to one uploaded revision."""

    account_id: int
    trade_id: int
    revision: int
    event_id: int
    revised_fee_components: CorrectableFeeComponents

    def __post_init__(self) -> None:
        """Require a persisted positive event identity and exact fee components."""

        if (
            any(
                type(value) is not int or value <= 0
                for value in (self.account_id, self.trade_id, self.revision, self.event_id)
            )
            or type(self.revised_fee_components) is not CorrectableFeeComponents
        ):
            raise ValueError("fee evidence predecessor identity is invalid")
        self.revised_fee_components.__post_init__()


@dataclass(frozen=True, slots=True)
class FeeCorrectionEvidenceVerificationSnapshot:
    """Typed local records reread by Infrastructure before proof is issued."""

    binding_locator: str
    artifact_account_id: int
    artifact_uploaded_by_id: int
    artifact_bytes: bytes
    artifact_sha256: str
    artifact_payload_sha256: str
    artifact_raw_row: FeeEvidenceRawRowJSON
    artifact_parsed_metadata: FeeEvidenceParsedMetadataJSON
    artifact_uploaded_at: datetime
    artifact_schema_version: str
    artifact_assurance_class: str
    binding_account_id: int
    binding_trade_id: int
    binding_attested_by_id: int
    binding_attestation_version: str
    binding_attestation_acknowledged: bool
    binding_assurance_class: str
    binding_content_sha256: str
    binding_payload_sha256: str
    binding_created_at: datetime
    binding_idempotency_key: str
    binding_expected_revision: int
    binding_expected_predecessor_id: int | None
    binding_trade_snapshot_sha256: str
    binding_policy_version: int
    binding_policy_sha256: str
    policy_ledger_currency: str
    binding_policy_snapshot: FeeCorrectionPolicySnapshotJSON
    current_account_id: int
    current_account_owner_id: int
    policy_account_id: int
    policy_version: int
    policy_enabled: bool
    policy_allows_operator_attested_upload: bool
    policy_valid_from: datetime | None
    policy_valid_until: datetime | None
    policy_updated_by_id: int | None
    trade: TradeEconomicFingerprintInput
    predecessor: FeeCorrectionEvidencePredecessorSnapshot | None
    parsed_upload: OperatorAttestedFeeEvidenceRow


@dataclass(frozen=True, slots=True)
class PersistedFeeCorrectionEventProof:
    """Typed financial event fields required for historical evidence checking."""

    account_id: int
    trade_id: int
    actor_user_id: int
    revision: int
    previous_event_id: int | None
    account_revision: int
    account_predecessor_hash: str
    idempotency_key: str
    request_payload_hash: str
    trade_snapshot_hash: str
    original_v4_receipt_hash: str | None
    receipt_snapshot_hash: str | None
    source_namespace: str
    source_record_id: str
    verifier_identity: str
    source_evidence_hash: str
    source_payload_hash: str
    source_observed_at: datetime
    evidence_verified_at: datetime
    authority_identity: str
    authority_record_id: str
    authority_hash: str
    authority_snapshot_sha256: str
    authority_snapshot_json: FeeCorrectionAuthorityEventSnapshotJSON
    previous_fee_components: CorrectableFeeComponents
    revised_fee_components: CorrectableFeeComponents
    original_slippage: Decimal
    posted_at: datetime
    posting_date: date

    def __post_init__(self) -> None:
        """Reject malformed persisted IDs, digests, fee values, or chronology."""

        if any(
            type(value) is not int or value <= 0
            for value in (
                self.account_id,
                self.trade_id,
                self.actor_user_id,
                self.revision,
                self.account_revision,
            )
        ):
            raise ValueError("persisted correction identity must be positive")
        if self.previous_event_id is not None and (
            type(self.previous_event_id) is not int or self.previous_event_id <= 0
        ):
            raise ValueError("persisted correction predecessor must be positive or null")
        if (self.revision == 1) != (self.previous_event_id is None):
            raise ValueError("per-Trade revision and predecessor are inconsistent")
        if self.account_revision < self.revision:
            raise ValueError("account revision cannot precede the per-Trade revision")
        for value in (
            self.request_payload_hash,
            self.trade_snapshot_hash,
            self.source_evidence_hash,
            self.source_payload_hash,
            self.authority_hash,
            self.authority_snapshot_sha256,
            self.account_predecessor_hash,
        ):
            if not _valid_sha256(value):
                raise ValueError("persisted correction digest is invalid")
        for receipt_digest in (
            self.original_v4_receipt_hash,
            self.receipt_snapshot_hash,
        ):
            if receipt_digest is not None and not _valid_sha256(receipt_digest):
                raise ValueError("persisted receipt digest is invalid")
        if (self.original_v4_receipt_hash is None) != (self.receipt_snapshot_hash is None):
            raise ValueError("persisted V4 receipt hashes must be both present or both absent")
        for locator in (
            self.idempotency_key,
            self.source_namespace,
            self.source_record_id,
            self.verifier_identity,
            self.authority_identity,
            self.authority_record_id,
        ):
            if type(locator) is not str or not locator or locator.strip() != locator:
                raise ValueError("persisted correction locator is invalid")
        if (
            type(self.previous_fee_components) is not CorrectableFeeComponents
            or type(self.revised_fee_components) is not CorrectableFeeComponents
        ):
            raise ValueError("persisted correction fees must be typed components")
        self.previous_fee_components.__post_init__()
        self.revised_fee_components.__post_init__()
        if type(self.original_slippage) is not Decimal or not self.original_slippage.is_finite():
            raise ValueError("persisted original slippage must be a finite Decimal")
        try:
            validate_ledger_money(
                self.original_slippage,
                "persisted.original_slippage",
                allow_zero=True,
            )
        except (ArithmeticError, TypeError, ValueError) as error:
            raise ValueError("persisted original slippage is invalid") from error
        if type(self.posting_date) is not date:
            raise ValueError("persisted posting date must be a date, not a datetime")
        for timestamp in (self.source_observed_at, self.evidence_verified_at, self.posted_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("persisted correction timestamps must be timezone-aware")
        if not (self.source_observed_at <= self.evidence_verified_at <= self.posted_at):
            raise ValueError("persisted correction evidence chronology is invalid")


@dataclass(frozen=True, slots=True)
class FeeCorrectionEvidencePersistedEventSnapshot:
    """Immutable local records used to validate one historical correction event."""

    binding_locator: str
    binding_account_id: int
    binding_trade_id: int
    binding_attested_by_id: int
    binding_attestation_version: str
    binding_attestation_acknowledged: bool
    binding_assurance_class: str
    binding_expected_revision: int
    binding_expected_predecessor_id: int | None
    binding_content_sha256: str
    binding_payload_sha256: str
    binding_created_at: datetime
    binding_trade_snapshot_sha256: str
    binding_policy_version: int
    binding_policy_sha256: str
    binding_policy_snapshot: FeeCorrectionPolicySnapshotJSON
    artifact_account_id: int
    artifact_uploaded_by_id: int
    artifact_bytes: bytes
    artifact_sha256: str
    artifact_payload_sha256: str
    artifact_raw_row: FeeEvidenceRawRowJSON
    artifact_parsed_metadata: FeeEvidenceParsedMetadataJSON
    artifact_uploaded_at: datetime
    artifact_schema_version: str
    artifact_assurance_class: str
    trade: TradeEconomicFingerprintInput
    receipt_snapshot_hash: str | None
    parsed_upload: OperatorAttestedFeeEvidenceRow


@dataclass(frozen=True, slots=True)
class FeeCorrectionEvidenceUploadCommand:
    """One bounded CSV upload explicitly attested by an authenticated owner."""

    account_id: int
    trade_id: int
    expected_revision: int
    expected_predecessor_id: int | None
    idempotency_key: str
    original_filename: str
    content: bytes
    attestation_acknowledged: bool

    def __post_init__(self) -> None:
        """Reject malformed scope, file, and acknowledgement before storage."""

        if any(type(value) is not int or value <= 0 for value in (self.account_id, self.trade_id)):
            raise FeeCorrectionBlockedError(
                "费用证据账户或成交标识无效", code="FEE_CORRECTION_EVIDENCE_INPUT_INVALID"
            )
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise FeeCorrectionBlockedError(
                "费用证据版本无效", code="FEE_CORRECTION_REVISION_CONFLICT"
            )
        if self.expected_predecessor_id is not None and (
            type(self.expected_predecessor_id) is not int or self.expected_predecessor_id <= 0
        ):
            raise FeeCorrectionBlockedError(
                "费用证据前序更正标识无效", code="FEE_CORRECTION_EVIDENCE_INPUT_INVALID"
            )
        if (self.expected_revision == 0) != (self.expected_predecessor_id is None):
            raise FeeCorrectionBlockedError(
                "费用证据版本与前序更正标识不一致",
                code="FEE_CORRECTION_REVISION_CONFLICT",
            )
        if (
            type(self.idempotency_key) is not str
            or not self.idempotency_key
            or self.idempotency_key.strip() != self.idempotency_key
            or len(self.idempotency_key) > 128
            or any(character.isspace() for character in self.idempotency_key)
        ):
            raise FeeCorrectionBlockedError(
                "费用证据幂等键无效", code="FEE_CORRECTION_EVIDENCE_INPUT_INVALID"
            )
        if (
            type(self.original_filename) is not str
            or not self.original_filename
            or self.original_filename.strip() != self.original_filename
            or len(self.original_filename) > 255
            or any(separator in self.original_filename for separator in ("/", "\\"))
            or not self.original_filename.lower().endswith(".csv")
        ):
            raise FeeCorrectionBlockedError(
                "仅接受单行规范 CSV 费用材料", code="FEE_CORRECTION_EVIDENCE_INPUT_INVALID"
            )
        if (
            type(self.content) is not bytes
            or not self.content
            or len(self.content) > MAX_UPLOAD_BYTES
        ):
            raise FeeCorrectionBlockedError(
                "费用材料为空或超过本地上传上限", code="FEE_CORRECTION_EVIDENCE_INPUT_INVALID"
            )
        if type(self.attestation_acknowledged) is not bool or not self.attestation_acknowledged:
            raise FeeCorrectionBlockedError(
                "必须明确确认这是操作者声明、非发行方认证材料",
                code="FEE_CORRECTION_OPERATOR_ATTESTATION_REQUIRED",
            )


@dataclass(frozen=True, slots=True)
class FeeCorrectionEvidenceUploadReceipt:
    """Local storage receipt; it is not a source-verification result."""

    source_locator: str
    content_sha256: str
    payload_sha256: str
    assurance_class: str
    stored_at: datetime


class FeeCorrectionEvidenceCaptureRepositoryProtocol(Protocol):
    """Persist immutable upload bytes and an owner-attested exact Trade binding."""

    def capture(
        self,
        command: FeeCorrectionEvidenceUploadCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionEvidenceUploadReceipt:
        """Store a source-class-labeled artifact after locked owner/policy checks."""
        ...


class FeeCorrectionEvidenceUploadUseCase:
    """Orchestrate owner-attested evidence capture without ORM dependencies."""

    def __init__(self, repository: FeeCorrectionEvidenceCaptureRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: FeeCorrectionEvidenceUploadCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionEvidenceUploadReceipt:
        """Capture only an authenticated principal's explicitly attested upload."""

        command.__post_init__()
        if _authenticated_principal_user_id(principal) is None:
            raise FeeCorrectionBlockedError(
                "费用材料上传需要有效的已认证账户主体",
                code="FEE_CORRECTION_PRINCIPAL_INVALID",
            )
        return self._repository.capture(command, principal=principal)


def _authenticated_principal_user_id(principal: object) -> int | None:
    """Narrow a request-bound principal without accepting a body-supplied ID."""

    if principal is None:
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
