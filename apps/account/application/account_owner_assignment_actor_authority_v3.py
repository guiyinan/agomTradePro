"""Request-bound, repeatedly revalidated actor authority for assignment v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
)


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


@dataclass(frozen=True, slots=True)
class AuthenticatedAccountPrincipalV3:
    """Bind a request principal to non-secret, owner-issued auth evidence.

    The context digest must identify sealed authentication evidence. It must not
    be derived directly from a session key, cookie, token, CSRF value, or
    password hash.
    """

    principal_id: str
    user_id: int
    authentication_context_hash: str
    authenticated_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        _token(self.principal_id, "principal_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("principal user_id must be an exact positive integer")
        _digest(self.authentication_context_hash, "authentication_context_hash")
        authenticated_at = _aware(self.authenticated_at, "authenticated_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if authenticated_at >= valid_until:
            raise ValueError("principal authentication clock is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether the exact request authentication remains current."""

        cutoff = _aware(as_of, "as_of")
        return self.authenticated_at <= cutoff < self.valid_until


@dataclass(frozen=True, slots=True)
class CurrentAccountActorAuthorityV3:
    """Exact-current Account-owned user and RBAC authority projection."""

    principal_id: str
    user_id: int
    authentication_context_hash: str
    actor_id: str
    is_authenticated: bool
    is_active: bool
    is_staff: bool
    is_superuser: bool
    rbac_role: str
    source_id: str
    source_version: str
    source_content_hash: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name in (
            "principal_id",
            "actor_id",
            "rbac_role",
            "source_id",
            "source_version",
        ):
            _token(getattr(self, name), name)
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("authority user_id must be an exact positive integer")
        _digest(self.authentication_context_hash, "authentication_context_hash")
        _digest(self.source_content_hash, "source_content_hash")
        for name in ("is_authenticated", "is_active", "is_staff", "is_superuser"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if recorded_at >= valid_until:
            raise ValueError("actor authority clock is invalid")


class ExactCurrentAccountActorAuthorityV3Reader(Protocol):
    """Revalidate one authenticated principal against current Account authority."""

    def get_exact_current(
        self,
        *,
        principal_id: str,
        user_id: int,
        expected_authentication_context_hash: str,
        as_of: datetime,
    ) -> CurrentAccountActorAuthorityV3 | None: ...


@dataclass(frozen=True, slots=True)
class CurrentAccountOwnerClaimantProviderV3:
    """Resolve a non-staff claimant by re-reading authority on every call."""

    principal: AuthenticatedAccountPrincipalV3
    authority_reader: ExactCurrentAccountActorAuthorityV3Reader

    def __post_init__(self) -> None:
        if type(self.principal) is not AuthenticatedAccountPrincipalV3:
            raise TypeError("principal must be an exact authenticated principal")
        self.principal.__post_init__()

    def get_current(self, *, as_of: datetime) -> AccountOwnerAssignmentServerActor | None:
        """Return a current claimant or fail closed after an authority re-read."""

        authority = _read_authority(self.principal, self.authority_reader, as_of)
        if authority is None or authority.is_staff or authority.is_superuser:
            return None
        return AccountOwnerAssignmentServerActor(
            actor_id=authority.actor_id,
            user_id=authority.user_id,
            role="account_owner_claimant",
            kind="human",
            is_staff=False,
        )


@dataclass(frozen=True, slots=True)
class CurrentAccountOwnerAssignmentApproverProviderV3:
    """Resolve a staff Account admin by re-reading authority on every call."""

    principal: AuthenticatedAccountPrincipalV3
    authority_reader: ExactCurrentAccountActorAuthorityV3Reader

    def __post_init__(self) -> None:
        if type(self.principal) is not AuthenticatedAccountPrincipalV3:
            raise TypeError("principal must be an exact authenticated principal")
        self.principal.__post_init__()

    def get_current(self, *, as_of: datetime) -> AccountOwnerAssignmentServerActor | None:
        """Return a current staff admin or fail closed after an authority re-read."""

        authority = _read_authority(self.principal, self.authority_reader, as_of)
        if authority is None or not authority.is_staff or authority.rbac_role != "admin":
            return None
        return AccountOwnerAssignmentServerActor(
            actor_id=authority.actor_id,
            user_id=authority.user_id,
            role="account_owner_assignment_approver",
            kind="human",
            is_staff=True,
        )


def _read_authority(
    principal: AuthenticatedAccountPrincipalV3,
    reader: ExactCurrentAccountActorAuthorityV3Reader,
    as_of: datetime,
) -> CurrentAccountActorAuthorityV3 | None:
    cutoff = _aware(as_of, "as_of")
    if not principal.is_current_at(cutoff):
        return None
    raw = reader.get_exact_current(
        principal_id=principal.principal_id,
        user_id=principal.user_id,
        expected_authentication_context_hash=principal.authentication_context_hash,
        as_of=cutoff,
    )
    if raw is None:
        return None
    if type(raw) is not CurrentAccountActorAuthorityV3:
        raise AccountOwnerAssignmentCorruption("actor authority type substitution")
    try:
        raw.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("actor authority is corrupt") from error
    if (
        raw.principal_id != principal.principal_id
        or raw.user_id != principal.user_id
        or raw.authentication_context_hash != principal.authentication_context_hash
        or raw.recorded_at > cutoff
    ):
        raise AccountOwnerAssignmentCorruption("actor authority selector or clock substitution")
    if not raw.is_authenticated or not raw.is_active or cutoff >= raw.valid_until:
        return None
    return raw


__all__ = [
    "AuthenticatedAccountPrincipalV3",
    "CurrentAccountActorAuthorityV3",
    "CurrentAccountOwnerAssignmentApproverProviderV3",
    "CurrentAccountOwnerClaimantProviderV3",
    "ExactCurrentAccountActorAuthorityV3Reader",
]
