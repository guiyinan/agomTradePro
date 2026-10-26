"""Composition root for public M1 risk policy Application use cases."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.risk_center.application.m1_rebalance_risk_policy import (
    GetM1RiskPolicyQualificationUseCase,
    M1RiskPolicyApplication,
    PublishM1RiskPolicyRevisionUseCase,
    RevokeM1RiskPolicyRevisionUseCase,
)
from apps.risk_center.infrastructure.m1_rebalance_risk_policy_repository import (
    DjangoM1RiskPolicyRevisionRepository,
)


def build_m1_risk_policy_application(*, using: str = DEFAULT_DB_ALIAS) -> M1RiskPolicyApplication:
    """Return the public publish/qualification use cases for other app compositions."""

    repository = DjangoM1RiskPolicyRevisionRepository(using=using)
    return M1RiskPolicyApplication(
        publish=PublishM1RiskPolicyRevisionUseCase(repository),
        qualify=GetM1RiskPolicyQualificationUseCase(repository),
        revoke=RevokeM1RiskPolicyRevisionUseCase(repository),
    )


__all__: tuple[str, ...] = ("build_m1_risk_policy_application",)
