"""Canonical evidence primitives for R5 fixed-income research contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum


def require_text(value: str, field_name: str, *, maximum: int = 200) -> None:
    """Validate one bounded non-blank text value."""

    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded non-blank string")


def require_token(value: str, field_name: str, *, maximum: int = 160) -> None:
    """Validate one bounded identifier without whitespace."""

    require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def require_aware(value: datetime, field_name: str) -> None:
    """Validate a timezone-aware timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def require_finite(value: Decimal, field_name: str) -> None:
    """Validate a finite Decimal value."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def require_sha256(value: str, field_name: str) -> None:
    """Validate a hexadecimal SHA-256 digest."""

    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def decimal_text(value: Decimal) -> str:
    """Return the canonical finite Decimal representation."""

    require_finite(value, "value")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def canonical_value(value: object) -> object:
    """Project supported values into deterministic JSON-compatible values."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, datetime):
        require_aware(value, "canonical datetime")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, tuple):
        return [canonical_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical payload dictionaries require string keys")
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    if is_dataclass(value):
        return {field.name: canonical_value(getattr(value, field.name)) for field in fields(value)}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    raise TypeError("canonical payload contains an unsupported value; use Decimal and exact tuples")


def canonical_hash(payload: object) -> str:
    """Return a lowercase SHA-256 digest over canonical JSON."""

    return hashlib.sha256(
        json.dumps(
            canonical_value(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class EvidenceRole(str, Enum):
    """Authoritative owner roles required by the R5 Phase-A contract."""

    PUBLICATION = "publication"
    BOND_MASTER = "bond_master"
    CASH_FLOW = "cash_flow"
    CALENDAR = "calendar"
    EXACT_PIT_INPUT = "exact_pit_input"
    FIXED_INCOME_ANALYTICS = "fixed_income_analytics"
    FIXED_INCOME_CANDIDATE = "fixed_income_candidate"
    FIXED_INCOME_INPUT_SET = "fixed_income_input_set"
    PORTFOLIO_INPUT = "portfolio_input"
    POLICY = "policy"


_EXPECTED_OWNER: dict[EvidenceRole, str] = {
    EvidenceRole.PUBLICATION: "data_center",
    EvidenceRole.BOND_MASTER: "data_center",
    EvidenceRole.CASH_FLOW: "data_center",
    EvidenceRole.CALENDAR: "data_center",
    EvidenceRole.EXACT_PIT_INPUT: "data_center",
    EvidenceRole.FIXED_INCOME_ANALYTICS: "fixed_income",
    EvidenceRole.FIXED_INCOME_CANDIDATE: "fixed_income",
    EvidenceRole.FIXED_INCOME_INPUT_SET: "fixed_income",
    EvidenceRole.PORTFOLIO_INPUT: "portfolio",
    EvidenceRole.POLICY: "research",
}


@dataclass(frozen=True)
class EvidenceLocator:
    """Stable ID/version locator accepted at an Application command boundary."""

    evidence_id: str
    version: str

    def __post_init__(self) -> None:
        require_token(self.evidence_id, "EvidenceLocator.evidence_id")
        require_token(self.version, "EvidenceLocator.version")


@dataclass(frozen=True)
class ExactEvidence:
    """Exact PIT evidence with distinct source and request-time clocks.

    ``observed_at`` is the source observation clock.  It is never derived from
    an evaluation/request timestamp.  ``available_at`` is the first time this
    exact version became knowable and ``valid_until`` is an exclusive bound.
    """

    role: EvidenceRole
    owner: str
    evidence_id: str
    version: str
    subject_id: str
    content_hash: str
    observed_at: datetime
    available_at: datetime
    valid_until: datetime
    currency: str | None
    curve_role: str | None
    upstream_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.role, EvidenceRole):
            raise ValueError("ExactEvidence.role is invalid")
        for name in ("owner", "evidence_id", "version", "subject_id"):
            require_token(str(getattr(self, name)), f"ExactEvidence.{name}")
        if self.owner != _EXPECTED_OWNER[self.role]:
            raise ValueError(
                f"{self.role.value} evidence must be owned by " f"{_EXPECTED_OWNER[self.role]}"
            )
        require_sha256(self.content_hash, "ExactEvidence.content_hash")
        for index, digest in enumerate(self.upstream_hashes):
            require_sha256(digest, f"ExactEvidence.upstream_hashes[{index}]")
        if len(self.upstream_hashes) != len(set(self.upstream_hashes)):
            raise ValueError("ExactEvidence.upstream_hashes cannot contain duplicates")
        if self.upstream_hashes != tuple(sorted(self.upstream_hashes)):
            raise ValueError("ExactEvidence.upstream_hashes must use canonical sort order")
        for name in ("observed_at", "available_at", "valid_until"):
            require_aware(getattr(self, name), f"ExactEvidence.{name}")
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede source observed_at")
        if self.valid_until <= self.available_at:
            raise ValueError("valid_until must follow available_at")
        if self.currency is not None:
            require_token(self.currency, "ExactEvidence.currency", maximum=12)
        if self.curve_role is not None:
            require_token(self.curve_role, "ExactEvidence.curve_role")

    @property
    def locator(self) -> EvidenceLocator:
        """Return the stable ID/version locator for exact rereads."""

        return EvidenceLocator(self.evidence_id, self.version)

    @property
    def seal_hash(self) -> str:
        """Hash the complete identity, PIT clocks, provenance, and source hash."""

        return canonical_hash(
            {
                "role": self.role,
                "owner": self.owner,
                "evidence_id": self.evidence_id,
                "version": self.version,
                "subject_id": self.subject_id,
                "content_hash": self.content_hash.lower(),
                "observed_at": self.observed_at,
                "available_at": self.available_at,
                "valid_until": self.valid_until,
                "currency": self.currency,
                "curve_role": self.curve_role,
                "upstream_hashes": tuple(digest.lower() for digest in self.upstream_hashes),
            }
        )

    def usability_reason(self, evaluated_at: datetime) -> str | None:
        """Return a stable future/stale reason or ``None`` when exact evidence is usable."""

        require_aware(evaluated_at, "evaluated_at")
        if self.observed_at > evaluated_at or self.available_at > evaluated_at:
            return "evidence_from_future"
        if self.valid_until <= evaluated_at:
            return "evidence_stale"
        return None


def exact_evidence_matches(
    expected: ExactEvidence,
    actual: ExactEvidence,
) -> bool:
    """Return whether an authoritative reread matches the expected complete seal."""

    return expected.seal_hash == actual.seal_hash


__all__ = [
    "EvidenceLocator",
    "EvidenceRole",
    "ExactEvidence",
    "canonical_hash",
    "canonical_value",
    "decimal_text",
    "exact_evidence_matches",
    "require_aware",
    "require_finite",
    "require_sha256",
    "require_text",
    "require_token",
]
