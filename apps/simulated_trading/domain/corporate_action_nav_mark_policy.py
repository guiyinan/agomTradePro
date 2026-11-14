"""Explicit policy for a simulation-only corporate-action NAV raw-price mark."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

_POLICY_SCHEMA = "simulated-corporate-action-nav-raw-mark-policy.v1"
_POLICY_PURPOSE = "simulated_corporate_action_nav_raw_mark"
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/_-]{0,191}\Z")


class SimulatedCorporateActionNavRawMarkPolicyError(ValueError):
    """Raised when an explicit simulated raw-price policy is malformed or out of scope."""


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionNavRawMarkPolicy:
    """Declare the exact daily, unadjusted publication usable as a raw mark.

    The policy describes a simulation valuation input only. It does not prove
    complete corporate-action coverage, tax treatment, account NAV, spendable
    cash, or permission to make an investment decision.
    """

    schema_version: str
    purpose: str
    policy_id: str
    version: str
    source: str
    publication_key: str
    frequency: str
    adjustment: str
    observation_basis: str
    currency: str
    supported_asset_types: tuple[str, ...]
    freshness_window_seconds: int

    def __post_init__(self) -> None:
        """Reject implicit source, adjustment, unit, type, and age semantics."""

        if self.schema_version != _POLICY_SCHEMA or type(self.schema_version) is not str:
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark policy schema is unsupported"
            )
        if self.purpose != _POLICY_PURPOSE or type(self.purpose) is not str:
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark policy purpose is unsupported"
            )
        for name in ("policy_id", "version", "source", "publication_key"):
            _require_token(getattr(self, name), name)
        if (
            type(self.frequency) is not str
            or self.frequency != "1d"
            or type(self.adjustment) is not str
            or self.adjustment != "none"
            or type(self.observation_basis) is not str
            or self.observation_basis != "daily_interval_end"
            or type(self.currency) is not str
            or self.currency != "CNY"
        ):
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark requires a daily unadjusted CNY close"
            )
        if (
            type(self.supported_asset_types) is not tuple
            or not self.supported_asset_types
            or any(type(value) is not str for value in self.supported_asset_types)
            or len(set(self.supported_asset_types)) != len(self.supported_asset_types)
        ):
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark requires explicit unique asset types"
            )
        for asset_type in self.supported_asset_types:
            _require_token(asset_type, "supported_asset_type")
        if type(self.freshness_window_seconds) is not int or self.freshness_window_seconds <= 0:
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark freshness window is outside its finite bound"
            )
        try:
            timedelta(seconds=self.freshness_window_seconds)
        except OverflowError as error:
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark age is not representable"
            ) from error

    @property
    def identity(self) -> str:
        """Return the purpose-bound policy identity."""

        self.__post_init__()
        return f"{self.purpose}:{self.policy_id}:{self.version}"

    @property
    def content_sha256(self) -> str:
        """Return a canonical digest of every explicit policy field."""

        return _canonical_sha256(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the strict JSON-compatible policy representation."""

        self.__post_init__()
        return {
            "schema_version": self.schema_version,
            "purpose": self.purpose,
            "policy_id": self.policy_id,
            "version": self.version,
            "source": self.source,
            "publication_key": self.publication_key,
            "frequency": self.frequency,
            "adjustment": self.adjustment,
            "observation_basis": self.observation_basis,
            "currency": self.currency,
            "supported_asset_types": list(self.supported_asset_types),
            "freshness_window_seconds": self.freshness_window_seconds,
        }

    @classmethod
    def from_payload(cls, payload: object) -> SimulatedCorporateActionNavRawMarkPolicy:
        """Decode one exact payload without accepting aliases or extra permissions."""

        if type(payload) is not dict or any(type(key) is not str for key in payload):
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark policy payload must be an exact object"
            )
        fields = cast(Mapping[str, object], payload)
        expected = frozenset(
            {
                "schema_version",
                "purpose",
                "policy_id",
                "version",
                "source",
                "publication_key",
                "frequency",
                "adjustment",
                "observation_basis",
                "currency",
                "supported_asset_types",
                "freshness_window_seconds",
            }
        )
        if frozenset(fields) != expected:
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark policy fields are incomplete or unknown"
            )
        raw_types = fields["supported_asset_types"]
        if (
            type(raw_types) is not list
            or any(type(item) is not str for item in raw_types)
            or type(fields["freshness_window_seconds"]) is not int
        ):
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark policy payload field types are invalid"
            )
        text_fields = expected - {"supported_asset_types", "freshness_window_seconds"}
        if any(type(fields[name]) is not str for name in text_fields):
            raise SimulatedCorporateActionNavRawMarkPolicyError(
                "corporate-action NAV raw mark policy text field types are invalid"
            )
        return cls(
            schema_version=cast(str, fields["schema_version"]),
            purpose=cast(str, fields["purpose"]),
            policy_id=cast(str, fields["policy_id"]),
            version=cast(str, fields["version"]),
            source=cast(str, fields["source"]),
            publication_key=cast(str, fields["publication_key"]),
            frequency=cast(str, fields["frequency"]),
            adjustment=cast(str, fields["adjustment"]),
            observation_basis=cast(str, fields["observation_basis"]),
            currency=cast(str, fields["currency"]),
            supported_asset_types=tuple(cast(str, item) for item in raw_types),
            freshness_window_seconds=fields["freshness_window_seconds"],
        )


def _require_token(value: object, field_name: str) -> None:
    """Require a bounded canonical source or policy token."""

    if type(value) is not str or _TOKEN_PATTERN.fullmatch(value) is None:
        raise SimulatedCorporateActionNavRawMarkPolicyError(
            f"corporate-action NAV raw mark {field_name} is invalid"
        )


def _canonical_sha256(payload: dict[str, object]) -> str:
    """Hash one finite canonical JSON policy payload."""

    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = (
    "SimulatedCorporateActionNavRawMarkPolicy",
    "SimulatedCorporateActionNavRawMarkPolicyError",
)
