"""Exact-current request adapter for canonical Account actor authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)


class CurrentActorAuthoritySourceReader(Protocol):
    """Read one exact-current canonical actor-authority source."""

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3 | None:
        """Return the selected current source, or ``None`` when unavailable."""


@dataclass(frozen=True, slots=True)
class CanonicalAccountActorAuthorityRequestReader:
    """Project one canonical actor source into the request authority contract.

    The source identity is closed at construction time.  Each request still
    supplies its principal, user, authentication-context content hash and PIT
    cutoff, which are checked against the returned immutable source.
    """

    current_reader: CurrentActorAuthoritySourceReader
    source_id: str
    source_version: str
    expected_content_hash: str

    def __post_init__(self) -> None:
        """Reject an invalid reader or non-canonical source selector."""

        if not callable(getattr(self.current_reader, "execute", None)):
            raise TypeError("current_reader must expose execute")
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.expected_content_hash, "expected_content_hash")

    def get_exact_current(
        self,
        *,
        principal_id: str,
        user_id: int,
        expected_authentication_context_hash: str,
        as_of: datetime,
    ) -> CurrentAccountActorAuthorityV3 | None:
        """Return the exact current request authority without any fallback."""

        _token(principal_id, "principal_id")
        if type(user_id) is not int or user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        _digest(
            expected_authentication_context_hash,
            "expected_authentication_context_hash",
        )
        _aware(as_of, "as_of")

        source = self.current_reader.execute(
            GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command(
                source_id=self.source_id,
                source_version=self.source_version,
                expected_content_hash=self.expected_content_hash,
                as_of=as_of,
            )
        )
        if source is None:
            return None
        if type(source) is not AccountOwnerAssignmentActorAuthoritySourceV3:
            raise AccountOwnerAssignmentCorruption(
                "actor authority source reader returned an invalid type"
            )
        try:
            source.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "actor authority source reader returned corrupt evidence"
            ) from error
        if (
            source.source_id,
            source.source_version,
            source.content_hash,
        ) != (self.source_id, self.source_version, self.expected_content_hash):
            raise AccountOwnerAssignmentCorruption("actor authority source selector substitution")
        if (
            source.principal_id,
            source.user_id,
            source.authentication_context_content_hash,
        ) != (principal_id, user_id, expected_authentication_context_hash):
            raise AccountOwnerAssignmentCorruption("actor authority request selector substitution")
        if source.recorded_at > as_of:
            raise AccountOwnerAssignmentCorruption(
                "actor authority source is recorded after the request cutoff"
            )
        if not source.is_temporally_current_at(as_of):
            return None
        try:
            return CurrentAccountActorAuthorityV3(
                principal_id=source.principal_id,
                user_id=source.user_id,
                authentication_context_hash=source.authentication_context_content_hash,
                actor_id=source.actor_id,
                is_authenticated=source.is_authenticated,
                is_active=source.is_active,
                is_staff=source.is_staff,
                is_superuser=source.is_superuser,
                rbac_role=source.rbac_role,
                source_id=source.source_id,
                source_version=source.source_version,
                source_content_hash=source.content_hash,
                recorded_at=source.recorded_at,
                valid_until=source.valid_until,
            )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "actor authority request projection is corrupt"
            ) from error


def _token(value: object, name: str) -> None:
    """Validate one bounded canonical token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    """Validate one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> None:
    """Validate one timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


__all__ = [
    "CanonicalAccountActorAuthorityRequestReader",
    "CurrentActorAuthoritySourceReader",
]
