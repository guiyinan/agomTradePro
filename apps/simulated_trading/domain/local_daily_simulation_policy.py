"""Explicit source and calculation policy for historical daily simulations."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from .execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
)

_POLICY_SCHEMA = "local-daily-simulation-policy.v1"
_BINDING_SCHEMA = "local-daily-simulation-policy-binding.v1"
_POLICY_PURPOSE = "historical_daily_simulation"
_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "purpose",
        "policy_id",
        "version",
        "price_publication_key",
        "provider_configuration_id",
        "provider_name",
        "instrument_snapshot_id",
        "currency",
        "frequency",
        "adjustment",
        "volume_unit",
        "participation_rate",
        "share_step",
        "allowed_qmt_suspend_flags",
        "currency_basis",
        "qmt_status_basis",
        "limit_price_basis",
    }
)
_PROVENANCE_FIELDS = frozenset(
    {
        "runtime_environment",
        "profile_id",
        "profile_key",
        "profile_version",
        "profile_content_hash",
        "profile_activated_at",
        "snapshot_id",
        "snapshot_content_hash",
        "snapshot_generated_at",
        "snapshot_effective_from",
        "read_at",
    }
)


class LocalDailySimulationPolicyError(SimulatedSettlementContractError):
    """Raised when a daily simulation policy or its runtime binding is invalid."""


def _require_policy_token(value: object, field_name: str) -> None:
    """Require one exact bounded policy or runtime identity token."""

    try:
        _require_token(value, field_name)
    except SimulatedSettlementContractError as error:
        raise LocalDailySimulationPolicyError(f"{field_name} is invalid") from error


def _require_provider_display_name(value: object) -> None:
    """Require a bounded configured provider name while allowing internal spaces."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 100
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise LocalDailySimulationPolicyError("provider_name is invalid")


def _require_policy_hash(value: object, field_name: str) -> None:
    """Require one bare lowercase SHA-256 runtime identity hash."""

    try:
        _require_hash(value, field_name)
    except SimulatedSettlementContractError as error:
        raise LocalDailySimulationPolicyError(f"{field_name} is invalid") from error


def _require_policy_clock(value: object, field_name: str) -> None:
    """Require one timezone-aware policy provenance clock."""

    try:
        _require_aware(value, field_name)
    except SimulatedSettlementContractError as error:
        raise LocalDailySimulationPolicyError(f"{field_name} is invalid") from error


def _require_json_object(
    payload: object,
    *,
    fields: frozenset[str],
    field_name: str,
) -> Mapping[str, object]:
    """Require an exact JSON object with the declared field set."""

    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise LocalDailySimulationPolicyError(f"{field_name} must be an exact JSON object")
    values = cast(Mapping[str, object], payload)
    if frozenset(values) != fields:
        raise LocalDailySimulationPolicyError(f"{field_name} fields are incomplete or unknown")
    return values


def _policy_decimal(value: object, field_name: str, *, maximum: Decimal | None = None) -> Decimal:
    """Parse a bounded exact decimal string without accepting float coercion."""

    if type(value) is not str or not value or len(value) > 257:
        raise LocalDailySimulationPolicyError(f"{field_name} must be a bounded decimal string")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise LocalDailySimulationPolicyError(f"{field_name} is not a decimal") from error
    parts = result.as_tuple()
    exponent = parts.exponent
    if (
        not result.is_finite()
        or not isinstance(exponent, int)
        or len(parts.digits) > 64
        or abs(exponent) > 64
        or format(result, "f") != value
    ):
        raise LocalDailySimulationPolicyError(f"{field_name} is not a canonical finite decimal")
    if result <= 0 or (maximum is not None and result > maximum):
        raise LocalDailySimulationPolicyError(f"{field_name} is outside the supported range")
    return result


def _canonical_utc(value: datetime, field_name: str) -> str:
    """Serialize one validated instant using the binding's exact UTC spelling."""

    try:
        return _utc_text(value)
    except SimulatedSettlementContractError as error:
        raise LocalDailySimulationPolicyError(f"{field_name} is invalid") from error


def _parse_utc(value: object, field_name: str) -> datetime:
    """Decode only the canonical UTC clock emitted by this module."""

    if type(value) is not str or not value.endswith("Z"):
        raise LocalDailySimulationPolicyError(f"{field_name} must be a canonical UTC string")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (OverflowError, TypeError, ValueError) as error:
        raise LocalDailySimulationPolicyError(f"{field_name} is invalid") from error
    _require_policy_clock(parsed, field_name)
    if _canonical_utc(parsed, field_name) != value:
        raise LocalDailySimulationPolicyError(f"{field_name} is not canonical UTC")
    return parsed


@dataclass(frozen=True, slots=True)
class LocalDailySimulationPolicy:
    """Declare every source identity and supported assumption for daily fills.

    The policy grants no source qualification by itself. Application code must
    separately verify same-session price, instrument, currency, limit and QMT
    daily-status evidence before constructing a matching observation.
    """

    schema_version: str
    purpose: str
    policy_id: str
    version: str
    price_publication_key: str
    provider_configuration_id: int
    provider_name: str
    instrument_snapshot_id: str
    currency: str
    frequency: str
    adjustment: str
    volume_unit: str
    participation_rate: Decimal
    share_step: Decimal
    allowed_qmt_suspend_flags: tuple[int, ...]
    currency_basis: str
    qmt_status_basis: str
    limit_price_basis: str

    def __post_init__(self) -> None:
        """Require one exact, explicit policy within the supported model scope."""

        if type(self.schema_version) is not str or self.schema_version != _POLICY_SCHEMA:
            raise LocalDailySimulationPolicyError("policy schema version is unsupported")
        if type(self.purpose) is not str or self.purpose != _POLICY_PURPOSE:
            raise LocalDailySimulationPolicyError("policy purpose is unsupported")
        for field_name in (
            "policy_id",
            "version",
            "price_publication_key",
        ):
            _require_policy_token(getattr(self, field_name), field_name)
        _require_provider_display_name(self.provider_name)
        if type(self.provider_configuration_id) is not int or self.provider_configuration_id <= 0:
            raise LocalDailySimulationPolicyError(
                "provider_configuration_id must be a positive exact integer"
            )
        self._validate_instrument_snapshot_id()
        fixed_fields = {
            "currency": "CNY",
            "frequency": "1d",
            "adjustment": "none",
            "volume_unit": "shares",
            "currency_basis": "same_session_stock_basic_capture",
            "qmt_status_basis": "owner_authenticated_normalized_daily_status",
            "limit_price_basis": "same_provider_cny_listing_native",
        }
        for field_name, expected in fixed_fields.items():
            value = getattr(self, field_name)
            if type(value) is not str or value != expected:
                raise LocalDailySimulationPolicyError(f"{field_name} is unsupported")
        self._validate_decimals()
        self._validate_qmt_flags()

    def _validate_instrument_snapshot_id(self) -> None:
        """Require the explicit instrument-reference snapshot UUID spelling."""

        if type(self.instrument_snapshot_id) is not str:
            raise LocalDailySimulationPolicyError("instrument_snapshot_id must be a UUID string")
        try:
            parsed = UUID(self.instrument_snapshot_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise LocalDailySimulationPolicyError("instrument_snapshot_id is invalid") from error
        if str(parsed) != self.instrument_snapshot_id:
            raise LocalDailySimulationPolicyError("instrument_snapshot_id is not canonical")

    def _validate_decimals(self) -> None:
        """Require explicit finite participation and exact quantity increments."""

        if type(self.participation_rate) is not Decimal or not self.participation_rate.is_finite():
            raise LocalDailySimulationPolicyError("participation_rate must be an exact Decimal")
        if type(self.share_step) is not Decimal or not self.share_step.is_finite():
            raise LocalDailySimulationPolicyError("share_step must be an exact Decimal")
        for field_name, value, maximum in (
            ("participation_rate", self.participation_rate, Decimal("1")),
            ("share_step", self.share_step, None),
        ):
            parts = value.as_tuple()
            exponent = parts.exponent
            if not isinstance(exponent, int) or len(parts.digits) > 64 or abs(exponent) > 64:
                raise LocalDailySimulationPolicyError(f"{field_name} exceeds its exact bound")
            if value <= 0 or (maximum is not None and value > maximum):
                raise LocalDailySimulationPolicyError(
                    f"{field_name} is outside the supported range"
                )

    def _validate_qmt_flags(self) -> None:
        """Require explicit, unique allow-listed normal or resumed status flags."""

        flags = self.allowed_qmt_suspend_flags
        if (
            type(flags) is not tuple
            or not flags
            or any(type(flag) is not int or flag not in {-1, 0} for flag in flags)
            or len(set(flags)) != len(flags)
        ):
            raise LocalDailySimulationPolicyError(
                "allowed_qmt_suspend_flags must explicitly select unique values from -1 and 0"
            )

    @property
    def identity(self) -> str:
        """Return the stable policy purpose, ID, and version."""

        self.__post_init__()
        return f"{self.purpose}:{self.policy_id}:{self.version}"

    @property
    def content_hash(self) -> str:
        """Return the canonical hash derived from every explicit policy value."""

        return _hash_payload(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the strict JSON representation without a caller-supplied hash."""

        self.__post_init__()
        return {
            "schema_version": self.schema_version,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "version": self.version,
            "price_publication_key": self.price_publication_key,
            "provider_configuration_id": self.provider_configuration_id,
            "provider_name": self.provider_name,
            "instrument_snapshot_id": self.instrument_snapshot_id,
            "currency": self.currency,
            "frequency": self.frequency,
            "adjustment": self.adjustment,
            "volume_unit": self.volume_unit,
            "participation_rate": format(self.participation_rate, "f"),
            "share_step": format(self.share_step, "f"),
            "allowed_qmt_suspend_flags": list(self.allowed_qmt_suspend_flags),
            "currency_basis": self.currency_basis,
            "qmt_status_basis": self.qmt_status_basis,
            "limit_price_basis": self.limit_price_basis,
        }

    @classmethod
    def from_payload(cls, payload: object) -> LocalDailySimulationPolicy:
        """Decode one exact policy payload with decimal strings and no defaults."""

        values = _require_json_object(payload, fields=_POLICY_FIELDS, field_name="policy")
        raw_flags = values["allowed_qmt_suspend_flags"]
        if type(raw_flags) is not list or any(type(flag) is not int for flag in raw_flags):
            raise LocalDailySimulationPolicyError(
                "allowed_qmt_suspend_flags must be an integer list"
            )
        text_fields = (
            "schema_version",
            "purpose",
            "policy_id",
            "version",
            "price_publication_key",
            "provider_name",
            "instrument_snapshot_id",
            "currency",
            "frequency",
            "adjustment",
            "volume_unit",
            "currency_basis",
            "qmt_status_basis",
            "limit_price_basis",
        )
        if any(type(values[field_name]) is not str for field_name in text_fields):
            raise LocalDailySimulationPolicyError("policy contains a non-string text field")
        return cls(
            schema_version=cast(str, values["schema_version"]),
            purpose=cast(str, values["purpose"]),
            policy_id=cast(str, values["policy_id"]),
            version=cast(str, values["version"]),
            price_publication_key=cast(str, values["price_publication_key"]),
            provider_configuration_id=cast(int, values["provider_configuration_id"]),
            provider_name=cast(str, values["provider_name"]),
            instrument_snapshot_id=cast(str, values["instrument_snapshot_id"]),
            currency=cast(str, values["currency"]),
            frequency=cast(str, values["frequency"]),
            adjustment=cast(str, values["adjustment"]),
            volume_unit=cast(str, values["volume_unit"]),
            participation_rate=_policy_decimal(
                values["participation_rate"], "participation_rate", maximum=Decimal("1")
            ),
            share_step=_policy_decimal(values["share_step"], "share_step"),
            allowed_qmt_suspend_flags=tuple(cast(int, flag) for flag in raw_flags),
            currency_basis=cast(str, values["currency_basis"]),
            qmt_status_basis=cast(str, values["qmt_status_basis"]),
            limit_price_basis=cast(str, values["limit_price_basis"]),
        )


@dataclass(frozen=True, slots=True)
class LocalDailySimulationPolicyRuntimeProvenance:
    """Retain active profile and immutable snapshot identity for one read."""

    runtime_environment: str
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_hash: str
    profile_activated_at: datetime
    snapshot_id: str
    snapshot_content_hash: str
    snapshot_generated_at: datetime
    snapshot_effective_from: datetime
    read_at: datetime

    def __post_init__(self) -> None:
        """Require exact active runtime identities, hashes and read chronology."""

        for field_name in ("runtime_environment", "profile_id", "profile_key", "snapshot_id"):
            _require_policy_token(getattr(self, field_name), field_name)
        for field_name in ("profile_content_hash", "snapshot_content_hash"):
            _require_policy_hash(getattr(self, field_name), field_name)
        if type(self.profile_version) is not int or self.profile_version <= 0:
            raise LocalDailySimulationPolicyError(
                "profile_version must be a positive exact integer"
            )
        for field_name in (
            "profile_activated_at",
            "snapshot_generated_at",
            "snapshot_effective_from",
            "read_at",
        ):
            _require_policy_clock(getattr(self, field_name), field_name)
        if self.profile_activated_at != self.snapshot_effective_from:
            raise LocalDailySimulationPolicyError("profile and snapshot activation clocks differ")
        if not self.profile_activated_at <= self.snapshot_generated_at <= self.read_at:
            raise LocalDailySimulationPolicyError(
                "runtime policy provenance is not known at cutoff"
            )

    def to_payload(self) -> dict[str, object]:
        """Return the complete runtime provenance as exact JSON-compatible values."""

        self.__post_init__()
        return {
            "runtime_environment": self.runtime_environment,
            "profile_id": self.profile_id,
            "profile_key": self.profile_key,
            "profile_version": self.profile_version,
            "profile_content_hash": self.profile_content_hash,
            "profile_activated_at": _canonical_utc(
                self.profile_activated_at, "profile_activated_at"
            ),
            "snapshot_id": self.snapshot_id,
            "snapshot_content_hash": self.snapshot_content_hash,
            "snapshot_generated_at": _canonical_utc(
                self.snapshot_generated_at, "snapshot_generated_at"
            ),
            "snapshot_effective_from": _canonical_utc(
                self.snapshot_effective_from, "snapshot_effective_from"
            ),
            "read_at": _canonical_utc(self.read_at, "read_at"),
        }

    @classmethod
    def from_payload(cls, payload: object) -> LocalDailySimulationPolicyRuntimeProvenance:
        """Decode one exact runtime provenance payload and validate its chronology."""

        values = _require_json_object(
            payload,
            fields=_PROVENANCE_FIELDS,
            field_name="runtime_provenance",
        )
        text_fields = (
            "runtime_environment",
            "profile_id",
            "profile_key",
            "profile_content_hash",
            "snapshot_id",
            "snapshot_content_hash",
        )
        if any(type(values[field_name]) is not str for field_name in text_fields):
            raise LocalDailySimulationPolicyError("runtime provenance has invalid text fields")
        if type(values["profile_version"]) is not int:
            raise LocalDailySimulationPolicyError(
                "runtime profile version must be an exact integer"
            )
        return cls(
            runtime_environment=cast(str, values["runtime_environment"]),
            profile_id=cast(str, values["profile_id"]),
            profile_key=cast(str, values["profile_key"]),
            profile_version=values["profile_version"],
            profile_content_hash=cast(str, values["profile_content_hash"]),
            profile_activated_at=_parse_utc(values["profile_activated_at"], "profile_activated_at"),
            snapshot_id=cast(str, values["snapshot_id"]),
            snapshot_content_hash=cast(str, values["snapshot_content_hash"]),
            snapshot_generated_at=_parse_utc(
                values["snapshot_generated_at"], "snapshot_generated_at"
            ),
            snapshot_effective_from=_parse_utc(
                values["snapshot_effective_from"], "snapshot_effective_from"
            ),
            read_at=_parse_utc(values["read_at"], "read_at"),
        )


@dataclass(frozen=True, slots=True)
class LocalDailySimulationPolicyBinding:
    """Pair one exact simulation policy with verified active runtime provenance."""

    policy: LocalDailySimulationPolicy
    provenance: LocalDailySimulationPolicyRuntimeProvenance

    def __post_init__(self) -> None:
        """Require exact immutable policy and provenance values."""

        if type(self.policy) is not LocalDailySimulationPolicy:
            raise LocalDailySimulationPolicyError("binding has an invalid policy")
        if type(self.provenance) is not LocalDailySimulationPolicyRuntimeProvenance:
            raise LocalDailySimulationPolicyError("binding has invalid runtime provenance")
        self.policy.__post_init__()
        self.provenance.__post_init__()

    @property
    def proof_content_hash(self) -> str:
        """Recompute a canonical seal over policy and runtime identity fields."""

        return _hash_payload(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the exact nested policy binding without any trusted digest."""

        self.__post_init__()
        return {
            "schema_version": _BINDING_SCHEMA,
            "policy": self.policy.to_payload(),
            "runtime_provenance": self.provenance.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: object) -> LocalDailySimulationPolicyBinding:
        """Decode a strict binding and recompute its digest from nested values."""

        values = _require_json_object(
            payload,
            fields=frozenset({"schema_version", "policy", "runtime_provenance"}),
            field_name="policy_binding",
        )
        if type(values["schema_version"]) is not str or values["schema_version"] != _BINDING_SCHEMA:
            raise LocalDailySimulationPolicyError("policy binding schema is unsupported")
        return cls(
            policy=LocalDailySimulationPolicy.from_payload(values["policy"]),
            provenance=LocalDailySimulationPolicyRuntimeProvenance.from_payload(
                values["runtime_provenance"]
            ),
        )

    def validate_at(self, *, as_of: datetime) -> None:
        """Require this policy binding to describe the caller's exact read cutoff."""

        self.__post_init__()
        _require_policy_clock(as_of, "requested_read_at")
        if self.provenance.read_at != as_of:
            raise LocalDailySimulationPolicyError("policy binding cutoff differs from request")


__all__ = (
    "LocalDailySimulationPolicy",
    "LocalDailySimulationPolicyBinding",
    "LocalDailySimulationPolicyError",
    "LocalDailySimulationPolicyRuntimeProvenance",
)
