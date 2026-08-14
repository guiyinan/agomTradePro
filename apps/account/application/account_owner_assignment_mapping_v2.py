"""Read-only consumer projection for authoritative Account mappings v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2Corruption,
    GetCurrentAccountOwnerAssignmentEvidenceV2Command,
)
from apps.account.domain.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2,
)


def _token(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class GetCurrentAuthoritativeAccountMappingV2Command:
    """Select one mapping by the physical owner row identity at a PIT cutoff."""

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
class AuthoritativeAccountMappingV2:
    """Consumer-safe identity mapping; it deliberately grants no execution right."""

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
        for field_name in (
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "evidence_id",
            "evidence_version",
        ):
            _token(getattr(self, field_name), field_name)
        if (
            type(self.underlying_unified_account_id) is not int
            or self.underlying_unified_account_id <= 0
        ):
            raise ValueError("underlying_unified_account_id must be an exact positive integer")
        if type(self.assigned_owner_user_id) is not int or self.assigned_owner_user_id <= 0:
            raise ValueError("assigned_owner_user_id must be an exact positive integer")
        if (
            type(self.evidence_content_hash) is not str
            or len(self.evidence_content_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.evidence_content_hash)
        ):
            raise ValueError("evidence_content_hash must be a lowercase SHA-256 digest")
        _aware(self.valid_until, "valid_until")
        if (
            self.assignment_state,
            self.authority_scope,
            self.evidence_status,
            self.execution_allowed,
        ) != ("authoritative", "identity_mapping_only", "inactive", False):
            raise ValueError("mapping authority boundary is invalid")


class AccountOwnerAssignmentEvidenceV2UnderlyingHeadReader(Protocol):
    """Read the final Account-owned evidence head for one underlying row."""

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> AccountOwnerAssignmentEvidenceV2 | None: ...


class CurrentAccountOwnerAssignmentEvidenceV2Reader(Protocol):
    """Revalidate dual mapping heads and all exact upstream v2 evidence."""

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV2Command
    ) -> AccountOwnerAssignmentEvidenceV2 | None: ...


class GetCurrentAuthoritativeAccountMappingV2:
    """Publish only a current, staff-approved owner mapping; never a legacy default."""

    def __init__(
        self,
        *,
        head_reader: AccountOwnerAssignmentEvidenceV2UnderlyingHeadReader,
        current_reader: CurrentAccountOwnerAssignmentEvidenceV2Reader,
    ) -> None:
        self._head_reader = head_reader
        self._current_reader = current_reader

    def execute(
        self, command: GetCurrentAuthoritativeAccountMappingV2Command
    ) -> AuthoritativeAccountMappingV2 | None:
        """Return the exact authoritative mapping or fail closed with no fallback."""

        if type(command) is not GetCurrentAuthoritativeAccountMappingV2Command:
            raise TypeError("command must be exact GetCurrentAuthoritativeAccountMappingV2Command")
        command.__post_init__()
        raw_head = self._head_reader.get_underlying_head(
            underlying_unified_account_namespace=(command.underlying_unified_account_namespace),
            underlying_unified_account_id=command.underlying_unified_account_id,
            as_of=command.as_of,
        )
        if raw_head is None:
            return None
        head = _evidence(raw_head)
        physical = head.subject.physical
        if (
            physical.underlying_unified_account_namespace
            != command.underlying_unified_account_namespace
            or physical.underlying_unified_account_id != command.underlying_unified_account_id
        ):
            raise AccountOwnerAssignmentEvidenceV2Corruption(
                "underlying mapping head selector substitution"
            )
        raw_current = self._current_reader.execute(
            GetCurrentAccountOwnerAssignmentEvidenceV2Command(
                expected_evidence=head,
                as_of=command.as_of,
            )
        )
        if raw_current is None:
            return None
        current = _evidence(raw_current)
        if current != head:
            raise AccountOwnerAssignmentEvidenceV2Corruption(
                "current mapping reader substituted the evidence head"
            )
        if current.assignment_state == "legacy_default":
            return None
        if current.assignment_state != "authoritative" or current.assigned_owner_user_id is None:
            raise AccountOwnerAssignmentEvidenceV2Corruption(
                "current mapping has no authoritative owner"
            )
        return AuthoritativeAccountMappingV2(
            account_namespace=physical.account_namespace,
            account_id=physical.account_id,
            underlying_unified_account_namespace=(physical.underlying_unified_account_namespace),
            underlying_unified_account_id=physical.underlying_unified_account_id,
            assigned_owner_user_id=current.assigned_owner_user_id,
            evidence_id=current.evidence_id,
            evidence_version=current.evidence_version,
            evidence_content_hash=current.content_hash,
            valid_until=current.valid_until,
        )


def _evidence(value: object) -> AccountOwnerAssignmentEvidenceV2:
    if type(value) is not AccountOwnerAssignmentEvidenceV2:
        raise AccountOwnerAssignmentEvidenceV2Corruption("mapping evidence type substitution")
    try:
        AccountOwnerAssignmentEvidenceV2.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV2Corruption("mapping evidence is corrupt") from error
    return value


__all__ = [
    "AccountOwnerAssignmentEvidenceV2UnderlyingHeadReader",
    "AuthoritativeAccountMappingV2",
    "CurrentAccountOwnerAssignmentEvidenceV2Reader",
    "GetCurrentAuthoritativeAccountMappingV2",
    "GetCurrentAuthoritativeAccountMappingV2Command",
]
