"""Account evidence sealing source-v2 and raw-observation provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER = "account"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_ARTIFACT_TYPE = "physical_account_row_observation_v2"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SCHEMA = "physical-account-row-observation.v2"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_PERMISSION = "evidence_only"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_STATUS = "inactive"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER_ASSIGNMENT_STATE = "unknown"

PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_OWNER = "simulated_trading"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_ARTIFACT_TYPE = "simulated_account_row_v2"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_SCHEMA = "simulated-account-row.v2"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_OWNER = "simulated_trading"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_ARTIFACT_TYPE = "simulated_account_raw_observation"
PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_SCHEMA = "simulated-account-raw-observation.v1"


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
class PhysicalAccountRowObservationV2:
    """Seal an Account observation and both exact upstream evidence layers."""

    observation_id: str
    observation_version: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    row_user_id: int | None
    raw_account_type: str
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    is_present: bool
    is_tombstone: bool
    source_id: str
    source_version: str
    source_identity_hash: str
    source_content_hash: str
    source_supersedes_content_hash: str | None
    source_observed_at: datetime
    source_recorded_at: datetime
    source_valid_until: datetime
    source_ttl_valid_until: datetime
    source_effective_valid_until: datetime
    raw_observation_id: str
    raw_observation_version: str
    raw_observation_identity_hash: str
    raw_observation_content_hash: str
    raw_observation_supersedes_content_hash: str | None
    raw_observation_observed_at: datetime
    raw_observation_valid_until: datetime
    recorded_at: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner_assignment_state: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER_ASSIGNMENT_STATE
    source_owner: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_OWNER
    source_artifact_type: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_ARTIFACT_TYPE
    source_schema: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_SCHEMA
    raw_observation_owner: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_OWNER
    raw_observation_artifact_type: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_ARTIFACT_TYPE
    raw_observation_schema: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_SCHEMA
    owner: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER
    artifact_type: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_ARTIFACT_TYPE
    schema: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SCHEMA
    permission: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_PERMISSION
    status: str = PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_STATUS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "observation_id",
            "observation_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "raw_account_type",
            "source_id",
            "source_version",
            "raw_observation_id",
            "raw_observation_version",
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
        for field_name in ("is_active", "is_present", "is_tombstone"):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be an exact boolean")
        if self.is_present == self.is_tombstone:
            raise ValueError("is_present and is_tombstone must be exact opposites")

        for field_name in (
            "row_created_at",
            "row_updated_at",
            "source_observed_at",
            "source_recorded_at",
            "source_valid_until",
            "source_ttl_valid_until",
            "source_effective_valid_until",
            "raw_observation_observed_at",
            "raw_observation_valid_until",
            "recorded_at",
            "ttl_valid_until",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not self.row_created_at <= self.row_updated_at <= self.source_observed_at:
            raise ValueError("physical account row v2 source clock sequence is invalid")
        if self.source_observed_at != self.raw_observation_observed_at:
            raise ValueError("source_observed_at must equal raw observation observed_at")
        if self.source_valid_until != self.raw_observation_valid_until:
            raise ValueError("source_valid_until must equal raw observation valid_until")
        if self.source_observed_at > self.source_recorded_at:
            raise ValueError("source_recorded_at cannot precede source_observed_at")
        if not (
            self.source_recorded_at < self.source_valid_until
            and self.source_recorded_at < self.source_ttl_valid_until
        ):
            raise ValueError("source validity must follow source recording")
        if self.source_effective_valid_until != min(
            self.source_valid_until,
            self.source_ttl_valid_until,
        ):
            raise ValueError("source effective validity is invalid")
        if self.source_recorded_at > self.recorded_at:
            raise ValueError("Account recorded_at must advance to or beyond source recording")
        if not (
            self.recorded_at < self.source_effective_valid_until
            and self.recorded_at < self.ttl_valid_until
        ):
            raise ValueError("Account validity must follow recording")
        if self.valid_until != min(
            self.source_effective_valid_until,
            self.ttl_valid_until,
        ):
            raise ValueError("Account effective validity is invalid")

        if self.source_id != self.raw_observation_id:
            raise ValueError("source_id must equal raw observation id")
        if self.source_version != self.raw_observation_version:
            raise ValueError("source_version must equal raw observation version")
        self._validate_upstream_hashes()
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")

        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("physical account row v2 identity_hash is invalid")
        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("physical account row v2 content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        fixed = (
            (self.owner, PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER, "owner"),
            (
                self.artifact_type,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_ARTIFACT_TYPE,
                "artifact_type",
            ),
            (self.schema, PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SCHEMA, "schema"),
            (
                self.permission,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_PERMISSION,
                "permission",
            ),
            (self.status, PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_STATUS, "status"),
            (
                self.owner_assignment_state,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER_ASSIGNMENT_STATE,
                "owner_assignment_state",
            ),
            (
                self.source_owner,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_OWNER,
                "source_owner",
            ),
            (
                self.source_artifact_type,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_ARTIFACT_TYPE,
                "source_artifact_type",
            ),
            (
                self.source_schema,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_SCHEMA,
                "source_schema",
            ),
            (
                self.raw_observation_owner,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_OWNER,
                "raw_observation_owner",
            ),
            (
                self.raw_observation_artifact_type,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_ARTIFACT_TYPE,
                "raw_observation_artifact_type",
            ),
            (
                self.raw_observation_schema,
                PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_SCHEMA,
                "raw_observation_schema",
            ),
        )
        for actual, expected, field_name in fixed:
            if actual != expected:
                raise ValueError(f"{field_name} is fixed")

    def _validate_upstream_hashes(self) -> None:
        expected_raw_identity = _canonical_hash(self._raw_identity_payload())
        _require_hash(
            self.raw_observation_identity_hash,
            "raw_observation_identity_hash",
        )
        if self.raw_observation_identity_hash != expected_raw_identity:
            raise ValueError("raw observation identity_hash is invalid")
        _require_hash(
            self.raw_observation_content_hash,
            "raw_observation_content_hash",
        )
        expected_raw_content = _canonical_hash(self._raw_content_payload())
        if self.raw_observation_content_hash != expected_raw_content:
            raise ValueError("raw observation content_hash is invalid")
        if self.raw_observation_supersedes_content_hash is not None:
            _require_hash(
                self.raw_observation_supersedes_content_hash,
                "raw_observation_supersedes_content_hash",
            )

        expected_source_identity = _canonical_hash(self._source_identity_payload())
        _require_hash(self.source_identity_hash, "source_identity_hash")
        if self.source_identity_hash != expected_source_identity:
            raise ValueError("source identity_hash is invalid")
        expected_source_content = _canonical_hash(self._source_content_payload())
        _require_hash(self.source_content_hash, "source_content_hash")
        if self.source_content_hash != expected_source_content:
            raise ValueError("source content_hash is invalid")
        if self.source_supersedes_content_hash is not None:
            _require_hash(
                self.source_supersedes_content_hash,
                "source_supersedes_content_hash",
            )

    @property
    def activation_available(self) -> bool:
        """Remain false because this envelope carries evidence, not authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because unknown ownership cannot authorize execution."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this Account capture is recorded and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether the final visible capture represents a live row."""

        return (
            self.is_knowable_at(as_of)
            and self.is_active
            and self.is_present
            and not self.is_tombstone
        )

    def _raw_identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.raw_observation_owner,
            "artifact_type": self.raw_observation_artifact_type,
            "schema": self.raw_observation_schema,
            "observation_id": self.raw_observation_id,
            "observation_version": self.raw_observation_version,
        }

    def _raw_content_payload(self) -> dict[str, object]:
        return {
            **self._raw_identity_payload(),
            "row_pk": self.underlying_unified_account_id,
            "row_user_id": self.row_user_id,
            "raw_account_type": self.raw_account_type,
            "is_active": self.is_active,
            "row_created_at": _utc_text(self.row_created_at),
            "row_updated_at": _utc_text(self.row_updated_at),
            "is_present": self.is_present,
            "is_tombstone": self.is_tombstone,
            "observed_at": _utc_text(self.raw_observation_observed_at),
            "valid_until": _utc_text(self.raw_observation_valid_until),
            "supersedes_content_hash": self.raw_observation_supersedes_content_hash,
            "permission": "evidence_only",
            "status": "inactive",
        }

    def _source_identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.source_owner,
            "artifact_type": self.source_artifact_type,
            "schema": self.source_schema,
            "source_id": self.source_id,
            "source_version": self.source_version,
        }

    def _source_content_payload(self) -> dict[str, object]:
        return {
            **self._source_identity_payload(),
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "row_user_id": self.row_user_id,
            "raw_account_type": self.raw_account_type,
            "is_active": self.is_active,
            "row_created_at": _utc_text(self.row_created_at),
            "row_updated_at": _utc_text(self.row_updated_at),
            "is_present": self.is_present,
            "is_tombstone": self.is_tombstone,
            "observed_at": _utc_text(self.source_observed_at),
            "recorded_at": _utc_text(self.source_recorded_at),
            "source_valid_until": _utc_text(self.source_valid_until),
            "ttl_valid_until": _utc_text(self.source_ttl_valid_until),
            "valid_until": _utc_text(self.source_effective_valid_until),
            "raw_observation_owner": self.raw_observation_owner,
            "raw_observation_artifact_type": self.raw_observation_artifact_type,
            "raw_observation_schema": self.raw_observation_schema,
            "raw_observation_id": self.raw_observation_id,
            "raw_observation_version": self.raw_observation_version,
            "raw_observation_identity_hash": self.raw_observation_identity_hash,
            "raw_observation_content_hash": self.raw_observation_content_hash,
            "raw_observation_observed_at": _utc_text(self.raw_observation_observed_at),
            "raw_observation_valid_until": _utc_text(self.raw_observation_valid_until),
            "raw_observation_supersedes_content_hash": (
                self.raw_observation_supersedes_content_hash
            ),
            "owner_assignment_state": "unknown",
            "supersedes_content_hash": self.source_supersedes_content_hash,
            "permission": "evidence_only",
            "status": "inactive",
        }

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
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "row_user_id": self.row_user_id,
            "raw_account_type": self.raw_account_type,
            "is_active": self.is_active,
            "row_created_at": _utc_text(self.row_created_at),
            "row_updated_at": _utc_text(self.row_updated_at),
            "is_present": self.is_present,
            "is_tombstone": self.is_tombstone,
            "source_owner": self.source_owner,
            "source_artifact_type": self.source_artifact_type,
            "source_schema": self.source_schema,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "source_identity_hash": self.source_identity_hash,
            "source_content_hash": self.source_content_hash,
            "source_supersedes_content_hash": self.source_supersedes_content_hash,
            "source_observed_at": _utc_text(self.source_observed_at),
            "source_recorded_at": _utc_text(self.source_recorded_at),
            "source_valid_until": _utc_text(self.source_valid_until),
            "source_ttl_valid_until": _utc_text(self.source_ttl_valid_until),
            "source_effective_valid_until": _utc_text(self.source_effective_valid_until),
            "raw_observation_owner": self.raw_observation_owner,
            "raw_observation_artifact_type": self.raw_observation_artifact_type,
            "raw_observation_schema": self.raw_observation_schema,
            "raw_observation_id": self.raw_observation_id,
            "raw_observation_version": self.raw_observation_version,
            "raw_observation_identity_hash": self.raw_observation_identity_hash,
            "raw_observation_content_hash": self.raw_observation_content_hash,
            "raw_observation_supersedes_content_hash": (
                self.raw_observation_supersedes_content_hash
            ),
            "raw_observation_observed_at": _utc_text(self.raw_observation_observed_at),
            "raw_observation_valid_until": _utc_text(self.raw_observation_valid_until),
            "recorded_at": _utc_text(self.recorded_at),
            "ttl_valid_until": _utc_text(self.ttl_valid_until),
            "valid_until": _utc_text(self.valid_until),
            "owner_assignment_state": self.owner_assignment_state,
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical Account v2 observation."""

        PhysicalAccountRowObservationV2.__post_init__(self)
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_physical_account_row_observation_v2_root(
    root: PhysicalAccountRowObservationV2,
) -> None:
    """Validate a root with no Account, source, or raw predecessor."""

    if type(root) is not PhysicalAccountRowObservationV2:
        raise TypeError("root must be an exact PhysicalAccountRowObservationV2")
    if root.supersedes_content_hash is not None:
        raise ValueError("root observation predecessor must be absent")
    if root.source_supersedes_content_hash is not None:
        raise ValueError("root source predecessor must be absent")
    if root.raw_observation_supersedes_content_hash is not None:
        raise ValueError("root raw observation predecessor must be absent")
    PhysicalAccountRowObservationV2.__post_init__(root)


def validate_physical_account_row_observation_v2_successor(
    previous: PhysicalAccountRowObservationV2,
    successor: PhysicalAccountRowObservationV2,
) -> None:
    """Validate adjacent captures across all three exact ledgers."""

    if type(previous) is not PhysicalAccountRowObservationV2:
        raise TypeError("previous must be an exact PhysicalAccountRowObservationV2")
    if type(successor) is not PhysicalAccountRowObservationV2:
        raise TypeError("successor must be an exact PhysicalAccountRowObservationV2")
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous observation")
    if successor.source_supersedes_content_hash != previous.source_content_hash:
        raise ValueError("successor does not bind the exact previous source")
    if successor.raw_observation_supersedes_content_hash != previous.raw_observation_content_hash:
        raise ValueError("successor does not bind the exact previous raw observation")
    PhysicalAccountRowObservationV2.__post_init__(previous)
    PhysicalAccountRowObservationV2.__post_init__(successor)
    if successor.observation_id != previous.observation_id:
        raise ValueError("successor changed observation_id")
    if successor.observation_version == previous.observation_version:
        raise ValueError("successor observation_version must advance")
    for field_name in (
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "source_id",
        "raw_observation_id",
        "row_created_at",
    ):
        if getattr(successor, field_name) != getattr(previous, field_name):
            raise ValueError(f"successor changed {field_name}")
    if successor.source_version == previous.source_version:
        raise ValueError("successor source_version must advance")
    if successor.raw_observation_version == previous.raw_observation_version:
        raise ValueError("successor raw_observation_version must advance")
    if successor.row_updated_at < previous.row_updated_at:
        raise ValueError("successor row_updated_at cannot regress")
    if successor.source_observed_at <= previous.source_observed_at:
        raise ValueError("successor source_observed_at must advance")
    if successor.source_recorded_at <= previous.source_recorded_at:
        raise ValueError("successor source_recorded_at must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


def resolve_physical_account_row_observation_v2_head(
    chain: tuple[PhysicalAccountRowObservationV2, ...],
    *,
    as_of: datetime,
) -> PhysicalAccountRowObservationV2 | None:
    """Resolve the PIT final head without inactive, tombstone, or expiry fallback."""

    _require_aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    for observation in chain:
        if type(observation) is not PhysicalAccountRowObservationV2:
            raise TypeError("chain values must be exact PhysicalAccountRowObservationV2 values")
        PhysicalAccountRowObservationV2.__post_init__(observation)
    if chain:
        validate_physical_account_row_observation_v2_root(chain[0])
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_physical_account_row_observation_v2_successor(previous, successor)
    visible = tuple(item for item in chain if item.recorded_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_current_at(as_of) else None


__all__ = [
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_ARTIFACT_TYPE",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER_ASSIGNMENT_STATE",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_PERMISSION",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_ARTIFACT_TYPE",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_OWNER",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_RAW_SCHEMA",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SCHEMA",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_ARTIFACT_TYPE",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_OWNER",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SOURCE_SCHEMA",
    "PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_STATUS",
    "PhysicalAccountRowObservationV2",
    "resolve_physical_account_row_observation_v2_head",
    "validate_physical_account_row_observation_v2_root",
    "validate_physical_account_row_observation_v2_successor",
]
