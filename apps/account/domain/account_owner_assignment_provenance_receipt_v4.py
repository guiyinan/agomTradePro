"""Source-bound single-owner provenance receipt built on canonical Account evidence.

The receipt records an already observed owner policy together with the exact
canonical Binding v2 graph.  It remains evidence only: this pure Domain type
does not authenticate a user, read a repository, or grant execution authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)

ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_OWNER = "account"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ARTIFACT_TYPE = (
    "account_owner_assignment_provenance_receipt_v4"
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_SCHEMA = (
    "account-owner-assignment-provenance-receipt.v4"
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_PERMISSION = "claim_evidence_only"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_STATUS = "inactive"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_PROVENANCE_KIND = "creation"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ASSIGNMENT_STATE = "claimed_owner"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_BLOCKERS = (
    "account_owner_assignment_provenance_receipt_v4_not_integrated",
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_IDENTITY_HASH_DOMAIN = (
    "account-owner-assignment-provenance-receipt.v4/identity"
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_CONTENT_HASH_DOMAIN = (
    "account-owner-assignment-provenance-receipt.v4/content"
)


def _token(value: object, name: str) -> str:
    """Validate one bounded canonical identifier."""

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
    """Validate one exact positive integer while rejecting bool."""

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
    """Validate one timezone-aware datetime without inventing a clock value."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize an aware datetime as canonical UTC microsecond text."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_hash(domain: str, payload: dict[str, object]) -> str:
    """Hash one canonical payload under a versioned Domain separator."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentProvenanceReceiptV4:
    """Seal a staff claimant against one current single-owner policy and graph.

    A real staff owner may occupy the claimant role in single-owner mode.  The
    nested policy and every upstream hash are source facts; their presence
    does not turn this receipt into authentication or execution authority.
    """

    receipt_id: str
    receipt_version: str
    policy: SingleOwnerAuthorityPolicyV1
    policy_identity_hash: str
    policy_content_hash: str
    binding: CanonicalAccountCreationBindingV2
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    allocation_identity_hash: str
    allocation_content_hash: str
    creation_root_identity_hash: str
    creation_root_content_hash: str
    binding_identity_hash: str
    binding_content_hash: str
    account_claim_hash: str
    underlying_claim_hash: str
    physical_observation_content_hash: str
    physical_source_content_hash: str
    physical_raw_observation_content_hash: str
    assigned_owner_user_id: int
    claimant: AccountOwnerAssignmentActor
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_OWNER
    artifact_type: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ARTIFACT_TYPE
    schema: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_SCHEMA
    provenance_kind: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_PROVENANCE_KIND
    assignment_state: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ASSIGNMENT_STATE
    permission: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_PERMISSION
    status: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_BLOCKERS

    def __post_init__(self) -> None:
        """Validate the policy, exact Binding v2 graph, clocks, and hash seals."""

        self._validate_fixed_semantics()
        for name in (
            "receipt_id",
            "receipt_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
        ):
            _token(getattr(self, name), name)
        _positive_integer(self.underlying_unified_account_id, "underlying_unified_account_id")
        _positive_integer(self.assigned_owner_user_id, "assigned_owner_user_id")
        for name in (
            "allocation_identity_hash",
            "allocation_content_hash",
            "creation_root_identity_hash",
            "creation_root_content_hash",
            "binding_identity_hash",
            "binding_content_hash",
            "account_claim_hash",
            "underlying_claim_hash",
            "physical_observation_content_hash",
            "physical_source_content_hash",
            "physical_raw_observation_content_hash",
            "policy_identity_hash",
            "policy_content_hash",
        ):
            _digest(getattr(self, name), name)

        if type(self.policy) is not SingleOwnerAuthorityPolicyV1:
            raise TypeError("policy must be an exact SingleOwnerAuthorityPolicyV1")
        self.policy.__post_init__()
        if self.policy_identity_hash != self.policy.identity_hash:
            raise ValueError("policy identity hash does not match exact policy")
        if self.policy_content_hash != self.policy.content_hash:
            raise ValueError("policy content hash does not match exact policy")

        if type(self.binding) is not CanonicalAccountCreationBindingV2:
            raise TypeError("binding must be an exact CanonicalAccountCreationBindingV2")
        self.binding.__post_init__()
        allocation = self.binding.allocation
        physical = self.binding.creation_root.physical_observation
        if (
            self.policy.account_namespace != self.binding.account_namespace_claim
            or self.policy.account_id != self.binding.account_id_claim
        ):
            raise ValueError("policy account scope does not match exact Binding v2")

        if type(self.claimant) is not AccountOwnerAssignmentActor:
            raise TypeError("claimant must be an exact AccountOwnerAssignmentActor")
        self.claimant.__post_init__()
        if self.claimant.role != "account_owner_claimant":
            raise ValueError("single-owner receipt requires claimant role")
        if not (
            self.assigned_owner_user_id
            == self.claimant.user_id
            == self.policy.owner_user_id
            == allocation.requested_row_user_id
            == physical.row_user_id
        ):
            raise ValueError(
                "claimant, policy owner, allocation requester, and physical row user must match"
            )

        for name in ("issued_at", "recorded_at", "valid_until"):
            _aware(getattr(self, name), name)
        if not self.binding.recorded_at <= self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("v4 receipt clock sequence is invalid")
        if not self.policy.is_current_at(self.recorded_at):
            raise ValueError("policy must be observed and current when receipt is recorded")
        if not self.binding.creation_root.is_knowable_at(self.recorded_at):
            raise ValueError("creation root must be current when receipt is recorded")
        if self.valid_until > min(
            allocation.valid_until,
            self.binding.creation_root.valid_until,
            physical.valid_until,
            self.policy.valid_until,
        ):
            raise ValueError("receipt cannot outlive policy or upstream evidence")
        if self.supersedes_content_hash is not None:
            _digest(self.supersedes_content_hash, "supersedes_content_hash")

        validate_account_owner_assignment_provenance_receipt_v4_binding(self, self.binding)
        expected_identity_hash = _canonical_hash(
            ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_IDENTITY_HASH_DOMAIN,
            self._identity_payload(),
        )
        self._validate_or_set_hash(
            "identity_hash",
            expected_identity_hash,
            "v4 receipt identity_hash is invalid",
        )
        expected_content_hash = _canonical_hash(
            ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        self._validate_or_set_hash(
            "content_hash",
            expected_content_hash,
            "v4 receipt content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject reinterpretation as another artifact or authority state."""

        for name, expected in (
            ("owner", ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_OWNER),
            ("artifact_type", ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ARTIFACT_TYPE),
            ("schema", ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_SCHEMA),
            (
                "provenance_kind",
                ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_PROVENANCE_KIND,
            ),
            (
                "assignment_state",
                ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ASSIGNMENT_STATE,
            ),
            ("permission", ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_PERMISSION),
            ("status", ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_STATUS),
        ):
            actual = getattr(self, name)
            if type(actual) is not str:
                raise TypeError(f"{name} must be an exact string")
            if actual != expected:
                raise ValueError(f"v4 receipt {name} is fixed")
        if type(self.blocker_codes) is not tuple:
            raise TypeError("blocker_codes must be an exact tuple")
        if self.blocker_codes != ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_BLOCKERS:
            raise ValueError("v4 receipt blocker_codes are fixed")

    def _validate_or_set_hash(self, name: str, expected: str, message: str) -> None:
        """Compute an omitted seal and reject every supplied mutation."""

        observed = getattr(self, name)
        if type(observed) is not str:
            raise TypeError(f"{name} must be an exact string")
        if observed == "":
            object.__setattr__(self, name, expected)
            return
        if _digest(observed, name) != expected:
            raise ValueError(message)

    @property
    def activation_available(self) -> bool:
        """Remain false because provenance evidence is not assignment authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this receipt cannot authorize execution."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this receipt had been recorded by the supplied cutoff."""

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return self.recorded_at <= cutoff

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this receipt and its policy remain current at a cutoff."""

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return (
            self.recorded_at <= cutoff < self.valid_until
            and self.policy.is_current_at(cutoff)
            and self.binding.creation_root.is_knowable_at(cutoff)
        )

    def _identity_payload(self) -> dict[str, object]:
        """Return stable v4 receipt identity fields."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "receipt_id": self.receipt_id,
            "receipt_version": self.receipt_version,
            "policy_identity_hash": self.policy_identity_hash,
        }

    def _content_payload(self) -> dict[str, object]:
        """Return every policy, upstream, claimant, clock, and provenance fact."""

        return {
            **self._identity_payload(),
            "policy": self.policy.to_payload(),
            "policy_identity_hash": self.policy_identity_hash,
            "policy_content_hash": self.policy_content_hash,
            "binding": self.binding.to_payload(),
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": self.underlying_unified_account_namespace,
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "allocation_identity_hash": self.allocation_identity_hash,
            "allocation_content_hash": self.allocation_content_hash,
            "creation_root_identity_hash": self.creation_root_identity_hash,
            "creation_root_content_hash": self.creation_root_content_hash,
            "binding_identity_hash": self.binding_identity_hash,
            "binding_content_hash": self.binding_content_hash,
            "account_claim_hash": self.account_claim_hash,
            "underlying_claim_hash": self.underlying_claim_hash,
            "physical_observation_content_hash": self.physical_observation_content_hash,
            "physical_source_content_hash": self.physical_source_content_hash,
            "physical_raw_observation_content_hash": self.physical_raw_observation_content_hash,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "claimant": self.claimant.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "provenance_kind": self.provenance_kind,
            "assignment_state": self.assignment_state,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical v4 receipt payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_provenance_receipt_v4_binding(
    receipt: AccountOwnerAssignmentProvenanceReceiptV4,
    binding: CanonicalAccountCreationBindingV2,
) -> None:
    """Require one v4 receipt to bind one exact Binding v2 and policy scope."""

    if type(receipt) is not AccountOwnerAssignmentProvenanceReceiptV4:
        raise TypeError("receipt must be an exact v4 receipt")
    if type(binding) is not CanonicalAccountCreationBindingV2:
        raise TypeError("binding must be an exact CanonicalAccountCreationBindingV2")
    binding.__post_init__()
    if type(receipt.policy) is not SingleOwnerAuthorityPolicyV1:
        raise TypeError("policy must be an exact SingleOwnerAuthorityPolicyV1")
    receipt.policy.__post_init__()
    _digest(receipt.policy_identity_hash, "policy_identity_hash")
    _digest(receipt.policy_content_hash, "policy_content_hash")
    if (
        receipt.policy_identity_hash != receipt.policy.identity_hash
        or receipt.policy_content_hash != receipt.policy.content_hash
    ):
        raise ValueError("receipt does not bind the exact single-owner policy hashes")
    if (
        receipt.policy.account_namespace != binding.account_namespace_claim
        or receipt.policy.account_id != binding.account_id_claim
    ):
        raise ValueError("policy account scope does not match exact Binding v2")
    actual = (
        receipt.binding,
        receipt.account_namespace,
        receipt.account_id,
        receipt.underlying_unified_account_namespace,
        receipt.underlying_unified_account_id,
        receipt.allocation_identity_hash,
        receipt.allocation_content_hash,
        receipt.creation_root_identity_hash,
        receipt.creation_root_content_hash,
        receipt.binding_identity_hash,
        receipt.binding_content_hash,
        receipt.account_claim_hash,
        receipt.underlying_claim_hash,
        receipt.physical_observation_content_hash,
        receipt.physical_source_content_hash,
        receipt.physical_raw_observation_content_hash,
    )
    physical = binding.creation_root.physical_observation
    expected = (
        binding,
        binding.account_namespace_claim,
        binding.account_id_claim,
        binding.underlying_unified_account_namespace_claim,
        binding.underlying_unified_account_id_claim,
        binding.allocation.identity_hash,
        binding.allocation.content_hash,
        binding.creation_root.identity_hash,
        binding.creation_root.content_hash,
        binding.identity_hash,
        binding.content_hash,
        binding.account_claim_hash,
        binding.underlying_claim_hash,
        physical.content_hash,
        physical.source_content_hash,
        physical.raw_observation_content_hash,
    )
    if actual != expected:
        raise ValueError("receipt does not bind the exact canonical Binding v2")


def validate_account_owner_assignment_provenance_receipt_v4_root(
    root: AccountOwnerAssignmentProvenanceReceiptV4,
) -> None:
    """Require the first v4 receipt to have no predecessor."""

    if type(root) is not AccountOwnerAssignmentProvenanceReceiptV4:
        raise TypeError("root must be an exact v4 receipt")
    root.__post_init__()
    if root.supersedes_content_hash is not None:
        raise ValueError("root predecessor must be absent")


def validate_account_owner_assignment_provenance_receipt_v4_successor(
    previous: AccountOwnerAssignmentProvenanceReceiptV4,
    successor: AccountOwnerAssignmentProvenanceReceiptV4,
) -> None:
    """Validate adjacent v4 receipts for one policy and immutable evidence graph."""

    if (
        type(previous) is not AccountOwnerAssignmentProvenanceReceiptV4
        or type(successor) is not AccountOwnerAssignmentProvenanceReceiptV4
    ):
        raise TypeError("receipt versions must be exact v4 values")
    previous.__post_init__()
    successor.__post_init__()
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind exact predecessor")
    for name in (
        "receipt_id",
        "policy",
        "policy_identity_hash",
        "policy_content_hash",
        "binding",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "assigned_owner_user_id",
        "claimant",
    ):
        if getattr(successor, name) != getattr(previous, name):
            raise ValueError(f"successor changed {name}")
    if successor.receipt_version == previous.receipt_version:
        raise ValueError("successor receipt_version must advance")
    if successor.issued_at <= previous.issued_at or successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor clocks must advance")


def resolve_account_owner_assignment_provenance_receipt_v4_head(
    chain: tuple[AccountOwnerAssignmentProvenanceReceiptV4, ...], *, as_of: datetime
) -> AccountOwnerAssignmentProvenanceReceiptV4 | None:
    """Return only the final visible current head; expired heads never fall back."""

    cutoff = _aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    if chain:
        validate_account_owner_assignment_provenance_receipt_v4_root(chain[0])
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_account_owner_assignment_provenance_receipt_v4_successor(previous, successor)
    visible = tuple(item for item in chain if item.recorded_at <= cutoff)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_current_at(cutoff) else None


__all__ = [
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ASSIGNMENT_STATE",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_CONTENT_HASH_DOMAIN",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_IDENTITY_HASH_DOMAIN",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_PROVENANCE_KIND",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_STATUS",
    "AccountOwnerAssignmentProvenanceReceiptV4",
    "resolve_account_owner_assignment_provenance_receipt_v4_head",
    "validate_account_owner_assignment_provenance_receipt_v4_binding",
    "validate_account_owner_assignment_provenance_receipt_v4_root",
    "validate_account_owner_assignment_provenance_receipt_v4_successor",
]
