"""Adapt correction ORM events to the immutable local proof contracts."""

from __future__ import annotations

from typing import cast

from apps.simulated_trading.application.fee_correction_evidence import (
    FeeCorrectionAuthorityEventSnapshotJSON,
    PersistedFeeCorrectionEventProof,
    verify_persisted_fee_correction_authority_snapshot,
)
from apps.simulated_trading.domain.fee_correction import CorrectableFeeComponents
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
    DjangoFeeCorrectionEvidenceRepository,
)


def proof_from_persisted_event(
    event: SimulatedFeeCorrectionEventModel,
    *,
    original_v4_receipt_hash: str | None,
) -> PersistedFeeCorrectionEventProof:
    """Build the exact typed proof input from one stored correction event."""

    if type(event.authority_snapshot_json) is not dict:
        raise ValueError("correction event is missing its immutable authority snapshot")
    if type(event.authority_snapshot_sha256) is not str:
        raise ValueError("correction event is missing its immutable authority snapshot digest")
    return PersistedFeeCorrectionEventProof(
        account_id=event.account_id,
        trade_id=event.trade_id,
        actor_user_id=event.actor_user_id,
        revision=event.revision,
        previous_event_id=event.previous_event_id,
        account_revision=event.account_revision,
        account_predecessor_hash=event.account_predecessor_hash,
        idempotency_key=event.idempotency_key,
        request_payload_hash=event.request_payload_hash,
        trade_snapshot_hash=event.trade_snapshot_hash,
        original_v4_receipt_hash=original_v4_receipt_hash,
        receipt_snapshot_hash=event.receipt_snapshot_hash,
        source_namespace=event.source_namespace,
        source_record_id=event.source_record_id,
        verifier_identity=event.verifier_identity,
        source_evidence_hash=event.source_evidence_hash,
        source_payload_hash=event.source_payload_hash,
        source_observed_at=event.source_observed_at,
        evidence_verified_at=event.evidence_verified_at,
        authority_identity=event.authority_identity,
        authority_record_id=event.authority_record_id,
        authority_hash=event.authority_hash,
        authority_snapshot_sha256=event.authority_snapshot_sha256,
        authority_snapshot_json=cast(
            FeeCorrectionAuthorityEventSnapshotJSON,
            event.authority_snapshot_json,
        ),
        previous_fee_components=CorrectableFeeComponents(
            commission=event.previous_commission,
            transfer_fee=event.previous_transfer_fee,
            stamp_duty=event.previous_stamp_duty,
        ),
        revised_fee_components=CorrectableFeeComponents(
            commission=event.revised_commission,
            transfer_fee=event.revised_transfer_fee,
            stamp_duty=event.revised_stamp_duty,
        ),
        original_slippage=event.original_slippage,
        posted_at=event.posted_at,
        posting_date=event.posting_date,
    )


class DjangoPersistedFeeCorrectionSourceProof:
    """Re-read original bytes, Trade, binding, and historical policy snapshot."""

    def __init__(self, repository: DjangoFeeCorrectionEvidenceRepository) -> None:
        self._repository = repository

    def validate_event(
        self,
        event: SimulatedFeeCorrectionEventModel,
        *,
        original_v4_receipt_hash: str | None,
    ) -> bool:
        """Require the local evidence repository to re-prove every source field."""

        try:
            proof = proof_from_persisted_event(
                event,
                original_v4_receipt_hash=original_v4_receipt_hash,
            )
            proof.__post_init__()
            return self._repository.verify_persisted_event(proof) is True
        except (ArithmeticError, TypeError, ValueError):
            return False


class PersistedFeeCorrectionAuthorityProof:
    """Validate the canonical event-bound policy and principal snapshot."""

    def validate_event(
        self,
        event: SimulatedFeeCorrectionEventModel,
        *,
        original_v4_receipt_hash: str | None,
    ) -> bool:
        """Verify the historical authorization snapshot without reading current policy."""

        try:
            proof = proof_from_persisted_event(
                event,
                original_v4_receipt_hash=original_v4_receipt_hash,
            )
            proof.__post_init__()
            return verify_persisted_fee_correction_authority_snapshot(proof)
        except (ArithmeticError, TypeError, ValueError):
            return False


__all__ = [
    "DjangoPersistedFeeCorrectionSourceProof",
    "PersistedFeeCorrectionAuthorityProof",
    "proof_from_persisted_event",
]
