"""Raw-observation-bound source evidence for one simulated account row."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

SIMULATED_ACCOUNT_ROW_SOURCE_V2_OWNER = "simulated_trading"
SIMULATED_ACCOUNT_ROW_SOURCE_V2_ARTIFACT_TYPE = "simulated_account_row_v2"
SIMULATED_ACCOUNT_ROW_SOURCE_V2_SCHEMA = "simulated-account-row.v2"
SIMULATED_ACCOUNT_ROW_SOURCE_V2_PERMISSION = "evidence_only"
SIMULATED_ACCOUNT_ROW_SOURCE_V2_STATUS = "inactive"
SIMULATED_ACCOUNT_ROW_SOURCE_V2_OWNER_ASSIGNMENT_STATE = "unknown"

SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_OWNER = "simulated_trading"
SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_ARTIFACT_TYPE = "simulated_account_raw_observation"
SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_SCHEMA = "simulated-account-raw-observation.v1"


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
class SimulatedAccountRowSourceV2:
    """Seal a source projection and its exact owner raw observation."""

    source_id: str
    source_version: str
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
    observed_at: datetime
    recorded_at: datetime
    source_valid_until: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    raw_observation_id: str
    raw_observation_version: str
    raw_observation_identity_hash: str
    raw_observation_content_hash: str
    raw_observation_observed_at: datetime
    raw_observation_valid_until: datetime
    raw_observation_supersedes_content_hash: str | None = None
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner_assignment_state: str = SIMULATED_ACCOUNT_ROW_SOURCE_V2_OWNER_ASSIGNMENT_STATE
    raw_observation_owner: str = SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_OWNER
    raw_observation_artifact_type: str = (
        SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_ARTIFACT_TYPE
    )
    raw_observation_schema: str = SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_SCHEMA
    owner: str = SIMULATED_ACCOUNT_ROW_SOURCE_V2_OWNER
    artifact_type: str = SIMULATED_ACCOUNT_ROW_SOURCE_V2_ARTIFACT_TYPE
    schema: str = SIMULATED_ACCOUNT_ROW_SOURCE_V2_SCHEMA
    permission: str = SIMULATED_ACCOUNT_ROW_SOURCE_V2_PERMISSION
    status: str = SIMULATED_ACCOUNT_ROW_SOURCE_V2_STATUS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "raw_account_type",
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
            "observed_at",
            "recorded_at",
            "source_valid_until",
            "ttl_valid_until",
            "valid_until",
            "raw_observation_observed_at",
            "raw_observation_valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("simulated account row source v2 clock sequence is invalid")
        if self.observed_at != self.raw_observation_observed_at:
            raise ValueError("observed_at must equal raw observation observed_at")
        if self.source_valid_until != self.raw_observation_valid_until:
            raise ValueError("source_valid_until must equal raw observation valid_until")
        if self.observed_at > self.recorded_at:
            raise ValueError("recorded_at cannot precede observed_at")
        if not (
            self.recorded_at < self.source_valid_until and self.recorded_at < self.ttl_valid_until
        ):
            raise ValueError("simulated account row source v2 validity must follow recording")
        if self.valid_until != min(self.source_valid_until, self.ttl_valid_until):
            raise ValueError("valid_until must equal minimum raw-source and TTL validity")

        if self.raw_observation_id != self.source_id:
            raise ValueError("raw_observation_id must equal source_id")
        if self.raw_observation_version != self.source_version:
            raise ValueError("raw_observation_version must equal source_version")
        expected_raw_identity_hash = _canonical_hash(self._raw_identity_payload())
        _require_hash(
            self.raw_observation_identity_hash,
            "raw_observation_identity_hash",
        )
        if self.raw_observation_identity_hash != expected_raw_identity_hash:
            raise ValueError("raw observation identity_hash is invalid")
        _require_hash(
            self.raw_observation_content_hash,
            "raw_observation_content_hash",
        )
        if self.raw_observation_supersedes_content_hash is not None:
            _require_hash(
                self.raw_observation_supersedes_content_hash,
                "raw_observation_supersedes_content_hash",
            )
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")

        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("simulated account row source v2 identity_hash is invalid")
        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("simulated account row source v2 content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        fixed = (
            (self.owner, SIMULATED_ACCOUNT_ROW_SOURCE_V2_OWNER, "owner"),
            (
                self.artifact_type,
                SIMULATED_ACCOUNT_ROW_SOURCE_V2_ARTIFACT_TYPE,
                "artifact_type",
            ),
            (self.schema, SIMULATED_ACCOUNT_ROW_SOURCE_V2_SCHEMA, "schema"),
            (
                self.permission,
                SIMULATED_ACCOUNT_ROW_SOURCE_V2_PERMISSION,
                "permission",
            ),
            (self.status, SIMULATED_ACCOUNT_ROW_SOURCE_V2_STATUS, "status"),
            (
                self.owner_assignment_state,
                SIMULATED_ACCOUNT_ROW_SOURCE_V2_OWNER_ASSIGNMENT_STATE,
                "owner_assignment_state",
            ),
            (
                self.raw_observation_owner,
                SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_OWNER,
                "raw_observation_owner",
            ),
            (
                self.raw_observation_artifact_type,
                SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_ARTIFACT_TYPE,
                "raw_observation_artifact_type",
            ),
            (
                self.raw_observation_schema,
                SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_SCHEMA,
                "raw_observation_schema",
            ),
        )
        for actual, expected, field_name in fixed:
            if actual != expected:
                raise ValueError(f"simulated account row source v2 {field_name} is fixed")

    @property
    def activation_available(self) -> bool:
        """Remain false because source evidence cannot authorize execution."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this envelope is evidence only."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact source version is recorded and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether the final source version represents a live row."""

        return (
            self.is_knowable_at(as_of)
            and self.is_present
            and not self.is_tombstone
            and self.is_active
        )

    def _raw_identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.raw_observation_owner,
            "artifact_type": self.raw_observation_artifact_type,
            "schema": self.raw_observation_schema,
            "observation_id": self.raw_observation_id,
            "observation_version": self.raw_observation_version,
        }

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "source_id": self.source_id,
            "source_version": self.source_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": self.underlying_unified_account_namespace,
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "row_user_id": self.row_user_id,
            "raw_account_type": self.raw_account_type,
            "is_active": self.is_active,
            "row_created_at": _utc_text(self.row_created_at),
            "row_updated_at": _utc_text(self.row_updated_at),
            "is_present": self.is_present,
            "is_tombstone": self.is_tombstone,
            "observed_at": _utc_text(self.observed_at),
            "recorded_at": _utc_text(self.recorded_at),
            "source_valid_until": _utc_text(self.source_valid_until),
            "ttl_valid_until": _utc_text(self.ttl_valid_until),
            "valid_until": _utc_text(self.valid_until),
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
            "owner_assignment_state": self.owner_assignment_state,
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical v2 source envelope."""

        SimulatedAccountRowSourceV2.__post_init__(self)
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_simulated_account_row_source_v2_root(
    root: SimulatedAccountRowSourceV2,
) -> None:
    """Validate a v2 source root with no claimed predecessor."""

    if type(root) is not SimulatedAccountRowSourceV2:
        raise TypeError("root must be an exact SimulatedAccountRowSourceV2")
    SimulatedAccountRowSourceV2.__post_init__(root)
    if root.supersedes_content_hash is not None:
        raise ValueError("root must not declare a predecessor")
    if root.raw_observation_supersedes_content_hash is not None:
        raise ValueError("root raw observation must not declare a predecessor")


def validate_simulated_account_row_source_v2_successor(
    previous: SimulatedAccountRowSourceV2,
    successor: SimulatedAccountRowSourceV2,
) -> None:
    """Validate adjacent revisions of one exact logical physical row."""

    if type(previous) is not SimulatedAccountRowSourceV2:
        raise TypeError("previous must be an exact SimulatedAccountRowSourceV2")
    if type(successor) is not SimulatedAccountRowSourceV2:
        raise TypeError("successor must be an exact SimulatedAccountRowSourceV2")
    SimulatedAccountRowSourceV2.__post_init__(previous)
    SimulatedAccountRowSourceV2.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous source")
    if successor.raw_observation_supersedes_content_hash != previous.raw_observation_content_hash:
        raise ValueError(
            "successor raw observation does not bind the exact previous raw observation"
        )
    if successor.source_id != previous.source_id:
        raise ValueError("successor changed source_id")
    if successor.source_version == previous.source_version:
        raise ValueError("successor source_version must advance")
    for field_name in (
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "row_created_at",
    ):
        if getattr(successor, field_name) != getattr(previous, field_name):
            raise ValueError(f"successor changed {field_name}")
    if successor.row_updated_at < previous.row_updated_at:
        raise ValueError("successor row_updated_at cannot regress")
    if successor.observed_at <= previous.observed_at:
        raise ValueError("successor observed_at must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


def resolve_simulated_account_row_source_v2_head(
    chain: tuple[SimulatedAccountRowSourceV2, ...],
    *,
    as_of: datetime,
) -> SimulatedAccountRowSourceV2 | None:
    """Resolve the PIT final head without inactive, tombstone, or expiry fallback."""

    _require_aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    for source in chain:
        if type(source) is not SimulatedAccountRowSourceV2:
            raise TypeError("chain values must be exact SimulatedAccountRowSourceV2 values")
        SimulatedAccountRowSourceV2.__post_init__(source)
    if chain:
        validate_simulated_account_row_source_v2_root(chain[0])
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_simulated_account_row_source_v2_successor(previous, successor)
    visible = tuple(source for source in chain if source.recorded_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_current_at(as_of) else None


__all__ = [
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_ARTIFACT_TYPE",
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_OWNER",
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_OWNER_ASSIGNMENT_STATE",
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_PERMISSION",
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_ARTIFACT_TYPE",
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_OWNER",
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_RAW_OBSERVATION_SCHEMA",
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_SCHEMA",
    "SIMULATED_ACCOUNT_ROW_SOURCE_V2_STATUS",
    "SimulatedAccountRowSourceV2",
    "resolve_simulated_account_row_source_v2_head",
    "validate_simulated_account_row_source_v2_root",
    "validate_simulated_account_row_source_v2_successor",
]
