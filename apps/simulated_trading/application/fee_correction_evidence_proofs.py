"""Pure validation of current fee evidence and persisted correction proofs."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import cast

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionRequest,
    VerifiedFeeCorrectionEvidence,
)
from apps.simulated_trading.domain.fee_correction import CorrectableFeeComponents

from .fee_correction_evidence_contracts import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    OPERATOR_ATTESTATION_VERSION,
    OPERATOR_FEE_CSV_SCHEMA,
    FeeCorrectionEvidencePersistedEventSnapshot,
    FeeCorrectionEvidencePredecessorSnapshot,
    FeeCorrectionEvidenceVerificationSnapshot,
    PersistedFeeCorrectionEventProof,
)
from .fee_correction_evidence_fingerprint import (
    fee_correction_policy_sha256,
    fee_correction_policy_snapshot_json,
    operator_fee_evidence_row_matches_trade,
    trade_economic_fingerprint_sha256,
)
from .fee_correction_evidence_values import (
    _canonical_aware_datetime,
    _canonical_uuid,
    _currency_token,
    _decimal_fixed,
    _parse_canonical_aware_datetime,
    _required_decimal,
    _valid_sha256,
)

_MAX_PERSISTED_FEE_COMPONENT = Decimal("99999999.99")


def verify_fee_correction_evidence_snapshot(
    snapshot: FeeCorrectionEvidenceVerificationSnapshot,
    request: FeeCorrectionRequest,
    *,
    verified_at: datetime,
) -> VerifiedFeeCorrectionEvidence | None:
    """Recheck local bytes, row, owner, policy, revision and exact Trade binding."""

    try:
        request.__post_init__()
        if verified_at.tzinfo is None or verified_at.utcoffset() is None:
            return None
        if any(
            value.tzinfo is None or value.utcoffset() is None or value > verified_at
            for value in (snapshot.artifact_uploaded_at, snapshot.binding_created_at)
        ):
            return None
        if (
            snapshot.binding_locator != request.source_locator
            or snapshot.binding_account_id != request.account_id
            or snapshot.binding_trade_id != request.trade_id
            or snapshot.binding_idempotency_key != request.idempotency_key
            or snapshot.current_account_id != request.account_id
            or snapshot.artifact_account_id != request.account_id
            or snapshot.policy_account_id != request.account_id
            or snapshot.trade.account_id != request.account_id
            or snapshot.trade.trade_id != request.trade_id
            or snapshot.binding_expected_revision != request.expected_revision
            or (snapshot.binding_expected_revision == 0)
            != (snapshot.binding_expected_predecessor_id is None)
        ):
            return None
        if (
            snapshot.artifact_schema_version != OPERATOR_FEE_CSV_SCHEMA
            or snapshot.artifact_assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or snapshot.binding_attestation_version != OPERATOR_ATTESTATION_VERSION
            or snapshot.binding_attestation_acknowledged is not True
            or snapshot.binding_assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
        ):
            return None
        if (
            snapshot.current_account_owner_id <= 0
            or snapshot.trade.account_owner_id != snapshot.current_account_owner_id
            or snapshot.binding_attested_by_id != snapshot.current_account_owner_id
            or snapshot.artifact_uploaded_by_id != snapshot.current_account_owner_id
            or snapshot.policy_updated_by_id != snapshot.current_account_owner_id
        ):
            return None
        if snapshot.artifact_sha256 != hashlib.sha256(snapshot.artifact_bytes).hexdigest():
            return None
        parsed = snapshot.parsed_upload
        if (
            parsed.raw_row != snapshot.artifact_raw_row
            or parsed.parsed_metadata != snapshot.artifact_parsed_metadata
            or parsed.payload_sha256 != snapshot.artifact_payload_sha256
            or parsed.schema_version != OPERATOR_FEE_CSV_SCHEMA
            or snapshot.binding_content_sha256 != snapshot.artifact_sha256
            or snapshot.binding_payload_sha256 != snapshot.artifact_payload_sha256
        ):
            return None
        current_trade_hash = trade_economic_fingerprint_sha256(snapshot.trade)
        if current_trade_hash != snapshot.binding_trade_snapshot_sha256:
            return None
        current_policy_hash = fee_correction_policy_sha256(
            account_id=snapshot.policy_account_id,
            version=snapshot.policy_version,
            enabled=snapshot.policy_enabled,
            allows_operator_attested_upload=snapshot.policy_allows_operator_attested_upload,
            ledger_currency=snapshot.policy_ledger_currency,
            valid_from=snapshot.policy_valid_from,
            valid_until=snapshot.policy_valid_until,
            updated_by_id=snapshot.policy_updated_by_id,
        )
        current_policy_snapshot = fee_correction_policy_snapshot_json(
            account_id=snapshot.policy_account_id,
            version=snapshot.policy_version,
            enabled=snapshot.policy_enabled,
            allows_operator_attested_upload=snapshot.policy_allows_operator_attested_upload,
            ledger_currency=snapshot.policy_ledger_currency,
            valid_from=snapshot.policy_valid_from,
            valid_until=snapshot.policy_valid_until,
            updated_by_id=snapshot.policy_updated_by_id,
        )
        if (
            snapshot.policy_version != snapshot.binding_policy_version
            or current_policy_hash != snapshot.binding_policy_sha256
            or current_policy_snapshot != snapshot.binding_policy_snapshot
            or not _currency_token(snapshot.policy_ledger_currency)
            or parsed.currency_code != snapshot.policy_ledger_currency
            or not snapshot.policy_enabled
            or not snapshot.policy_allows_operator_attested_upload
            or (snapshot.policy_valid_from is not None and verified_at < snapshot.policy_valid_from)
            or (
                snapshot.policy_valid_until is not None
                and verified_at >= snapshot.policy_valid_until
            )
        ):
            return None
        if not operator_fee_evidence_row_matches_trade(parsed, snapshot.trade):
            return None
        if (
            parsed.source_observed_at > verified_at
            or snapshot.trade.fee_amounts_known is not True
            or snapshot.trade.transfer_fee is None
            or snapshot.trade.stamp_duty is None
            or any(not known for known in parsed.fee_known)
            or any(precision is None or precision > 2 for precision in parsed.fee_precisions)
            or any(amount is None for amount in parsed.fee_amounts)
        ):
            return None
        predecessor = snapshot.predecessor
        if snapshot.binding_expected_revision == 0:
            if predecessor is not None:
                return None
            previous_fees = CorrectableFeeComponents(
                commission=snapshot.trade.commission,
                transfer_fee=snapshot.trade.transfer_fee,
                stamp_duty=snapshot.trade.stamp_duty,
            )
        else:
            if (
                type(predecessor) is not FeeCorrectionEvidencePredecessorSnapshot
                or predecessor.account_id != snapshot.binding_account_id
                or predecessor.trade_id != snapshot.binding_trade_id
                or predecessor.revision != snapshot.binding_expected_revision
                or predecessor.event_id != snapshot.binding_expected_predecessor_id
            ):
                return None
            previous_fees = predecessor.revised_fee_components
        revised_fees = CorrectableFeeComponents(
            commission=_required_decimal(parsed.fee_amounts[0]),
            transfer_fee=_required_decimal(parsed.fee_amounts[1]),
            stamp_duty=_required_decimal(parsed.fee_amounts[2]),
        )
        if not _fee_components_fit_event_storage(previous_fees) or not (
            _fee_components_fit_event_storage(revised_fees)
        ):
            return None
        return VerifiedFeeCorrectionEvidence(
            account_id=request.account_id,
            trade_id=request.trade_id,
            asset_code=parsed.asset_code,
            expected_revision=request.expected_revision,
            expected_predecessor_id=snapshot.binding_expected_predecessor_id,
            trade_snapshot_hash=current_trade_hash,
            previous_fee_components=previous_fees,
            revised_fee_components=revised_fees,
            source_namespace=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
            source_record_id=snapshot.binding_locator,
            evidence_sha256=snapshot.artifact_sha256,
            source_payload_sha256=snapshot.artifact_payload_sha256,
            verifier_identity="local.operator_attested_csv.v1",
            source_observed_at=parsed.source_observed_at,
            verified_at=verified_at,
        )
    except (ArithmeticError, TypeError, ValueError, KeyError):
        return None


def verify_persisted_fee_correction_authority_snapshot(
    proof: PersistedFeeCorrectionEventProof,
) -> bool:
    """Recompute the immutable event-bound owner and policy authorization."""

    if type(proof) is not PersistedFeeCorrectionEventProof:
        return False
    try:
        proof.__post_init__()
        payload_value = proof.authority_snapshot_json
        expected_keys = {
            "schema",
            "account_id",
            "account_owner_user_id",
            "account_type",
            "account_active",
            "actor_user_id",
            "actor_authenticated",
            "principal_enabled",
            "authority_identity",
            "authority_record_id",
            "authority_sha256",
            "authorization_scope",
            "policy_version",
            "policy_sha256",
            "policy_ledger_currency",
            "policy_enabled",
            "policy_allows_operator_attested_upload",
            "policy_valid_from",
            "policy_valid_until",
            "policy_updated_by_id",
            "trade_id",
            "trade_snapshot_hash",
            "original_v4_receipt_hash",
            "receipt_snapshot_hash",
            "source_namespace",
            "source_record_id",
            "verifier_identity",
            "source_evidence_hash",
            "source_payload_hash",
            "source_observed_at",
            "evidence_verified_at",
            "request_payload_hash",
            "idempotency_key",
            "revision",
            "previous_event_id",
            "account_revision",
            "account_predecessor_hash",
            "previous_fees",
            "revised_fees",
            "original_slippage",
            "posting_time",
            "posting_date",
        }
        if type(payload_value) is not dict:
            return False
        payload_object = cast(dict[str, object], payload_value)
        if set(payload_object) != expected_keys:
            return False
        payload = payload_value
        string_keys = (
            "schema",
            "account_type",
            "authority_identity",
            "authority_record_id",
            "authority_sha256",
            "authorization_scope",
            "policy_sha256",
            "policy_ledger_currency",
            "trade_snapshot_hash",
            "source_namespace",
            "source_record_id",
            "verifier_identity",
            "source_evidence_hash",
            "source_payload_hash",
            "source_observed_at",
            "evidence_verified_at",
            "request_payload_hash",
            "idempotency_key",
            "account_predecessor_hash",
            "original_slippage",
            "posting_time",
            "posting_date",
        )
        if any(type(payload_object[key]) is not str for key in string_keys):
            return False
        integer_keys = (
            "account_id",
            "account_owner_user_id",
            "actor_user_id",
            "policy_version",
            "trade_id",
            "revision",
            "account_revision",
        )
        for key in integer_keys:
            value = payload_object[key]
            if type(value) is not int or value <= 0:
                return False
        boolean_keys = (
            "account_active",
            "actor_authenticated",
            "principal_enabled",
            "policy_enabled",
            "policy_allows_operator_attested_upload",
        )
        if any(type(payload_object[key]) is not bool for key in boolean_keys):
            return False
        if payload_object["previous_event_id"] is not None and (
            type(payload_object["previous_event_id"]) is not int
            or payload_object["previous_event_id"] <= 0
        ):
            return False
        if payload_object["policy_updated_by_id"] is not None and (
            type(payload_object["policy_updated_by_id"]) is not int
            or payload_object["policy_updated_by_id"] <= 0
        ):
            return False
        for digest_key in (
            "authority_sha256",
            "policy_sha256",
            "trade_snapshot_hash",
            "source_evidence_hash",
            "source_payload_hash",
            "account_predecessor_hash",
        ):
            digest_value = payload_object[digest_key]
            if type(digest_value) is not str or not _valid_sha256(digest_value):
                return False
        for digest_key in ("original_v4_receipt_hash", "receipt_snapshot_hash"):
            digest = payload_object[digest_key]
            if digest is not None and (type(digest) is not str or not _valid_sha256(digest)):
                return False
        if (payload_object["original_v4_receipt_hash"] is None) != (
            payload_object["receipt_snapshot_hash"] is None
        ):
            return False
        if not _currency_token(payload_object["policy_ledger_currency"]):
            return False
        for key in ("policy_valid_from", "policy_valid_until"):
            if payload_object[key] is not None and type(payload_object[key]) is not str:
                return False
        for fee_key in ("previous_fees", "revised_fees"):
            fee_value = payload_object[fee_key]
            if type(fee_value) is not dict:
                return False
            fee_fields = cast(dict[str, object], fee_value)
            if set(fee_fields) != {"commission", "transfer_fee", "stamp_duty"} or any(
                type(value) is not str for value in fee_fields.values()
            ):
                return False

        if (
            payload["schema"] != "simulated-fee-correction-authority-event.v1"
            or payload["authority_record_id"] != proof.authority_record_id
            or payload["authority_identity"] != proof.authority_identity
            or payload["authority_sha256"] != proof.authority_hash
            or payload["account_id"] != proof.account_id
            or payload["account_owner_user_id"] != proof.actor_user_id
            or payload["account_type"] != "simulated"
            or payload["account_active"] is not True
            or payload["actor_user_id"] != proof.actor_user_id
            or payload["actor_authenticated"] is not True
            or payload["principal_enabled"] is not True
            or payload["trade_id"] != proof.trade_id
            or payload["trade_snapshot_hash"] != proof.trade_snapshot_hash
            or payload["original_v4_receipt_hash"] != proof.original_v4_receipt_hash
            or payload["receipt_snapshot_hash"] != proof.receipt_snapshot_hash
            or payload["source_namespace"] != proof.source_namespace
            or payload["source_record_id"] != proof.source_record_id
            or payload["verifier_identity"] != proof.verifier_identity
            or payload["source_evidence_hash"] != proof.source_evidence_hash
            or payload["source_payload_hash"] != proof.source_payload_hash
            or payload["source_observed_at"] != _canonical_aware_datetime(proof.source_observed_at)
            or payload["evidence_verified_at"]
            != _canonical_aware_datetime(proof.evidence_verified_at)
            or payload["idempotency_key"] != proof.idempotency_key
            or payload["request_payload_hash"] != proof.request_payload_hash
            or payload["revision"] != proof.revision
            or payload["previous_event_id"] != proof.previous_event_id
            or payload["account_revision"] != proof.account_revision
            or payload["account_predecessor_hash"] != proof.account_predecessor_hash
            or payload["policy_enabled"] is not True
            or payload["policy_allows_operator_attested_upload"] is not True
            or payload["policy_updated_by_id"] is None
            or payload["policy_updated_by_id"] != proof.actor_user_id
            or payload["authorization_scope"] != "simulated_fee_correction:operator_attested_upload"
            or proof.authority_identity != "local.owner_policy.v1"
        ):
            return False
        if payload["policy_sha256"] != proof.authority_hash:
            return False
        policy_valid_from = _parse_canonical_aware_datetime(payload["policy_valid_from"])
        policy_valid_until = _parse_canonical_aware_datetime(payload["policy_valid_until"])
        posting_time = _parse_canonical_aware_datetime(payload["posting_time"])
        source_observed_at = _parse_canonical_aware_datetime(payload["source_observed_at"])
        evidence_verified_at = _parse_canonical_aware_datetime(payload["evidence_verified_at"])
        if any(value is None for value in (posting_time, source_observed_at, evidence_verified_at)):
            return False
        posting_date = date.fromisoformat(payload["posting_date"])
        if (
            posting_date.isoformat() != payload["posting_date"]
            or posting_time != proof.posted_at
            or posting_date != proof.posting_date
            or source_observed_at != proof.source_observed_at
            or evidence_verified_at != proof.evidence_verified_at
            or (policy_valid_from is not None and proof.posted_at < policy_valid_from)
            or (policy_valid_until is not None and proof.posted_at >= policy_valid_until)
        ):
            return False
        expected_previous_fees = {
            "commission": _decimal_fixed(proof.previous_fee_components.commission, 2),
            "transfer_fee": _decimal_fixed(proof.previous_fee_components.transfer_fee, 2),
            "stamp_duty": _decimal_fixed(proof.previous_fee_components.stamp_duty, 2),
        }
        expected_revised_fees = {
            "commission": _decimal_fixed(proof.revised_fee_components.commission, 2),
            "transfer_fee": _decimal_fixed(proof.revised_fee_components.transfer_fee, 2),
            "stamp_duty": _decimal_fixed(proof.revised_fee_components.stamp_duty, 2),
        }
        if (
            payload["previous_fees"] != expected_previous_fees
            or payload["revised_fees"] != expected_revised_fees
            or payload["original_slippage"] != _decimal_fixed(proof.original_slippage, 2)
        ):
            return False
        policy_digest = fee_correction_policy_sha256(
            account_id=payload["account_id"],
            version=payload["policy_version"],
            enabled=payload["policy_enabled"],
            allows_operator_attested_upload=payload["policy_allows_operator_attested_upload"],
            ledger_currency=payload["policy_ledger_currency"],
            valid_from=policy_valid_from,
            valid_until=policy_valid_until,
            updated_by_id=payload["policy_updated_by_id"],
        )
        if policy_digest != payload["policy_sha256"]:
            return False
        canonical_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest() == proof.authority_snapshot_sha256
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False


def verify_persisted_fee_correction_event_snapshot(
    snapshot: FeeCorrectionEvidencePersistedEventSnapshot,
    proof: PersistedFeeCorrectionEventProof,
) -> bool:
    """Validate a stored event against immutable uploaded bytes and binding.

    This validates the event-bound source and authority snapshots. The JSON is
    a local server authorization record; it does not claim external identity
    provider or broker/issuer authentication beyond the recorded app boundary.
    """

    try:
        if type(proof) is not PersistedFeeCorrectionEventProof:
            return False
        proof.__post_init__()
        if not verify_persisted_fee_correction_authority_snapshot(proof):
            return False
        if not _fee_components_fit_event_storage(proof.previous_fee_components) or not (
            _fee_components_fit_event_storage(proof.revised_fee_components)
        ):
            return False
        binding_uuid = _canonical_uuid(snapshot.binding_locator)
        if (
            binding_uuid != proof.source_record_id
            or snapshot.binding_account_id != proof.account_id
            or snapshot.binding_trade_id != proof.trade_id
            or snapshot.artifact_account_id != proof.account_id
            or snapshot.trade.account_id != proof.account_id
            or snapshot.trade.trade_id != proof.trade_id
            or snapshot.binding_expected_revision + 1 != proof.revision
            or snapshot.binding_expected_predecessor_id != proof.previous_event_id
            or snapshot.binding_attested_by_id <= 0
            or snapshot.trade.account_owner_id != snapshot.binding_attested_by_id
            or snapshot.artifact_uploaded_by_id != snapshot.binding_attested_by_id
            or any(
                value.tzinfo is None
                or value.utcoffset() is None
                or value > proof.evidence_verified_at
                for value in (snapshot.artifact_uploaded_at, snapshot.binding_created_at)
            )
        ):
            return False
        if (
            snapshot.binding_attestation_version != OPERATOR_ATTESTATION_VERSION
            or snapshot.binding_attestation_acknowledged is not True
            or snapshot.binding_assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or snapshot.artifact_assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or snapshot.artifact_schema_version != OPERATOR_FEE_CSV_SCHEMA
            or proof.source_namespace != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or proof.verifier_identity != "local.operator_attested_csv.v1"
        ):
            return False
        if (
            snapshot.artifact_sha256 != hashlib.sha256(snapshot.artifact_bytes).hexdigest()
            or snapshot.binding_content_sha256 != snapshot.artifact_sha256
            or snapshot.binding_payload_sha256 != snapshot.artifact_payload_sha256
            or proof.source_evidence_hash != snapshot.artifact_sha256
            or proof.source_payload_hash != snapshot.artifact_payload_sha256
            or snapshot.parsed_upload.raw_row != snapshot.artifact_raw_row
            or snapshot.parsed_upload.parsed_metadata != snapshot.artifact_parsed_metadata
            or snapshot.parsed_upload.payload_sha256 != snapshot.artifact_payload_sha256
            or snapshot.parsed_upload.schema_version != OPERATOR_FEE_CSV_SCHEMA
        ):
            return False
        policy = snapshot.binding_policy_snapshot
        policy_valid_from = _parse_canonical_aware_datetime(policy["valid_from"])
        policy_valid_until = _parse_canonical_aware_datetime(policy["valid_until"])
        policy_digest = fee_correction_policy_sha256(
            account_id=policy["account_id"],
            version=policy["version"],
            enabled=policy["enabled"],
            allows_operator_attested_upload=policy["allows_operator_attested_upload"],
            ledger_currency=policy["ledger_currency"],
            valid_from=policy_valid_from,
            valid_until=policy_valid_until,
            updated_by_id=policy["updated_by_id"],
        )
        policy_canonical = fee_correction_policy_snapshot_json(
            account_id=policy["account_id"],
            version=policy["version"],
            enabled=policy["enabled"],
            allows_operator_attested_upload=policy["allows_operator_attested_upload"],
            ledger_currency=policy["ledger_currency"],
            valid_from=policy_valid_from,
            valid_until=policy_valid_until,
            updated_by_id=policy["updated_by_id"],
        )
        if (
            policy_canonical != policy
            or policy_digest != snapshot.binding_policy_sha256
            or policy["account_id"] != proof.account_id
            or policy["version"] != snapshot.binding_policy_version
            or policy["enabled"] is not True
            or policy["allows_operator_attested_upload"] is not True
            or not _currency_token(policy["ledger_currency"])
            or proof.authority_snapshot_json["policy_ledger_currency"] != policy["ledger_currency"]
            or snapshot.parsed_upload.currency_code != policy["ledger_currency"]
            or type(policy["updated_by_id"]) is not int
            or policy["updated_by_id"] <= 0
            or policy["updated_by_id"] != snapshot.binding_attested_by_id
            or (policy_valid_from is not None and proof.evidence_verified_at < policy_valid_from)
            or (policy_valid_until is not None and proof.evidence_verified_at >= policy_valid_until)
        ):
            return False
        authority = proof.authority_snapshot_json
        if (
            proof.authority_hash != snapshot.binding_policy_sha256
            or authority["actor_user_id"] != snapshot.binding_attested_by_id
            or authority["account_owner_user_id"] != snapshot.binding_attested_by_id
            or authority["policy_version"] != policy["version"]
            or authority["policy_sha256"] != snapshot.binding_policy_sha256
            or authority["authority_sha256"] != snapshot.binding_policy_sha256
            or authority["policy_enabled"] is not policy["enabled"]
            or authority["policy_allows_operator_attested_upload"]
            is not policy["allows_operator_attested_upload"]
            or authority["policy_ledger_currency"] != policy["ledger_currency"]
            or authority["policy_valid_from"] != policy["valid_from"]
            or authority["policy_valid_until"] != policy["valid_until"]
            or authority["policy_updated_by_id"] != policy["updated_by_id"]
        ):
            return False
        if (
            trade_economic_fingerprint_sha256(snapshot.trade)
            != snapshot.binding_trade_snapshot_sha256
        ):
            return False
        if (
            proof.trade_snapshot_hash != snapshot.binding_trade_snapshot_sha256
            or proof.original_v4_receipt_hash != snapshot.trade.original_v4_receipt_hash
            or proof.receipt_snapshot_hash != snapshot.receipt_snapshot_hash
            or proof.original_slippage != snapshot.trade.slippage
            or not operator_fee_evidence_row_matches_trade(snapshot.parsed_upload, snapshot.trade)
            or proof.source_observed_at != snapshot.parsed_upload.source_observed_at
            or proof.source_observed_at > proof.evidence_verified_at
        ):
            return False
        parsed = snapshot.parsed_upload
        if (
            any(not known for known in parsed.fee_known)
            or any(precision is None or precision > 2 for precision in parsed.fee_precisions)
            or any(amount is None for amount in parsed.fee_amounts)
        ):
            return False
        revised_fees = CorrectableFeeComponents(
            commission=_required_decimal(parsed.fee_amounts[0]),
            transfer_fee=_required_decimal(parsed.fee_amounts[1]),
            stamp_duty=_required_decimal(parsed.fee_amounts[2]),
        )
        if proof.revised_fee_components != revised_fees:
            return False
        if proof.revision == 1:
            if (
                snapshot.trade.fee_amounts_known is not True
                or snapshot.trade.transfer_fee is None
                or snapshot.trade.stamp_duty is None
            ):
                return False
            original_fees = CorrectableFeeComponents(
                commission=snapshot.trade.commission,
                transfer_fee=snapshot.trade.transfer_fee,
                stamp_duty=snapshot.trade.stamp_duty,
            )
            if proof.previous_fee_components != original_fees:
                return False
        return True
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False


def _fee_components_fit_event_storage(components: CorrectableFeeComponents) -> bool:
    """Check the physical DecimalField range used by fee-correction events."""

    if type(components) is not CorrectableFeeComponents:
        return False
    try:
        components.__post_init__()
    except (ArithmeticError, TypeError, ValueError):
        return False
    return all(
        amount.is_finite() and amount >= Decimal("0") and amount <= _MAX_PERSISTED_FEE_COMPONENT
        for amount in (components.commission, components.transfer_fee, components.stamp_duty)
    )
