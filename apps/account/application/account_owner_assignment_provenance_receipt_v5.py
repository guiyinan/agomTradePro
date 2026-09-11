"""Application contracts for inactive Account owner provenance receipt v5."""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    GetCurrentCanonicalAccountOwnershipReobservationV1Command,
)
from apps.account.application.single_owner_policy_resolution import (
    CurrentSingleOwnerPoliciesReader,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
    validate_account_owner_assignment_provenance_receipt_v5_root,
    validate_account_owner_assignment_provenance_receipt_v5_successor,
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
from core.exceptions import DataValidationError, DuplicateResourceError, ResourceNotFoundError

_RECORD_SEAL_DOMAIN = "account-owner-assignment-provenance-receipt.v5/record"
_LEDGER_SEAL_DOMAIN = "account-owner-assignment-provenance-receipt.v5/ledger"


class AccountOwnerAssignmentProvenanceReceiptV5Unavailable(ResourceNotFoundError):
    """An exact V5 receipt or current parent is unavailable."""


class AccountOwnerAssignmentProvenanceReceiptV5Conflict(DuplicateResourceError):
    """An immutable V5 first winner or logical head differs."""


class AccountOwnerAssignmentProvenanceReceiptV5Corruption(DataValidationError):
    """A repository or current reader substituted invalid V5 evidence."""


def _token(value: object, field_name: str) -> None:
    """Validate one bounded canonical selector token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _digest(value: object, field_name: str) -> None:
    """Validate one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _aware(value: object, field_name: str) -> datetime:
    """Validate one timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class PersistedAccountOwnerAssignmentProvenanceReceiptV5:
    """Wrap one exact immutable V5 receipt and its ledger seals."""

    receipt: AccountOwnerAssignmentProvenanceReceiptV5
    record_seal: str = ""
    ledger_seal: str = ""

    def __post_init__(self) -> None:
        """Revalidate the exact receipt and compute or verify both seals."""

        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV5:
            raise TypeError("receipt must be an exact AccountOwnerAssignmentProvenanceReceiptV5")
        self.receipt.__post_init__()
        expected_record = _canonical_hash(_RECORD_SEAL_DOMAIN, self.receipt.to_payload())
        expected_ledger = _canonical_hash(
            _LEDGER_SEAL_DOMAIN,
            {
                "receipt_identity_hash": self.receipt.identity_hash,
                "receipt_content_hash": self.receipt.content_hash,
                "record_seal": expected_record,
                "policy_content_hash": self.receipt.policy.content_hash,
                "binding_content_hash": self.receipt.binding.content_hash,
                "reobservation_content_hash": self.receipt.reobservation.content_hash,
            },
        )
        for field_name, expected in (
            ("record_seal", expected_record),
            ("ledger_seal", expected_ledger),
        ):
            observed = getattr(self, field_name)
            if type(observed) is not str:
                raise TypeError(f"{field_name} must be an exact string")
            if observed == "":
                object.__setattr__(self, field_name, expected)
            elif _checked_digest(observed, field_name) != expected:
                raise ValueError(f"V5 receipt {field_name} is invalid")


@dataclass(frozen=True, slots=True)
class IssueAccountOwnerAssignmentProvenanceReceiptV5Command:
    """Request first-winner persistence of one exact V5 receipt."""

    receipt: AccountOwnerAssignmentProvenanceReceiptV5
    predecessor: AccountOwnerAssignmentProvenanceReceiptV5 | None = None

    def __post_init__(self) -> None:
        """Validate a V5 root or its exact Domain successor relation."""

        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV5:
            raise TypeError("receipt must be an exact V5 receipt")
        if self.predecessor is None:
            validate_account_owner_assignment_provenance_receipt_v5_root(self.receipt)
        else:
            validate_account_owner_assignment_provenance_receipt_v5_successor(
                self.predecessor, self.receipt
            )


RecordAccountOwnerAssignmentProvenanceReceiptV5Command = (
    IssueAccountOwnerAssignmentProvenanceReceiptV5Command
)


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentProvenanceReceiptV5Command:
    """Select one historical V5 receipt by exact identity and content hash."""

    receipt_id: str
    receipt_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate identity, hash, and aware point-in-time cutoff."""

        _token(self.receipt_id, "receipt_id")
        _token(self.receipt_version, "receipt_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command:
    """Select one V5 receipt only while all current parents still agree."""

    receipt_id: str
    receipt_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate exact current selectors and aware cutoff."""

        GetExactAccountOwnerAssignmentProvenanceReceiptV5Command(
            self.receipt_id,
            self.receipt_version,
            self.expected_content_hash,
            self.as_of,
        )


class AccountOwnerAssignmentProvenanceReceiptV5Repository(Protocol):
    """Persist V5 first winners and expose exact historical reads."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository unit of work."""
        ...

    def now(self) -> datetime:
        """Return the repository's aware server clock."""
        ...

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return the identity first winner knowable at the cutoff."""
        ...

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return the final logical receipt head at the cutoff."""
        ...

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV5,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5:
        """Append or replay one exact root or successor first winner."""
        ...

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return one exact historical V5 record."""
        ...


class ExactCanonicalAccountCreationBindingV2Reader(Protocol):
    """Read one exact permanent BindingV2 through its public Application port."""

    def execute(
        self, command: GetExactCanonicalAccountCreationBindingV2Command
    ) -> CanonicalAccountCreationBindingV2 | None:
        """Return the requested immutable BindingV2."""
        ...


class CurrentCanonicalAccountOwnershipReobservationV1Reader(Protocol):
    """Read one exact current ReobservationV1 through its public port."""

    def execute(
        self, command: GetCurrentCanonicalAccountOwnershipReobservationV1Command
    ) -> CanonicalAccountOwnershipReobservationV1 | None:
        """Return the requested current ReobservationV1."""
        ...


class IssueAccountOwnerAssignmentProvenanceReceiptV5:
    """Persist or replay one V5 root/successor first winner."""

    def __init__(self, repository: AccountOwnerAssignmentProvenanceReceiptV5Repository) -> None:
        """Inject the immutable receipt repository boundary."""

        self._repository = repository

    def execute(
        self, command: IssueAccountOwnerAssignmentProvenanceReceiptV5Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV5:
        """Validate Domain lineage, append once, and replay the exact winner."""

        if type(command) is not IssueAccountOwnerAssignmentProvenanceReceiptV5Command:
            raise TypeError("command must be an exact V5 issue command")
        command.__post_init__()
        expected = PersistedAccountOwnerAssignmentProvenanceReceiptV5(command.receipt)
        receipt = expected.receipt
        with self._repository.atomic():
            cutoff = _repository_clock(self._repository.now())
            winner = _record(
                self._repository.get_winner(
                    receipt_id=receipt.receipt_id,
                    receipt_version=receipt.receipt_version,
                    as_of=cutoff,
                )
            )
            if winner is not None:
                if winner.receipt.recorded_at > cutoff:
                    raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
                        "repository returned a future V5 receipt winner"
                    )
                if winner != expected:
                    raise AccountOwnerAssignmentProvenanceReceiptV5Conflict(
                        "V5 receipt identity has another first winner"
                    )
                return winner.receipt
            if receipt.recorded_at > cutoff:
                raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
                    "V5 receipt was recorded in the future"
                )
            head = _optional_record(
                self._repository.get_current_head(
                    receipt_id=receipt.receipt_id,
                    as_of=cutoff,
                )
            )
            if command.predecessor is not None and (
                head is None or head.receipt != command.predecessor
            ):
                raise AccountOwnerAssignmentProvenanceReceiptV5Conflict(
                    "V5 receipt predecessor is not the logical head"
                )
            predecessor_hash = head.receipt.content_hash if head is not None else None
            if head is None:
                validate_account_owner_assignment_provenance_receipt_v5_root(receipt)
            else:
                try:
                    validate_account_owner_assignment_provenance_receipt_v5_successor(
                        head.receipt, receipt
                    )
                except (TypeError, ValueError) as error:
                    raise AccountOwnerAssignmentProvenanceReceiptV5Conflict(
                        "V5 receipt successor does not bind the logical head"
                    ) from error
            persisted = _record(
                self._repository.append(
                    expected,
                    expected_predecessor_hash=predecessor_hash,
                    recorded_at=receipt.recorded_at,
                )
            )
            if persisted != expected:
                raise AccountOwnerAssignmentProvenanceReceiptV5Conflict(
                    "concurrent V5 receipt first winner differs"
                )
            return persisted.receipt


class GetExactAccountOwnerAssignmentProvenanceReceiptV5:
    """Read one exact historical V5 receipt without TTL filtering."""

    def __init__(self, repository: AccountOwnerAssignmentProvenanceReceiptV5Repository) -> None:
        """Inject the immutable receipt repository boundary."""

        self._repository = repository

    def execute(
        self, command: GetExactAccountOwnerAssignmentProvenanceReceiptV5Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return an exact record whenever its ``recorded_at`` is knowable."""

        if type(command) is not GetExactAccountOwnerAssignmentProvenanceReceiptV5Command:
            raise TypeError("command must be an exact V5 historical command")
        command.__post_init__()
        value = _record(
            self._repository.get_exact_by_hash(
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if value is None:
            return None
        receipt = value.receipt
        if (
            receipt.receipt_id != command.receipt_id
            or receipt.receipt_version != command.receipt_version
            or receipt.content_hash != command.expected_content_hash
        ):
            raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "historical V5 receipt selector substitution"
            )
        return receipt if receipt.is_knowable_at(command.as_of) else None


class GetCurrentAccountOwnerAssignmentProvenanceReceiptV5:
    """Read V5 only after policy, Binding, re-observation, and head rechecks."""

    def __init__(
        self,
        *,
        repository: AccountOwnerAssignmentProvenanceReceiptV5Repository,
        binding_reader: ExactCanonicalAccountCreationBindingV2Reader,
        policy_reader: CurrentSingleOwnerPoliciesReader,
        reobservation_reader: CurrentCanonicalAccountOwnershipReobservationV1Reader,
    ) -> None:
        """Inject public readers for every current source and the receipt store."""

        self._repository = repository
        self._binding_reader = binding_reader
        self._policy_reader = policy_reader
        self._reobservation_reader = reobservation_reader

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return only the exact current logical V5 receipt."""

        if type(command) is not GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command:
            raise TypeError("command must be an exact V5 current command")
        command.__post_init__()
        value = GetExactAccountOwnerAssignmentProvenanceReceiptV5(self._repository).execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptV5Command(
                command.receipt_id,
                command.receipt_version,
                command.expected_content_hash,
                command.as_of,
            )
        )
        if value is None or not value.is_current_at(command.as_of):
            return None
        if not self._check_binding(value, command.as_of):
            return None
        if not self._check_policy(value, command.as_of):
            return None
        if not self._check_reobservation(value, command.as_of):
            return None
        head = _optional_record(
            self._repository.get_current_head(
                receipt_id=value.receipt_id,
                as_of=command.as_of,
            )
        )
        if head is None or head.receipt != value:
            return None
        return value

    def _check_binding(
        self, receipt: AccountOwnerAssignmentProvenanceReceiptV5, as_of: datetime
    ) -> bool:
        """Re-read and compare the exact permanent BindingV2."""

        value = self._binding_reader.execute(
            GetExactCanonicalAccountCreationBindingV2Command(
                binding_id=receipt.binding.binding_id,
                binding_version=receipt.binding.binding_version,
                expected_content_hash=receipt.binding.content_hash,
                as_of=as_of,
            )
        )
        if value is None:
            return False
        if type(value) is not CanonicalAccountCreationBindingV2 or value != receipt.binding:
            raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "V5 BindingV2 selector substitution"
            )
        return True

    def _check_policy(
        self, receipt: AccountOwnerAssignmentProvenanceReceiptV5, as_of: datetime
    ) -> bool:
        """Re-read the complete current policy scope and compare exact policy seals."""

        policies = self._policy_reader.get_current_for_scope(
            account_namespace=receipt.account_namespace,
            account_id=receipt.account_id,
            as_of=as_of,
        )
        if type(policies) is not tuple:
            raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "current V5 policy reader returned a substituted collection"
            )
        checked = tuple(policies)
        if len(checked) != 1:
            return False
        policy = checked[0]
        if type(policy) is not SingleOwnerAuthorityPolicyV1:
            raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "current V5 policy reader returned a substituted type"
            )
        policy.__post_init__()
        if policy != receipt.policy or not policy.is_current_at(as_of):
            return False
        return True

    def _check_reobservation(
        self, receipt: AccountOwnerAssignmentProvenanceReceiptV5, as_of: datetime
    ) -> bool:
        """Re-read and compare the exact current ReobservationV1."""

        value = self._reobservation_reader.execute(
            GetCurrentCanonicalAccountOwnershipReobservationV1Command(
                observation_id=receipt.reobservation.observation_id,
                observation_version=receipt.reobservation.observation_version,
                expected_content_hash=receipt.reobservation.content_hash,
                as_of=as_of,
            )
        )
        if value is None:
            return False
        if type(value) is not CanonicalAccountOwnershipReobservationV1:
            raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "current V5 ReobservationV1 type substitution"
            )
        if value != receipt.reobservation:
            raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "current V5 ReobservationV1 selector substitution"
            )
        return True


def _record(value: object | None) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
    """Require one exact persisted envelope or preserve an absent result."""

    if value is None:
        return None
    if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV5:
        raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
            "V5 receipt repository returned a substituted record type"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
            "V5 receipt repository returned an invalid record"
        ) from error
    return value


def _optional_record(
    value: PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
    """Validate a reader record while keeping ``None`` as unavailable."""

    return _record(value)


def _repository_clock(value: object) -> datetime:
    """Validate and classify the repository clock."""

    try:
        return _aware(value, "repository clock")
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV5Corruption(
            "V5 repository clock is invalid"
        ) from error


def _checked_digest(value: object, field_name: str) -> str:
    """Validate and return one persisted digest."""

    if type(value) is not str:
        raise ValueError(f"{field_name} must be an exact string")
    _digest(value, field_name)
    return value


def _canonical_hash(domain: str, payload: dict[str, object]) -> str:
    """Hash one canonical payload under a versioned application seal domain."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV5Conflict",
    "AccountOwnerAssignmentProvenanceReceiptV5Corruption",
    "AccountOwnerAssignmentProvenanceReceiptV5Repository",
    "AccountOwnerAssignmentProvenanceReceiptV5Unavailable",
    "CurrentCanonicalAccountOwnershipReobservationV1Reader",
    "ExactCanonicalAccountCreationBindingV2Reader",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptV5",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command",
    "GetExactAccountOwnerAssignmentProvenanceReceiptV5",
    "GetExactAccountOwnerAssignmentProvenanceReceiptV5Command",
    "IssueAccountOwnerAssignmentProvenanceReceiptV5",
    "IssueAccountOwnerAssignmentProvenanceReceiptV5Command",
    "PersistedAccountOwnerAssignmentProvenanceReceiptV5",
    "RecordAccountOwnerAssignmentProvenanceReceiptV5Command",
]
