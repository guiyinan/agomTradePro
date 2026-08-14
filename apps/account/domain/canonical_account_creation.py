"""Account-owned canonical identity allocation and first-row binding evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)


def _token(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be an exact positive integer")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash(payload: dict[str, object]) -> str:
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
class CanonicalAccountCreationRequester:
    """Authenticated human requesting a canonical identity for their own row."""

    actor_id: str
    user_id: int
    role: str = "account_creator"
    kind: str = "human"
    is_authenticated: bool = True

    def __post_init__(self) -> None:
        _token(self.actor_id, "actor_id")
        _positive_int(self.user_id, "user_id")
        if (self.role, self.kind, self.is_authenticated) != (
            "account_creator",
            "human",
            True,
        ):
            raise ValueError("requester must be an authenticated human account_creator")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical requester payload."""

        self.__post_init__()
        return {
            "actor_id": self.actor_id,
            "is_authenticated": self.is_authenticated,
            "kind": self.kind,
            "role": self.role,
            "user_id": self.user_id,
        }


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationServiceRecorder:
    """Fixed automated service identity recording an allocation or binding."""

    service_id: str
    role: str
    kind: str = "service"
    is_automated: bool = True

    def __post_init__(self) -> None:
        _token(self.service_id, "service_id")
        if self.role not in {
            "canonical_account_identity_allocator",
            "canonical_account_creation_binder",
        }:
            raise ValueError("service recorder role is invalid")
        if (self.kind, self.is_automated) != ("service", True):
            raise ValueError("service recorder must be automated")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical recorder payload."""

        self.__post_init__()
        return {
            "is_automated": self.is_automated,
            "kind": self.kind,
            "role": self.role,
            "service_id": self.service_id,
        }


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationAllocation:
    """Reserve an Account-owned canonical ID before a physical row exists."""

    allocation_id: str
    allocation_version: str
    canonical_account_namespace: str
    canonical_account_id: str
    requested_row_user_id: int
    requested_raw_account_type: str
    intended_underlying_unified_account_namespace: str
    request_fingerprint_hash: str
    requested_by: CanonicalAccountCreationRequester
    allocated_at: datetime
    valid_until: datetime
    recorded_by: CanonicalAccountCreationServiceRecorder = CanonicalAccountCreationServiceRecorder(
        service_id="account-identity-allocator",
        role="canonical_account_identity_allocator",
    )
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = "account"
    artifact_type: str = "canonical_account_creation_allocation"
    schema: str = "canonical-account-creation-allocation.v1"
    intended_purpose: str = "simulated_account_create"
    permission: str = "identity_allocation_only"
    status: str = "inactive"

    def __post_init__(self) -> None:
        if (
            self.owner,
            self.artifact_type,
            self.schema,
            self.canonical_account_namespace,
            self.intended_underlying_unified_account_namespace,
            self.intended_purpose,
            self.permission,
            self.status,
        ) != (
            "account",
            "canonical_account_creation_allocation",
            "canonical-account-creation-allocation.v1",
            "account",
            "simulated-account-row",
            "simulated_account_create",
            "identity_allocation_only",
            "inactive",
        ):
            raise ValueError("canonical Account allocation authority is invalid")
        for field_name in (
            "allocation_id",
            "allocation_version",
            "canonical_account_id",
            "requested_raw_account_type",
        ):
            _token(getattr(self, field_name), field_name)
        _positive_int(self.requested_row_user_id, "requested_row_user_id")
        if type(self.requested_by) is not CanonicalAccountCreationRequester:
            raise TypeError("requested_by must be exact CanonicalAccountCreationRequester")
        self.requested_by.__post_init__()
        if self.requested_row_user_id != self.requested_by.user_id:
            raise ValueError("requester must own the requested physical row")
        if type(self.recorded_by) is not CanonicalAccountCreationServiceRecorder:
            raise TypeError("recorded_by must be exact CanonicalAccountCreationServiceRecorder")
        self.recorded_by.__post_init__()
        if self.recorded_by.role != "canonical_account_identity_allocator":
            raise ValueError("allocation recorder role is invalid")
        _digest(self.request_fingerprint_hash, "request_fingerprint_hash")
        _aware(self.allocated_at, "allocated_at")
        _aware(self.valid_until, "valid_until")
        if self.allocated_at >= self.valid_until:
            raise ValueError("allocation validity must follow allocation")
        self._seal_hashes()

    @property
    def activation_available(self) -> bool:
        """An allocation can never activate an account."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """An allocation is identity evidence only."""

        return True

    def _identity_payload(self) -> dict[str, object]:
        return {
            "allocation_id": self.allocation_id,
            "allocation_version": self.allocation_version,
            "artifact_type": self.artifact_type,
            "owner": self.owner,
            "schema": self.schema,
        }

    def to_payload(self) -> dict[str, object]:
        """Return and revalidate the complete canonical allocation payload."""

        self.__post_init__()
        return self._content_payload()

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "allocated_at": _utc_text(self.allocated_at),
            "canonical_account_id": self.canonical_account_id,
            "canonical_account_namespace": self.canonical_account_namespace,
            "intended_purpose": self.intended_purpose,
            "intended_underlying_unified_account_namespace": (
                self.intended_underlying_unified_account_namespace
            ),
            "permission": self.permission,
            "recorded_by": self.recorded_by.to_payload(),
            "request_fingerprint_hash": self.request_fingerprint_hash,
            "requested_by": self.requested_by.to_payload(),
            "requested_raw_account_type": self.requested_raw_account_type,
            "requested_row_user_id": self.requested_row_user_id,
            "status": self.status,
            "valid_until": _utc_text(self.valid_until),
        }

    def _seal_hashes(self) -> None:
        identity = _hash(self._identity_payload())
        content = _hash(self._content_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", identity)
        elif _digest(self.identity_hash, "identity_hash") != identity:
            raise ValueError("identity_hash is invalid")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", content)
        elif _digest(self.content_hash, "content_hash") != content:
            raise ValueError("content_hash is invalid")


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationBinding:
    """Consume one allocation by binding it to one exact live Physical v2 root."""

    binding_id: str
    binding_version: str
    allocation: CanonicalAccountCreationAllocation
    physical_observation: PhysicalAccountRowObservationV2
    account_namespace_claim: str
    account_id_claim: str
    underlying_unified_account_namespace_claim: str
    underlying_unified_account_id_claim: int
    recorded_by: CanonicalAccountCreationServiceRecorder
    recorded_at: datetime
    valid_until: datetime
    account_claim_hash: str = ""
    underlying_claim_hash: str = ""
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = "account"
    artifact_type: str = "canonical_account_creation_binding"
    schema: str = "canonical-account-creation-binding.v1"
    permission: str = "identity_binding_evidence_only"
    status: str = "inactive"
    binding_state: str = "pending_owner_approval"
    owner_assignment_state: str = "unknown"

    def __post_init__(self) -> None:
        if (
            self.owner,
            self.artifact_type,
            self.schema,
            self.permission,
            self.status,
            self.binding_state,
            self.owner_assignment_state,
        ) != (
            "account",
            "canonical_account_creation_binding",
            "canonical-account-creation-binding.v1",
            "identity_binding_evidence_only",
            "inactive",
            "pending_owner_approval",
            "unknown",
        ):
            raise ValueError("canonical Account binding authority is invalid")
        _token(self.binding_id, "binding_id")
        _token(self.binding_version, "binding_version")
        if type(self.allocation) is not CanonicalAccountCreationAllocation:
            raise TypeError("allocation must be exact CanonicalAccountCreationAllocation")
        self.allocation.__post_init__()
        if type(self.physical_observation) is not PhysicalAccountRowObservationV2:
            raise TypeError("physical_observation must be exact PhysicalAccountRowObservationV2")
        self.physical_observation.__post_init__()
        physical = self.physical_observation
        if (
            not physical.is_active
            or not physical.is_present
            or physical.is_tombstone
            or physical.supersedes_content_hash is not None
        ):
            raise ValueError("physical live root is required")
        if (
            self.account_namespace_claim != self.allocation.canonical_account_namespace
            or self.account_namespace_claim != physical.account_namespace
            or self.account_id_claim != self.allocation.canonical_account_id
            or self.account_id_claim != physical.account_id
        ):
            raise ValueError("account claim does not match allocation and physical root")
        if (
            self.underlying_unified_account_namespace_claim
            != self.allocation.intended_underlying_unified_account_namespace
            or self.underlying_unified_account_namespace_claim
            != physical.underlying_unified_account_namespace
            or self.underlying_unified_account_id_claim != physical.underlying_unified_account_id
        ):
            raise ValueError("underlying claim does not match the physical root")
        _positive_int(
            self.underlying_unified_account_id_claim,
            "underlying_unified_account_id_claim",
        )
        if physical.row_user_id != self.allocation.requested_row_user_id:
            raise ValueError("physical row user does not match allocation")
        if physical.raw_account_type != self.allocation.requested_raw_account_type:
            raise ValueError("physical row type does not match allocation")
        if type(self.recorded_by) is not CanonicalAccountCreationServiceRecorder:
            raise TypeError("recorded_by must be exact CanonicalAccountCreationServiceRecorder")
        self.recorded_by.__post_init__()
        if self.recorded_by.role != "canonical_account_creation_binder":
            raise ValueError("binding recorder role is invalid")
        _aware(self.recorded_at, "recorded_at")
        _aware(self.valid_until, "valid_until")
        if self.recorded_at < physical.recorded_at:
            raise ValueError("binding recording cannot precede physical root")
        if self.recorded_at >= self.allocation.valid_until:
            raise ValueError("allocation must be live when bound")
        if self.valid_until != min(self.allocation.valid_until, physical.valid_until):
            raise ValueError("binding valid_until must equal the upstream minimum")
        if self.recorded_at >= self.valid_until:
            raise ValueError("binding validity must follow recording")
        self._seal_hashes()

    @property
    def activation_available(self) -> bool:
        """A technical creation binding cannot activate ownership."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """A creation binding grants no execution authority."""

        return True

    def _identity_payload(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "owner": self.owner,
            "schema": self.schema,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "account_claim_hash": self.account_claim_hash,
            "account_id_claim": self.account_id_claim,
            "account_namespace_claim": self.account_namespace_claim,
            "allocation_content_hash": self.allocation.content_hash,
            "allocation_id": self.allocation.allocation_id,
            "allocation_identity_hash": self.allocation.identity_hash,
            "allocation_version": self.allocation.allocation_version,
            "binding_state": self.binding_state,
            "owner_assignment_state": self.owner_assignment_state,
            "permission": self.permission,
            "physical_content_hash": self.physical_observation.content_hash,
            "physical_identity_hash": self.physical_observation.identity_hash,
            "physical_observation_id": self.physical_observation.observation_id,
            "physical_observation_version": self.physical_observation.observation_version,
            "physical_raw_content_hash": self.physical_observation.raw_observation_content_hash,
            "physical_recorded_at": _utc_text(self.physical_observation.recorded_at),
            "physical_source_content_hash": self.physical_observation.source_content_hash,
            "recorded_at": _utc_text(self.recorded_at),
            "recorded_by": self.recorded_by.to_payload(),
            "status": self.status,
            "underlying_claim_hash": self.underlying_claim_hash,
            "underlying_unified_account_id_claim": (self.underlying_unified_account_id_claim),
            "underlying_unified_account_namespace_claim": (
                self.underlying_unified_account_namespace_claim
            ),
            "valid_until": _utc_text(self.valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return and revalidate the complete canonical binding payload."""

        self.__post_init__()
        return self._content_payload()

    def _seal_hashes(self) -> None:
        account_claim = _hash(
            {
                "account_id": self.account_id_claim,
                "account_namespace": self.account_namespace_claim,
                "claim": "canonical_account_creation_binding.account.v1",
            }
        )
        underlying_claim = _hash(
            {
                "claim": "canonical_account_creation_binding.underlying.v1",
                "underlying_unified_account_id": self.underlying_unified_account_id_claim,
                "underlying_unified_account_namespace": (
                    self.underlying_unified_account_namespace_claim
                ),
            }
        )
        for field_name, current, expected in (
            ("account_claim_hash", self.account_claim_hash, account_claim),
            ("underlying_claim_hash", self.underlying_claim_hash, underlying_claim),
        ):
            if not current:
                object.__setattr__(self, field_name, expected)
            elif _digest(current, field_name) != expected:
                raise ValueError(f"{field_name} is invalid")
        identity = _hash(self._identity_payload())
        content = _hash(self._content_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", identity)
        elif _digest(self.identity_hash, "identity_hash") != identity:
            raise ValueError("identity_hash is invalid")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", content)
        elif _digest(self.content_hash, "content_hash") != content:
            raise ValueError("content_hash is invalid")


def resolve_canonical_account_creation_binding(
    binding: CanonicalAccountCreationBinding,
    *,
    as_of: datetime,
) -> CanonicalAccountCreationBinding | None:
    """Return one exact PIT binding without expiry or terminal fallback."""

    if type(binding) is not CanonicalAccountCreationBinding:
        raise TypeError("binding must be exact CanonicalAccountCreationBinding")
    binding.__post_init__()
    _aware(as_of, "as_of")
    if binding.recorded_at <= as_of < binding.valid_until:
        return binding
    return None


__all__ = [
    "CanonicalAccountCreationAllocation",
    "CanonicalAccountCreationBinding",
    "CanonicalAccountCreationRequester",
    "CanonicalAccountCreationServiceRecorder",
    "resolve_canonical_account_creation_binding",
]
