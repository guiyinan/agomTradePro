"""Strict lossless codecs for immutable tax liability state and journal components.

Public digests validate stored bytes and arithmetic consistency. They are not
owner authority, source qualification, or substitutes for original Audit and
Outbox verification by the atomic repository.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TypeGuard

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    CorporateActionTaxLiabilityState,
    CorporateActionTaxLiabilityTransition,
    TaxLiabilityCashAction,
    TaxLiabilityCashRequest,
    TaxLiabilityScope,
    TaxLiabilityTransitionKind,
    _scope_payload,
)
from core.exceptions import BusinessLogicError

_SCOPE_FIELDS = frozenset(
    {
        "account_id",
        "owner_user_id",
        "security_id",
        "asset_code",
        "corporate_action_id",
        "source_namespace",
        "logical_source_event_id",
        "target_disposition_id",
        "record_date",
        "target_settlement_date",
    }
)
_STATE_FIELDS = frozenset(
    {
        "schema",
        "scope",
        "assessment_revision_id",
        "supersedes_assessment_revision_id",
        "assessment_semantic_sha256",
        "currency_quantum",
        "assessed_amount",
        "net_collected_amount",
    }
)
_TRANSITION_FIELDS = frozenset(
    {
        "schema",
        "kind",
        "before_state_sha256",
        "state_after_sha256",
        "cash_request",
        "tax_due_delta",
        "collected_delta",
        "outstanding_delta",
        "cash_delta",
    }
)
_MAX_PAYLOAD_BYTES = 1_048_576


def _invalid(message: str) -> BusinessLogicError:
    """Classify stored financial evidence failures without repairing bytes."""
    return BusinessLogicError(message, code="TAX_LIABILITY_STORED_EVIDENCE_INVALID")


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow a JSON boundary object to exact string-keyed fields."""
    return type(value) is dict and all(type(key) is str for key in value)


def _object(value: object, fields: frozenset[str]) -> dict[str, object]:
    """Reject missing, unknown and weakly typed JSON object fields."""
    if not _is_object(value) or frozenset(value) != fields:
        raise _invalid("stored tax evidence has missing or unexpected fields")
    return value


def canonical_liability_json(payload: dict[str, object]) -> str:
    """Encode exact JSON-compatible financial facts using the Domain's ASCII codec."""
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise _invalid("stored tax evidence exceeds the supported component size")
        return encoded
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as error:
        raise _invalid("stored tax evidence is not canonical JSON") from error


def _read_document(payload: str, expected_sha256: str) -> dict[str, object]:
    """Verify exact byte seal and canonical form before narrowing any stored fields."""
    if (
        type(payload) is not str
        or type(expected_sha256) is not str
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise _invalid("stored tax evidence requires exact text and a SHA-256 seal")
    try:
        raw = payload.encode("utf-8")
        if len(raw) > _MAX_PAYLOAD_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise _invalid("stored tax evidence byte seal differs")
        parsed: object = json.loads(payload)
        if not _is_object(parsed) or canonical_liability_json(parsed) != payload:
            raise _invalid("stored tax evidence is not a canonical object")
        return parsed
    except (ValueError, UnicodeEncodeError, RecursionError) as error:
        raise _invalid("stored tax evidence cannot be decoded") from error


def _text(value: object) -> str:
    """Keep JSON strings exact for downstream Domain validation."""
    if type(value) is not str:
        raise _invalid("stored tax evidence string field is untyped")
    return value


def _integer(value: object) -> int:
    """Require an exact integer rather than a boolean or coerced float."""
    if type(value) is not int:
        raise _invalid("stored tax evidence identity is not an exact integer")
    return value


def _money(value: object) -> Decimal:
    """Decode lossless decimal text without binary floats or coercion defaults."""
    try:
        return Decimal(_text(value))
    except InvalidOperation as error:
        raise _invalid("stored tax evidence money is not decimal text") from error


def _date(value: object) -> date:
    """Decode one exact ISO calendar date without inventing a time of day."""
    text = _text(value)
    parsed = date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise _invalid("stored tax evidence date is not canonical")
    return parsed


def _scope(value: object) -> TaxLiabilityScope:
    """Narrow every stored scope field before constructing the Domain value."""
    fields = _object(value, _SCOPE_FIELDS)
    return TaxLiabilityScope(
        account_id=_integer(fields["account_id"]),
        owner_user_id=_integer(fields["owner_user_id"]),
        security_id=_text(fields["security_id"]),
        asset_code=_text(fields["asset_code"]),
        corporate_action_id=_text(fields["corporate_action_id"]),
        source_namespace=_text(fields["source_namespace"]),
        logical_source_event_id=_text(fields["logical_source_event_id"]),
        target_disposition_id=_text(fields["target_disposition_id"]),
        record_date=_date(fields["record_date"]),
        target_settlement_date=_date(fields["target_settlement_date"]),
    )


def tax_liability_scope_sha256(scope: TaxLiabilityScope) -> str:
    """Return the stable exact disposition scope used for journal serialization locks."""
    if type(scope) is not TaxLiabilityScope:
        raise _invalid("an exact tax liability scope is required")
    scope.__post_init__()
    return hashlib.sha256(canonical_liability_json(_scope_payload(scope)).encode()).hexdigest()


def encode_liability_state(state: CorporateActionTaxLiabilityState) -> str:
    """Retain the original verified Domain state payload byte for byte."""
    if type(state) is not CorporateActionTaxLiabilityState:
        raise _invalid("an exact tax liability state is required")
    state.verify_integrity()
    return canonical_liability_json(state._payload())


def decode_liability_state(payload: str, expected_sha256: str) -> CorporateActionTaxLiabilityState:
    """Reconstruct and revalidate exact state facts; a new hash never grants authority."""
    try:
        fields = _object(_read_document(payload, expected_sha256), _STATE_FIELDS)
        if fields["schema"] != "corporate-action-tax-liability-state.v1":
            raise _invalid("stored tax liability state schema is unknown")
        supersedes = fields["supersedes_assessment_revision_id"]
        state = CorporateActionTaxLiabilityState(
            scope=_scope(fields["scope"]),
            assessment_revision_id=_text(fields["assessment_revision_id"]),
            supersedes_assessment_revision_id=None if supersedes is None else _text(supersedes),
            assessment_semantic_sha256=_text(fields["assessment_semantic_sha256"]),
            currency_quantum=_money(fields["currency_quantum"]),
            assessed_amount=_money(fields["assessed_amount"]),
            net_collected_amount=_money(fields["net_collected_amount"]),
        )
        if state.state_sha256 != expected_sha256:
            raise _invalid("stored liability values differ from the canonical Domain state")
        return state
    except (DeferredDividendTaxValidationError, ValueError, InvalidOperation) as error:
        raise _invalid("stored tax liability state failed Domain validation") from error


def encode_liability_transition(transition: CorporateActionTaxLiabilityTransition) -> str:
    """Retain the exact Domain before/after lineage, cash request and arithmetic."""
    if type(transition) is not CorporateActionTaxLiabilityTransition:
        raise _invalid("an exact tax liability transition is required")
    transition.verify_integrity()
    return canonical_liability_json(transition._payload())


def decode_liability_transition(
    payload: str,
    expected_sha256: str,
    *,
    before_state: CorporateActionTaxLiabilityState | None,
    state_after: CorporateActionTaxLiabilityState,
) -> CorporateActionTaxLiabilityTransition:
    """Verify the original transition against its exact persisted predecessor state."""
    try:
        if type(state_after) is not CorporateActionTaxLiabilityState or (
            before_state is not None and type(before_state) is not CorporateActionTaxLiabilityState
        ):
            raise _invalid("stored journal requires exact typed before/after states")
        state_after.verify_integrity()
        if before_state is not None:
            before_state.verify_integrity()
        fields = _object(_read_document(payload, expected_sha256), _TRANSITION_FIELDS)
        if (
            fields["schema"] != "corporate-action-tax-liability-transition.v1"
            or fields["state_after_sha256"] != state_after.state_sha256
            or fields["before_state_sha256"]
            != (None if before_state is None else before_state.state_sha256)
        ):
            raise _invalid("stored journal differs from the exact state lineage")
        request_fields = fields["cash_request"]
        request: TaxLiabilityCashRequest | None = None
        if request_fields is not None:
            cash = _object(request_fields, frozenset({"action", "book_cash", "reserved_cash"}))
            request = TaxLiabilityCashRequest(
                action=TaxLiabilityCashAction(_text(cash["action"])),
                book_cash=_money(cash["book_cash"]),
                reserved_cash=_money(cash["reserved_cash"]),
            )
        transition = CorporateActionTaxLiabilityTransition(
            kind=TaxLiabilityTransitionKind(_text(fields["kind"])),
            before_state=before_state,
            state_after=state_after,
            cash_request=request,
            tax_due_delta=_money(fields["tax_due_delta"]),
            collected_delta=_money(fields["collected_delta"]),
            outstanding_delta=_money(fields["outstanding_delta"]),
            cash_delta=_money(fields["cash_delta"]),
        )
        if transition.transition_sha256 != expected_sha256:
            raise _invalid("stored financial journal differs from canonical Domain facts")
        return transition
    except (DeferredDividendTaxValidationError, ValueError, InvalidOperation) as error:
        raise _invalid("stored financial journal failed Domain validation") from error


__all__ = [
    "canonical_liability_json",
    "decode_liability_state",
    "decode_liability_transition",
    "encode_liability_state",
    "encode_liability_transition",
    "tax_liability_scope_sha256",
]
