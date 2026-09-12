"""Inactive subject evidence for a current Account ownership re-observation.

Subject v5 is the versioned bridge between a re-observation-backed provenance
receipt and a later evidence value.  It remains evidence only; it does not
authenticate a person, publish an owner decision, or authorize execution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)
from apps.account.domain.validation_graph import (
    validate_once_per_graph,
    validation_graph_operation,
)

ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_OWNER = "account"
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_ARTIFACT_TYPE = "account_owner_assignment_subject_v5"
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_SCHEMA = "account-owner-assignment-subject.v5"
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_PERMISSION = "evidence_only"
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_STATUS = "inactive"
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_BLOCKERS = (
    "account_owner_assignment_subject_v5_not_integrated",
)
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_IDENTITY_HASH_DOMAIN = (
    "account-owner-assignment-subject.v5/identity"
)
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_CONTENT_HASH_DOMAIN = (
    "account-owner-assignment-subject.v5/content"
)


def _token(value: object, name: str) -> str:
    """Validate one bounded exact canonical token."""

    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _positive_integer(value: object, name: str) -> int:
    """Validate one exact positive integer, rejecting bool values."""

    if type(value) is not int:
        raise TypeError(f"{name} must be an exact positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be an exact positive integer")
    return value


def _digest(value: object, name: str) -> str:
    """Validate one lowercase SHA-256 digest."""

    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    """Validate one timezone-aware datetime without choosing a clock."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize one aware datetime as canonical UTC microsecond text."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_hash(domain: str, payload: dict[str, object]) -> str:
    """Hash one payload under the independent v5 Subject separator."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentSubjectV5:
    """Seal a current owner receipt, permanent Binding, and Reobservation v1."""

    subject_id: str
    subject_version: str
    receipt: AccountOwnerAssignmentProvenanceReceiptV5
    binding: CanonicalAccountCreationBindingV2
    reobservation: CanonicalAccountOwnershipReobservationV1
    receipt_identity_hash: str
    receipt_content_hash: str
    policy_identity_hash: str
    policy_content_hash: str
    binding_identity_hash: str
    binding_content_hash: str
    allocation_identity_hash: str
    allocation_content_hash: str
    account_claim_hash: str
    underlying_claim_hash: str
    reobservation_identity_hash: str
    reobservation_content_hash: str
    current_physical_observation_content_hash: str
    current_physical_source_content_hash: str
    current_physical_raw_observation_content_hash: str
    requested_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_OWNER
    artifact_type: str = ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_ARTIFACT_TYPE
    schema: str = ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_SCHEMA
    permission: str = ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_PERMISSION
    status: str = ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_BLOCKERS

    @validate_once_per_graph
    def __post_init__(self) -> None:
        """Validate the nested v5 graph, source seals, clocks, and inactive state."""

        self._validate_fixed_semantics()
        _token(self.subject_id, "subject_id")
        _token(self.subject_version, "subject_version")
        for name in (
            "receipt_identity_hash",
            "receipt_content_hash",
            "policy_identity_hash",
            "policy_content_hash",
            "binding_identity_hash",
            "binding_content_hash",
            "allocation_identity_hash",
            "allocation_content_hash",
            "account_claim_hash",
            "underlying_claim_hash",
            "reobservation_identity_hash",
            "reobservation_content_hash",
            "current_physical_observation_content_hash",
            "current_physical_source_content_hash",
            "current_physical_raw_observation_content_hash",
        ):
            _digest(getattr(self, name), name)

        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV5:
            raise TypeError("receipt must be an exact AccountOwnerAssignmentProvenanceReceiptV5")
        if type(self.binding) is not CanonicalAccountCreationBindingV2:
            raise TypeError("binding must be an exact CanonicalAccountCreationBindingV2")
        if type(self.reobservation) is not CanonicalAccountOwnershipReobservationV1:
            raise TypeError(
                "reobservation must be an exact CanonicalAccountOwnershipReobservationV1"
            )
        self.receipt.__post_init__()
        self.binding.__post_init__()
        self.reobservation.__post_init__()
        if self.receipt.binding != self.binding:
            raise ValueError("subject must bind the exact receipt Binding v2")
        if self.receipt.reobservation != self.reobservation:
            raise ValueError("subject must bind the exact receipt reobservation")
        if self.reobservation.binding != self.binding:
            raise ValueError("subject reobservation must bind the exact Binding v2")

        policy = self.receipt.policy
        allocation = self.binding.allocation
        current = self.reobservation.current_physical
        actual = (
            self.receipt_identity_hash,
            self.receipt_content_hash,
            self.policy_identity_hash,
            self.policy_content_hash,
            self.binding_identity_hash,
            self.binding_content_hash,
            self.allocation_identity_hash,
            self.allocation_content_hash,
            self.account_claim_hash,
            self.underlying_claim_hash,
            self.reobservation_identity_hash,
            self.reobservation_content_hash,
            self.current_physical_observation_content_hash,
            self.current_physical_source_content_hash,
            self.current_physical_raw_observation_content_hash,
        )
        expected = (
            self.receipt.identity_hash,
            self.receipt.content_hash,
            policy.identity_hash,
            policy.content_hash,
            self.binding.identity_hash,
            self.binding.content_hash,
            allocation.identity_hash,
            allocation.content_hash,
            self.binding.account_claim_hash,
            self.binding.underlying_claim_hash,
            self.reobservation.identity_hash,
            self.reobservation.content_hash,
            current.content_hash,
            current.source_content_hash,
            current.raw_observation_content_hash,
        )
        if actual != expected:
            raise ValueError("subject does not bind the complete v5 source graph")

        _aware(self.requested_at, "requested_at")
        _aware(self.valid_until, "valid_until")
        if not self.receipt.recorded_at <= self.requested_at < self.valid_until:
            raise ValueError("subject v5 clock sequence is invalid")
        if not self.receipt.is_current_at(self.requested_at):
            raise ValueError("subject v5 requires a current receipt and policy")
        if not self.reobservation.is_current_at(self.requested_at):
            raise ValueError("subject v5 requires a current reobservation")
        if not self.binding.is_knowable_at(self.requested_at):
            raise ValueError("subject v5 requires a knowable permanent Binding")
        if self.valid_until > min(
            self.receipt.valid_until,
            policy.valid_until,
            self.reobservation.valid_until,
        ):
            raise ValueError("subject v5 validity exceeds receipt, policy, or reobservation")

        expected_identity_hash = _canonical_hash(
            ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_IDENTITY_HASH_DOMAIN,
            self._identity_payload(),
        )
        self._validate_or_set_hash(
            "identity_hash",
            expected_identity_hash,
            "subject v5 identity_hash is invalid",
        )
        expected_content_hash = _canonical_hash(
            ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        self._validate_or_set_hash(
            "content_hash",
            expected_content_hash,
            "subject v5 content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject reinterpretation as authority or another artifact version."""

        for name, expected in (
            ("owner", ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_OWNER),
            ("artifact_type", ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_ARTIFACT_TYPE),
            ("schema", ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_SCHEMA),
            ("permission", ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_PERMISSION),
            ("status", ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_STATUS),
        ):
            actual = getattr(self, name)
            if type(actual) is not str:
                raise TypeError(f"{name} must be an exact string")
            if actual != expected:
                raise ValueError(f"subject v5 {name} is fixed")
        if type(self.blocker_codes) is not tuple:
            raise TypeError("blocker_codes must be an exact tuple")
        if self.blocker_codes != ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_BLOCKERS:
            raise ValueError("subject v5 blocker_codes are fixed")

    def _validate_or_set_hash(self, name: str, expected: str, message: str) -> None:
        """Compute omitted hashes and reject all supplied substitutions."""

        observed = getattr(self, name)
        if type(observed) is not str:
            raise TypeError(f"{name} must be an exact string")
        if observed == "":
            object.__setattr__(self, name, expected)
            return
        if _digest(observed, name) != expected:
            raise ValueError(message)

    @property
    def claimant(self) -> AccountOwnerAssignmentActor:
        """Expose the claimant sealed by the nested Receipt v5."""

        return self.receipt.claimant

    @property
    def policy(self) -> SingleOwnerAuthorityPolicyV1:
        """Expose the single-owner policy sealed by the nested Receipt v5."""

        return self.receipt.policy

    @property
    def activation_available(self) -> bool:
        """Remain false because a subject grants no owner or execution authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a subject is inactive evidence only."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the subject had been requested by the supplied cutoff."""

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return self.requested_at <= cutoff

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether the complete subject and re-observation remain current."""

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return (
            self.requested_at <= cutoff < self.valid_until
            and self.binding.is_knowable_at(cutoff)
            and self.receipt.is_current_at(cutoff)
            and self.reobservation.is_current_at(cutoff)
        )

    def _identity_payload(self) -> dict[str, object]:
        """Return stable identity fields bound to policy, Binding, and re-observation."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "policy_identity_hash": self.policy_identity_hash,
            "receipt_identity_hash": self.receipt_identity_hash,
            "binding_identity_hash": self.binding_identity_hash,
            "reobservation_identity_hash": self.reobservation_identity_hash,
        }

    def _content_payload(self) -> dict[str, object]:
        """Return every nested source, seal, clock, and inactive-state fact."""

        return {
            **self._identity_payload(),
            "receipt": self.receipt.to_payload(),
            "binding": self.binding.to_payload(),
            "reobservation": self.reobservation.to_payload(),
            "receipt_identity_hash": self.receipt_identity_hash,
            "receipt_content_hash": self.receipt_content_hash,
            "policy_identity_hash": self.policy_identity_hash,
            "policy_content_hash": self.policy_content_hash,
            "binding_identity_hash": self.binding_identity_hash,
            "binding_content_hash": self.binding_content_hash,
            "allocation_identity_hash": self.allocation_identity_hash,
            "allocation_content_hash": self.allocation_content_hash,
            "account_claim_hash": self.account_claim_hash,
            "underlying_claim_hash": self.underlying_claim_hash,
            "reobservation_identity_hash": self.reobservation_identity_hash,
            "reobservation_content_hash": self.reobservation_content_hash,
            "current_physical_observation_content_hash": (
                self.current_physical_observation_content_hash
            ),
            "current_physical_source_content_hash": self.current_physical_source_content_hash,
            "current_physical_raw_observation_content_hash": (
                self.current_physical_raw_observation_content_hash
            ),
            "requested_at": _utc_text(self.requested_at),
            "valid_until": _utc_text(self.valid_until),
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    @validation_graph_operation
    def to_payload(self) -> dict[str, object]:
        """Return and revalidate the complete inactive v5 Subject payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_subject_v5_root(
    subject: AccountOwnerAssignmentSubjectV5,
) -> None:
    """Validate one immutable Subject v5 root value."""

    if type(subject) is not AccountOwnerAssignmentSubjectV5:
        raise TypeError("subject must be an exact AccountOwnerAssignmentSubjectV5")
    subject.__post_init__()


__all__ = [
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_CONTENT_HASH_DOMAIN",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_IDENTITY_HASH_DOMAIN",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V5_STATUS",
    "AccountOwnerAssignmentSubjectV5",
    "validate_account_owner_assignment_subject_v5_root",
]
