"""Read composition for durable single-owner policy and canonical actor facts."""

from __future__ import annotations

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_request_reader,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipantsProvider,
    SingleOwnerPolicyBinding,
)
from apps.account.application.single_owner_policy_resolution import (
    ResolveCurrentSingleOwnerPolicyBinding,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)


def build_current_single_owner_policy_resolver(
    *, using: str
) -> ResolveCurrentSingleOwnerPolicyBinding:
    """Build a scope-complete resolver on one explicit database without granting authority."""
    if type(using) is not str or not using or any(character.isspace() for character in using):
        raise ValueError("using must be an explicit canonical database alias")
    return ResolveCurrentSingleOwnerPolicyBinding(
        reader=DjangoSingleOwnerAuthorityPolicyV1Repository(using=using)
    )


def build_current_single_owner_participants_provider(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    policy_binding: SingleOwnerPolicyBinding,
    actor_source_id: str,
    actor_source_version: str,
    actor_source_content_hash: str,
    using: str = "default",
) -> CurrentSingleOwnerParticipantsProvider:
    """Bind both durable sources to one alias for current, non-granting role reads.

    This factory serves standalone reads. Writers must use their transaction
    composition and locked source revalidation before an authority append.
    """

    if type(principal) is not AuthenticatedAccountPrincipalV3:
        raise TypeError("principal must be an exact authenticated principal")
    if type(policy_binding) is not SingleOwnerPolicyBinding:
        raise TypeError("policy_binding must be an exact server-owned binding")
    principal.__post_init__()
    policy_binding.__post_init__()
    actor_reader = build_account_actor_authority_request_reader(
        source_id=actor_source_id,
        source_version=actor_source_version,
        expected_content_hash=actor_source_content_hash,
        using=using,
    )
    return CurrentSingleOwnerParticipantsProvider(
        principal=principal,
        binding=policy_binding,
        policies=DjangoSingleOwnerAuthorityPolicyV1Repository(using=using),
        actors=actor_reader,
    )
