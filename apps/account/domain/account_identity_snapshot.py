"""Inactive Account-owned identity evidence for one canonical account namespace."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

ACCOUNT_IDENTITY_SNAPSHOT_OWNER = "account"
ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE = "account_identity_snapshot"
ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA = "account-identity-snapshot.v1"
ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION = "identity_evidence_only"
ACCOUNT_IDENTITY_SNAPSHOT_STATUS = "inactive"
ACCOUNT_IDENTITY_SNAPSHOT_BLOCKERS = ("account_identity_source_provider_not_integrated",)
ACCOUNT_IDENTITY_PROVENANCE_KINDS = ("authoritative", "manual_reclaim")
ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER = "account"
ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE = "account_owner_reclaim_receipt"


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
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
class AccountIdentitySnapshot:
    """Content-addressed identity evidence that never grants execution authority."""

    source_id: str
    source_version: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    owner_user_id: int
    provenance_kind: str
    legacy_default_user_assignment: bool
    underlying_source_id: str
    underlying_source_version: str
    underlying_source_content_hash: str
    underlying_source_recorded_at: datetime
    underlying_source_valid_until: datetime
    ttl_valid_until: datetime
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    reclaim_receipt_owner: str | None = None
    reclaim_receipt_artifact_type: str | None = None
    reclaim_receipt_id: str | None = None
    reclaim_receipt_version: str | None = None
    reclaim_receipt_content_hash: str | None = None
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_IDENTITY_SNAPSHOT_OWNER
    artifact_type: str = ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE
    schema: str = ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA
    permission: str = ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION
    status: str = ACCOUNT_IDENTITY_SNAPSHOT_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_IDENTITY_SNAPSHOT_BLOCKERS
    account_type: str = "real"
    is_active: bool = True

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "provenance_kind",
            "underlying_source_id",
            "underlying_source_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if type(self.owner_user_id) is not int:
            raise TypeError("owner_user_id must be an exact integer")
        if self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be positive")
        if type(self.legacy_default_user_assignment) is not bool:
            raise TypeError("legacy_default_user_assignment must be an exact boolean")
        _require_hash(
            self.underlying_source_content_hash,
            "underlying_source_content_hash",
        )
        self._validate_provenance()
        for field_name in (
            "underlying_source_recorded_at",
            "underlying_source_valid_until",
            "ttl_valid_until",
            "issued_at",
            "recorded_at",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        expected_valid_until = min(
            self.underlying_source_valid_until,
            self.ttl_valid_until,
        )
        if self.valid_until != expected_valid_until:
            raise ValueError("valid_until must equal the minimum source and TTL validity")
        if not (
            self.underlying_source_recorded_at
            <= self.issued_at
            <= self.recorded_at
            < self.underlying_source_valid_until
            and self.recorded_at < self.ttl_valid_until
        ):
            raise ValueError("account identity snapshot clock sequence is invalid")
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")
        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("account identity snapshot identity_hash is invalid")
        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("account identity snapshot content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        if self.owner != ACCOUNT_IDENTITY_SNAPSHOT_OWNER:
            raise ValueError("account identity snapshot owner is fixed")
        if self.artifact_type != ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE:
            raise ValueError("account identity snapshot artifact_type is fixed")
        if self.schema != ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA:
            raise ValueError("account identity snapshot schema is fixed")
        if self.permission != ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION:
            raise ValueError("account identity snapshot permission is fixed")
        if self.status != ACCOUNT_IDENTITY_SNAPSHOT_STATUS:
            raise ValueError("account identity snapshot status is fixed inactive")
        if self.blocker_codes != ACCOUNT_IDENTITY_SNAPSHOT_BLOCKERS:
            raise ValueError("account identity snapshot blocker_codes are fixed")
        if self.account_type != "real" or self.is_active is not True:
            raise ValueError("account identity snapshot requires an active real account")

    def _validate_provenance(self) -> None:
        if self.provenance_kind not in ACCOUNT_IDENTITY_PROVENANCE_KINDS:
            raise ValueError("account identity provenance_kind is invalid")
        receipt_values = (
            self.reclaim_receipt_owner,
            self.reclaim_receipt_artifact_type,
            self.reclaim_receipt_id,
            self.reclaim_receipt_version,
            self.reclaim_receipt_content_hash,
        )
        if self.legacy_default_user_assignment and self.provenance_kind != "manual_reclaim":
            raise ValueError("legacy default-user accounts require manual_reclaim provenance")
        if self.provenance_kind == "authoritative":
            if any(value is not None for value in receipt_values):
                raise ValueError("authoritative provenance cannot carry a reclaim receipt")
            return
        if any(value is None for value in receipt_values):
            raise ValueError("manual_reclaim provenance requires an exact reclaim receipt")
        if self.reclaim_receipt_owner != ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER:
            raise ValueError("reclaim receipt owner is invalid")
        if self.reclaim_receipt_artifact_type != ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE:
            raise ValueError("reclaim receipt artifact_type is invalid")
        for field_name in (
            "reclaim_receipt_owner",
            "reclaim_receipt_artifact_type",
            "reclaim_receipt_id",
            "reclaim_receipt_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.reclaim_receipt_content_hash, "reclaim_receipt_content_hash")

    @property
    def activation_available(self) -> bool:
        """Remain false until a trusted Account source provider is integrated."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because identity evidence grants no execution authority."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact evidence is recorded and unexpired at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

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
            "owner_user_id": self.owner_user_id,
            "account_type": self.account_type,
            "is_active": self.is_active,
            "provenance_kind": self.provenance_kind,
            "legacy_default_user_assignment": self.legacy_default_user_assignment,
            "underlying_source_id": self.underlying_source_id,
            "underlying_source_version": self.underlying_source_version,
            "underlying_source_content_hash": self.underlying_source_content_hash,
            "reclaim_receipt_owner": self.reclaim_receipt_owner,
            "reclaim_receipt_artifact_type": self.reclaim_receipt_artifact_type,
            "reclaim_receipt_id": self.reclaim_receipt_id,
            "reclaim_receipt_version": self.reclaim_receipt_version,
            "reclaim_receipt_content_hash": self.reclaim_receipt_content_hash,
            "underlying_source_recorded_at": _utc_text(self.underlying_source_recorded_at),
            "underlying_source_valid_until": _utc_text(self.underlying_source_valid_until),
            "ttl_valid_until": _utc_text(self.ttl_valid_until),
            "issued_at": _utc_text(self.issued_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical inactive evidence payload."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_identity_snapshot_successor(
    previous: AccountIdentitySnapshot,
    successor: AccountIdentitySnapshot,
) -> None:
    """Validate one adjacent version in the same Account-owned identity chain."""

    if type(previous) is not AccountIdentitySnapshot:
        raise TypeError("previous must be an exact AccountIdentitySnapshot")
    if type(successor) is not AccountIdentitySnapshot:
        raise TypeError("successor must be an exact AccountIdentitySnapshot")
    AccountIdentitySnapshot.__post_init__(previous)
    AccountIdentitySnapshot.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous snapshot")
    if successor.source_id != previous.source_id:
        raise ValueError("successor changed source identity")
    if successor.source_version == previous.source_version:
        raise ValueError("successor source_version must advance")
    for field_name in (
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "owner_user_id",
    ):
        if getattr(successor, field_name) != getattr(previous, field_name):
            raise ValueError(f"successor changed {field_name}")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


__all__ = [
    "ACCOUNT_IDENTITY_PROVENANCE_KINDS",
    "ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE",
    "ACCOUNT_IDENTITY_SNAPSHOT_BLOCKERS",
    "ACCOUNT_IDENTITY_SNAPSHOT_OWNER",
    "ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION",
    "ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA",
    "ACCOUNT_IDENTITY_SNAPSHOT_STATUS",
    "ACCOUNT_OWNER_RECLAIM_RECEIPT_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_RECLAIM_RECEIPT_OWNER",
    "AccountIdentitySnapshot",
    "validate_account_identity_snapshot_successor",
]
