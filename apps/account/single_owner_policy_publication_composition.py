"""Compose the policy publisher on one explicit persistence alias."""

from apps.account.application.single_owner_policy_publication import (
    CurrentSingleOwnerPolicyPublicationInputs,
    PublishSingleOwnerAuthorityPolicyV1,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)


def build_single_owner_policy_publisher(
    *, using: str, current_inputs: CurrentSingleOwnerPolicyPublicationInputs
) -> PublishSingleOwnerAuthorityPolicyV1:
    """Bind the repository and current inputs without manufacturing an identity."""
    if type(using) is not str or not using or any(character.isspace() for character in using):
        raise ValueError("Policy publication requires an explicit database alias")
    return PublishSingleOwnerAuthorityPolicyV1(
        repository=DjangoSingleOwnerAuthorityPolicyV1Repository(using=using),
        current_inputs=current_inputs,
    )
