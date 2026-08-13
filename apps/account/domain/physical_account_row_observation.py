"""Account-owned physical account-row evidence without owner inference."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER = "account"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE = "physical_account_row_observation"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA = "physical-account-row-observation.v1"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_PERMISSION = "evidence_only"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_STATUS = "inactive"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_BLOCKERS = (
    "physical_account_row_observation_provider_not_integrated",
)
PHYSICAL_ACCOUNT_ROW_OWNER_ASSIGNMENT_STATE = "unknown"
PHYSICAL_ACCOUNT_ROW_SOURCE_OWNER = "simulated_trading"
PHYSICAL_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE = "simulated_account_row"


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
class PhysicalAccountRowObservation:
    """Immutable physical-row observation that deliberately claims no owner."""

    observation_id: str
    observation_version: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    raw_source_owner: str
    raw_source_artifact_type: str
    raw_source_id: str
    raw_source_version: str
    raw_source_content_hash: str
    row_user_id: int | None
    account_type: str
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    observed_at: datetime
    recorded_at: datetime
    raw_source_valid_until: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner_assignment_state: str = PHYSICAL_ACCOUNT_ROW_OWNER_ASSIGNMENT_STATE
    owner: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER
    artifact_type: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE
    schema: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA
    permission: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_PERMISSION
    status: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_STATUS
    blocker_codes: tuple[str, ...] = PHYSICAL_ACCOUNT_ROW_OBSERVATION_BLOCKERS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "observation_id",
            "observation_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "raw_source_owner",
            "raw_source_artifact_type",
            "raw_source_id",
            "raw_source_version",
            "account_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if self.row_user_id is not None and type(self.row_user_id) is not int:
            raise TypeError("row_user_id must be null or an exact integer")
        if self.row_user_id is not None and self.row_user_id <= 0:
            raise ValueError("row_user_id must be null or positive")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact boolean")
        _require_hash(self.raw_source_content_hash, "raw_source_content_hash")
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")
        for field_name in (
            "row_created_at",
            "row_updated_at",
            "observed_at",
            "recorded_at",
            "raw_source_valid_until",
            "ttl_valid_until",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("physical account row clock sequence is invalid")
        if not self.observed_at <= self.recorded_at:
            raise ValueError("recorded_at cannot precede observed_at")
        if not (
            self.recorded_at < self.raw_source_valid_until
            and self.recorded_at < self.ttl_valid_until
        ):
            raise ValueError("physical account row validity must follow recording")
        if self.valid_until != min(
            self.raw_source_valid_until,
            self.ttl_valid_until,
        ):
            raise ValueError("valid_until must equal minimum source and TTL validity")
        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("physical account row identity_hash is invalid")
        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("physical account row content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        fixed = (
            (self.owner, PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER, "owner"),
            (
                self.artifact_type,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE,
                "artifact_type",
            ),
            (self.schema, PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA, "schema"),
            (
                self.permission,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_PERMISSION,
                "permission",
            ),
            (self.status, PHYSICAL_ACCOUNT_ROW_OBSERVATION_STATUS, "status"),
            (
                self.owner_assignment_state,
                PHYSICAL_ACCOUNT_ROW_OWNER_ASSIGNMENT_STATE,
                "owner_assignment_state",
            ),
            (self.raw_source_owner, PHYSICAL_ACCOUNT_ROW_SOURCE_OWNER, "raw_source_owner"),
            (
                self.raw_source_artifact_type,
                PHYSICAL_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE,
                "raw_source_artifact_type",
            ),
        )
        for actual, expected, field_name in fixed:
            if actual != expected:
                raise ValueError(f"physical account row {field_name} is fixed")
        if self.blocker_codes != PHYSICAL_ACCOUNT_ROW_OBSERVATION_BLOCKERS:
            raise ValueError("physical account row blocker_codes are fixed")

    @property
    def activation_available(self) -> bool:
        """Remain false because a physical row is evidence, not authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because physical-row evidence cannot authorize execution."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact row observation is recorded and unexpired."""

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

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": self.underlying_unified_account_namespace,
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "raw_source_owner": self.raw_source_owner,
            "raw_source_artifact_type": self.raw_source_artifact_type,
            "raw_source_id": self.raw_source_id,
            "raw_source_version": self.raw_source_version,
            "raw_source_content_hash": self.raw_source_content_hash,
            "row_user_id": self.row_user_id,
            "account_type": self.account_type,
            "is_active": self.is_active,
            "row_created_at": _utc_text(self.row_created_at),
            "row_updated_at": _utc_text(self.row_updated_at),
            "observed_at": _utc_text(self.observed_at),
            "recorded_at": _utc_text(self.recorded_at),
            "raw_source_valid_until": _utc_text(self.raw_source_valid_until),
            "ttl_valid_until": _utc_text(self.ttl_valid_until),
            "valid_until": _utc_text(self.valid_until),
            "owner_assignment_state": self.owner_assignment_state,
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return canonical physical-row evidence with fixed execution blockers."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_physical_account_row_observation_successor(
    previous: PhysicalAccountRowObservation,
    successor: PhysicalAccountRowObservation,
) -> None:
    """Validate adjacent observations for one exact physical source row."""

    if type(previous) is not PhysicalAccountRowObservation:
        raise TypeError("previous must be an exact PhysicalAccountRowObservation")
    if type(successor) is not PhysicalAccountRowObservation:
        raise TypeError("successor must be an exact PhysicalAccountRowObservation")
    PhysicalAccountRowObservation.__post_init__(previous)
    PhysicalAccountRowObservation.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous observation")
    if successor.observation_id != previous.observation_id:
        raise ValueError("successor changed observation_id")
    if successor.observation_version == previous.observation_version:
        raise ValueError("successor observation_version must advance")
    for field_name in (
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "raw_source_owner",
        "raw_source_artifact_type",
        "raw_source_id",
    ):
        if getattr(successor, field_name) != getattr(previous, field_name):
            raise ValueError(f"successor changed {field_name}")
    if successor.raw_source_version == previous.raw_source_version:
        raise ValueError("successor raw_source_version must advance")
    if successor.observed_at <= previous.observed_at:
        raise ValueError("successor observed_at must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


def resolve_physical_account_row_observation_head(
    chain: tuple[PhysicalAccountRowObservation, ...],
    *,
    as_of: datetime,
) -> PhysicalAccountRowObservation | None:
    """Resolve the PIT head; a final expired/inactive row never falls back."""

    _require_aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    for observation in chain:
        if type(observation) is not PhysicalAccountRowObservation:
            raise TypeError("chain values must be exact PhysicalAccountRowObservation values")
        PhysicalAccountRowObservation.__post_init__(observation)
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_physical_account_row_observation_successor(previous, successor)
    visible = tuple(item for item in chain if item.recorded_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    if not head.is_active or not head.is_knowable_at(as_of):
        return None
    return head


__all__ = [
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_BLOCKERS",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_PERMISSION",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_STATUS",
    "PHYSICAL_ACCOUNT_ROW_OWNER_ASSIGNMENT_STATE",
    "PHYSICAL_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE",
    "PHYSICAL_ACCOUNT_ROW_SOURCE_OWNER",
    "PhysicalAccountRowObservation",
    "resolve_physical_account_row_observation_head",
    "validate_physical_account_row_observation_successor",
]
