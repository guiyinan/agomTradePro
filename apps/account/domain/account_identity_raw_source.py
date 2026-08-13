"""Account-owned raw identity source evidence with no execution authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

ACCOUNT_IDENTITY_RAW_SOURCE_OWNER = "account"
ACCOUNT_IDENTITY_RAW_SOURCE_ARTIFACT_TYPE = "account_identity_raw_source"
ACCOUNT_IDENTITY_RAW_SOURCE_SCHEMA = "account-identity-raw-source.v1"
ACCOUNT_IDENTITY_RAW_SOURCE_PERMISSION = "source_evidence_only"
ACCOUNT_IDENTITY_RAW_SOURCE_STATUS = "inactive"
ACCOUNT_IDENTITY_RAW_SOURCE_BLOCKERS = ("account_owner_assignment_provider_not_integrated",)
ACCOUNT_IDENTITY_ASSIGNMENT_STATES = (
    "authoritative",
    "legacy_default",
    "unknown",
)
ACCOUNT_ASSIGNMENT_EVIDENCE_OWNER = "account"
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_TYPE = "account_owner_assignment_evidence"
ACCOUNT_LEGACY_DEFAULT_ASSIGNMENT_EVIDENCE_TYPE = "account_legacy_default_assignment_evidence"


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
class AccountIdentityRawSource:
    """Immutable observation of one Account identity source, never an authority grant."""

    source_id: str
    source_version: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    owner_user_id: int | None
    assignment_state: str
    assignment_evidence_owner: str | None
    assignment_evidence_artifact_type: str | None
    assignment_evidence_id: str | None
    assignment_evidence_version: str | None
    assignment_evidence_content_hash: str | None
    row_source_owner: str
    row_source_artifact_type: str
    row_source_id: str
    row_source_version: str
    row_source_content_hash: str
    observed_at: datetime
    recorded_at: datetime
    row_source_valid_until: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    is_active: bool
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_IDENTITY_RAW_SOURCE_OWNER
    artifact_type: str = ACCOUNT_IDENTITY_RAW_SOURCE_ARTIFACT_TYPE
    schema: str = ACCOUNT_IDENTITY_RAW_SOURCE_SCHEMA
    permission: str = ACCOUNT_IDENTITY_RAW_SOURCE_PERMISSION
    status: str = ACCOUNT_IDENTITY_RAW_SOURCE_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_IDENTITY_RAW_SOURCE_BLOCKERS
    account_type: str = "real"

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "row_source_owner",
            "row_source_artifact_type",
            "row_source_id",
            "row_source_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact boolean")
        _require_hash(self.row_source_content_hash, "row_source_content_hash")
        self._validate_assignment()
        for field_name in (
            "observed_at",
            "recorded_at",
            "row_source_valid_until",
            "ttl_valid_until",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        expected_valid_until = min(
            self.row_source_valid_until,
            self.ttl_valid_until,
        )
        if self.valid_until != expected_valid_until:
            raise ValueError("valid_until must equal the minimum row-source and TTL validity")
        if not (
            self.observed_at <= self.recorded_at < self.row_source_valid_until
            and self.recorded_at < self.ttl_valid_until
        ):
            raise ValueError("account identity raw source clock sequence is invalid")
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")
        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("account identity raw source identity_hash is invalid")
        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("account identity raw source content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        if self.owner != ACCOUNT_IDENTITY_RAW_SOURCE_OWNER:
            raise ValueError("account identity raw source owner is fixed")
        if self.artifact_type != ACCOUNT_IDENTITY_RAW_SOURCE_ARTIFACT_TYPE:
            raise ValueError("account identity raw source artifact_type is fixed")
        if self.schema != ACCOUNT_IDENTITY_RAW_SOURCE_SCHEMA:
            raise ValueError("account identity raw source schema is fixed")
        if self.permission != ACCOUNT_IDENTITY_RAW_SOURCE_PERMISSION:
            raise ValueError("account identity raw source permission is fixed")
        if self.status != ACCOUNT_IDENTITY_RAW_SOURCE_STATUS:
            raise ValueError("account identity raw source status is fixed inactive")
        if self.blocker_codes != ACCOUNT_IDENTITY_RAW_SOURCE_BLOCKERS:
            raise ValueError("account identity raw source blocker_codes are fixed")
        if self.account_type != "real":
            raise ValueError("account identity raw source account_type is fixed real")

    def _validate_assignment(self) -> None:
        if type(self.assignment_state) is not str:
            raise TypeError("assignment_state must be an exact string")
        if self.assignment_state not in ACCOUNT_IDENTITY_ASSIGNMENT_STATES:
            raise ValueError("assignment_state is invalid")
        if self.owner_user_id is not None and (
            type(self.owner_user_id) is not int or self.owner_user_id <= 0
        ):
            raise ValueError("owner_user_id must be null or an exact positive integer")
        evidence = (
            self.assignment_evidence_owner,
            self.assignment_evidence_artifact_type,
            self.assignment_evidence_id,
            self.assignment_evidence_version,
            self.assignment_evidence_content_hash,
        )
        if self.assignment_state == "unknown":
            if self.owner_user_id is not None or any(value is not None for value in evidence):
                raise ValueError("unknown assignment cannot claim an owner or evidence")
            return
        if any(value is None for value in evidence):
            raise ValueError(f"{self.assignment_state} assignment requires exact evidence")
        for field_name in (
            "assignment_evidence_owner",
            "assignment_evidence_artifact_type",
            "assignment_evidence_id",
            "assignment_evidence_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(
            self.assignment_evidence_content_hash,
            "assignment_evidence_content_hash",
        )
        if self.assignment_evidence_owner != ACCOUNT_ASSIGNMENT_EVIDENCE_OWNER:
            raise ValueError(f"{self.assignment_state} assignment evidence owner is invalid")
        if self.assignment_state == "authoritative":
            if self.owner_user_id is None:
                raise ValueError("authoritative assignment requires an exact owner")
            if self.assignment_evidence_artifact_type != ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_TYPE:
                raise ValueError("authoritative assignment evidence type is invalid")
            return
        if self.owner_user_id is not None:
            raise ValueError("legacy_default assignment cannot claim an owner")
        if (
            self.assignment_evidence_artifact_type
            != ACCOUNT_LEGACY_DEFAULT_ASSIGNMENT_EVIDENCE_TYPE
        ):
            raise ValueError("legacy_default assignment evidence type is invalid")

    @property
    def activation_available(self) -> bool:
        """Remain false because raw source evidence grants no activation authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because an Account observation is never an execution grant."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact observation is recorded and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def is_issuable_at(self, as_of: datetime) -> bool:
        """Return whether the evidence can support authoritative identity issuance."""

        return (
            self.is_knowable_at(as_of)
            and self.is_active
            and self.assignment_state == "authoritative"
            and self.owner_user_id is not None
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
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "owner_user_id": self.owner_user_id,
            "account_type": self.account_type,
            "is_active": self.is_active,
            "assignment_state": self.assignment_state,
            "assignment_evidence_owner": self.assignment_evidence_owner,
            "assignment_evidence_artifact_type": (self.assignment_evidence_artifact_type),
            "assignment_evidence_id": self.assignment_evidence_id,
            "assignment_evidence_version": self.assignment_evidence_version,
            "assignment_evidence_content_hash": (self.assignment_evidence_content_hash),
            "row_source_owner": self.row_source_owner,
            "row_source_artifact_type": self.row_source_artifact_type,
            "row_source_id": self.row_source_id,
            "row_source_version": self.row_source_version,
            "row_source_content_hash": self.row_source_content_hash,
            "observed_at": _utc_text(self.observed_at),
            "recorded_at": _utc_text(self.recorded_at),
            "row_source_valid_until": _utc_text(self.row_source_valid_until),
            "ttl_valid_until": _utc_text(self.ttl_valid_until),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical inactive raw-source evidence payload."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def _assignment_reference(source: AccountIdentityRawSource) -> tuple[object, ...]:
    return (
        source.assignment_state,
        source.assignment_evidence_owner,
        source.assignment_evidence_artifact_type,
        source.assignment_evidence_id,
        source.assignment_evidence_version,
        source.assignment_evidence_content_hash,
    )


def validate_account_identity_raw_source_successor(
    previous: AccountIdentityRawSource,
    successor: AccountIdentityRawSource,
) -> None:
    """Validate one adjacent raw-source version in the same logical chain."""

    if type(previous) is not AccountIdentityRawSource:
        raise TypeError("previous must be an exact AccountIdentityRawSource")
    if type(successor) is not AccountIdentityRawSource:
        raise TypeError("successor must be an exact AccountIdentityRawSource")
    AccountIdentityRawSource.__post_init__(previous)
    AccountIdentityRawSource.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous raw source")
    if successor.source_id != previous.source_id:
        raise ValueError("successor changed source_id")
    if successor.source_version == previous.source_version:
        raise ValueError("successor source_version must advance")
    for field_name in (
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "row_source_owner",
        "row_source_artifact_type",
        "row_source_id",
    ):
        if getattr(successor, field_name) != getattr(previous, field_name):
            raise ValueError(f"successor changed {field_name}")
    if successor.row_source_version == previous.row_source_version:
        raise ValueError("successor row_source_version must advance")
    if successor.observed_at <= previous.observed_at:
        raise ValueError("successor observed_at must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")
    if successor.owner_user_id != previous.owner_user_id and _assignment_reference(
        successor
    ) == _assignment_reference(previous):
        raise ValueError("owner change requires new exact assignment evidence")


def resolve_account_identity_raw_source_head(
    chain: tuple[AccountIdentityRawSource, ...],
    *,
    as_of: datetime,
) -> AccountIdentityRawSource | None:
    """Return the visible logical head without falling back from inactive or expiry."""

    _require_aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    for source in chain:
        if type(source) is not AccountIdentityRawSource:
            raise TypeError("chain values must be exact AccountIdentityRawSource values")
        AccountIdentityRawSource.__post_init__(source)
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_account_identity_raw_source_successor(previous, successor)
    visible = tuple(source for source in chain if source.recorded_at <= as_of)
    return visible[-1] if visible else None


__all__ = [
    "ACCOUNT_ASSIGNMENT_EVIDENCE_OWNER",
    "ACCOUNT_IDENTITY_ASSIGNMENT_STATES",
    "ACCOUNT_IDENTITY_RAW_SOURCE_ARTIFACT_TYPE",
    "ACCOUNT_IDENTITY_RAW_SOURCE_BLOCKERS",
    "ACCOUNT_IDENTITY_RAW_SOURCE_OWNER",
    "ACCOUNT_IDENTITY_RAW_SOURCE_PERMISSION",
    "ACCOUNT_IDENTITY_RAW_SOURCE_SCHEMA",
    "ACCOUNT_IDENTITY_RAW_SOURCE_STATUS",
    "ACCOUNT_LEGACY_DEFAULT_ASSIGNMENT_EVIDENCE_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_TYPE",
    "AccountIdentityRawSource",
    "resolve_account_identity_raw_source_head",
    "validate_account_identity_raw_source_successor",
]
