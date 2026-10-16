"""Composition root for strict simulated fee-policy version creation."""

from __future__ import annotations

from apps.simulated_trading.application.fee_policy_v2 import (
    CreateFeePolicyVersionUseCase,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)


def build_create_fee_policy_version_use_case(
    *,
    using: str,
) -> CreateFeePolicyVersionUseCase:
    """Compose the operator use case with one explicit FeeConfig database alias."""

    repository = DjangoFeePolicyV2Repository(using=using)
    return CreateFeePolicyVersionUseCase(repository=repository)


__all__: tuple[str, ...] = ("build_create_fee_policy_version_use_case",)
