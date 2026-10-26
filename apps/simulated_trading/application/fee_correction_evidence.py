"""Stable public Application API for local simulated fee evidence."""

from __future__ import annotations

from apps.simulated_trading.application.fee_correction import (  # noqa: F401
    AuthenticatedFeeCorrectionPrincipalProtocol as AuthenticatedFeeCorrectionPrincipalProtocol,
)
from apps.simulated_trading.application.fee_correction import (  # noqa: F401
    FeeCorrectionBlockedError as FeeCorrectionBlockedError,
)
from apps.simulated_trading.application.fee_correction import (  # noqa: F401
    FeeCorrectionRequest as FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction import (  # noqa: F401
    VerifiedFeeCorrectionEvidence as VerifiedFeeCorrectionEvidence,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (  # noqa: F401
    validate_ledger_money as validate_ledger_money,
)
from apps.simulated_trading.domain.fee_correction import (  # noqa: F401
    CorrectableFeeComponents as CorrectableFeeComponents,
)

from .fee_correction_evidence_contracts import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    MAX_UPLOAD_BYTES,
    OPERATOR_ATTESTATION_VERSION,
    OPERATOR_FEE_CSV_SCHEMA,
    FeeCorrectionAuthorityEventSnapshotJSON,
    FeeCorrectionEvidenceCaptureRepositoryProtocol,
    FeeCorrectionEvidencePersistedEventSnapshot,
    FeeCorrectionEvidenceUploadCommand,
    FeeCorrectionEvidenceUploadReceipt,
    FeeCorrectionEvidenceUploadUseCase,
    FeeCorrectionEvidenceVerificationSnapshot,
    FeeCorrectionFeeComponentsJSON,
    FeeCorrectionPolicySnapshotJSON,
    FeeEvidenceFeeMetadataJSON,
    FeeEvidenceParsedMetadataJSON,
    FeeEvidenceRawRowJSON,
    OperatorAttestedFeeEvidenceRow,
    PersistedFeeCorrectionEventProof,
    TradeEconomicFingerprintInput,
)
from .fee_correction_evidence_fingerprint import (
    fee_correction_policy_sha256,
    fee_correction_policy_snapshot_json,
    operator_fee_evidence_row_matches_trade,
    trade_economic_fingerprint_sha256,
)
from .fee_correction_evidence_proofs import (
    verify_fee_correction_evidence_snapshot,
    verify_persisted_fee_correction_authority_snapshot,
    verify_persisted_fee_correction_event_snapshot,
)

__all__ = [
    "ASSURANCE_OPERATOR_ATTESTED_UPLOAD",
    "FeeCorrectionEvidenceCaptureRepositoryProtocol",
    "FeeCorrectionEvidenceUploadCommand",
    "FeeCorrectionEvidenceUploadReceipt",
    "FeeCorrectionEvidenceUploadUseCase",
    "FeeCorrectionAuthorityEventSnapshotJSON",
    "FeeCorrectionEvidencePersistedEventSnapshot",
    "FeeCorrectionEvidenceVerificationSnapshot",
    "FeeCorrectionFeeComponentsJSON",
    "FeeCorrectionPolicySnapshotJSON",
    "FeeEvidenceFeeMetadataJSON",
    "FeeEvidenceParsedMetadataJSON",
    "FeeEvidenceRawRowJSON",
    "MAX_UPLOAD_BYTES",
    "OPERATOR_ATTESTATION_VERSION",
    "OPERATOR_FEE_CSV_SCHEMA",
    "OperatorAttestedFeeEvidenceRow",
    "PersistedFeeCorrectionEventProof",
    "TradeEconomicFingerprintInput",
    "fee_correction_policy_sha256",
    "fee_correction_policy_snapshot_json",
    "operator_fee_evidence_row_matches_trade",
    "trade_economic_fingerprint_sha256",
    "verify_fee_correction_evidence_snapshot",
    "verify_persisted_fee_correction_authority_snapshot",
    "verify_persisted_fee_correction_event_snapshot",
]
