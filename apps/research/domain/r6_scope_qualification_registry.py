"""Canonical Research owner records for R6 scope-to-qualification bindings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256

from apps.research.domain.state_model_activation import (
    R6ActivationScope,
    validate_r6_activation_scope,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationRef,
)

BINDING_DEFINITION_VERSION = "research-r6-scope-qualification-definition.v1"
BINDING_SOURCE_RECEIPT_VERSION = "research-r6-scope-qualification-source.v1"


def _token(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value) > 300
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be a bounded exact token")
    return value


def _hash(value: object, label: str) -> str:
    text = _token(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _aware(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")
    return value


def _utc(value: datetime) -> str:
    return _aware(value, "R6 binding clock").astimezone(UTC).isoformat(timespec="microseconds")


def _canonical_hash(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _copy_scope(value: object) -> R6ActivationScope:
    if type(value) is not R6ActivationScope:
        raise TypeError("R6 binding scope must use the exact activation scope type")
    validate_r6_activation_scope(value)
    copied = R6ActivationScope(
        scope_id=value.scope_id,
        scope_version=value.scope_version,
        purpose=value.purpose,
        label_protocol_version=value.label_protocol_version,
        research_only=value.research_only,
        must_not_use_for_decision=value.must_not_use_for_decision,
        must_not_replace_regime=value.must_not_replace_regime,
        must_not_publish_current=value.must_not_publish_current,
        must_not_execute=value.must_not_execute,
    )
    if copied != value:
        raise ValueError("R6 binding scope differs after replay")
    return copied


def _copy_qualification_ref(value: object) -> R6QualificationRef:
    if type(value) is not R6QualificationRef:
        raise TypeError("R6 binding qualification ref type differs")
    R6QualificationRef.__post_init__(value)
    copied = R6QualificationRef(value.assessment_id, value.assessment_hash)
    if copied != value:
        raise ValueError("R6 binding qualification ref differs after replay")
    return copied


@dataclass(frozen=True)
class R6ScopeQualificationBindingDefinition:
    """One independent scope definition bound to an exact promoted qualification."""

    binding_id: str
    binding_version: str
    definition_version: str
    scope: R6ActivationScope
    qualification_ref: R6QualificationRef
    effective_at: datetime
    valid_until: datetime
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_replace_regime: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        binding_version: str,
        scope: R6ActivationScope,
        qualification_ref: R6QualificationRef,
        effective_at: datetime,
        valid_until: datetime,
    ) -> R6ScopeQualificationBindingDefinition:
        """Seal a complete owner definition without assessment backfilling."""

        return cls(
            binding_id=binding_id,
            binding_version=binding_version,
            definition_version=BINDING_DEFINITION_VERSION,
            scope=_copy_scope(scope),
            qualification_ref=_copy_qualification_ref(qualification_ref),
            effective_at=effective_at,
            valid_until=valid_until,
        )

    def __post_init__(self) -> None:
        _token(self.binding_id, "R6 binding definition binding_id")
        _token(self.binding_version, "R6 binding definition binding_version")
        if self.definition_version != BINDING_DEFINITION_VERSION:
            raise ValueError("R6 binding definition version is unsupported")
        scope = _copy_scope(self.scope)
        qualification_ref = _copy_qualification_ref(self.qualification_ref)
        _aware(self.effective_at, "R6 binding definition effective_at")
        _aware(self.valid_until, "R6 binding definition valid_until")
        if self.effective_at >= self.valid_until:
            raise ValueError("R6 binding definition validity is empty")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_replace_regime
            and self.must_not_execute
        ):
            raise ValueError("R6 binding definition safety flags differ")
        object.__setattr__(
            self,
            "content_hash",
            _canonical_hash(
                {
                    "schema": BINDING_DEFINITION_VERSION,
                    "binding": (self.binding_id, self.binding_version),
                    "scope": (scope.scope_id, scope.scope_version, scope.content_hash),
                    "qualification": (
                        qualification_ref.assessment_id,
                        qualification_ref.assessment_hash,
                    ),
                    "window": (_utc(self.effective_at), _utc(self.valid_until)),
                    "research_only": True,
                    "must_not_publish_current": True,
                    "must_not_use_for_decision": True,
                    "must_not_replace_regime": True,
                    "must_not_execute": True,
                }
            ),
        )

    def validated_copy(self) -> R6ScopeQualificationBindingDefinition:
        """Return an exact class-bound recursive reconstruction."""

        if type(self) is not R6ScopeQualificationBindingDefinition:
            raise TypeError("R6 binding definition type differs")
        copied = R6ScopeQualificationBindingDefinition.create(
            binding_id=self.binding_id,
            binding_version=self.binding_version,
            scope=_copy_scope(self.scope),
            qualification_ref=_copy_qualification_ref(self.qualification_ref),
            effective_at=self.effective_at,
            valid_until=self.valid_until,
        )
        if copied != self:
            raise ValueError("R6 binding definition differs after replay")
        return copied


@dataclass(frozen=True)
class R6ScopeQualificationSourceReceipt:
    """Independent Research receipt binding one exact owner definition."""

    source_receipt_id: str
    source_receipt_version: str
    source_owner: str
    binding_id: str
    binding_version: str
    definition_hash: str
    available_at: datetime
    valid_until: datetime
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        source_receipt_id: str,
        source_receipt_version: str,
        binding_id: str,
        binding_version: str,
        definition_hash: str,
        available_at: datetime,
        valid_until: datetime,
        evidence_ref: str,
    ) -> R6ScopeQualificationSourceReceipt:
        """Create a content-addressed Research source receipt."""

        values = (
            source_receipt_id,
            source_receipt_version,
            "research",
            binding_id,
            binding_version,
            definition_hash,
            available_at,
            valid_until,
            evidence_ref,
        )
        return cls(*values, _source_hash(*values))

    def __post_init__(self) -> None:
        for label, value in (
            ("source_receipt_id", self.source_receipt_id),
            ("source_receipt_version", self.source_receipt_version),
            ("source_owner", self.source_owner),
            ("binding_id", self.binding_id),
            ("binding_version", self.binding_version),
            ("evidence_ref", self.evidence_ref),
        ):
            _token(value, f"R6 binding source {label}")
        if self.source_receipt_version != BINDING_SOURCE_RECEIPT_VERSION:
            raise ValueError("R6 binding source version is unsupported")
        if self.source_owner != "research":
            raise ValueError("R6 binding source must be Research-owned")
        _hash(self.definition_hash, "R6 binding source definition_hash")
        _hash(self.content_hash, "R6 binding source content_hash")
        _aware(self.available_at, "R6 binding source available_at")
        _aware(self.valid_until, "R6 binding source valid_until")
        if self.available_at >= self.valid_until:
            raise ValueError("R6 binding source validity is empty")
        if self.content_hash != _source_hash(
            self.source_receipt_id,
            self.source_receipt_version,
            self.source_owner,
            self.binding_id,
            self.binding_version,
            self.definition_hash,
            self.available_at,
            self.valid_until,
            self.evidence_ref,
        ):
            raise ValueError("R6 binding source hash differs")

    def validated_copy(self) -> R6ScopeQualificationSourceReceipt:
        """Return an exact class-bound reconstruction."""

        if type(self) is not R6ScopeQualificationSourceReceipt:
            raise TypeError("R6 binding source type differs")
        copied = R6ScopeQualificationSourceReceipt.create(
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            binding_id=self.binding_id,
            binding_version=self.binding_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("R6 binding source differs after replay")
        return copied


def _source_hash(
    source_receipt_id: str,
    source_receipt_version: str,
    source_owner: str,
    binding_id: str,
    binding_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return _canonical_hash(
        {
            "schema": BINDING_SOURCE_RECEIPT_VERSION,
            "source": (source_receipt_id, source_receipt_version, source_owner),
            "binding": (binding_id, binding_version, definition_hash),
            "window": (_utc(available_at), _utc(valid_until)),
            "evidence_ref": evidence_ref,
        }
    )


__all__ = [
    "BINDING_DEFINITION_VERSION",
    "BINDING_SOURCE_RECEIPT_VERSION",
    "R6ScopeQualificationBindingDefinition",
    "R6ScopeQualificationSourceReceipt",
]
