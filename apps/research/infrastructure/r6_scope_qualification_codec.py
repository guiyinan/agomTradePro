"""Strict codec for the canonical R6 scope-to-qualification owner graph."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.research.domain.r6_scope_qualification_registry import (
    BINDING_DEFINITION_VERSION,
    R6ScopeQualificationBindingDefinition,
    R6ScopeQualificationSourceReceipt,
)
from apps.research.domain.state_model_activation import R6ActivationScope
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationRef,
)


class R6ScopeQualificationCodecError(ValueError):
    """A persisted R6 binding payload is malformed or noncanonical."""


def _mapping(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise R6ScopeQualificationCodecError(f"{label} must be an exact object")
    payload = cast(dict[str, object], value)
    if frozenset(payload) != keys:
        raise R6ScopeQualificationCodecError(f"{label} keys differ")
    return payload


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise R6ScopeQualificationCodecError(f"{label} must be an exact string")
    return value


def _flag(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise R6ScopeQualificationCodecError(f"{label} must be an exact boolean")
    return value


def _utc_text(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R6ScopeQualificationCodecError("R6 binding clock is invalid")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _clock(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise R6ScopeQualificationCodecError(f"{label} is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise R6ScopeQualificationCodecError(f"{label} must be timezone-aware")
    canonical = parsed.astimezone(UTC)
    if text != canonical.isoformat(timespec="microseconds"):
        raise R6ScopeQualificationCodecError(f"{label} must use canonical UTC text")
    return canonical


_SCOPE_KEYS = frozenset(
    {
        "scope_id",
        "scope_version",
        "purpose",
        "label_protocol_version",
        "research_only",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "must_not_publish_current",
        "must_not_execute",
        "content_hash",
    }
)
_REF_KEYS = frozenset({"assessment_id", "assessment_hash"})
_DEFINITION_KEYS = frozenset(
    {
        "binding_id",
        "binding_version",
        "definition_version",
        "scope",
        "qualification_ref",
        "effective_at",
        "valid_until",
        "research_only",
        "must_not_publish_current",
        "must_not_use_for_decision",
        "must_not_replace_regime",
        "must_not_execute",
        "content_hash",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "source_receipt_id",
        "source_receipt_version",
        "source_owner",
        "binding_id",
        "binding_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "evidence_ref",
        "content_hash",
    }
)


def encode_r6_scope_qualification_definition(
    value: R6ScopeQualificationBindingDefinition,
) -> dict[str, object]:
    """Encode one recursively validated exact binding definition."""

    try:
        definition = R6ScopeQualificationBindingDefinition.validated_copy(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise R6ScopeQualificationCodecError("R6 binding definition is invalid") from error
    scope = definition.scope
    return {
        "binding_id": definition.binding_id,
        "binding_version": definition.binding_version,
        "definition_version": definition.definition_version,
        "scope": {
            "scope_id": scope.scope_id,
            "scope_version": scope.scope_version,
            "purpose": scope.purpose,
            "label_protocol_version": scope.label_protocol_version,
            "research_only": scope.research_only,
            "must_not_use_for_decision": scope.must_not_use_for_decision,
            "must_not_replace_regime": scope.must_not_replace_regime,
            "must_not_publish_current": scope.must_not_publish_current,
            "must_not_execute": scope.must_not_execute,
            "content_hash": scope.content_hash,
        },
        "qualification_ref": {
            "assessment_id": definition.qualification_ref.assessment_id,
            "assessment_hash": definition.qualification_ref.assessment_hash,
        },
        "effective_at": _utc_text(definition.effective_at),
        "valid_until": _utc_text(definition.valid_until),
        "research_only": definition.research_only,
        "must_not_publish_current": definition.must_not_publish_current,
        "must_not_use_for_decision": definition.must_not_use_for_decision,
        "must_not_replace_regime": definition.must_not_replace_regime,
        "must_not_execute": definition.must_not_execute,
        "content_hash": definition.content_hash,
    }


def decode_r6_scope_qualification_definition(
    value: object,
) -> R6ScopeQualificationBindingDefinition:
    """Strictly restore one canonical binding definition."""

    payload = _mapping(value, _DEFINITION_KEYS, "R6 binding definition")
    scope_payload = _mapping(payload["scope"], _SCOPE_KEYS, "R6 binding scope")
    ref_payload = _mapping(payload["qualification_ref"], _REF_KEYS, "R6 binding qualification ref")
    try:
        if _text(payload["definition_version"], "definition_version") != (
            BINDING_DEFINITION_VERSION
        ):
            raise ValueError("definition version differs")
        scope = R6ActivationScope(
            scope_id=_text(scope_payload["scope_id"], "scope_id"),
            scope_version=_text(scope_payload["scope_version"], "scope_version"),
            purpose=_text(scope_payload["purpose"], "purpose"),
            label_protocol_version=_text(
                scope_payload["label_protocol_version"], "label_protocol_version"
            ),
            research_only=_flag(scope_payload["research_only"], "scope research_only"),
            must_not_use_for_decision=_flag(
                scope_payload["must_not_use_for_decision"],
                "scope must_not_use_for_decision",
            ),
            must_not_replace_regime=_flag(
                scope_payload["must_not_replace_regime"],
                "scope must_not_replace_regime",
            ),
            must_not_publish_current=_flag(
                scope_payload["must_not_publish_current"],
                "scope must_not_publish_current",
            ),
            must_not_execute=_flag(scope_payload["must_not_execute"], "scope must_not_execute"),
        )
        if scope.content_hash != _text(scope_payload["content_hash"], "scope hash"):
            raise ValueError("scope hash differs")
        definition = R6ScopeQualificationBindingDefinition.create(
            binding_id=_text(payload["binding_id"], "binding_id"),
            binding_version=_text(payload["binding_version"], "binding_version"),
            scope=scope,
            qualification_ref=R6QualificationRef(
                _text(ref_payload["assessment_id"], "assessment_id"),
                _text(ref_payload["assessment_hash"], "assessment_hash"),
            ),
            effective_at=_clock(payload["effective_at"], "effective_at"),
            valid_until=_clock(payload["valid_until"], "valid_until"),
        )
        for key in (
            "research_only",
            "must_not_publish_current",
            "must_not_use_for_decision",
            "must_not_replace_regime",
            "must_not_execute",
        ):
            if getattr(definition, key) != _flag(payload[key], key):
                raise ValueError("definition safety flags differ")
        if definition.content_hash != _text(payload["content_hash"], "definition hash"):
            raise ValueError("definition hash differs")
        return definition
    except (AttributeError, TypeError, ValueError) as error:
        raise R6ScopeQualificationCodecError("R6 binding definition validation failed") from error


def encode_r6_scope_qualification_source(
    value: R6ScopeQualificationSourceReceipt,
) -> dict[str, object]:
    """Encode one exact Research source receipt."""

    try:
        source = R6ScopeQualificationSourceReceipt.validated_copy(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise R6ScopeQualificationCodecError("R6 binding source is invalid") from error
    return {
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_owner": source.source_owner,
        "binding_id": source.binding_id,
        "binding_version": source.binding_version,
        "definition_hash": source.definition_hash,
        "available_at": _utc_text(source.available_at),
        "valid_until": _utc_text(source.valid_until),
        "evidence_ref": source.evidence_ref,
        "content_hash": source.content_hash,
    }


def decode_r6_scope_qualification_source(
    value: object,
) -> R6ScopeQualificationSourceReceipt:
    """Strictly restore one Research source receipt."""

    payload = _mapping(value, _SOURCE_KEYS, "R6 binding source")
    try:
        source = R6ScopeQualificationSourceReceipt.create(
            source_receipt_id=_text(payload["source_receipt_id"], "source_receipt_id"),
            source_receipt_version=_text(
                payload["source_receipt_version"], "source_receipt_version"
            ),
            binding_id=_text(payload["binding_id"], "binding_id"),
            binding_version=_text(payload["binding_version"], "binding_version"),
            definition_hash=_text(payload["definition_hash"], "definition_hash"),
            available_at=_clock(payload["available_at"], "available_at"),
            valid_until=_clock(payload["valid_until"], "valid_until"),
            evidence_ref=_text(payload["evidence_ref"], "evidence_ref"),
        )
        if source.source_owner != _text(payload["source_owner"], "source_owner"):
            raise ValueError("source owner differs")
        if source.content_hash != _text(payload["content_hash"], "source hash"):
            raise ValueError("source hash differs")
        return source
    except (AttributeError, TypeError, ValueError) as error:
        raise R6ScopeQualificationCodecError("R6 binding source validation failed") from error


__all__ = [
    "R6ScopeQualificationCodecError",
    "decode_r6_scope_qualification_definition",
    "decode_r6_scope_qualification_source",
    "encode_r6_scope_qualification_definition",
    "encode_r6_scope_qualification_source",
]
