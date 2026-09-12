"""Current physical re-observation for a permanently bound Account creation.

This value records that a currently available physical account row still has
the exact identity sealed by a durable creation Binding.  It is evidence only:
it grants no owner, tenant, approval, or execution authority and it does not
extend the lifetime of any older capture.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)

CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_OWNER = "account"
CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_ARTIFACT_TYPE = (
    "canonical_account_ownership_reobservation_v1"
)
CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_SCHEMA = "canonical-account-ownership-reobservation.v1"
CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_PERMISSION = "evidence_only"
CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_STATUS = "inactive"
CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_IDENTITY_HASH_DOMAIN = (
    "canonical-account-ownership-reobservation.v1/identity"
)
CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_CONTENT_HASH_DOMAIN = (
    "canonical-account-ownership-reobservation.v1/content"
)


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    """Validate one bounded, exact canonical token."""

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


def _require_digest(value: object, field_name: str) -> str:
    """Validate one explicit lowercase SHA-256 digest."""

    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    """Validate one timezone-aware datetime without creating a clock value."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize one aware datetime using canonical UTC microseconds."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_hash(domain: str, payload: dict[str, object]) -> str:
    """Hash a canonical payload under an explicit versioned domain separator."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalAccountOwnershipReobservationV1:
    """Seal one current physical row against a permanent creation Binding.

    The Binding is checked only for knowledge at ``recorded_at``; its old
    allocation and physical-root TTLs may therefore have expired.  The new
    physical observation supplies the short-lived current window, and the
    resulting value remains inactive evidence rather than an owner decision.
    """

    observation_id: str
    observation_version: str
    binding: CanonicalAccountCreationBindingV2
    current_physical: PhysicalAccountRowObservationV2
    recorded_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_OWNER
    artifact_type: str = CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_ARTIFACT_TYPE
    schema: str = CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_SCHEMA
    permission: str = CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_PERMISSION
    status: str = CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_STATUS

    def __post_init__(self) -> None:
        """Validate fixed semantics, source identity, clocks, and both seals."""

        self._validate_fixed_semantics()
        _require_token(self.observation_id, "observation_id")
        _require_token(self.observation_version, "observation_version")
        if type(self.binding) is not CanonicalAccountCreationBindingV2:
            raise TypeError("binding must be an exact CanonicalAccountCreationBindingV2")
        if type(self.current_physical) is not PhysicalAccountRowObservationV2:
            raise TypeError("current_physical must be an exact PhysicalAccountRowObservationV2")
        self.binding.__post_init__()
        self.current_physical.__post_init__()
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")

        if not self.binding.is_knowable_at(self.recorded_at):
            raise ValueError("binding must be knowable when reobservation is recorded")
        if self.recorded_at < self.binding.recorded_at:
            raise ValueError("recorded_at cannot precede the durable binding")
        if self.recorded_at < self.current_physical.recorded_at:
            raise ValueError("recorded_at cannot precede current physical observation")
        if not self.current_physical.is_current_at(self.recorded_at):
            raise ValueError("current physical observation must be current when recorded")
        if self.valid_until != self.current_physical.valid_until:
            raise ValueError("valid_until must equal current physical valid_until")

        old_physical = self.binding.creation_root.physical_observation
        allocation = self.binding.allocation
        current = self.current_physical
        if (
            current.account_namespace != self.binding.account_namespace_claim
            or current.account_id != self.binding.account_id_claim
        ):
            raise ValueError("current physical canonical account scope does not match binding")
        if (
            current.underlying_unified_account_namespace
            != self.binding.underlying_unified_account_namespace_claim
            or current.underlying_unified_account_id
            != self.binding.underlying_unified_account_id_claim
        ):
            raise ValueError("current physical underlying row scope does not match binding")
        if (
            current.row_user_id != allocation.requested_row_user_id
            or current.row_user_id != old_physical.row_user_id
        ):
            raise ValueError("current physical row user does not match binding")
        if (
            current.raw_account_type != allocation.requested_raw_account_type
            or current.raw_account_type != old_physical.raw_account_type
        ):
            raise ValueError("current physical raw account type does not match binding")
        if current.row_created_at != old_physical.row_created_at:
            raise ValueError("current physical row_created_at does not match binding")
        if current.row_updated_at < old_physical.row_updated_at:
            raise ValueError("current physical row_updated_at cannot regress")

        expected_identity_hash = _canonical_hash(
            CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_IDENTITY_HASH_DOMAIN,
            self._identity_payload(),
        )
        self._validate_or_set_hash(
            "identity_hash",
            expected_identity_hash,
            "ownership reobservation identity_hash is invalid",
        )
        expected_content_hash = _canonical_hash(
            CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        self._validate_or_set_hash(
            "content_hash",
            expected_content_hash,
            "ownership reobservation content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject reinterpretation as an executable or another artifact."""

        for field_name, expected in (
            ("owner", CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_OWNER),
            (
                "artifact_type",
                CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_ARTIFACT_TYPE,
            ),
            ("schema", CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_SCHEMA),
            ("permission", CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_PERMISSION),
            ("status", CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_STATUS),
        ):
            actual = getattr(self, field_name)
            if type(actual) is not str:
                raise TypeError(f"{field_name} must be an exact string")
            if actual != expected:
                raise ValueError(f"ownership reobservation {field_name} is fixed")

    def _validate_or_set_hash(self, field_name: str, expected: str, message: str) -> None:
        """Compute an omitted hash and reject any supplied mutation."""

        observed = getattr(self, field_name)
        if type(observed) is not str:
            raise TypeError(f"{field_name} must be an exact string")
        if observed == "":
            object.__setattr__(self, field_name, expected)
            return
        if _require_digest(observed, field_name) != expected:
            raise ValueError(message)

    @property
    def activation_available(self) -> bool:
        """Remain false because this observation grants no authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because evidence cannot authorize an operation."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the sealed re-observation had been recorded by a PIT."""

        cutoff = _require_aware(as_of, "as_of")
        self.__post_init__()
        return self.recorded_at <= cutoff

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this current physical fact remains usable at a PIT."""

        cutoff = _require_aware(as_of, "as_of")
        self.__post_init__()
        return (
            self.recorded_at <= cutoff < self.valid_until
            and self.binding.is_knowable_at(cutoff)
            and self.current_physical.is_current_at(cutoff)
        )

    def _identity_payload(self) -> dict[str, object]:
        """Return the stable identity fields used by the identity seal."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "observation_id": self.observation_id,
            "observation_version": self.observation_version,
        }

    def _content_payload(self) -> dict[str, object]:
        """Return every nested source, clock, and inactive-state fact."""

        return {
            **self._identity_payload(),
            "binding": self.binding.to_payload(),
            "current_physical": self.current_physical.to_payload(),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "identity_hash": self.identity_hash,
            "permission": self.permission,
            "status": self.status,
        }

    def to_payload(self) -> dict[str, object]:
        """Return and revalidate the complete inactive evidence payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


__all__ = [
    "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_ARTIFACT_TYPE",
    "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_CONTENT_HASH_DOMAIN",
    "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_IDENTITY_HASH_DOMAIN",
    "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_OWNER",
    "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_PERMISSION",
    "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_SCHEMA",
    "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_V1_STATUS",
    "CanonicalAccountOwnershipReobservationV1",
]
