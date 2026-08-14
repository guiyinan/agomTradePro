"""Durable creation binding from one allocation to one exact creation root."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationServiceRecorder,
)

CANONICAL_ACCOUNT_CREATION_BINDING_V2_OWNER = "account"
CANONICAL_ACCOUNT_CREATION_BINDING_V2_ARTIFACT_TYPE = "canonical_account_creation_binding_v2"
CANONICAL_ACCOUNT_CREATION_BINDING_V2_SCHEMA = "canonical-account-creation-binding.v2"
CANONICAL_ACCOUNT_CREATION_BINDING_V2_PERMISSION = "identity_binding_evidence_only"
CANONICAL_ACCOUNT_CREATION_BINDING_V2_STATUS = "inactive"
CANONICAL_ACCOUNT_CREATION_BINDING_V2_BINDING_STATE = "bound_pending_owner_approval"
CANONICAL_ACCOUNT_CREATION_BINDING_V2_OWNER_ASSIGNMENT_STATE = "unknown"


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
class CanonicalAccountCreationBindingV2:
    """Permanently bind one allocation to one exact creation-root mapping."""

    binding_id: str
    binding_version: str
    allocation: CanonicalAccountCreationAllocation
    creation_root: AllocatedPhysicalAccountRowObservationV3
    account_namespace_claim: str
    account_id_claim: str
    underlying_unified_account_namespace_claim: str
    underlying_unified_account_id_claim: int
    creation_root_identity_hash: str
    creation_root_content_hash: str
    physical_observation_content_hash: str
    physical_source_content_hash: str
    physical_raw_observation_content_hash: str
    recorded_by: CanonicalAccountCreationServiceRecorder
    recorded_at: datetime
    account_claim_hash: str = ""
    underlying_claim_hash: str = ""
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = CANONICAL_ACCOUNT_CREATION_BINDING_V2_OWNER
    artifact_type: str = CANONICAL_ACCOUNT_CREATION_BINDING_V2_ARTIFACT_TYPE
    schema: str = CANONICAL_ACCOUNT_CREATION_BINDING_V2_SCHEMA
    permission: str = CANONICAL_ACCOUNT_CREATION_BINDING_V2_PERMISSION
    status: str = CANONICAL_ACCOUNT_CREATION_BINDING_V2_STATUS
    binding_state: str = CANONICAL_ACCOUNT_CREATION_BINDING_V2_BINDING_STATE
    owner_assignment_state: str = CANONICAL_ACCOUNT_CREATION_BINDING_V2_OWNER_ASSIGNMENT_STATE

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        _require_token(self.binding_id, "binding_id")
        _require_token(self.binding_version, "binding_version")
        for field_name in (
            "account_namespace_claim",
            "account_id_claim",
            "underlying_unified_account_namespace_claim",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_positive_integer(
            self.underlying_unified_account_id_claim,
            "underlying_unified_account_id_claim",
        )
        if type(self.allocation) is not CanonicalAccountCreationAllocation:
            raise TypeError("allocation must be an exact CanonicalAccountCreationAllocation")
        if type(self.creation_root) is not AllocatedPhysicalAccountRowObservationV3:
            raise TypeError(
                "creation_root must be an exact AllocatedPhysicalAccountRowObservationV3"
            )
        allocation_payload = self._allocation_payload()
        creation_root_payload = self.creation_root.to_payload()
        if self.creation_root.allocation != self.allocation:
            raise ValueError("creation root does not bind the exact allocation")

        physical = self.creation_root.physical_observation
        if (
            self.account_namespace_claim != self.allocation.canonical_account_namespace
            or self.account_namespace_claim != physical.account_namespace
            or self.account_id_claim != self.allocation.canonical_account_id
            or self.account_id_claim != physical.account_id
        ):
            raise ValueError("account claim does not match allocation and creation root")
        if (
            self.underlying_unified_account_namespace_claim
            != self.allocation.intended_underlying_unified_account_namespace
            or self.underlying_unified_account_namespace_claim
            != physical.underlying_unified_account_namespace
            or self.underlying_unified_account_id_claim != physical.underlying_unified_account_id
        ):
            raise ValueError("underlying claim does not match the creation root")
        if physical.row_user_id != self.allocation.requested_row_user_id:
            raise ValueError("creation root row user does not match allocation")
        if physical.raw_account_type != self.allocation.requested_raw_account_type:
            raise ValueError("creation root account type does not match allocation")

        for field_name, actual, expected in (
            (
                "creation root identity",
                self.creation_root_identity_hash,
                self.creation_root.identity_hash,
            ),
            (
                "creation root content",
                self.creation_root_content_hash,
                self.creation_root.content_hash,
            ),
            (
                "physical observation content",
                self.physical_observation_content_hash,
                physical.content_hash,
            ),
            (
                "physical source content",
                self.physical_source_content_hash,
                physical.source_content_hash,
            ),
            (
                "physical raw observation content",
                self.physical_raw_observation_content_hash,
                physical.raw_observation_content_hash,
            ),
        ):
            _require_hash(actual, field_name.replace(" ", "_"))
            if actual != expected:
                raise ValueError(f"{field_name} hash does not match creation root")

        if type(self.recorded_by) is not CanonicalAccountCreationServiceRecorder:
            raise TypeError("recorded_by must be an exact CanonicalAccountCreationServiceRecorder")
        self.recorded_by.__post_init__()
        if self.recorded_by.role != "canonical_account_creation_binder":
            raise ValueError("durable binding recorder must be the creation binder service")
        _require_aware(self.recorded_at, "recorded_at")
        if not self.allocation.allocated_at <= self.recorded_at < self.allocation.valid_until:
            raise ValueError("allocation must be valid when durable binding is recorded")
        if not self.creation_root.recorded_at <= self.recorded_at < self.creation_root.valid_until:
            raise ValueError("creation root must be valid when durable binding is recorded")

        expected_account_claim_hash = _canonical_hash(self._account_claim_payload())
        expected_underlying_claim_hash = _canonical_hash(self._underlying_claim_payload())
        for field_name, current, expected in (
            ("account_claim_hash", self.account_claim_hash, expected_account_claim_hash),
            (
                "underlying_claim_hash",
                self.underlying_claim_hash,
                expected_underlying_claim_hash,
            ),
        ):
            if not current:
                object.__setattr__(self, field_name, expected)
            else:
                _require_hash(current, field_name)
                if current != expected:
                    raise ValueError(f"{field_name} is invalid")

        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("durable binding identity_hash is invalid")
        expected_content_hash = _canonical_hash(
            self._content_payload(
                allocation_payload=allocation_payload,
                creation_root_payload=creation_root_payload,
            )
        )
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("durable binding content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        for actual, expected, field_name in (
            (self.owner, CANONICAL_ACCOUNT_CREATION_BINDING_V2_OWNER, "owner"),
            (
                self.artifact_type,
                CANONICAL_ACCOUNT_CREATION_BINDING_V2_ARTIFACT_TYPE,
                "artifact_type",
            ),
            (self.schema, CANONICAL_ACCOUNT_CREATION_BINDING_V2_SCHEMA, "schema"),
            (
                self.permission,
                CANONICAL_ACCOUNT_CREATION_BINDING_V2_PERMISSION,
                "permission",
            ),
            (self.status, CANONICAL_ACCOUNT_CREATION_BINDING_V2_STATUS, "status"),
            (
                self.binding_state,
                CANONICAL_ACCOUNT_CREATION_BINDING_V2_BINDING_STATE,
                "binding_state",
            ),
            (
                self.owner_assignment_state,
                CANONICAL_ACCOUNT_CREATION_BINDING_V2_OWNER_ASSIGNMENT_STATE,
                "owner_assignment_state",
            ),
        ):
            if actual != expected:
                raise ValueError(f"durable binding {field_name} is fixed")

    @property
    def activation_available(self) -> bool:
        """Remain false because the durable mapping grants no authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true while owner approval is absent."""

        return True

    @property
    def mapping_reusable(self) -> bool:
        """Remain false because a durable creation mapping is one-time."""

        return False

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this permanent mapping had been recorded by one PIT."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
        }

    def _account_claim_payload(self) -> dict[str, object]:
        return {
            "claim": "canonical_account_creation_binding_v2.account.v2",
            "account_namespace": self.account_namespace_claim,
            "account_id": self.account_id_claim,
        }

    def _underlying_claim_payload(self) -> dict[str, object]:
        return {
            "claim": "canonical_account_creation_binding_v2.underlying.v2",
            "underlying_unified_account_namespace": (
                self.underlying_unified_account_namespace_claim
            ),
            "underlying_unified_account_id": (self.underlying_unified_account_id_claim),
        }

    def _allocation_payload(self) -> dict[str, object]:
        self.allocation.__post_init__()
        return {
            **self.allocation.to_payload(),
            "identity_hash": self.allocation.identity_hash,
            "content_hash": self.allocation.content_hash,
        }

    def _content_payload(
        self,
        *,
        allocation_payload: dict[str, object],
        creation_root_payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "allocation": allocation_payload,
            "creation_root": creation_root_payload,
            "account_namespace_claim": self.account_namespace_claim,
            "account_id_claim": self.account_id_claim,
            "account_claim_hash": self.account_claim_hash,
            "underlying_unified_account_namespace_claim": (
                self.underlying_unified_account_namespace_claim
            ),
            "underlying_unified_account_id_claim": (self.underlying_unified_account_id_claim),
            "underlying_claim_hash": self.underlying_claim_hash,
            "creation_root_identity_hash": self.creation_root_identity_hash,
            "creation_root_content_hash": self.creation_root_content_hash,
            "physical_observation_content_hash": (self.physical_observation_content_hash),
            "physical_source_content_hash": self.physical_source_content_hash,
            "physical_raw_observation_content_hash": (self.physical_raw_observation_content_hash),
            "recorded_by": self.recorded_by.to_payload(),
            "recorded_at": _utc_text(self.recorded_at),
            "permission": self.permission,
            "status": self.status,
            "binding_state": self.binding_state,
            "owner_assignment_state": self.owner_assignment_state,
        }

    def to_payload(self) -> dict[str, object]:
        """Return and revalidate the complete durable binding evidence."""

        CanonicalAccountCreationBindingV2.__post_init__(self)
        return {
            **self._content_payload(
                allocation_payload=self._allocation_payload(),
                creation_root_payload=self.creation_root.to_payload(),
            ),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
            "mapping_reusable": False,
        }


def resolve_canonical_account_creation_binding_v2(
    binding: CanonicalAccountCreationBindingV2,
    *,
    as_of: datetime,
) -> CanonicalAccountCreationBindingV2 | None:
    """Resolve exact durable evidence by recording knowledge time only."""

    if type(binding) is not CanonicalAccountCreationBindingV2:
        raise TypeError("binding must be an exact CanonicalAccountCreationBindingV2")
    CanonicalAccountCreationBindingV2.__post_init__(binding)
    _require_aware(as_of, "as_of")
    return binding if binding.is_knowable_at(as_of) else None


__all__ = [
    "CANONICAL_ACCOUNT_CREATION_BINDING_V2_ARTIFACT_TYPE",
    "CANONICAL_ACCOUNT_CREATION_BINDING_V2_BINDING_STATE",
    "CANONICAL_ACCOUNT_CREATION_BINDING_V2_OWNER",
    "CANONICAL_ACCOUNT_CREATION_BINDING_V2_OWNER_ASSIGNMENT_STATE",
    "CANONICAL_ACCOUNT_CREATION_BINDING_V2_PERMISSION",
    "CANONICAL_ACCOUNT_CREATION_BINDING_V2_SCHEMA",
    "CANONICAL_ACCOUNT_CREATION_BINDING_V2_STATUS",
    "CanonicalAccountCreationBindingV2",
    "resolve_canonical_account_creation_binding_v2",
]
