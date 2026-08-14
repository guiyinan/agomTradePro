"""Unified evidence that one canonical Account creation allocation was consumed."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)

CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_OWNER = "account"
CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_ARTIFACT_TYPE = (
    "canonical_account_creation_consumption_claim"
)
CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_SCHEMA = (
    "canonical-account-creation-consumption-claim.v1"
)
CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_PERMISSION = "evidence_only"
CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_STATUS = "inactive"
CANONICAL_ACCOUNT_CREATION_CONSUMER_GENERATIONS = ("v1", "v2")


def resolve_canonical_account_creation_consumption_claim_identity(
    allocation: CanonicalAccountCreationAllocation,
    *,
    consumer_generation: str,
) -> tuple[str, str]:
    """Derive one stable claim identity without accepting caller-selected tokens."""

    if type(allocation) is not CanonicalAccountCreationAllocation:
        raise TypeError("allocation must be an exact CanonicalAccountCreationAllocation")
    allocation.__post_init__()
    _require_token(consumer_generation, "consumer_generation")
    if consumer_generation not in CANONICAL_ACCOUNT_CREATION_CONSUMER_GENERATIONS:
        raise ValueError("consumer_generation must be exactly v1 or v2")
    return f"allocation-consumption-{allocation.identity_hash}", consumer_generation


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an exact integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


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
class CanonicalAccountCreationConsumptionClaim:
    """Seal one allocation's exact v1 or v2 creation consumer without authority."""

    claim_id: str
    claim_version: str
    allocation: CanonicalAccountCreationAllocation
    consumer_generation: str
    consumer: CanonicalAccountCreationBinding | CanonicalAccountCreationBindingV2
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    physical_v2_content_hash: str
    physical_v3_root_content_hash: str | None
    recorded_at: datetime
    account_claim_hash: str = ""
    underlying_claim_hash: str = ""
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_OWNER
    artifact_type: str = CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_ARTIFACT_TYPE
    schema: str = CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_SCHEMA
    permission: str = CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_PERMISSION
    status: str = CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_STATUS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        _require_token(self.claim_id, "claim_id")
        _require_token(self.claim_version, "claim_version")
        if type(self.allocation) is not CanonicalAccountCreationAllocation:
            raise TypeError("allocation must be an exact CanonicalAccountCreationAllocation")
        self.allocation.__post_init__()
        _require_token(self.consumer_generation, "consumer_generation")
        if self.consumer_generation not in CANONICAL_ACCOUNT_CREATION_CONSUMER_GENERATIONS:
            raise ValueError("consumer_generation must be exactly v1 or v2")
        _require_aware(self.recorded_at, "recorded_at")

        physical_content_hash: str
        if self.consumer_generation == "v1":
            if type(self.consumer) is not CanonicalAccountCreationBinding:
                raise TypeError("v1 consumer must be an exact CanonicalAccountCreationBinding")
            consumer_v1 = self.consumer
            consumer_v1.__post_init__()
            physical = consumer_v1.physical_observation
            physical_content_hash = physical.content_hash
            if self.physical_v3_root_content_hash is not None:
                raise ValueError("v1 consumer requires physical_v3_root_content_hash to be None")
            if self.recorded_at >= consumer_v1.valid_until:
                raise ValueError("v1 consumer must remain valid when consumption is recorded")
        else:
            if type(self.consumer) is not CanonicalAccountCreationBindingV2:
                raise TypeError("v2 consumer must be an exact CanonicalAccountCreationBindingV2")
            consumer_v2 = self.consumer
            consumer_v2.__post_init__()
            physical = consumer_v2.creation_root.physical_observation
            physical_content_hash = physical.content_hash
            if self.physical_v3_root_content_hash is None:
                raise ValueError("v2 consumer requires physical_v3_root_content_hash")
            _require_hash(
                self.physical_v3_root_content_hash,
                "physical_v3_root_content_hash",
            )
            if self.physical_v3_root_content_hash != consumer_v2.creation_root.content_hash:
                raise ValueError("physical_v3_root_content_hash does not match v2 consumer")

        if self.consumer.allocation != self.allocation:
            raise ValueError("consumer does not bind the exact allocation")
        for field_name in (
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_positive_integer(
            self.underlying_unified_account_id,
            "underlying_unified_account_id",
        )
        if (
            self.account_namespace != self.consumer.account_namespace_claim
            or self.account_id != self.consumer.account_id_claim
        ):
            raise ValueError("Account raw key does not match the exact consumer")
        if (
            self.underlying_unified_account_namespace
            != self.consumer.underlying_unified_account_namespace_claim
            or self.underlying_unified_account_id
            != self.consumer.underlying_unified_account_id_claim
        ):
            raise ValueError("underlying raw key does not match the exact consumer")
        _require_hash(self.physical_v2_content_hash, "physical_v2_content_hash")
        if self.physical_v2_content_hash != physical_content_hash:
            raise ValueError("physical_v2_content_hash does not match the exact consumer")

        if self.recorded_at != self.consumer.recorded_at:
            raise ValueError("consumption and consumer must have the exact same recorded_at")
        if self.recorded_at >= self.allocation.valid_until:
            raise ValueError("allocation must remain valid when consumption is recorded")

        expected_account_claim_hash = _canonical_hash(self._account_claim_payload())
        expected_underlying_claim_hash = _canonical_hash(self._underlying_claim_payload())
        for field_name, supplied, expected in (
            ("account_claim_hash", self.account_claim_hash, expected_account_claim_hash),
            (
                "underlying_claim_hash",
                self.underlying_claim_hash,
                expected_underlying_claim_hash,
            ),
        ):
            if supplied:
                _require_hash(supplied, field_name)
                if supplied != expected:
                    raise ValueError(f"{field_name} is invalid")
            object.__setattr__(self, field_name, expected)

        expected_identity_hash = _canonical_hash(self._identity_payload())
        if self.identity_hash:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("consumption claim identity_hash is invalid")
        object.__setattr__(self, "identity_hash", expected_identity_hash)
        expected_content_hash = _canonical_hash(self._content_payload())
        if self.content_hash:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("consumption claim content_hash is invalid")
        object.__setattr__(self, "content_hash", expected_content_hash)

    def _validate_fixed_semantics(self) -> None:
        for actual, expected, field_name in (
            (self.owner, CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_OWNER, "owner"),
            (
                self.artifact_type,
                CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_ARTIFACT_TYPE,
                "artifact_type",
            ),
            (self.schema, CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_SCHEMA, "schema"),
            (
                self.permission,
                CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_PERMISSION,
                "permission",
            ),
            (self.status, CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_STATUS, "status"),
        ):
            if actual != expected:
                raise ValueError(f"consumption claim {field_name} is fixed")

    @property
    def activation_available(self) -> bool:
        """Remain false because consumption evidence cannot activate an account."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because consumption evidence grants no execution authority."""

        return True

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "claim_id": self.claim_id,
            "claim_version": self.claim_version,
        }

    def _account_claim_payload(self) -> dict[str, object]:
        return {
            "claim": "canonical_account_creation_consumption_claim.account.v1",
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
        }

    def _underlying_claim_payload(self) -> dict[str, object]:
        return {
            "claim": "canonical_account_creation_consumption_claim.underlying.v1",
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
        }

    def _allocation_payload(self) -> dict[str, object]:
        self.allocation.__post_init__()
        return {
            **self.allocation.to_payload(),
            "identity_hash": self.allocation.identity_hash,
            "content_hash": self.allocation.content_hash,
        }

    def _consumer_ref_payload(self) -> dict[str, object]:
        self.consumer.__post_init__()
        return {
            "owner": self.consumer.owner,
            "artifact_type": self.consumer.artifact_type,
            "schema": self.consumer.schema,
            "consumer_id": self.consumer.binding_id,
            "consumer_version": self.consumer.binding_version,
            "identity_hash": self.consumer.identity_hash,
            "content_hash": self.consumer.content_hash,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "allocation": self._allocation_payload(),
            "consumer_generation": self.consumer_generation,
            "consumer_ref": self._consumer_ref_payload(),
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "account_claim_hash": self.account_claim_hash,
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "underlying_claim_hash": self.underlying_claim_hash,
            "physical_v2_content_hash": self.physical_v2_content_hash,
            "physical_v3_root_content_hash": self.physical_v3_root_content_hash,
            "recorded_at": _utc_text(self.recorded_at),
            "permission": self.permission,
            "status": self.status,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical allocation plus exact non-recursive consumer reference."""

        CanonicalAccountCreationConsumptionClaim.__post_init__(self)
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


__all__ = [
    "CANONICAL_ACCOUNT_CREATION_CONSUMER_GENERATIONS",
    "CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_ARTIFACT_TYPE",
    "CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_OWNER",
    "CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_PERMISSION",
    "CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_SCHEMA",
    "CANONICAL_ACCOUNT_CREATION_CONSUMPTION_CLAIM_STATUS",
    "CanonicalAccountCreationConsumptionClaim",
    "resolve_canonical_account_creation_consumption_claim_identity",
]
