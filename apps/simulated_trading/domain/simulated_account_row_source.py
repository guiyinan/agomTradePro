"""Immutable SimulatedTrading-owned source evidence for one account row."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

SIMULATED_ACCOUNT_ROW_SOURCE_OWNER = "simulated_trading"
SIMULATED_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE = "simulated_account_row"
SIMULATED_ACCOUNT_ROW_SOURCE_SCHEMA = "simulated-account-row.v1"
SIMULATED_ACCOUNT_ROW_SOURCE_PERMISSION = "evidence_only"
SIMULATED_ACCOUNT_ROW_SOURCE_STATUS = "inactive"
SIMULATED_ACCOUNT_ROW_SOURCE_OWNER_ASSIGNMENT_STATE = "unknown"


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
class SimulatedAccountRowSource:
    """Seal an exact physical-row observation without inferring ownership."""

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
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner_assignment_state: str = SIMULATED_ACCOUNT_ROW_SOURCE_OWNER_ASSIGNMENT_STATE
    owner: str = SIMULATED_ACCOUNT_ROW_SOURCE_OWNER
    artifact_type: str = SIMULATED_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE
    schema: str = SIMULATED_ACCOUNT_ROW_SOURCE_SCHEMA
    permission: str = SIMULATED_ACCOUNT_ROW_SOURCE_PERMISSION
    status: str = SIMULATED_ACCOUNT_ROW_SOURCE_STATUS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "raw_account_type",
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
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("simulated account row source clock sequence is invalid")
        if not self.observed_at <= self.recorded_at:
            raise ValueError("recorded_at cannot precede observed_at")
        if not (
            self.recorded_at < self.source_valid_until and self.recorded_at < self.ttl_valid_until
        ):
            raise ValueError("simulated account row source validity must follow recording")
        if self.valid_until != min(self.source_valid_until, self.ttl_valid_until):
            raise ValueError("valid_until must equal minimum source and TTL validity")
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")
        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("simulated account row source identity_hash is invalid")
        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("simulated account row source content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        fixed = (
            (self.owner, SIMULATED_ACCOUNT_ROW_SOURCE_OWNER, "owner"),
            (
                self.artifact_type,
                SIMULATED_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE,
                "artifact_type",
            ),
            (self.schema, SIMULATED_ACCOUNT_ROW_SOURCE_SCHEMA, "schema"),
            (
                self.permission,
                SIMULATED_ACCOUNT_ROW_SOURCE_PERMISSION,
                "permission",
            ),
            (self.status, SIMULATED_ACCOUNT_ROW_SOURCE_STATUS, "status"),
            (
                self.owner_assignment_state,
                SIMULATED_ACCOUNT_ROW_SOURCE_OWNER_ASSIGNMENT_STATE,
                "owner_assignment_state",
            ),
        )
        for actual, expected, field_name in fixed:
            if actual != expected:
                raise ValueError(f"simulated account row source {field_name} is fixed")

    @property
    def activation_available(self) -> bool:
        """Remain false because physical source evidence grants no authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a source observation cannot authorize execution."""

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
            "owner_assignment_state": self.owner_assignment_state,
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical source envelope."""

        SimulatedAccountRowSource.__post_init__(self)
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_simulated_account_row_source_successor(
    previous: SimulatedAccountRowSource,
    successor: SimulatedAccountRowSource,
) -> None:
    """Validate adjacent revisions for one exact logical physical row."""

    if type(previous) is not SimulatedAccountRowSource:
        raise TypeError("previous must be an exact SimulatedAccountRowSource")
    if type(successor) is not SimulatedAccountRowSource:
        raise TypeError("successor must be an exact SimulatedAccountRowSource")
    SimulatedAccountRowSource.__post_init__(previous)
    SimulatedAccountRowSource.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous source")
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


def resolve_simulated_account_row_source_head(
    chain: tuple[SimulatedAccountRowSource, ...],
    *,
    as_of: datetime,
) -> SimulatedAccountRowSource | None:
    """Resolve a PIT head without fallback from inactive, tombstone, or expiry."""

    _require_aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    for source in chain:
        if type(source) is not SimulatedAccountRowSource:
            raise TypeError("chain values must be exact SimulatedAccountRowSource values")
        SimulatedAccountRowSource.__post_init__(source)
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_simulated_account_row_source_successor(previous, successor)
    visible = tuple(source for source in chain if source.recorded_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_current_at(as_of) else None


__all__ = [
    "SIMULATED_ACCOUNT_ROW_SOURCE_ARTIFACT_TYPE",
    "SIMULATED_ACCOUNT_ROW_SOURCE_OWNER",
    "SIMULATED_ACCOUNT_ROW_SOURCE_OWNER_ASSIGNMENT_STATE",
    "SIMULATED_ACCOUNT_ROW_SOURCE_PERMISSION",
    "SIMULATED_ACCOUNT_ROW_SOURCE_SCHEMA",
    "SIMULATED_ACCOUNT_ROW_SOURCE_STATUS",
    "SimulatedAccountRowSource",
    "resolve_simulated_account_row_source_head",
    "validate_simulated_account_row_source_successor",
]
