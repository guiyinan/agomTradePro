"""Inactive content-addressed contracts for Portfolio policy benchmarks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

POLICY_BENCHMARK_SNAPSHOT_OWNER = "portfolio"
POLICY_BENCHMARK_SNAPSHOT_ARTIFACT_TYPE = "policy_benchmark_snapshot"
POLICY_BENCHMARK_SNAPSHOT_SCHEMA = "portfolio-policy-benchmark-snapshot.v1"
POLICY_BENCHMARK_SNAPSHOT_PERMISSION = "inactive"
POLICY_BENCHMARK_SNAPSHOT_BLOCKERS = (
    "planning_policy_owner_source_not_integrated",
    "benchmark_definition_owner_source_not_integrated",
    "daily_benchmark_valuation_not_integrated",
    "benchmark_approval_not_integrated",
)

_ACCOUNT_SOURCE = ("account", "unified_account_identity_snapshot")
_PLANNING_POLICY_SOURCE = ("portfolio", "planning_policy_activation")
_BENCHMARK_DEFINITION_SOURCE = ("portfolio", "policy_benchmark_definition")


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_decimal(value: object, field_name: str) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be an exact Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value.is_zero() and value.is_signed():
        raise ValueError(f"{field_name} cannot be negative zero")
    return value


def _decimal_text(value: Decimal) -> str:
    """Return one non-exponent canonical representation without changing value."""

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkSourceRef:
    """Exact owner-issued source identity with a bounded knowledge window."""

    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in ("owner", "artifact_type", "artifact_id", "artifact_version"):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("source reference validity window is invalid")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact source is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def to_payload(self) -> dict[str, object]:
        """Return the canonical source reference payload."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "content_hash": self.content_hash,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkComponent:
    """One ordered, positive, exact-Decimal policy benchmark component."""

    benchmark_code: str
    weight: Decimal
    ordinal: int

    def __post_init__(self) -> None:
        _require_token(self.benchmark_code, "benchmark_code", maximum=64)
        weight = _require_decimal(self.weight, "weight")
        if not Decimal("0") < weight <= Decimal("1"):
            raise ValueError("weight must be within (0, 1]")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical component payload with a plain Decimal weight."""

        return {
            "benchmark_code": self.benchmark_code,
            "weight": _decimal_text(self.weight),
            "ordinal": self.ordinal,
        }


@dataclass(frozen=True, slots=True)
class PortfolioPolicyBenchmarkSnapshot:
    """Portfolio-owned benchmark candidate that grants no execution authority."""

    snapshot_id: str
    snapshot_version: str
    account_namespace: str
    account_id: str
    owner_user_id: int
    base_currency: str
    account_identity_ref: PolicyBenchmarkSourceRef
    planning_policy_ref: PolicyBenchmarkSourceRef
    benchmark_definition_ref: PolicyBenchmarkSourceRef
    components: tuple[PolicyBenchmarkComponent, ...]
    cash_weight: Decimal
    inception_at: datetime
    observed_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_snapshot_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = POLICY_BENCHMARK_SNAPSHOT_OWNER
    artifact_type: str = POLICY_BENCHMARK_SNAPSHOT_ARTIFACT_TYPE
    schema: str = POLICY_BENCHMARK_SNAPSHOT_SCHEMA
    permission: str = POLICY_BENCHMARK_SNAPSHOT_PERMISSION
    blocker_codes: tuple[str, ...] = POLICY_BENCHMARK_SNAPSHOT_BLOCKERS

    def __post_init__(self) -> None:
        self._validate_fixed_authority()
        for field_name in (
            "snapshot_id",
            "snapshot_version",
            "account_namespace",
            "account_id",
            "base_currency",
        ):
            _require_token(getattr(self, field_name), field_name)
        if len(self.base_currency) != 3 or self.base_currency.upper() != self.base_currency:
            raise ValueError("base_currency must be an uppercase three-letter code")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        self._validate_sources()
        self._validate_components()
        self._validate_clocks()
        if self.supersedes_snapshot_hash is not None:
            _require_hash(self.supersedes_snapshot_hash, "supersedes_snapshot_hash")
        expected_identity = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity:
                raise ValueError("policy benchmark identity_hash is invalid")
        expected_content = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content:
                raise ValueError("policy benchmark content_hash is invalid")

    def _validate_fixed_authority(self) -> None:
        if self.owner != POLICY_BENCHMARK_SNAPSHOT_OWNER:
            raise ValueError("policy benchmark owner is fixed")
        if self.artifact_type != POLICY_BENCHMARK_SNAPSHOT_ARTIFACT_TYPE:
            raise ValueError("policy benchmark artifact_type is fixed")
        if self.schema != POLICY_BENCHMARK_SNAPSHOT_SCHEMA:
            raise ValueError("policy benchmark schema is fixed")
        if self.permission != POLICY_BENCHMARK_SNAPSHOT_PERMISSION:
            raise ValueError("policy benchmark permission is fixed inactive")
        if self.blocker_codes != POLICY_BENCHMARK_SNAPSHOT_BLOCKERS:
            raise ValueError("policy benchmark blocker_codes are fixed")

    def _validate_sources(self) -> None:
        expected = (
            ("account_identity_ref", _ACCOUNT_SOURCE),
            ("planning_policy_ref", _PLANNING_POLICY_SOURCE),
            ("benchmark_definition_ref", _BENCHMARK_DEFINITION_SOURCE),
        )
        for field_name, authority in expected:
            value = getattr(self, field_name)
            if type(value) is not PolicyBenchmarkSourceRef:
                raise TypeError(f"{field_name} must be an exact source reference")
            PolicyBenchmarkSourceRef.__post_init__(value)
            if (value.owner, value.artifact_type) != authority:
                raise ValueError(f"{field_name} owner or artifact type is invalid")

    def _validate_components(self) -> None:
        if type(self.components) is not tuple or not self.components:
            raise ValueError("components must be a non-empty exact tuple")
        codes: set[str] = set()
        total_weight = Decimal("0")
        for expected_ordinal, component in enumerate(self.components):
            if type(component) is not PolicyBenchmarkComponent:
                raise TypeError("components must contain exact benchmark components")
            PolicyBenchmarkComponent.__post_init__(component)
            if component.ordinal != expected_ordinal:
                raise ValueError("component ordinal must be contiguous and ordered")
            if component.benchmark_code in codes:
                raise ValueError("benchmark component codes must be unique")
            codes.add(component.benchmark_code)
            total_weight += component.weight
        cash_weight = _require_decimal(self.cash_weight, "cash_weight")
        if cash_weight != Decimal("0"):
            raise ValueError("cash_weight is fixed to exact zero in this schema")
        if total_weight + cash_weight != Decimal("1"):
            raise ValueError("benchmark component and cash weights must sum exactly to one")

    def _validate_clocks(self) -> None:
        for field_name in ("inception_at", "observed_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        expected_valid_until = min(
            self.account_identity_ref.valid_until,
            self.planning_policy_ref.valid_until,
            self.benchmark_definition_ref.valid_until,
        )
        if self.valid_until != expected_valid_until:
            raise ValueError("valid_until must equal the strict source minimum")
        if not self.inception_at <= self.observed_at <= self.recorded_at < self.valid_until:
            raise ValueError("policy benchmark clock sequence is invalid")
        if any(
            source.recorded_at > self.recorded_at
            for source in (
                self.account_identity_ref,
                self.planning_policy_ref,
                self.benchmark_definition_ref,
            )
        ):
            raise ValueError("policy benchmark source is not knowable at the recording clock")

    @property
    def activation_available(self) -> bool:
        """Remain false until all owner sources, valuation, and approval are integrated."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this candidate is explicitly inactive."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the inactive snapshot is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "owner_user_id": self.owner_user_id,
            "base_currency": self.base_currency,
            "account_identity_ref": self.account_identity_ref.to_payload(),
            "planning_policy_ref": self.planning_policy_ref.to_payload(),
            "benchmark_definition_ref": self.benchmark_definition_ref.to_payload(),
            "components": [component.to_payload() for component in self.components],
            "cash_weight": _decimal_text(self.cash_weight),
            "inception_at": _utc_text(self.inception_at),
            "observed_at": _utc_text(self.observed_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_snapshot_hash": self.supersedes_snapshot_hash,
            "permission": self.permission,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical snapshot with explicit inactive safety markers."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_policy_benchmark_snapshot_successor(
    previous: PortfolioPolicyBenchmarkSnapshot,
    successor: PortfolioPolicyBenchmarkSnapshot,
) -> None:
    """Validate one adjacent snapshot in the same account benchmark chain."""

    if type(previous) is not PortfolioPolicyBenchmarkSnapshot:
        raise TypeError("previous must be an exact policy benchmark snapshot")
    if type(successor) is not PortfolioPolicyBenchmarkSnapshot:
        raise TypeError("successor must be an exact policy benchmark snapshot")
    PortfolioPolicyBenchmarkSnapshot.__post_init__(previous)
    PortfolioPolicyBenchmarkSnapshot.__post_init__(successor)
    if successor.supersedes_snapshot_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous snapshot")
    if (
        successor.account_namespace != previous.account_namespace
        or successor.account_id != previous.account_id
        or successor.owner_user_id != previous.owner_user_id
    ):
        raise ValueError("successor changed policy benchmark account identity")
    if successor.base_currency != previous.base_currency:
        raise ValueError("successor changed policy benchmark base currency")
    if successor.inception_at != previous.inception_at:
        raise ValueError("successor changed policy benchmark inception")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


__all__ = [
    "POLICY_BENCHMARK_SNAPSHOT_ARTIFACT_TYPE",
    "POLICY_BENCHMARK_SNAPSHOT_BLOCKERS",
    "POLICY_BENCHMARK_SNAPSHOT_OWNER",
    "POLICY_BENCHMARK_SNAPSHOT_PERMISSION",
    "POLICY_BENCHMARK_SNAPSHOT_SCHEMA",
    "PolicyBenchmarkComponent",
    "PolicyBenchmarkSourceRef",
    "PortfolioPolicyBenchmarkSnapshot",
    "validate_policy_benchmark_snapshot_successor",
]
