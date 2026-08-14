"""Complete inactive definition contract for Portfolio policy benchmarks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

POLICY_BENCHMARK_DEFINITION_OWNER = "portfolio"
POLICY_BENCHMARK_DEFINITION_TYPE = "policy_benchmark_definition"
POLICY_BENCHMARK_DEFINITION_SCHEMA = "portfolio-policy-benchmark-definition.v1"
POLICY_BENCHMARK_DEFINITION_PERMISSION = "definition_only"
POLICY_BENCHMARK_DEFINITION_BLOCKERS = (
    "benchmark_methodology_owner_sources_not_integrated",
    "benchmark_definition_activation_not_integrated",
    "daily_benchmark_valuation_not_integrated",
)

_SOURCE_TYPES = (
    "corporate_action_methodology",
    "cost_tax_methodology",
    "fx_fixing_methodology",
    "price_fixing_methodology",
    "trading_calendar_definition",
)


def _token(value: object, field_name: str, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: object, field_name: str) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be an exact Decimal")
    if not value.is_finite() or (value.is_zero() and value.is_signed()):
        raise ValueError(f"{field_name} must be finite and cannot be negative zero")
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkMethodologyRef:
    """Exact owner-issued methodology or calendar definition reference."""

    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in ("owner", "artifact_type", "artifact_id", "artifact_version"):
            _token(getattr(self, field_name), field_name)
        if self.artifact_type not in _SOURCE_TYPES:
            raise ValueError("methodology artifact_type is not recognized")
        _hash(self.content_hash, "content_hash")
        _aware(self.recorded_at, "recorded_at")
        _aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("methodology reference validity window is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return the exact owner reference."""

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
class PolicyBenchmarkConstituentDefinition:
    """One ordered benchmark constituent with exact weight and currency."""

    benchmark_code: str
    price_identifier: str
    currency: str
    weight: Decimal
    ordinal: int

    def __post_init__(self) -> None:
        _token(self.benchmark_code, "benchmark_code", 64)
        _token(self.price_identifier, "price_identifier", 128)
        _token(self.currency, "currency", 3)
        if len(self.currency) != 3 or self.currency.upper() != self.currency:
            raise ValueError("currency must be an uppercase three-letter code")
        weight = _decimal(self.weight, "weight")
        if not Decimal("0") < weight <= Decimal("1"):
            raise ValueError("weight must be within (0, 1]")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("ordinal must be an exact non-negative integer")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical constituent."""

        return {
            "benchmark_code": self.benchmark_code,
            "price_identifier": self.price_identifier,
            "currency": self.currency,
            "weight": _decimal_text(self.weight),
            "ordinal": self.ordinal,
        }


@dataclass(frozen=True, slots=True)
class PortfolioPolicyBenchmarkDefinition:
    """Complete benchmark methodology definition without activation authority."""

    definition_id: str
    definition_version: str
    base_currency: str
    constituents: tuple[PolicyBenchmarkConstituentDefinition, ...]
    trading_calendar_ref: PolicyBenchmarkMethodologyRef
    price_fixing_ref: PolicyBenchmarkMethodologyRef
    fx_fixing_ref: PolicyBenchmarkMethodologyRef
    corporate_action_ref: PolicyBenchmarkMethodologyRef
    cost_tax_ref: PolicyBenchmarkMethodologyRef
    valuation_timezone: str
    valuation_cutoff: str
    evaluation_window_days: int
    max_price_age_seconds: int
    max_fx_age_seconds: int
    missing_price_policy: str
    missing_fx_policy: str
    recorded_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = POLICY_BENCHMARK_DEFINITION_OWNER
    artifact_type: str = POLICY_BENCHMARK_DEFINITION_TYPE
    schema: str = POLICY_BENCHMARK_DEFINITION_SCHEMA
    permission: str = POLICY_BENCHMARK_DEFINITION_PERMISSION
    blocker_codes: tuple[str, ...] = POLICY_BENCHMARK_DEFINITION_BLOCKERS

    def __post_init__(self) -> None:
        self._validate_authority()
        for field_name in (
            "definition_id",
            "definition_version",
            "base_currency",
            "valuation_timezone",
            "valuation_cutoff",
        ):
            _token(getattr(self, field_name), field_name)
        if len(self.base_currency) != 3 or self.base_currency.upper() != self.base_currency:
            raise ValueError("base_currency must be an uppercase three-letter code")
        if self.missing_price_policy != "fail_closed":
            raise ValueError("missing_price_policy is fixed fail_closed")
        if self.missing_fx_policy != "fail_closed":
            raise ValueError("missing_fx_policy is fixed fail_closed")
        for field_name in (
            "evaluation_window_days",
            "max_price_age_seconds",
            "max_fx_age_seconds",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be an exact positive integer")
        self._validate_constituents()
        refs = self._methodology_refs()
        expected_types = _SOURCE_TYPES
        if tuple(ref.artifact_type for ref in refs) != expected_types:
            raise ValueError("benchmark methodology refs must be complete and ordered")
        for ref in refs:
            if type(ref) is not PolicyBenchmarkMethodologyRef:
                raise TypeError("methodology refs must use the exact Domain type")
            PolicyBenchmarkMethodologyRef.__post_init__(ref)
        _aware(self.recorded_at, "recorded_at")
        _aware(self.valid_until, "valid_until")
        if any(ref.recorded_at > self.recorded_at for ref in refs):
            raise ValueError("methodology source is not knowable at definition recording")
        if self.valid_until != min(ref.valid_until for ref in refs):
            raise ValueError("valid_until must equal the methodology source minimum")
        if self.recorded_at >= self.valid_until:
            raise ValueError("benchmark definition validity window is invalid")
        expected_identity = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity)
        elif _hash(self.identity_hash, "identity_hash") != expected_identity:
            raise ValueError("benchmark definition identity_hash is invalid")
        expected_content = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content)
        elif _hash(self.content_hash, "content_hash") != expected_content:
            raise ValueError("benchmark definition content_hash is invalid")

    def _validate_authority(self) -> None:
        if (
            self.owner != POLICY_BENCHMARK_DEFINITION_OWNER
            or self.artifact_type != POLICY_BENCHMARK_DEFINITION_TYPE
            or self.schema != POLICY_BENCHMARK_DEFINITION_SCHEMA
            or self.permission != POLICY_BENCHMARK_DEFINITION_PERMISSION
            or self.blocker_codes != POLICY_BENCHMARK_DEFINITION_BLOCKERS
        ):
            raise ValueError("policy benchmark definition authority is fixed")

    def _validate_constituents(self) -> None:
        if type(self.constituents) is not tuple or not self.constituents:
            raise ValueError("constituents must be a non-empty exact tuple")
        total = Decimal("0")
        codes: set[str] = set()
        price_ids: set[str] = set()
        for ordinal, item in enumerate(self.constituents):
            if type(item) is not PolicyBenchmarkConstituentDefinition:
                raise TypeError("constituents must contain exact Domain values")
            PolicyBenchmarkConstituentDefinition.__post_init__(item)
            if item.ordinal != ordinal:
                raise ValueError("constituent ordinals must be contiguous and ordered")
            if item.benchmark_code in codes or item.price_identifier in price_ids:
                raise ValueError("constituent identities must be unique")
            codes.add(item.benchmark_code)
            price_ids.add(item.price_identifier)
            total += item.weight
        if total != Decimal("1"):
            raise ValueError("constituent weights must sum exactly to one")

    def _methodology_refs(self) -> tuple[PolicyBenchmarkMethodologyRef, ...]:
        return (
            self.corporate_action_ref,
            self.cost_tax_ref,
            self.fx_fixing_ref,
            self.price_fixing_ref,
            self.trading_calendar_ref,
        )

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a benchmark definition is never trade authority."""

        return True

    @property
    def activation_available(self) -> bool:
        """Remain false until owner methodologies and activation are integrated."""

        return False

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this definition is knowable and unexpired."""

        _aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "definition_id": self.definition_id,
            "definition_version": self.definition_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "base_currency": self.base_currency,
            "constituents": [item.to_payload() for item in self.constituents],
            "methodology_refs": [ref.to_payload() for ref in self._methodology_refs()],
            "valuation_timezone": self.valuation_timezone,
            "valuation_cutoff": self.valuation_cutoff,
            "evaluation_window_days": self.evaluation_window_days,
            "max_price_age_seconds": self.max_price_age_seconds,
            "max_fx_age_seconds": self.max_fx_age_seconds,
            "missing_price_policy": self.missing_price_policy,
            "missing_fx_policy": self.missing_fx_policy,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "permission": self.permission,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete definition and explicit inactive markers."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


__all__ = [
    "POLICY_BENCHMARK_DEFINITION_BLOCKERS",
    "POLICY_BENCHMARK_DEFINITION_OWNER",
    "POLICY_BENCHMARK_DEFINITION_PERMISSION",
    "POLICY_BENCHMARK_DEFINITION_SCHEMA",
    "POLICY_BENCHMARK_DEFINITION_TYPE",
    "PolicyBenchmarkConstituentDefinition",
    "PolicyBenchmarkMethodologyRef",
    "PortfolioPolicyBenchmarkDefinition",
]
