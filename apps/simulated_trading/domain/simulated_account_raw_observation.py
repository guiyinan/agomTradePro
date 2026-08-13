"""Immutable owner observations of physical SimulatedAccount rows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

SIMULATED_ACCOUNT_RAW_OBSERVATION_OWNER = "simulated_trading"
SIMULATED_ACCOUNT_RAW_OBSERVATION_ARTIFACT_TYPE = "simulated_account_raw_observation"
SIMULATED_ACCOUNT_RAW_OBSERVATION_SCHEMA = "simulated-account-raw-observation.v1"
SIMULATED_ACCOUNT_RAW_OBSERVATION_PERMISSION = "evidence_only"
SIMULATED_ACCOUNT_RAW_OBSERVATION_STATUS = "inactive"


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
class SimulatedAccountRawObservation:
    """Seal one owner-observed physical row without assigning authority."""

    observation_id: str
    observation_version: str
    row_pk: int
    row_user_id: int | None
    raw_account_type: str
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    is_present: bool
    is_tombstone: bool
    observed_at: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = SIMULATED_ACCOUNT_RAW_OBSERVATION_OWNER
    artifact_type: str = SIMULATED_ACCOUNT_RAW_OBSERVATION_ARTIFACT_TYPE
    schema: str = SIMULATED_ACCOUNT_RAW_OBSERVATION_SCHEMA
    permission: str = SIMULATED_ACCOUNT_RAW_OBSERVATION_PERMISSION
    status: str = SIMULATED_ACCOUNT_RAW_OBSERVATION_STATUS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "observation_id",
            "observation_version",
            "raw_account_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.row_pk) is not int:
            raise TypeError("row_pk must be an exact integer")
        if self.row_pk <= 0:
            raise ValueError("row_pk must be positive")
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
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("raw simulated account observation clock sequence is invalid")
        if self.observed_at >= self.valid_until:
            raise ValueError("raw simulated account observation validity is invalid")
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")

        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("raw observation identity_hash is invalid")

        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("raw observation content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        for actual, expected, field_name in (
            (self.owner, SIMULATED_ACCOUNT_RAW_OBSERVATION_OWNER, "owner"),
            (
                self.artifact_type,
                SIMULATED_ACCOUNT_RAW_OBSERVATION_ARTIFACT_TYPE,
                "artifact_type",
            ),
            (self.schema, SIMULATED_ACCOUNT_RAW_OBSERVATION_SCHEMA, "schema"),
            (
                self.permission,
                SIMULATED_ACCOUNT_RAW_OBSERVATION_PERMISSION,
                "permission",
            ),
            (self.status, SIMULATED_ACCOUNT_RAW_OBSERVATION_STATUS, "status"),
        ):
            if actual != expected:
                raise ValueError(f"raw observation {field_name} is fixed")

    @property
    def activation_available(self) -> bool:
        """Remain false because a row observation conveys no authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this record cannot authorize execution."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact observation is visible and unexpired."""

        _require_aware(as_of, "as_of")
        return self.observed_at <= as_of < self.valid_until

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
            "row_pk": self.row_pk,
            "row_user_id": self.row_user_id,
            "raw_account_type": self.raw_account_type,
            "is_active": self.is_active,
            "row_created_at": _utc_text(self.row_created_at),
            "row_updated_at": _utc_text(self.row_updated_at),
            "is_present": self.is_present,
            "is_tombstone": self.is_tombstone,
            "observed_at": _utc_text(self.observed_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical owner observation envelope."""

        SimulatedAccountRawObservation.__post_init__(self)
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_simulated_account_raw_observation_root(
    root: SimulatedAccountRawObservation,
) -> None:
    """Validate a root observation with no claimed predecessor."""

    if type(root) is not SimulatedAccountRawObservation:
        raise TypeError("root must be an exact SimulatedAccountRawObservation")
    SimulatedAccountRawObservation.__post_init__(root)
    if root.supersedes_content_hash is not None:
        raise ValueError("root must not declare a predecessor")


def validate_simulated_account_raw_observation_successor(
    previous: SimulatedAccountRawObservation,
    successor: SimulatedAccountRawObservation,
) -> None:
    """Validate one adjacent revision of the same physical row."""

    if type(previous) is not SimulatedAccountRawObservation:
        raise TypeError("previous must be an exact SimulatedAccountRawObservation")
    if type(successor) is not SimulatedAccountRawObservation:
        raise TypeError("successor must be an exact SimulatedAccountRawObservation")
    SimulatedAccountRawObservation.__post_init__(previous)
    SimulatedAccountRawObservation.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous observation")
    if successor.observation_id != previous.observation_id:
        raise ValueError("successor changed observation_id")
    if successor.observation_version == previous.observation_version:
        raise ValueError("successor observation_version must advance")
    if successor.row_pk != previous.row_pk:
        raise ValueError("successor changed row_pk")
    if successor.row_created_at != previous.row_created_at:
        raise ValueError("successor changed row_created_at")
    if successor.row_updated_at < previous.row_updated_at:
        raise ValueError("successor row_updated_at cannot regress")
    if successor.observed_at <= previous.observed_at:
        raise ValueError("successor observed_at must advance")


def resolve_simulated_account_raw_observation_head(
    chain: tuple[SimulatedAccountRawObservation, ...],
    *,
    as_of: datetime,
) -> SimulatedAccountRawObservation | None:
    """Resolve the visible raw head without expiry or tombstone fallback."""

    _require_aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    for observation in chain:
        if type(observation) is not SimulatedAccountRawObservation:
            raise TypeError("chain values must be exact SimulatedAccountRawObservation values")
        SimulatedAccountRawObservation.__post_init__(observation)
    if chain:
        validate_simulated_account_raw_observation_root(chain[0])
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_simulated_account_raw_observation_successor(previous, successor)
    visible = tuple(observation for observation in chain if observation.observed_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_knowable_at(as_of) else None


__all__ = [
    "SIMULATED_ACCOUNT_RAW_OBSERVATION_ARTIFACT_TYPE",
    "SIMULATED_ACCOUNT_RAW_OBSERVATION_OWNER",
    "SIMULATED_ACCOUNT_RAW_OBSERVATION_PERMISSION",
    "SIMULATED_ACCOUNT_RAW_OBSERVATION_SCHEMA",
    "SIMULATED_ACCOUNT_RAW_OBSERVATION_STATUS",
    "SimulatedAccountRawObservation",
    "resolve_simulated_account_raw_observation_head",
    "validate_simulated_account_raw_observation_root",
    "validate_simulated_account_raw_observation_successor",
]
