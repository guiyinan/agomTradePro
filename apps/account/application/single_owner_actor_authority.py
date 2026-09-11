"""Resolve one real administrator under an exact server-owned single-owner policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
    CurrentAccountActorAuthorityV3,
    ExactCurrentAccountActorAuthorityV3Reader,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
)
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_participants,
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


@dataclass(frozen=True, slots=True)
class SingleOwnerPolicyBinding:
    """Select one policy and scope supplied by the server composition root."""

    policy_id: str
    policy_version: str
    expected_content_hash: str
    tenant_id: str
    owner_id: str
    account_namespace: str
    account_id: str

    def __post_init__(self) -> None:
        for name in (
            "policy_id",
            "policy_version",
            "tenant_id",
            "owner_id",
            "account_namespace",
            "account_id",
        ):
            _token(getattr(self, name), name)
        _digest(self.expected_content_hash, "expected_content_hash")


class ExactCurrentSingleOwnerPolicyReader(Protocol):
    """Revalidate an exact policy against its current durable source on each call."""

    def get_exact_current(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SingleOwnerAuthorityPolicyV1 | None: ...


@dataclass(frozen=True, slots=True)
class CurrentSingleOwnerParticipants:
    """Source-bound role projections of one real human, granting no scope themselves."""

    policy: SingleOwnerAuthorityPolicyV1
    authority: CurrentAccountActorAuthorityV3
    claimant: AccountOwnerAssignmentActor
    approver: AccountOwnerAssignmentActor
    observed_at: datetime
    valid_until: datetime


@dataclass(frozen=True, slots=True)
class CurrentSingleOwnerParticipantsProvider:
    """Read exact policy and authentication facts anew without caching authority."""

    principal: AuthenticatedAccountPrincipalV3
    binding: SingleOwnerPolicyBinding
    policies: ExactCurrentSingleOwnerPolicyReader
    actors: ExactCurrentAccountActorAuthorityV3Reader

    def __post_init__(self) -> None:
        if type(self.principal) is not AuthenticatedAccountPrincipalV3:
            raise TypeError("principal must be an exact authenticated principal")
        if type(self.binding) is not SingleOwnerPolicyBinding:
            raise TypeError("binding must be an exact server-owned policy selector")
        self.principal.__post_init__()
        self.binding.__post_init__()

    def get_current(self, *, as_of: datetime) -> CurrentSingleOwnerParticipants | None:
        """Resolve both roles only while the selected policy and real admin remain current.

        A writer must call this within its canonical unit of work and revalidate
        before append. This read projection is neither an approval nor a grant.
        """

        self.__post_init__()
        if not self.principal.is_current_at(as_of):
            return None
        policy = self._policy(as_of=as_of)
        if policy is None or policy.owner_user_id != self.principal.user_id:
            return None
        authority = self._authority(as_of=as_of)
        if authority is None:
            return None
        claimant = AccountOwnerAssignmentActor(
            actor_id=authority.actor_id,
            user_id=authority.user_id,
            role="account_owner_claimant",
            is_staff=authority.is_staff,
        )
        approver = AccountOwnerAssignmentActor(
            actor_id=authority.actor_id,
            user_id=authority.user_id,
            role="account_owner_assignment_approver",
            is_staff=authority.is_staff,
        )
        validate_single_owner_participants(
            policy=policy,
            claimant=claimant,
            approver=approver,
            as_of=as_of,
        )
        return CurrentSingleOwnerParticipants(
            policy,
            authority,
            claimant,
            approver,
            as_of,
            min(policy.valid_until, authority.valid_until, self.principal.valid_until),
        )

    def _policy(self, *, as_of: datetime) -> SingleOwnerAuthorityPolicyV1 | None:
        policy = self.policies.get_exact_current(
            policy_id=self.binding.policy_id,
            policy_version=self.binding.policy_version,
            expected_content_hash=self.binding.expected_content_hash,
            as_of=as_of,
        )
        if policy is None:
            return None
        if type(policy) is not SingleOwnerAuthorityPolicyV1:
            raise AccountOwnerAssignmentCorruption("single-owner policy type substitution")
        try:
            _digest(policy.content_hash, "policy content_hash")
            _digest(policy.identity_hash, "policy identity_hash")
            policy.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("single-owner policy is corrupt") from error
        for name in (
            "policy_id",
            "policy_version",
            "tenant_id",
            "owner_id",
            "account_namespace",
            "account_id",
        ):
            if getattr(policy, name) != getattr(self.binding, name):
                raise AccountOwnerAssignmentCorruption("single-owner policy scope substitution")
        if policy.content_hash != self.binding.expected_content_hash:
            raise AccountOwnerAssignmentCorruption("single-owner policy hash substitution")
        return policy if policy.is_current_at(as_of) else None

    def _authority(self, *, as_of: datetime) -> CurrentAccountActorAuthorityV3 | None:
        authority = self.actors.get_exact_current(
            principal_id=self.principal.principal_id,
            user_id=self.principal.user_id,
            expected_authentication_context_hash=self.principal.authentication_context_hash,
            as_of=as_of,
        )
        if authority is None:
            return None
        if type(authority) is not CurrentAccountActorAuthorityV3:
            raise AccountOwnerAssignmentCorruption("actor authority type substitution")
        try:
            authority.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("actor authority is corrupt") from error
        if (
            authority.principal_id != self.principal.principal_id
            or authority.user_id != self.principal.user_id
            or authority.authentication_context_hash != self.principal.authentication_context_hash
            or authority.recorded_at > as_of
        ):
            raise AccountOwnerAssignmentCorruption("actor authority selector or clock substitution")
        if (
            not authority.is_authenticated
            or not authority.is_active
            or not authority.is_staff
            or authority.rbac_role != "admin"
            or as_of >= authority.valid_until
        ):
            return None
        return authority
