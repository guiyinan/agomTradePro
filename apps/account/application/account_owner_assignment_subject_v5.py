"""Application contracts for durable inactive Account owner Subject V5 evidence."""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
    validate_account_owner_assignment_subject_v5_root,
)
from core.exceptions import DataValidationError, DuplicateResourceError, ResourceNotFoundError

_RECORD_SEAL_DOMAIN = "account-owner-assignment-subject.v5/record"
_LEDGER_SEAL_DOMAIN = "account-owner-assignment-subject.v5/ledger"


class AccountOwnerAssignmentSubjectV5Conflict(DuplicateResourceError):
    """The immutable Subject V5 first winner differs from the requested value."""


class AccountOwnerAssignmentSubjectV5Corruption(DataValidationError):
    """A repository or current reader substituted invalid Subject V5 evidence."""


class AccountOwnerAssignmentSubjectV5Unavailable(ResourceNotFoundError):
    """The Subject V5 store or an exact durable parent is unavailable."""


def _token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _digest(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class PersistedAccountOwnerAssignmentSubjectV5:
    """Wrap one exact immutable Subject V5 and its durable seals."""

    subject: AccountOwnerAssignmentSubjectV5
    record_seal: str = ""
    ledger_seal: str = ""

    def __post_init__(self) -> None:
        """Revalidate the subject graph and compute or verify both seals."""

        if type(self.subject) is not AccountOwnerAssignmentSubjectV5:
            raise TypeError("subject must be an exact AccountOwnerAssignmentSubjectV5")
        self.subject.__post_init__()
        expected_record = _canonical_hash(_RECORD_SEAL_DOMAIN, self.subject.to_payload())
        expected_ledger = _canonical_hash(
            _LEDGER_SEAL_DOMAIN,
            {
                "subject_identity_hash": self.subject.identity_hash,
                "subject_content_hash": self.subject.content_hash,
                "record_seal": expected_record,
                "receipt_content_hash": self.subject.receipt.content_hash,
                "binding_content_hash": self.subject.binding.content_hash,
                "reobservation_content_hash": self.subject.reobservation.content_hash,
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
                raise ValueError(f"Subject V5 {field_name} is invalid")


@dataclass(frozen=True, slots=True)
class RegisterAccountOwnerAssignmentSubjectV5Command:
    """Request first-winner persistence of one exact Subject V5."""

    subject: AccountOwnerAssignmentSubjectV5

    def __post_init__(self) -> None:
        """Require the exact immutable Subject V5 root type."""

        validate_account_owner_assignment_subject_v5_root(self.subject)


RecordAccountOwnerAssignmentSubjectV5Command = RegisterAccountOwnerAssignmentSubjectV5Command


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentSubjectV5Command:
    """Select one historical Subject V5 by exact identity and content hash."""

    subject_id: str
    subject_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate identity, hash, and aware point-in-time cutoff."""

        _token(self.subject_id, "subject_id")
        _token(self.subject_version, "subject_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentSubjectV5Command:
    """Select one Subject V5 only while its exact Receipt V5 remains current."""

    subject_id: str
    subject_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate exact current selectors and aware cutoff."""

        GetExactAccountOwnerAssignmentSubjectV5Command(
            self.subject_id,
            self.subject_version,
            self.expected_content_hash,
            self.as_of,
        )


class AccountOwnerAssignmentSubjectV5Repository(Protocol):
    """Persist Subject V5 first winners and expose exact historical reads."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository unit of work."""
        ...

    def now(self) -> datetime:
        """Return the repository's aware server clock."""
        ...

    def get_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentSubjectV5 | None:
        """Return the identity first winner knowable at the cutoff."""
        ...

    def append(
        self,
        record: PersistedAccountOwnerAssignmentSubjectV5,
        *,
        requested_at: datetime,
    ) -> PersistedAccountOwnerAssignmentSubjectV5:
        """Append or replay one exact Subject V5 first winner."""
        ...

    def get_exact_by_hash(
        self,
        *,
        subject_id: str,
        subject_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentSubjectV5 | None:
        """Return one exact historical Subject V5 record."""
        ...


class CurrentAccountOwnerAssignmentProvenanceReceiptV5Reader(Protocol):
    """Read one exact Receipt V5 only while its complete parent graph is current."""

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return the exact current Receipt V5 or no value."""
        ...


class RegisterAccountOwnerAssignmentSubjectV5:
    """Persist or replay one immutable Subject V5 first winner."""

    def __init__(self, repository: AccountOwnerAssignmentSubjectV5Repository) -> None:
        """Inject the immutable Subject V5 repository boundary."""

        self._repository = repository

    def execute(
        self, command: RegisterAccountOwnerAssignmentSubjectV5Command
    ) -> AccountOwnerAssignmentSubjectV5:
        """Append once and reject a different winner for the same identity."""

        if type(command) is not RegisterAccountOwnerAssignmentSubjectV5Command:
            raise TypeError("command must be an exact Subject V5 register command")
        command.__post_init__()
        expected = PersistedAccountOwnerAssignmentSubjectV5(command.subject)
        subject = expected.subject
        with self._repository.atomic():
            cutoff = _repository_clock(self._repository.now())
            winner = _record(
                self._repository.get_winner(
                    subject_id=subject.subject_id,
                    subject_version=subject.subject_version,
                    as_of=cutoff,
                )
            )
            if winner is not None:
                if winner.subject.requested_at > cutoff:
                    raise AccountOwnerAssignmentSubjectV5Corruption(
                        "repository returned a future Subject V5 winner"
                    )
                if winner != expected:
                    raise AccountOwnerAssignmentSubjectV5Conflict(
                        "Subject V5 identity has another first winner"
                    )
                return winner.subject
            if subject.requested_at > cutoff:
                raise AccountOwnerAssignmentSubjectV5Corruption(
                    "Subject V5 was requested in the future"
                )
            persisted = _record(
                self._repository.append(expected, requested_at=subject.requested_at)
            )
            if persisted != expected:
                raise AccountOwnerAssignmentSubjectV5Conflict(
                    "concurrent Subject V5 first winner differs"
                )
            return expected.subject


class GetExactAccountOwnerAssignmentSubjectV5:
    """Read exact historical Subject V5 evidence without TTL filtering."""

    def __init__(self, repository: AccountOwnerAssignmentSubjectV5Repository) -> None:
        """Inject the immutable Subject V5 repository boundary."""

        self._repository = repository

    def execute(
        self, command: GetExactAccountOwnerAssignmentSubjectV5Command
    ) -> AccountOwnerAssignmentSubjectV5 | None:
        """Return the exact subject whenever its requested clock is knowable."""

        if type(command) is not GetExactAccountOwnerAssignmentSubjectV5Command:
            raise TypeError("command must be an exact Subject V5 historical command")
        command.__post_init__()
        value = _record(
            self._repository.get_exact_by_hash(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if value is None:
            return None
        subject = value.subject
        if (
            subject.subject_id != command.subject_id
            or subject.subject_version != command.subject_version
            or subject.content_hash != command.expected_content_hash
        ):
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "historical Subject V5 selector substitution"
            )
        return subject if subject.is_knowable_at(command.as_of) else None


class GetCurrentAccountOwnerAssignmentSubjectV5:
    """Read Subject V5 only while its exact Receipt V5 graph is current."""

    def __init__(
        self,
        *,
        repository: AccountOwnerAssignmentSubjectV5Repository,
        current_receipt_reader: CurrentAccountOwnerAssignmentProvenanceReceiptV5Reader,
    ) -> None:
        """Inject historical storage and the public current Receipt V5 reader."""

        self._repository = repository
        self._current_receipt_reader = current_receipt_reader

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentSubjectV5Command
    ) -> AccountOwnerAssignmentSubjectV5 | None:
        """Return only an unexpired subject with the exact current Receipt V5."""

        if type(command) is not GetCurrentAccountOwnerAssignmentSubjectV5Command:
            raise TypeError("command must be an exact Subject V5 current command")
        command.__post_init__()
        exact = GetExactAccountOwnerAssignmentSubjectV5(self._repository).execute(
            GetExactAccountOwnerAssignmentSubjectV5Command(
                command.subject_id,
                command.subject_version,
                command.expected_content_hash,
                command.as_of,
            )
        )
        if exact is None or not exact.is_current_at(command.as_of):
            return None
        receipt = self._current_receipt_reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptV5Command(
                receipt_id=exact.receipt.receipt_id,
                receipt_version=exact.receipt.receipt_version,
                expected_content_hash=exact.receipt.content_hash,
                as_of=command.as_of,
            )
        )
        if receipt is None:
            return None
        if type(receipt) is not AccountOwnerAssignmentProvenanceReceiptV5:
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "current Receipt V5 reader substituted the result type"
            )
        try:
            receipt.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "current Receipt V5 reader returned invalid evidence"
            ) from error
        if receipt != exact.receipt:
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "current Receipt V5 reader substituted another receipt"
            )
        return exact


def _record(value: object | None) -> PersistedAccountOwnerAssignmentSubjectV5 | None:
    if value is None:
        return None
    if type(value) is not PersistedAccountOwnerAssignmentSubjectV5:
        raise AccountOwnerAssignmentSubjectV5Corruption(
            "repository substituted the Subject V5 record type"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentSubjectV5Corruption(
            "repository returned an invalid Subject V5 record"
        ) from error
    return value


def _repository_clock(value: object) -> datetime:
    try:
        return _aware(value, "repository clock")
    except ValueError as error:
        raise AccountOwnerAssignmentSubjectV5Corruption(
            "Subject V5 repository clock is invalid"
        ) from error


def _checked_digest(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be an exact string")
    _digest(value, field_name)
    return value


def _canonical_hash(domain: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AccountOwnerAssignmentSubjectV5Conflict",
    "AccountOwnerAssignmentSubjectV5Corruption",
    "AccountOwnerAssignmentSubjectV5Repository",
    "AccountOwnerAssignmentSubjectV5Unavailable",
    "CurrentAccountOwnerAssignmentProvenanceReceiptV5Reader",
    "GetCurrentAccountOwnerAssignmentSubjectV5",
    "GetCurrentAccountOwnerAssignmentSubjectV5Command",
    "GetExactAccountOwnerAssignmentSubjectV5",
    "GetExactAccountOwnerAssignmentSubjectV5Command",
    "PersistedAccountOwnerAssignmentSubjectV5",
    "RecordAccountOwnerAssignmentSubjectV5Command",
    "RegisterAccountOwnerAssignmentSubjectV5",
    "RegisterAccountOwnerAssignmentSubjectV5Command",
]
