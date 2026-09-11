"""Resolve one current single-owner policy without hiding scope collisions.

This Application boundary consumes a server-owned, already current policy
reader.  It does not read the database, authenticate a user, or grant owner,
tenant, or execution authority.  The reader must return every current policy
head for the requested canonical Account scope so this resolver can reject a
collision instead of accepting a user-filtered winner.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
)
from apps.account.application.single_owner_actor_authority import (
    SingleOwnerPolicyBinding,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)


class CurrentSingleOwnerPoliciesReader(Protocol):
    """Read every current policy head for one exact canonical Account scope."""

    def get_current_for_scope(
        self,
        *,
        account_namespace: str,
        account_id: str,
        as_of: datetime,
    ) -> tuple[SingleOwnerAuthorityPolicyV1, ...]:
        """Return all current policy heads for the supplied point in time."""

        ...


def _require_token(value: object, field_name: str) -> str:
    """Validate one trusted canonical scope token before querying the reader."""

    if type(value) is not str:
        raise AccountOwnerAssignmentCorruption(f"{field_name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise AccountOwnerAssignmentCorruption(f"{field_name} must be a bounded canonical token")
    return value


def _require_owner_user_id(value: object) -> int:
    """Validate the trusted owner selector without allowing bool as an ID."""

    if type(value) is not int:
        raise AccountOwnerAssignmentCorruption("owner_user_id must be an exact positive integer")
    if value <= 0:
        raise AccountOwnerAssignmentCorruption("owner_user_id must be an exact positive integer")
    return value


def _require_aware(value: object) -> datetime:
    """Validate the caller's aware point-in-time cutoff."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AccountOwnerAssignmentCorruption("as_of must be timezone-aware")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Require one complete lowercase SHA-256 seal from the reader."""

    if type(value) is not str:
        raise AccountOwnerAssignmentCorruption(f"{field_name} must be an exact digest")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise AccountOwnerAssignmentCorruption(f"{field_name} must be an exact digest")
    return value


class ResolveCurrentSingleOwnerPolicyBinding:
    """Resolve one exact policy binding from all current heads in one scope.

    owner_user_id is an expected server-side owner selector.  It is checked
    only after the reader has returned the complete scope set; it is never
    passed to the reader as a filter.  Therefore a second active policy for
    another owner cannot be hidden by a user-specific query.
    """

    def __init__(self, reader: CurrentSingleOwnerPoliciesReader) -> None:
        """Store the injected current-head reader without opening any store."""

        if not callable(getattr(reader, "get_current_for_scope", None)):
            raise TypeError("reader must implement get_current_for_scope")
        self._reader = reader

    def resolve(
        self,
        *,
        account_namespace: str,
        account_id: str,
        owner_user_id: int,
        as_of: datetime,
    ) -> SingleOwnerPolicyBinding | None:
        """Return the sole current policy binding, or None when none exists.

        The inputs are trusted server-side canonical facts.  This method only
        resolves policy evidence; authentication and any later authority
        decision remain separate Application operations.
        """

        namespace = _require_token(account_namespace, "account_namespace")
        canonical_account_id = _require_token(account_id, "account_id")
        expected_owner_user_id = _require_owner_user_id(owner_user_id)
        cutoff = _require_aware(as_of)

        policies = self._reader.get_current_for_scope(
            account_namespace=namespace,
            account_id=canonical_account_id,
            as_of=cutoff,
        )

        if type(policies) is not tuple:
            raise AccountOwnerAssignmentCorruption(
                "current single-owner policy source returned a substituted collection"
            )

        checked_policies = tuple(self._check_policy(policy, cutoff) for policy in policies)
        if not checked_policies:
            return None
        if len(checked_policies) != 1:
            raise AccountOwnerAssignmentConflict(
                "multiple current single-owner policies cover one Account scope"
            )

        policy = checked_policies[0]
        if (
            policy.account_namespace != namespace
            or policy.account_id != canonical_account_id
            or policy.owner_user_id != expected_owner_user_id
        ):
            raise AccountOwnerAssignmentCorruption(
                "current single-owner policy scope or owner selector was substituted"
            )
        try:
            binding = SingleOwnerPolicyBinding(
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                expected_content_hash=policy.content_hash,
                tenant_id=policy.tenant_id,
                owner_id=policy.owner_id,
                account_namespace=policy.account_namespace,
                account_id=policy.account_id,
            )
            binding.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "current single-owner policy could not form an exact binding"
            ) from error
        return binding

    def execute(
        self,
        *,
        account_namespace: str,
        account_id: str,
        owner_user_id: int,
        as_of: datetime,
    ) -> SingleOwnerPolicyBinding | None:
        """Resolve the same policy binding through the Application command seam."""

        return self.resolve(
            account_namespace=account_namespace,
            account_id=account_id,
            owner_user_id=owner_user_id,
            as_of=as_of,
        )

    @staticmethod
    def _check_policy(
        value: object,
        cutoff: datetime,
    ) -> SingleOwnerAuthorityPolicyV1:
        """Validate one complete current policy without computing missing seals."""

        if type(value) is not SingleOwnerAuthorityPolicyV1:
            raise AccountOwnerAssignmentCorruption(
                "current single-owner policy source returned a substituted type"
            )
        policy = value
        _require_digest(policy.identity_hash, "policy identity_hash")
        _require_digest(policy.content_hash, "policy content_hash")
        try:
            policy.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "current single-owner policy source returned a bad seal"
            ) from error
        if not policy.is_current_at(cutoff):
            raise AccountOwnerAssignmentCorruption(
                "current single-owner policy is expired, revoked, or future"
            )
        return policy


__all__ = [
    "CurrentSingleOwnerPoliciesReader",
    "ResolveCurrentSingleOwnerPolicyBinding",
]
