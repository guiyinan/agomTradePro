"""Read-only facade for authoritative Account identity mappings v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
)
from apps.account.application.account_owner_assignment_evidence_v3 import (
    GetCurrentAccountOwnerAssignmentEvidenceV3Command,
)
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
)


def _token(value: object, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _aware(value: object, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class GetCurrentAuthoritativeAccountMappingV3Command:
    """Select one mapping by its underlying physical-row identity at a PIT cutoff."""

    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    as_of: datetime

    def __post_init__(self) -> None:
        _token(
            self.underlying_unified_account_namespace,
            "underlying_unified_account_namespace",
        )
        if (
            type(self.underlying_unified_account_id) is not int
            or self.underlying_unified_account_id <= 0
        ):
            raise ValueError("underlying_unified_account_id must be an exact positive integer")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class AuthoritativeAccountMappingV3:
    """Consumer-safe identity mapping that deliberately grants no execution right."""

    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    assigned_owner_user_id: int
    evidence_id: str
    evidence_version: str
    evidence_content_hash: str
    valid_until: datetime
    assignment_state: str = "authoritative"
    authority_scope: str = "identity_mapping_only"
    evidence_status: str = "inactive"
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for name in (
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "evidence_id",
            "evidence_version",
        ):
            _token(getattr(self, name), name)
        if (
            type(self.underlying_unified_account_id) is not int
            or self.underlying_unified_account_id <= 0
        ):
            raise ValueError("underlying_unified_account_id must be an exact positive integer")
        if type(self.assigned_owner_user_id) is not int or self.assigned_owner_user_id <= 0:
            raise ValueError("assigned_owner_user_id must be an exact positive integer")
        _digest(self.evidence_content_hash, "evidence_content_hash")
        _aware(self.valid_until, "valid_until")
        if (
            self.assignment_state,
            self.authority_scope,
            self.evidence_status,
            self.execution_allowed,
        ) != ("authoritative", "identity_mapping_only", "inactive", False):
            raise ValueError("mapping authority boundary is invalid")


class AccountOwnerAssignmentEvidenceV3UnderlyingHeadReader(Protocol):
    """Read the final Account-owned Evidence-v3 head for one underlying row."""

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV3 | None: ...


class CurrentAccountOwnerAssignmentEvidenceV3Reader(Protocol):
    """Revalidate both mapping heads and every exact-current v3 upstream artifact."""

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV3Command
    ) -> AccountOwnerAssignmentEvidenceV3 | None: ...


class GetCurrentAuthoritativeAccountMappingV3:
    """Publish only a current staff-approved v3 owner mapping, without fallback."""

    def __init__(
        self,
        *,
        head_reader: AccountOwnerAssignmentEvidenceV3UnderlyingHeadReader,
        current_reader: CurrentAccountOwnerAssignmentEvidenceV3Reader,
    ) -> None:
        self._head_reader = head_reader
        self._current_reader = current_reader

    def execute(
        self, command: GetCurrentAuthoritativeAccountMappingV3Command
    ) -> AuthoritativeAccountMappingV3 | None:
        """Return one exact authoritative identity mapping or fail closed."""

        if type(command) is not GetCurrentAuthoritativeAccountMappingV3Command:
            raise TypeError("command must be exact GetCurrentAuthoritativeAccountMappingV3Command")
        command.__post_init__()
        raw_head = self._head_reader.get_underlying_head(
            underlying_unified_account_namespace=command.underlying_unified_account_namespace,
            underlying_unified_account_id=command.underlying_unified_account_id,
            as_of=command.as_of,
        )
        if raw_head is None:
            return None
        head = _evidence(raw_head)
        binding = head.subject.binding
        if (
            binding.underlying_unified_account_namespace_claim
            != command.underlying_unified_account_namespace
            or binding.underlying_unified_account_id_claim != command.underlying_unified_account_id
        ):
            raise AccountOwnerAssignmentCorruption(
                "underlying Evidence-v3 head selector substitution"
            )
        raw_current = self._current_reader.execute(
            GetCurrentAccountOwnerAssignmentEvidenceV3Command(
                evidence_id=head.evidence_id,
                evidence_version=head.evidence_version,
                expected_content_hash=head.content_hash,
                as_of=command.as_of,
            )
        )
        if raw_current is None:
            return None
        current = _evidence(raw_current)
        if current != head:
            raise AccountOwnerAssignmentCorruption(
                "current Evidence-v3 reader substituted the mapping head"
            )
        if current.assignment_state != "authoritative":
            return None
        return AuthoritativeAccountMappingV3(
            account_namespace=binding.account_namespace_claim,
            account_id=binding.account_id_claim,
            underlying_unified_account_namespace=(
                binding.underlying_unified_account_namespace_claim
            ),
            underlying_unified_account_id=binding.underlying_unified_account_id_claim,
            assigned_owner_user_id=current.assigned_owner_user_id,
            evidence_id=current.evidence_id,
            evidence_version=current.evidence_version,
            evidence_content_hash=current.content_hash,
            valid_until=current.valid_until,
        )


def _evidence(value: object) -> AccountOwnerAssignmentEvidenceV3:
    if type(value) is not AccountOwnerAssignmentEvidenceV3:
        raise AccountOwnerAssignmentCorruption("mapping Evidence-v3 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("mapping Evidence-v3 is corrupt") from error
    return value


__all__ = [
    "AccountOwnerAssignmentEvidenceV3UnderlyingHeadReader",
    "AuthoritativeAccountMappingV3",
    "CurrentAccountOwnerAssignmentEvidenceV3Reader",
    "GetCurrentAuthoritativeAccountMappingV3",
    "GetCurrentAuthoritativeAccountMappingV3Command",
]
