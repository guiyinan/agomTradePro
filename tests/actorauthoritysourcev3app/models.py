"""Expose only actor-authority source v3 models under the Account label."""

from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
)

__all__ = [
    "AccountOwnerAssignmentActorAuthoritySourceV3Model",
    "AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel",
]
