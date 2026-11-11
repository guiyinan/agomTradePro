"""Immutable owner-scoped service-write lease facts for simulated actions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION = "simulated_corporate_action_stage_write"
SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID = "simulated-trading"
SIMULATED_CORPORATE_ACTION_WRITE_LEASE_SCHEMA = "account.simulated_corporate_action_write_lease.v1"
_LEASE_CONTENT_HASH_DOMAIN = "account.simulated-corporate-action-write-lease.v1/content"


class SimulatedCorporateActionWriteLeaseRevocationState(StrEnum):
    """Explicit provider-reported lease state; absence is never treated as active."""

    ACTIVE = "active"
    REVOKED = "revoked"


def _token(value: object, name: str) -> str:
    """Validate and return a bounded canonical identity token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    """Validate and return a lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    """Validate one exact timezone-aware datetime without changing it."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize an aware datetime with stable UTC microsecond precision."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(domain: str, payload: dict[str, object]) -> str:
    """Hash a canonical JSON payload under an independent domain separator."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteLeaseBinding:
    """Exact permission, service actor, owner scope, account identity, and policy lineage."""

    permission: str
    service_actor_id: str
    account_namespace: str
    account_id: str
    owner_user_id: int
    tenant_id: str
    owner_id: str
    account_source_id: str
    account_source_version: str
    account_source_content_hash: str
    policy_id: str
    policy_version: str
    policy_content_hash: str

    def __post_init__(self) -> None:
        """Reject broad, non-service, or incomplete owner/account bindings."""

        if self.permission != SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION:
            raise ValueError("write lease permission is unsupported")
        if self.service_actor_id != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID:
            raise ValueError("write lease service actor is unsupported")
        for name in (
            "permission",
            "service_actor_id",
            "account_namespace",
            "account_id",
            "tenant_id",
            "owner_id",
            "account_source_id",
            "account_source_version",
            "policy_id",
            "policy_version",
        ):
            _token(getattr(self, name), name)
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be an exact positive integer")
        _digest(self.account_source_content_hash, "account_source_content_hash")
        _digest(self.policy_content_hash, "policy_content_hash")

    def to_payload(self) -> dict[str, object]:
        """Return every binding fact for the lease content hash."""

        self.__post_init__()
        return {
            "permission": self.permission,
            "service_actor_id": self.service_actor_id,
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "owner_id": self.owner_id,
            "account_source_id": self.account_source_id,
            "account_source_version": self.account_source_version,
            "account_source_content_hash": self.account_source_content_hash,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_content_hash": self.policy_content_hash,
        }


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteLeaseSelector:
    """Select one provider-issued lease and its exact current authority source."""

    lease_id: str
    lease_version: str
    source_id: str
    source_version: str
    source_content_hash: str
    binding: SimulatedCorporateActionWriteLeaseBinding

    def __post_init__(self) -> None:
        """Validate immutable lease and issuer-source selectors."""

        for name in ("lease_id", "lease_version", "source_id", "source_version"):
            _token(getattr(self, name), name)
        _digest(self.source_content_hash, "source_content_hash")
        if type(self.binding) is not SimulatedCorporateActionWriteLeaseBinding:
            raise TypeError("binding must be an exact SimulatedCorporateActionWriteLeaseBinding")
        self.binding.__post_init__()

    def to_payload(self) -> dict[str, object]:
        """Return all exact selectors and owner lineage covered by the lease hash."""

        self.__post_init__()
        return {
            "lease_id": self.lease_id,
            "lease_version": self.lease_version,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "source_content_hash": self.source_content_hash,
            "binding": self.binding.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionWriteLease:
    """Provider projection of one finite, revocable owner-bound service permission."""

    selector: SimulatedCorporateActionWriteLeaseSelector
    recorded_at: datetime
    valid_until: datetime
    revocation_state: SimulatedCorporateActionWriteLeaseRevocationState
    revocation_source_id: str | None
    revocation_source_version: str | None
    revocation_source_content_hash: str | None
    revocation_recorded_at: datetime | None
    content_hash: str = ""
    schema: str = SIMULATED_CORPORATE_ACTION_WRITE_LEASE_SCHEMA

    def __post_init__(self) -> None:
        """Verify exact source, revocation, validity clocks, and canonical content hash."""

        if type(self.selector) is not SimulatedCorporateActionWriteLeaseSelector:
            raise TypeError("selector must be an exact SimulatedCorporateActionWriteLeaseSelector")
        self.selector.__post_init__()
        if self.schema != SIMULATED_CORPORATE_ACTION_WRITE_LEASE_SCHEMA:
            raise ValueError("write lease schema is unsupported")
        _token(self.schema, "schema")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if recorded_at >= valid_until:
            raise ValueError("write lease validity interval is empty")
        if type(self.revocation_state) is not SimulatedCorporateActionWriteLeaseRevocationState:
            raise TypeError("revocation_state must be an exact lease revocation state")
        revocation_fields = (
            self.revocation_source_id,
            self.revocation_source_version,
            self.revocation_source_content_hash,
            self.revocation_recorded_at,
        )
        if self.revocation_state is SimulatedCorporateActionWriteLeaseRevocationState.ACTIVE:
            if any(value is not None for value in revocation_fields):
                raise ValueError("active write lease cannot carry revocation evidence")
        else:
            if any(value is None for value in revocation_fields):
                raise ValueError("revoked write lease requires exact revocation evidence")
            _token(self.revocation_source_id, "revocation_source_id")
            _token(self.revocation_source_version, "revocation_source_version")
            _digest(self.revocation_source_content_hash, "revocation_source_content_hash")
            revocation_recorded_at = _aware(
                self.revocation_recorded_at,
                "revocation_recorded_at",
            )
            if revocation_recorded_at < recorded_at:
                raise ValueError("revocation cannot be recorded before its lease")
        if type(self.content_hash) is not str:
            raise TypeError("content_hash must be an exact string")
        expected_hash = _hash(
            _LEASE_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        if self.content_hash == "":
            object.__setattr__(self, "content_hash", expected_hash)
        elif _digest(self.content_hash, "content_hash") != expected_hash:
            raise ValueError("write lease content_hash does not match its exact facts")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return active authority only inside the recorded half-open lease window."""

        self.__post_init__()
        cutoff = _aware(as_of, "as_of")
        return (
            self.revocation_state is SimulatedCorporateActionWriteLeaseRevocationState.ACTIVE
            and self.recorded_at <= cutoff < self.valid_until
        )

    def _content_payload(self) -> dict[str, object]:
        """Serialize every provider, owner, policy, clock, and revocation fact."""

        return {
            "schema": self.schema,
            "selector": self.selector.to_payload(),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "revocation_state": self.revocation_state.value,
            "revocation_source_id": self.revocation_source_id,
            "revocation_source_version": self.revocation_source_version,
            "revocation_source_content_hash": self.revocation_source_content_hash,
            "revocation_recorded_at": (
                _utc_text(self.revocation_recorded_at)
                if self.revocation_recorded_at is not None
                else None
            ),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete immutable lease projection and content hash."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "content_hash": self.content_hash,
        }


__all__ = [
    "SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID",
    "SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION",
    "SIMULATED_CORPORATE_ACTION_WRITE_LEASE_SCHEMA",
    "SimulatedCorporateActionWriteLease",
    "SimulatedCorporateActionWriteLeaseBinding",
    "SimulatedCorporateActionWriteLeaseRevocationState",
    "SimulatedCorporateActionWriteLeaseSelector",
]
