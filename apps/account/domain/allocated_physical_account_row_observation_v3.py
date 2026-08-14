"""Creation-root evidence joining a canonical allocation to Physical v2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
    validate_physical_account_row_observation_v2_root,
)

ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_OWNER = "account"
ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_ARTIFACT_TYPE = (
    "allocated_physical_account_row_observation_v3"
)
ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_SCHEMA = (
    "allocated-physical-account-row-observation.v3"
)
ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_PERMISSION = "evidence_only"
ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_STATUS = "inactive"
ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_IDENTITY_ANCHOR_KIND = "creation_allocation"
ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_OWNER_ASSIGNMENT_STATE = "unknown"


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
class AllocatedPhysicalAccountRowObservationV3:
    """Seal one allocation and its exact first live Physical v2 row."""

    observation_id: str
    observation_version: str
    allocation: CanonicalAccountCreationAllocation
    physical_observation: PhysicalAccountRowObservationV2
    recorded_at: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    identity_anchor_kind: str = ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_IDENTITY_ANCHOR_KIND
    owner_assignment_state: str = (
        ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_OWNER_ASSIGNMENT_STATE
    )
    owner: str = ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_OWNER
    artifact_type: str = ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_ARTIFACT_TYPE
    schema: str = ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_SCHEMA
    permission: str = ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_PERMISSION
    status: str = ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_STATUS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        _require_token(self.observation_id, "observation_id")
        _require_token(self.observation_version, "observation_version")
        if type(self.allocation) is not CanonicalAccountCreationAllocation:
            raise TypeError("allocation must be an exact CanonicalAccountCreationAllocation")
        if type(self.physical_observation) is not PhysicalAccountRowObservationV2:
            raise TypeError("physical_observation must be an exact PhysicalAccountRowObservationV2")

        allocation_payload = self._allocation_payload()
        validate_physical_account_row_observation_v2_root(self.physical_observation)
        physical_payload = self.physical_observation.to_payload()
        physical = self.physical_observation
        if not physical.is_active or not physical.is_present or physical.is_tombstone:
            raise ValueError("a live physical root is required")
        if (
            physical.account_namespace != allocation_payload["canonical_account_namespace"]
            or physical.account_id != allocation_payload["canonical_account_id"]
        ):
            raise ValueError("physical account label does not match allocation")
        if physical.row_user_id != allocation_payload["requested_row_user_id"]:
            raise ValueError("physical row user does not match allocation")
        if physical.raw_account_type != allocation_payload["requested_raw_account_type"]:
            raise ValueError("physical account type does not match allocation")
        if (
            physical.underlying_unified_account_namespace
            != allocation_payload["intended_underlying_unified_account_namespace"]
        ):
            raise ValueError("physical underlying namespace does not match allocation")

        for field_name in ("recorded_at", "ttl_valid_until", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if self.recorded_at < self.allocation.allocated_at:
            raise ValueError("recorded_at cannot precede allocation")
        if self.recorded_at < physical.recorded_at:
            raise ValueError("recorded_at cannot precede physical root")
        if not self.allocation.allocated_at <= self.recorded_at < self.allocation.valid_until:
            raise ValueError("allocation must be live when the creation root is recorded")
        if not physical.is_current_at(self.recorded_at):
            raise ValueError("a live physical root is required at recorded_at")
        expected_valid_until = min(
            self.allocation.valid_until,
            physical.valid_until,
            self.ttl_valid_until,
        )
        if self.valid_until != expected_valid_until:
            raise ValueError("valid_until must equal the three-way validity minimum")
        if self.recorded_at >= self.ttl_valid_until:
            raise ValueError("TTL validity must follow recording")
        if self.recorded_at >= self.valid_until:
            raise ValueError("creation-root validity must follow recording")

        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("allocated physical root identity_hash is invalid")
        expected_content_hash = _canonical_hash(
            self._content_payload(
                allocation_payload=allocation_payload,
                physical_payload=physical_payload,
            )
        )
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("allocated physical root content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        for actual, expected, field_name in (
            (self.owner, ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_OWNER, "owner"),
            (
                self.artifact_type,
                ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_ARTIFACT_TYPE,
                "artifact_type",
            ),
            (
                self.schema,
                ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_SCHEMA,
                "schema",
            ),
            (
                self.identity_anchor_kind,
                ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_IDENTITY_ANCHOR_KIND,
                "identity_anchor_kind",
            ),
            (
                self.owner_assignment_state,
                ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_OWNER_ASSIGNMENT_STATE,
                "owner_assignment_state",
            ),
            (
                self.permission,
                ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_PERMISSION,
                "permission",
            ),
            (
                self.status,
                ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_STATUS,
                "status",
            ),
        ):
            if actual != expected:
                raise ValueError(f"allocated physical root {field_name} is fixed")

    @property
    def activation_available(self) -> bool:
        """Remain false because creation-root evidence grants no authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this wrapper cannot authorize execution."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact creation root is recorded and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "observation_id": self.observation_id,
            "observation_version": self.observation_version,
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
        physical_payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "allocation": allocation_payload,
            "physical_observation": physical_payload,
            "recorded_at": _utc_text(self.recorded_at),
            "ttl_valid_until": _utc_text(self.ttl_valid_until),
            "valid_until": _utc_text(self.valid_until),
            "identity_anchor_kind": self.identity_anchor_kind,
            "owner_assignment_state": self.owner_assignment_state,
            "permission": self.permission,
            "status": self.status,
        }

    def to_payload(self) -> dict[str, object]:
        """Return and revalidate the complete nested creation-root payload."""

        AllocatedPhysicalAccountRowObservationV3.__post_init__(self)
        return {
            **self._content_payload(
                allocation_payload=self._allocation_payload(),
                physical_payload=self.physical_observation.to_payload(),
            ),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def resolve_allocated_physical_account_row_observation_v3(
    observation: AllocatedPhysicalAccountRowObservationV3,
    *,
    as_of: datetime,
) -> AllocatedPhysicalAccountRowObservationV3 | None:
    """Resolve one exact creation root without expiry or terminal fallback."""

    if type(observation) is not AllocatedPhysicalAccountRowObservationV3:
        raise TypeError("observation must be an exact AllocatedPhysicalAccountRowObservationV3")
    AllocatedPhysicalAccountRowObservationV3.__post_init__(observation)
    _require_aware(as_of, "as_of")
    return observation if observation.is_knowable_at(as_of) else None


__all__ = [
    "ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_ARTIFACT_TYPE",
    "ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_IDENTITY_ANCHOR_KIND",
    "ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_OWNER",
    "ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_OWNER_ASSIGNMENT_STATE",
    "ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_PERMISSION",
    "ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_SCHEMA",
    "ALLOCATED_PHYSICAL_ACCOUNT_ROW_OBSERVATION_V3_STATUS",
    "AllocatedPhysicalAccountRowObservationV3",
    "resolve_allocated_physical_account_row_observation_v3",
]
