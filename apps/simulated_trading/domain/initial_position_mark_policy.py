"""Explicit runtime policy and provenance for an initial-position mark."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from .execution_settlement_primitives import _hash_payload, _utc_text
from .initial_position_mark import (
    InitialPositionMarkValidationError,
    _require_mark_clock,
    _require_mark_hash,
    _require_mark_token,
)

_POLICY_SCHEMA = "simulated-initial-position-mark-policy.v1"
_DAILY_INTERVAL_POLICY_SCHEMA = "simulated-initial-position-mark-policy.daily-interval.v1"
_BINDING_SCHEMA = "simulated-initial-position-mark-policy-binding.v1"
_POLICY_PURPOSE = "apply_time_initial_position_mark"
_M1_REBALANCE_PUBLICATION_KEY = "m1-rebalance-reference"
_LEGACY_OBSERVATION_BASIS = "legacy_source_observed"
_DAILY_INTERVAL_OBSERVATION_BASIS = "daily_interval_end"


@dataclass(frozen=True, slots=True)
class InitialPositionMarkPolicy:
    """Declare the exact source, price semantics, asset scope, and mark age.

    The observation-basis constructor default preserves only the old v1
    payload's legacy meaning. The daily-interval schema requires its basis to be
    selected explicitly. This value describes policy but does not authorize
    wiring the reader into a trade composition or extend a source beyond scope.
    """

    schema_version: str
    purpose: str
    policy_id: str
    version: str
    publication_key: str
    source: str
    frequency: str
    adjustment: str
    supported_asset_types: tuple[str, ...]
    freshness_window_seconds: int
    observation_basis: str = _LEGACY_OBSERVATION_BASIS

    def __post_init__(self) -> None:
        """Require an exact versioned policy with every qualification explicit."""

        if type(self.schema_version) is not str or self.schema_version not in {
            _POLICY_SCHEMA,
            _DAILY_INTERVAL_POLICY_SCHEMA,
        }:
            raise InitialPositionMarkValidationError(
                "initial-position mark policy schema is unsupported"
            )
        expected_observation_basis = (
            _LEGACY_OBSERVATION_BASIS
            if self.schema_version == _POLICY_SCHEMA
            else _DAILY_INTERVAL_OBSERVATION_BASIS
        )
        if (
            type(self.observation_basis) is not str
            or self.observation_basis != expected_observation_basis
        ):
            raise InitialPositionMarkValidationError(
                "initial-position mark policy observation basis does not match its schema"
            )
        for field_name in (
            "purpose",
            "policy_id",
            "version",
            "publication_key",
            "source",
            "frequency",
            "adjustment",
        ):
            _require_mark_token(getattr(self, field_name), field_name)
        if self.purpose != _POLICY_PURPOSE:
            raise InitialPositionMarkValidationError(
                "initial-position mark policy purpose is unsupported"
            )
        if self.publication_key == _M1_REBALANCE_PUBLICATION_KEY:
            raise InitialPositionMarkValidationError(
                "M1 rebalance publication cannot authorize an initial-position mark"
            )
        if self.frequency != "1d" or self.adjustment != "none":
            raise InitialPositionMarkValidationError(
                "initial-position mark policy requires an explicit daily unadjusted close"
            )
        if (
            type(self.supported_asset_types) is not tuple
            or not self.supported_asset_types
            or any(type(asset_type) is not str for asset_type in self.supported_asset_types)
            or len(set(self.supported_asset_types)) != len(self.supported_asset_types)
        ):
            raise InitialPositionMarkValidationError(
                "initial-position mark policy requires unique explicit asset types"
            )
        for asset_type in self.supported_asset_types:
            _require_mark_token(asset_type, "supported_asset_type")
        if type(self.freshness_window_seconds) is not int or self.freshness_window_seconds <= 0:
            raise InitialPositionMarkValidationError(
                "initial-position mark freshness window must be a positive exact integer"
            )
        _require_mark_token(self.identity, "policy_identity")

    @property
    def identity(self) -> str:
        """Return the stable purpose, policy ID, and version identity."""

        return f"{self.purpose}:{self.policy_id}:{self.version}"

    @property
    def content_hash(self) -> str:
        """Return a canonical digest derived from every explicit policy field."""

        return _hash_payload(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the exact JSON-compatible policy payload without a supplied hash."""

        self.__post_init__()
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "version": self.version,
            "publication_key": self.publication_key,
            "source": self.source,
            "frequency": self.frequency,
            "adjustment": self.adjustment,
            "supported_asset_types": list(self.supported_asset_types),
            "freshness_window_seconds": self.freshness_window_seconds,
        }
        if self.schema_version == _DAILY_INTERVAL_POLICY_SCHEMA:
            payload["observation_basis"] = self.observation_basis
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> InitialPositionMarkPolicy:
        """Decode one exact JSON policy object and reject unknown or omitted fields."""

        if type(payload) is not dict or any(type(key) is not str for key in payload):
            raise InitialPositionMarkValidationError(
                "initial-position mark policy payload must be an exact JSON object"
            )
        fields = cast(Mapping[str, object], payload)
        schema_version = fields.get("schema_version")
        if type(schema_version) is not str or schema_version not in {
            _POLICY_SCHEMA,
            _DAILY_INTERVAL_POLICY_SCHEMA,
        }:
            raise InitialPositionMarkValidationError(
                "initial-position mark policy schema is unsupported"
            )
        expected_fields = {
            "schema_version",
            "purpose",
            "policy_id",
            "version",
            "publication_key",
            "source",
            "frequency",
            "adjustment",
            "supported_asset_types",
            "freshness_window_seconds",
        }
        if schema_version == _DAILY_INTERVAL_POLICY_SCHEMA:
            expected_fields.add("observation_basis")
        expected = frozenset(expected_fields)
        if frozenset(fields) != expected:
            raise InitialPositionMarkValidationError(
                "initial-position mark policy payload fields are incomplete or unknown"
            )
        raw_asset_types = fields["supported_asset_types"]
        raw_window = fields["freshness_window_seconds"]
        if (
            type(raw_asset_types) is not list
            or any(type(asset_type) is not str for asset_type in raw_asset_types)
            or type(raw_window) is not int
        ):
            raise InitialPositionMarkValidationError(
                "initial-position mark policy payload has invalid field types"
            )
        string_fields: tuple[str, ...] = (
            "schema_version",
            "purpose",
            "policy_id",
            "version",
            "publication_key",
            "source",
            "frequency",
            "adjustment",
        )
        if schema_version == _DAILY_INTERVAL_POLICY_SCHEMA:
            string_fields = (*string_fields, "observation_basis")
        if any(type(fields[field_name]) is not str for field_name in string_fields):
            raise InitialPositionMarkValidationError(
                "initial-position mark policy payload has invalid text fields"
            )
        asset_types = tuple(cast(str, asset_type) for asset_type in raw_asset_types)
        return cls(
            schema_version=cast(str, fields["schema_version"]),
            purpose=cast(str, fields["purpose"]),
            policy_id=cast(str, fields["policy_id"]),
            version=cast(str, fields["version"]),
            publication_key=cast(str, fields["publication_key"]),
            source=cast(str, fields["source"]),
            frequency=cast(str, fields["frequency"]),
            adjustment=cast(str, fields["adjustment"]),
            supported_asset_types=asset_types,
            freshness_window_seconds=raw_window,
            observation_basis=(
                cast(str, fields["observation_basis"])
                if schema_version == _DAILY_INTERVAL_POLICY_SCHEMA
                else _LEGACY_OBSERVATION_BASIS
            ),
        )


@dataclass(frozen=True, slots=True)
class InitialPositionMarkRuntimeProvenance:
    """Retain the verified active profile and snapshot identity around one read."""

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
        """Require exact runtime identities, hashes, and active snapshot clocks."""

        for field_name in (
            "runtime_environment",
            "profile_id",
            "profile_key",
            "snapshot_id",
        ):
            _require_mark_token(getattr(self, field_name), field_name)
        for field_name in ("profile_content_hash", "snapshot_content_hash"):
            _require_mark_hash(getattr(self, field_name), field_name)
        if type(self.profile_version) is not int or self.profile_version <= 0:
            raise InitialPositionMarkValidationError(
                "initial-position mark runtime profile version must be positive"
            )
        for field_name in (
            "profile_activated_at",
            "snapshot_generated_at",
            "snapshot_effective_from",
            "read_at",
        ):
            _require_mark_clock(getattr(self, field_name), field_name)
        if self.profile_activated_at != self.snapshot_effective_from:
            raise InitialPositionMarkValidationError(
                "initial-position mark profile and snapshot effective clocks differ"
            )
        if not self.profile_activated_at <= self.snapshot_generated_at <= self.read_at:
            raise InitialPositionMarkValidationError(
                "initial-position mark runtime provenance is not known at its read cutoff"
            )

    def to_payload(self) -> dict[str, object]:
        """Return the canonical complete profile and snapshot provenance payload."""

        self.__post_init__()
        return {
            "runtime_environment": self.runtime_environment,
            "profile_id": self.profile_id,
            "profile_key": self.profile_key,
            "profile_version": self.profile_version,
            "profile_content_hash": self.profile_content_hash,
            "profile_activated_at": _utc_text(self.profile_activated_at),
            "snapshot_id": self.snapshot_id,
            "snapshot_content_hash": self.snapshot_content_hash,
            "snapshot_generated_at": _utc_text(self.snapshot_generated_at),
            "snapshot_effective_from": _utc_text(self.snapshot_effective_from),
            "read_at": _utc_text(self.read_at),
        }


@dataclass(frozen=True, slots=True)
class InitialPositionMarkPolicyBinding:
    """Pair one exact policy with its verified runtime-profile provenance."""

    policy: InitialPositionMarkPolicy
    provenance: InitialPositionMarkRuntimeProvenance

    def __post_init__(self) -> None:
        """Require exact typed nested values and their complete provenance."""

        if type(self.policy) is not InitialPositionMarkPolicy:
            raise InitialPositionMarkValidationError(
                "initial-position mark policy binding has an invalid policy"
            )
        if type(self.provenance) is not InitialPositionMarkRuntimeProvenance:
            raise InitialPositionMarkValidationError(
                "initial-position mark policy binding has invalid runtime provenance"
            )
        self.policy.__post_init__()
        self.provenance.__post_init__()

    @property
    def proof_content_hash(self) -> str:
        """Return a canonical seal over policy content and all active runtime provenance."""

        self.__post_init__()
        return _hash_payload(
            {
                "schema": _BINDING_SCHEMA,
                "policy": self.policy.to_payload(),
                "runtime_provenance": self.provenance.to_payload(),
            }
        )

    def validate_at(self, *, as_of: datetime) -> None:
        """Require this policy binding to describe the exact supplied read cutoff."""

        self.__post_init__()
        _require_mark_clock(as_of, "requested_read_at")
        if self.provenance.read_at != as_of:
            raise InitialPositionMarkValidationError(
                "initial-position mark policy was read at a different cutoff"
            )


__all__ = (
    "InitialPositionMarkPolicy",
    "InitialPositionMarkPolicyBinding",
    "InitialPositionMarkRuntimeProvenance",
)
