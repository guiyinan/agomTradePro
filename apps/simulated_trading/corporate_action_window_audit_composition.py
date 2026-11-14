"""Retain finite current-window proof inside an audited financial transaction."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import fields, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol, cast

from django.utils import timezone

from apps.audit.domain.system_audit_event import JSONValue
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowEvidence,
    CorporateActionCurrentOfficialWindowReader,
    CorporateActionCurrentOfficialWindowReason,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
)
from apps.simulated_trading.application.corporate_action_share_tax_proof import (
    ShareCapitalTaxQualificationProof,
)
from apps.simulated_trading.application.corporate_action_window_policy_provenance import (
    CorporateActionWindowPolicyProvenance,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionKind,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_constructor_codec import (
    encode_corporate_action_constructor,
    restore_corporate_action_constructor,
)

_SCHEMA = "simulated.corporate_action.official_window.v2"
_logger = logging.getLogger(__name__)
_FIELDS = frozenset(field.name for field in fields(CorporateActionCurrentOfficialWindowEvidence))
_PAYLOAD_FIELDS = (_FIELDS - {"freshness_status"}) | {
    "schema",
    "freshness_at_check",
    "request_payload_sha256",
}


def _blocked(message: str) -> CorporateActionPostingBlockedError:
    """Return the stable financial-window blocking outcome."""
    _logger.warning("Corporate-action financial window blocked: %s", message)
    return CorporateActionPostingBlockedError(
        message,
        code="CORPORATE_ACTION_CURRENT_OFFICIAL_WINDOW_BLOCKED",
    )


def _text(value: JSONValue) -> str:
    """Narrow a retained JSON token without coercing booleans or missing values."""
    if type(value) is not str or not value or len(value) > 512:
        raise _blocked("retained window text is invalid")
    return value


def _positive_int(value: JSONValue) -> int:
    """Narrow an exact positive account identity at the JSON boundary."""
    if type(value) is not int or value <= 0:
        raise _blocked("retained window account identity is invalid")
    return value


def _instant(value: JSONValue) -> datetime:
    """Parse a canonical aware original instant without refreshing its clock."""
    try:
        instant = datetime.fromisoformat(_text(value))
        if instant.tzinfo is None or instant.utcoffset() is None or instant.isoformat() != value:
            raise ValueError("noncanonical original instant")
        return instant
    except (TypeError, ValueError, OverflowError) as error:
        raise _blocked("retained window instant is invalid") from error


def _day(value: JSONValue) -> date:
    """Parse one exact original date-only endpoint."""
    try:
        day = date.fromisoformat(_text(value))
        if day.isoformat() != value:
            raise ValueError("noncanonical original date")
        return day
    except (TypeError, ValueError) as error:
        raise _blocked("retained window date is invalid") from error


def corporate_action_window_audit_payload(
    evidence: CorporateActionCurrentOfficialWindowEvidence,
    request: CorporateActionStageRequest,
    *,
    recorded_at: datetime,
) -> dict[str, JSONValue]:
    """Serialize exact entry-time window evidence; preserve every original clock.

    Freshness is explicitly historical at this check. The retained material is
    not a later current-window lease or independent permission to write money.
    """
    try:
        if type(evidence) is not CorporateActionCurrentOfficialWindowEvidence:
            raise ValueError("window evidence must be typed")
        evidence.__post_init__()
        request.__post_init__()
        if (
            not evidence.window_ready
            or evidence.account_id != request.account_id
            or evidence.owner_user_id != request.owner_user_id
            or evidence.asset_code != request.asset_code
            or evidence.security_id != request.security_id
            or evidence.source_record_id != request.source_record_id
            or evidence.source_revision_id != request.source_revision_id
            or evidence.source_payload_sha256 != request.source_payload_sha256
            or evidence.source_observed_at != request.source_observed_at
            or evidence.checked_at is None
            or evidence.expires_at is None
            or type(recorded_at) is not datetime
            or recorded_at.tzinfo is None
            or recorded_at.utcoffset() is None
            or not request.qualified_at <= evidence.checked_at <= recorded_at < evidence.expires_at
            or request.posted_at > recorded_at
        ):
            raise ValueError("window evidence differs from its request or original Audit clock")
    except (TypeError, ValueError, OverflowError) as error:
        raise _blocked("current official-window evidence is unavailable or changed") from error
    payload: dict[str, JSONValue] = {}
    if evidence.share_tax_proof is not None:
        evidence.share_tax_proof.verify_for(request, as_of=recorded_at)
    for field in fields(evidence):
        value: object = getattr(evidence, field.name)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, StrEnum):
            value = value.value
        elif type(value) is CorporateActionWindowPolicyProvenance:
            payload[field.name] = encode_corporate_action_constructor(value)
            continue
        elif type(value) is ShareCapitalTaxQualificationProof:
            payload[field.name] = encode_corporate_action_constructor(value)
            continue
        if value is not None and type(value) not in (str, int, bool):
            raise _blocked("window evidence cannot be serialized exactly")
        payload[field.name] = cast(JSONValue, value)
    payload["freshness_at_check"] = payload.pop("freshness_status")
    payload["schema"] = _SCHEMA
    payload["request_payload_sha256"] = request.payload_sha256
    return payload


def restore_corporate_action_window_audit_evidence(
    payload: JSONValue,
    request: CorporateActionStageRequest,
    *,
    recorded_at: datetime,
) -> CorporateActionCurrentOfficialWindowEvidence:
    """Validate original Audit proof at its original clock, without granting current use."""
    if (
        not isinstance(payload, dict)
        or set(payload) != _PAYLOAD_FIELDS
        or payload.get("schema") != _SCHEMA
        or payload.get("window_ready") is not True
        or payload.get("must_not_use_for_decision") is not True
    ):
        raise _blocked("retained window evidence shape is invalid")
    try:
        evidence = CorporateActionCurrentOfficialWindowEvidence(
            window_ready=True,
            reason_code=CorporateActionCurrentOfficialWindowReason.WINDOW_READY_PREREQUISITE_ONLY,
            freshness_status="current",
            reliability_status="verified",
            account_id=_positive_int(payload["account_id"]),
            owner_user_id=_positive_int(payload["owner_user_id"]),
            asset_code=_text(payload["asset_code"]),
            security_id=_text(payload["security_id"]),
            source_record_id=_text(payload["source_record_id"]),
            source_revision_id=_text(payload["source_revision_id"]),
            source_payload_sha256=_text(payload["source_payload_sha256"]),
            source_observed_at=_instant(payload["source_observed_at"]),
            window_start_on=_day(payload["window_start_on"]),
            window_end_on=_day(payload["window_end_on"]),
            original_first_observed_at=_instant(payload["original_first_observed_at"]),
            original_listing_verified_at=_instant(payload["original_listing_verified_at"]),
            original_proof_recorded_at=_instant(payload["original_proof_recorded_at"]),
            checked_at=_instant(payload["checked_at"]),
            expires_at=_instant(payload["expires_at"]),
            runtime_environment=_text(payload["runtime_environment"]),
            policy_sha256=_text(payload["policy_sha256"]),
            calendar_policy_sha256=_text(payload["calendar_policy_sha256"]),
            scope_sha256=_text(payload["scope_sha256"]),
            selected_event_sha256=_text(payload["selected_event_sha256"]),
            policy_provenance=_restore_policy_provenance(payload["policy_provenance"]),
            share_tax_proof=_restore_share_tax_proof(payload["share_tax_proof"]),
        )
    except (TypeError, ValueError, OverflowError, KeyError) as error:
        raise _blocked("retained window evidence is invalid") from error
    if corporate_action_window_audit_payload(evidence, request, recorded_at=recorded_at) != payload:
        raise _blocked("retained window evidence differs from its canonical request binding")
    return evidence


def _restore_policy_provenance(value: JSONValue) -> CorporateActionWindowPolicyProvenance:
    """Restore full original selected configuration through trusted static constructors."""
    restored = restore_corporate_action_constructor(value, CorporateActionWindowPolicyProvenance)
    if type(restored) is not CorporateActionWindowPolicyProvenance:
        raise _blocked("retained window configuration provenance is invalid")
    return restored


def _restore_share_tax_proof(value: JSONValue) -> ShareCapitalTaxQualificationProof | None:
    """Restore original complete model proof without asking for current sources or consent."""
    if value is None:
        return None
    restored = restore_corporate_action_constructor(value, ShareCapitalTaxQualificationProof)
    if type(restored) is not ShareCapitalTaxQualificationProof:
        raise _blocked("retained share model proof is invalid")
    return restored


def corporate_action_window_audit_sha256(payload: dict[str, JSONValue]) -> str:
    """Hash the complete canonical window material retained with the financial Audit."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ShareCapitalTaxProofReader(Protocol):
    """Read actual server-composed share model evidence for this exact financial request."""

    def read_current(
        self, request: CorporateActionStageRequest, *, as_of: datetime
    ) -> ShareCapitalTaxQualificationProof:
        """Return complete original configuration/instrument/source qualification."""
        ...


class CorporateActionWindowAuditGate:
    """Check a current window inside the owner transaction and again before commit."""

    def __init__(
        self,
        reader: CorporateActionCurrentOfficialWindowReader,
        *,
        share_tax_reader: ShareCapitalTaxProofReader | None = None,
    ) -> None:
        """Bind the server-composed current-window reader, never a client payload."""
        self._reader = reader
        self._share_tax_reader = share_tax_reader

    def read_entry_evidence(
        self, request: CorporateActionStageRequest
    ) -> CorporateActionCurrentOfficialWindowEvidence:
        """Capture original current-window evidence while the account lock is held."""
        evidence = self._reader.read_current(request, as_of=timezone.now())
        if type(evidence) is not CorporateActionCurrentOfficialWindowEvidence:
            raise _blocked("current official-window reader returned an untyped result")
        evidence.__post_init__()
        if not evidence.window_ready:
            raise _blocked(
                f"current official-window evidence blocked: {evidence.reason_code.value}"
            )
        if (
            request.action_kind is CorporateActionKind.SHARE_DISTRIBUTION
            and self._share_tax_reader is not None
        ):
            proof = self._share_tax_reader.read_current(request, as_of=timezone.now())
            checked = timezone.now()
            proof.verify_for(request, as_of=checked)
            if (
                evidence.checked_at is None
                or evidence.expires_at is None
                or checked < evidence.checked_at
            ):
                raise _blocked("share model has no complete official financial window")
            evidence = replace(
                evidence,
                checked_at=checked,
                expires_at=min(evidence.expires_at, proof.valid_until),
                share_tax_proof=proof,
            )
        corporate_action_window_audit_payload(evidence, request, recorded_at=timezone.now())
        return evidence

    def assert_unchanged(
        self,
        request: CorporateActionStageRequest,
        original: CorporateActionCurrentOfficialWindowEvidence,
    ) -> CorporateActionCurrentOfficialWindowEvidence:
        """Reject changed policy, calendar, body, window head, expiry or source identity."""
        current = self.read_entry_evidence(request)
        if original.share_tax_proof is not None:
            if (
                current.share_tax_proof is None
                or current.share_tax_proof.selection_sha256
                != original.share_tax_proof.selection_sha256
            ):
                raise _blocked("current share model changed before financial commit")
            current_for_comparison = replace(current, share_tax_proof=original.share_tax_proof)
        else:
            current_for_comparison = current
        if (
            current.checked_at is None
            or original.checked_at is None
            or current.checked_at < original.checked_at
            or replace(current_for_comparison, checked_at=original.checked_at) != original
        ):
            raise _blocked("current official-window evidence changed before financial commit")
        return current
