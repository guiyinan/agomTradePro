"""Pure identity and event-snapshot helpers for fee correction persistence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

from django.contrib.auth import get_user_model

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionBlockedError,
    FeeCorrectionReceipt,
    FeeCorrectionRequest,
    VerifiedFeeCorrectionAuthorization,
    VerifiedFeeCorrectionEvidence,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_history import _exact_money
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)

_SHA256_HEX = frozenset("0123456789abcdef")


def _blocked(message: str, code: str) -> FeeCorrectionBlockedError:
    """Build the stable application error for a rejected correction boundary."""

    return FeeCorrectionBlockedError(message, code=code)


def _is_digest(value: object) -> bool:
    """Require an exact lowercase SHA-256 digest from a proof codec."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in _SHA256_HEX for character in value)
    )


def _principal_user_id(principal: object) -> int | None:
    """Narrow a Django request user without accepting duck-typed input claims."""

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


def _stable_decimal(value: Decimal) -> str:
    """Return a canonical two-place money string for semantic hashes."""

    return format(_exact_money(value, "fee_correction.payload_money"), ".2f")


def _request_payload_hash(
    *,
    request: FeeCorrectionRequest,
    evidence: VerifiedFeeCorrectionEvidence,
    authorization: VerifiedFeeCorrectionAuthorization,
) -> str:
    """Hash the stable economic and proof identity, excluding verification time."""

    payload: dict[str, object] = {
        "schema": "simulated-fee-correction-request.v1",
        "account_id": request.account_id,
        "trade_id": request.trade_id,
        "idempotency_key": request.idempotency_key,
        "expected_revision": request.expected_revision,
        "expected_predecessor_id": evidence.expected_predecessor_id,
        "trade_snapshot_hash": evidence.trade_snapshot_hash,
        "source_namespace": evidence.source_namespace,
        "source_record_id": evidence.source_record_id,
        "source_evidence_hash": evidence.evidence_sha256,
        "source_payload_hash": evidence.source_payload_sha256,
        "source_observed_at": _utc_text(evidence.source_observed_at),
        "previous_fees": {
            "commission": _stable_decimal(evidence.previous_fee_components.commission),
            "transfer_fee": _stable_decimal(evidence.previous_fee_components.transfer_fee),
            "stamp_duty": _stable_decimal(evidence.previous_fee_components.stamp_duty),
        },
        "revised_fees": {
            "commission": _stable_decimal(evidence.revised_fee_components.commission),
            "transfer_fee": _stable_decimal(evidence.revised_fee_components.transfer_fee),
            "stamp_duty": _stable_decimal(evidence.revised_fee_components.stamp_duty),
        },
        "verifier_identity": evidence.verifier_identity,
        "actor_user_id": authorization.actor_user_id,
        "authority_identity": authorization.authority_identity,
        "authority_record_id": authorization.authority_record_id,
        "authority_hash": authorization.authority_sha256,
        "policy_version": authorization.policy_version,
        "policy_sha256": authorization.policy_sha256,
        "policy_enabled": authorization.policy_enabled,
        "policy_allows_operator_attested_upload": authorization.policy_allows_operator_attested_upload,
        "policy_ledger_currency": authorization.policy_ledger_currency,
        "policy_valid_from": (_utc_text(authorization.policy_valid_from)),
        "policy_valid_until": (_utc_text(authorization.policy_valid_until)),
        "policy_updated_by_id": authorization.policy_updated_by_id,
        "principal_enabled": authorization.principal_enabled,
        "authorization_scope": authorization.authorization_scope,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_text(value: datetime | None) -> str | None:
    """Format one optional aware datetime as canonical UTC microsecond text."""

    if value is None:
        return None
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _blocked("授权时间窗必须带时区", "FEE_CORRECTION_AUTHORITY_INVALID")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _authority_snapshot_payload(
    *,
    account: SimulatedAccountModel,
    request: FeeCorrectionRequest,
    evidence: VerifiedFeeCorrectionEvidence,
    authorization: VerifiedFeeCorrectionAuthorization,
    request_hash: str,
    revision: int,
    account_revision: int,
    account_predecessor_hash: str,
    predecessor_id: int | None,
    receipt_hash: str | None,
    receipt_snapshot: str | None,
    original_slippage: Decimal,
    posted_at: datetime,
    posting_date: date,
) -> dict[str, object]:
    """Capture the exact locked owner/policy/proof scope for historical replay."""

    return {
        "schema": "simulated-fee-correction-authority-event.v1",
        "account_id": account.pk,
        "account_owner_user_id": account.user_id,
        "account_type": account.account_type,
        "account_active": account.is_active,
        "actor_user_id": authorization.actor_user_id,
        "actor_authenticated": True,
        "principal_enabled": authorization.principal_enabled,
        "authority_identity": authorization.authority_identity,
        "authority_record_id": authorization.authority_record_id,
        "authority_sha256": authorization.authority_sha256,
        "authorization_scope": authorization.authorization_scope,
        "policy_version": authorization.policy_version,
        "policy_sha256": authorization.policy_sha256,
        "policy_enabled": authorization.policy_enabled,
        "policy_allows_operator_attested_upload": authorization.policy_allows_operator_attested_upload,
        "policy_ledger_currency": authorization.policy_ledger_currency,
        "policy_valid_from": _utc_text(authorization.policy_valid_from),
        "policy_valid_until": _utc_text(authorization.policy_valid_until),
        "policy_updated_by_id": authorization.policy_updated_by_id,
        "trade_id": request.trade_id,
        "trade_snapshot_hash": evidence.trade_snapshot_hash,
        "original_v4_receipt_hash": receipt_hash,
        "receipt_snapshot_hash": receipt_snapshot,
        "source_namespace": evidence.source_namespace,
        "source_record_id": evidence.source_record_id,
        "verifier_identity": evidence.verifier_identity,
        "source_evidence_hash": evidence.evidence_sha256,
        "source_payload_hash": evidence.source_payload_sha256,
        "source_observed_at": evidence.source_observed_at.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "evidence_verified_at": evidence.verified_at.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "request_payload_hash": request_hash,
        "idempotency_key": request.idempotency_key,
        "revision": revision,
        "account_revision": account_revision,
        "account_predecessor_hash": account_predecessor_hash,
        "previous_event_id": predecessor_id,
        "previous_fees": {
            "commission": _stable_decimal(evidence.previous_fee_components.commission),
            "transfer_fee": _stable_decimal(evidence.previous_fee_components.transfer_fee),
            "stamp_duty": _stable_decimal(evidence.previous_fee_components.stamp_duty),
        },
        "revised_fees": {
            "commission": _stable_decimal(evidence.revised_fee_components.commission),
            "transfer_fee": _stable_decimal(evidence.revised_fee_components.transfer_fee),
            "stamp_duty": _stable_decimal(evidence.revised_fee_components.stamp_duty),
        },
        "original_slippage": _stable_decimal(original_slippage),
        "posting_time": _utc_text(posted_at),
        "posting_date": posting_date.isoformat(),
    }


def _authority_snapshot_sha256(payload: dict[str, object]) -> str:
    """Hash the exact event-bound authority snapshot JSON."""

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_authority_snapshot_event(
    event: SimulatedFeeCorrectionEventModel,
    *,
    original_v4_receipt_hash: str | None,
) -> bool:
    """Validate the immutable locked-principal snapshot against its event row."""

    raw_snapshot = event.authority_snapshot_json
    if type(raw_snapshot) is not dict or not _is_digest(event.authority_snapshot_sha256):
        return False
    snapshot = cast(dict[str, object], raw_snapshot)
    expected_keys = frozenset(
        {
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
            "policy_enabled",
            "policy_allows_operator_attested_upload",
            "policy_ledger_currency",
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
            "account_revision",
            "account_predecessor_hash",
            "previous_event_id",
            "previous_fees",
            "revised_fees",
            "original_slippage",
            "posting_time",
            "posting_date",
        }
    )
    if set(snapshot) != expected_keys:
        return False
    if (
        snapshot["schema"] != "simulated-fee-correction-authority-event.v1"
        or snapshot["account_id"] != event.account_id
        or snapshot["account_type"] != "simulated"
        or snapshot["account_active"] is not True
        or type(snapshot["account_owner_user_id"]) is not int
        or snapshot["account_owner_user_id"] != event.actor_user_id
        or snapshot["actor_user_id"] != event.actor_user_id
        or snapshot["actor_authenticated"] is not True
        or snapshot["principal_enabled"] is not True
        or snapshot["authority_identity"] != event.authority_identity
        or snapshot["authority_record_id"] != event.authority_record_id
        or snapshot["authority_sha256"] != event.authority_hash
        or snapshot["authorization_scope"] != "simulated_fee_correction:operator_attested_upload"
        or type(snapshot["policy_version"]) is not int
        or snapshot["policy_version"] <= 0
        or snapshot["policy_sha256"] != event.authority_hash
        or not _is_digest(snapshot["policy_sha256"])
        or snapshot["policy_enabled"] is not True
        or snapshot["policy_allows_operator_attested_upload"] is not True
        or type(snapshot["policy_ledger_currency"]) is not str
        or len(snapshot["policy_ledger_currency"]) != 3
        or any(
            character < "A" or character > "Z" for character in snapshot["policy_ledger_currency"]
        )
        or (
            snapshot["policy_updated_by_id"] is not None
            and (
                type(snapshot["policy_updated_by_id"]) is not int
                or snapshot["policy_updated_by_id"] <= 0
            )
        )
        or snapshot["trade_id"] != event.trade_id
        or snapshot["trade_snapshot_hash"] != event.trade_snapshot_hash
        or snapshot["receipt_snapshot_hash"] != event.receipt_snapshot_hash
        or snapshot["source_namespace"] != event.source_namespace
        or snapshot["source_record_id"] != event.source_record_id
        or snapshot["verifier_identity"] != event.verifier_identity
        or snapshot["source_evidence_hash"] != event.source_evidence_hash
        or snapshot["source_payload_hash"] != event.source_payload_hash
        or snapshot["source_observed_at"]
        != event.source_observed_at.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
        or snapshot["evidence_verified_at"]
        != event.evidence_verified_at.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
        or snapshot["request_payload_hash"] != event.request_payload_hash
        or snapshot["idempotency_key"] != event.idempotency_key
        or snapshot["revision"] != event.revision
        or type(snapshot["account_revision"]) is not int
        or snapshot["account_revision"] != event.account_revision
        or snapshot["account_predecessor_hash"] != event.account_predecessor_hash
        or snapshot["previous_event_id"] != event.previous_event_id
        or snapshot["original_slippage"] != format(event.original_slippage, ".2f")
        or snapshot["posting_time"]
        != event.posted_at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        or snapshot["posting_date"] != event.posting_date.isoformat()
        or snapshot["original_v4_receipt_hash"] != original_v4_receipt_hash
    ):
        return False
    if event.receipt_snapshot_hash is None:
        if snapshot["original_v4_receipt_hash"] is not None:
            return False
    elif not _is_digest(snapshot["original_v4_receipt_hash"]):
        return False
    for fee_key in ("previous_fees", "revised_fees"):
        fee_snapshot = snapshot[fee_key]
        if type(fee_snapshot) is not dict:
            return False
        fees = cast(dict[str, object], fee_snapshot)
        if set(fees) != {"commission", "transfer_fee", "stamp_duty"}:
            return False
        prefix = "previous" if fee_key == "previous_fees" else "revised"
        expected_fees = (
            {
                "commission": event.previous_commission,
                "transfer_fee": event.previous_transfer_fee,
                "stamp_duty": event.previous_stamp_duty,
            }
            if prefix == "previous"
            else {
                "commission": event.revised_commission,
                "transfer_fee": event.revised_transfer_fee,
                "stamp_duty": event.revised_stamp_duty,
            }
        )
        if any(fees[name] != format(expected_fees[name], ".2f") for name in expected_fees):
            return False
    try:
        if _authority_snapshot_sha256(snapshot) != event.authority_snapshot_sha256:
            return False
        policy_from = _parse_utc_text(snapshot["policy_valid_from"])
        policy_until = _parse_utc_text(snapshot["policy_valid_until"])
    except (TypeError, ValueError):
        return False
    posted_at = event.posted_at.astimezone(UTC)
    if (policy_from is not None and posted_at < policy_from) or (
        policy_until is not None and posted_at >= policy_until
    ):
        return False
    return True


def _parse_utc_text(value: object) -> datetime | None:
    """Parse one canonical UTC snapshot timestamp, or an allowed null bound."""

    if value is None:
        return None
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError("snapshot timestamp must be canonical UTC text")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() is None or _utc_text(parsed) != value:
        raise ValueError("snapshot timestamp is not canonical")
    return parsed.astimezone(UTC)


def _same_evidence_semantics(
    before: VerifiedFeeCorrectionEvidence,
    current: VerifiedFeeCorrectionEvidence,
) -> bool:
    """Compare re-read source proof while allowing verification time to advance."""

    return (
        before.account_id == current.account_id
        and before.trade_id == current.trade_id
        and before.asset_code == current.asset_code
        and before.expected_revision == current.expected_revision
        and before.expected_predecessor_id == current.expected_predecessor_id
        and before.trade_snapshot_hash == current.trade_snapshot_hash
        and before.previous_fee_components == current.previous_fee_components
        and before.revised_fee_components == current.revised_fee_components
        and before.source_namespace == current.source_namespace
        and before.source_record_id == current.source_record_id
        and before.evidence_sha256 == current.evidence_sha256
        and before.source_payload_sha256 == current.source_payload_sha256
        and before.verifier_identity == current.verifier_identity
        and before.source_observed_at == current.source_observed_at
    )


def _same_authority(
    before: VerifiedFeeCorrectionAuthorization,
    current: VerifiedFeeCorrectionAuthorization,
) -> bool:
    """Require the protected-boundary authority proof to match exactly."""

    return before == current


def _receipt_from_event(
    event: SimulatedFeeCorrectionEventModel,
    *,
    replayed: bool,
) -> FeeCorrectionReceipt:
    """Project a persisted event to the idempotent application receipt."""

    if type(event.pk) is not int or event.pk <= 0:
        raise _blocked("费用更正事件缺少已保存主键", "FEE_CORRECTION_HISTORY_INVALID")
    return FeeCorrectionReceipt(
        event_id=event.pk,
        account_id=event.account_id,
        trade_id=event.trade_id,
        revision=event.revision,
        payload_hash=event.request_payload_hash,
        replayed=replayed,
    )


__all__ = [
    "_authority_snapshot_payload",
    "_authority_snapshot_sha256",
    "_blocked",
    "_is_digest",
    "_principal_user_id",
    "_receipt_from_event",
    "_request_payload_hash",
    "_same_authority",
    "_same_evidence_semantics",
    "validate_authority_snapshot_event",
]
