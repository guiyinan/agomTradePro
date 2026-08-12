"""Immutable approval and activation records for Evidence operator specs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.research.domain.evidence_contracts import EvidenceOperatorSpec


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: object, field_name: str) -> None:
    if type(value) is not str or len(value) != 64 or value != value.lower():
        raise ValueError(f"{field_name} must be a sha256 hex digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a sha256 hex digest") from error


def _require_optional_hash(value: object, field_name: str) -> None:
    if value is not None:
        _require_hash(value, field_name)


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _approval_payload(
    *,
    owner: str,
    capability: str,
    approval_id: str,
    approval_version: str,
    owner_record_id: str,
    owner_record_version: str,
    owner_record_hash: str,
    operator_id: str,
    operator_version: str,
    definition_hash: str,
    supersedes_activation_hash: str | None,
    approved_by: str,
    issued_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "owner": owner,
        "capability": capability,
        "approval_id": approval_id,
        "approval_version": approval_version,
        "owner_record_id": owner_record_id,
        "owner_record_version": owner_record_version,
        "owner_record_hash": owner_record_hash,
        "operator_id": operator_id,
        "operator_version": operator_version,
        "definition_hash": definition_hash,
        "supersedes_activation_hash": supersedes_activation_hash,
        "approved_by": approved_by,
        "issued_at": _utc_text(issued_at),
        "valid_until": _utc_text(valid_until),
    }


def _activation_payload(
    *,
    definition_hash: str,
    approval_hash: str,
    recorded_at: datetime,
    supersedes_activation_hash: str | None,
) -> dict[str, object]:
    return {
        "definition_hash": definition_hash,
        "approval_hash": approval_hash,
        "recorded_at": _utc_text(recorded_at),
        "supersedes_activation_hash": supersedes_activation_hash,
    }


@dataclass(frozen=True)
class EvidenceOperatorSpecDefinition:
    """Trusted definition plus the exact activation record it supersedes."""

    operator_spec: EvidenceOperatorSpec
    supersedes_activation_hash: str | None
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        operator_spec: EvidenceOperatorSpec,
        supersedes_activation_hash: str | None,
    ) -> EvidenceOperatorSpecDefinition:
        """Seal a trusted version definition and its predecessor identity."""

        values: dict[str, object] = {
            "operator_spec_hash": operator_spec.content_hash,
            "supersedes_activation_hash": supersedes_activation_hash,
        }
        return cls(
            operator_spec=operator_spec,
            supersedes_activation_hash=supersedes_activation_hash,
            content_hash=_canonical_hash(values),
        )

    def __post_init__(self) -> None:
        if type(self.operator_spec) is not EvidenceOperatorSpec:
            raise TypeError("operator_spec must be exact EvidenceOperatorSpec")
        EvidenceOperatorSpec.__post_init__(self.operator_spec)
        _require_optional_hash(
            self.supersedes_activation_hash,
            "supersedes_activation_hash",
        )
        _require_hash(self.content_hash, "content_hash")
        expected = _canonical_hash(
            {
                "operator_spec_hash": self.operator_spec.content_hash,
                "supersedes_activation_hash": self.supersedes_activation_hash,
            }
        )
        if self.content_hash != expected:
            raise ValueError("operator specification definition content_hash is invalid")


@dataclass(frozen=True)
class EvidenceOperatorSpecApprovalReceipt:
    """Research copy of one exact external-owner approval."""

    owner: str
    capability: str
    approval_id: str
    approval_version: str
    owner_record_id: str
    owner_record_version: str
    owner_record_hash: str
    operator_id: str
    operator_version: str
    definition_hash: str
    supersedes_activation_hash: str | None
    approved_by: str
    issued_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        approval_id: str,
        approval_version: str,
        owner_record_id: str,
        owner_record_version: str,
        owner_record_hash: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        approved_by: str,
        issued_at: datetime,
        valid_until: datetime,
    ) -> EvidenceOperatorSpecApprovalReceipt:
        """Create a canonical receipt with fixed external authority semantics."""

        values = _approval_payload(
            owner="risk_center",
            capability="evidence_operator_spec_activation",
            approval_id=approval_id,
            approval_version=approval_version,
            owner_record_id=owner_record_id,
            owner_record_version=owner_record_version,
            owner_record_hash=owner_record_hash,
            operator_id=operator_id,
            operator_version=operator_version,
            definition_hash=definition_hash,
            supersedes_activation_hash=supersedes_activation_hash,
            approved_by=approved_by,
            issued_at=issued_at,
            valid_until=valid_until,
        )
        return cls(
            owner="risk_center",
            capability="evidence_operator_spec_activation",
            approval_id=approval_id,
            approval_version=approval_version,
            owner_record_id=owner_record_id,
            owner_record_version=owner_record_version,
            owner_record_hash=owner_record_hash,
            operator_id=operator_id,
            operator_version=operator_version,
            definition_hash=definition_hash,
            supersedes_activation_hash=supersedes_activation_hash,
            approved_by=approved_by,
            issued_at=issued_at,
            valid_until=valid_until,
            content_hash=_canonical_hash(values),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "owner",
            "capability",
            "approval_id",
            "approval_version",
            "owner_record_id",
            "owner_record_version",
            "operator_id",
            "operator_version",
            "approved_by",
        ):
            _require_token(getattr(self, field_name), field_name)
        if self.owner != "risk_center" or self.capability != "evidence_operator_spec_activation":
            raise ValueError("operator specification approval authority is invalid")
        for field_name in ("owner_record_hash", "definition_hash", "content_hash"):
            _require_hash(getattr(self, field_name), field_name)
        _require_optional_hash(
            self.supersedes_activation_hash,
            "supersedes_activation_hash",
        )
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.valid_until, "valid_until")
        if self.issued_at >= self.valid_until:
            raise ValueError("approval validity window is invalid")
        expected = _canonical_hash(
            _approval_payload(
                owner=self.owner,
                capability=self.capability,
                approval_id=self.approval_id,
                approval_version=self.approval_version,
                owner_record_id=self.owner_record_id,
                owner_record_version=self.owner_record_version,
                owner_record_hash=self.owner_record_hash,
                operator_id=self.operator_id,
                operator_version=self.operator_version,
                definition_hash=self.definition_hash,
                supersedes_activation_hash=self.supersedes_activation_hash,
                approved_by=self.approved_by,
                issued_at=self.issued_at,
                valid_until=self.valid_until,
            )
        )
        if self.content_hash != expected:
            raise ValueError("operator specification approval content_hash is invalid")


@dataclass(frozen=True)
class ActivatedEvidenceOperatorSpec:
    """Research-owned immutable activated operator spec and approval graph."""

    definition: EvidenceOperatorSpecDefinition
    approval: EvidenceOperatorSpecApprovalReceipt
    recorded_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        definition: EvidenceOperatorSpecDefinition,
        approval: EvidenceOperatorSpecApprovalReceipt,
        recorded_at: datetime,
    ) -> ActivatedEvidenceOperatorSpec:
        """Validate and seal one exact activated version."""

        values = _activation_payload(
            definition_hash=definition.content_hash,
            approval_hash=approval.content_hash,
            recorded_at=recorded_at,
            supersedes_activation_hash=definition.supersedes_activation_hash,
        )
        return cls(
            definition=definition,
            approval=approval,
            recorded_at=recorded_at,
            content_hash=_canonical_hash(values),
        )

    def __post_init__(self) -> None:
        if type(self.definition) is not EvidenceOperatorSpecDefinition:
            raise TypeError("definition must be exact EvidenceOperatorSpecDefinition")
        if type(self.approval) is not EvidenceOperatorSpecApprovalReceipt:
            raise TypeError("approval must be exact EvidenceOperatorSpecApprovalReceipt")
        EvidenceOperatorSpecDefinition.__post_init__(self.definition)
        EvidenceOperatorSpecApprovalReceipt.__post_init__(self.approval)
        _require_aware(self.recorded_at, "recorded_at")
        _require_hash(self.content_hash, "content_hash")
        spec = self.definition.operator_spec
        if (
            self.approval.operator_id != spec.operator_id
            or self.approval.operator_version != spec.operator_version
            or self.approval.definition_hash != self.definition.content_hash
            or self.approval.supersedes_activation_hash
            != self.definition.supersedes_activation_hash
        ):
            raise ValueError("operator specification approval substitution")
        if not self.approval.issued_at <= self.recorded_at < self.approval.valid_until:
            raise ValueError("operator specification recorded outside approval validity")
        if not spec.activated_at <= self.recorded_at < spec.valid_until:
            raise ValueError("operator specification recorded outside specification validity")
        expected = _canonical_hash(
            _activation_payload(
                definition_hash=self.definition.content_hash,
                approval_hash=self.approval.content_hash,
                recorded_at=self.recorded_at,
                supersedes_activation_hash=self.definition.supersedes_activation_hash,
            )
        )
        if self.content_hash != expected:
            raise ValueError("activated operator specification content_hash is invalid")

    @property
    def operator_spec(self) -> EvidenceOperatorSpec:
        """Return the strictly bound canonical operator specification."""

        return self.definition.operator_spec

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this version is knowable and valid at a PIT cutoff."""

        _require_aware(as_of, "as_of")
        spec = self.operator_spec
        return (
            self.recorded_at <= as_of
            and spec.activated_at <= as_of < spec.valid_until
            and self.approval.issued_at <= as_of < self.approval.valid_until
        )


__all__ = [
    "ActivatedEvidenceOperatorSpec",
    "EvidenceOperatorSpecApprovalReceipt",
    "EvidenceOperatorSpecDefinition",
]
