"""Composition root for the isolated publication-policy activation workflow."""

from __future__ import annotations

from apps.data_center.application.publication_policy_activation import (
    ActivatePublicationPoliciesUseCase,
)
from apps.data_center.infrastructure.publication_policy_activation_repository import (
    DjangoPublicationPolicyActivationRepository,
)


def get_publication_policy_activation_use_case() -> ActivatePublicationPoliciesUseCase:
    """Return the guarded, policy-only activation use case."""

    return ActivatePublicationPoliciesUseCase(DjangoPublicationPolicyActivationRepository())


__all__ = ["get_publication_policy_activation_use_case"]
