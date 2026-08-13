"""Read-only Django adapters for Portfolio transition-plan owner readers."""

from __future__ import annotations

from datetime import datetime

from apps.portfolio.application.transition_plan_inactive_approval import (
    TransitionPlanDefinition,
)
from apps.portfolio.application.transition_plan_inactive_receipt_reader import (
    ExactInactiveTransitionPlanApprovalReceiptRepository,
)
from apps.portfolio.application.transition_plan_order_reader import (
    ExactActiveTransitionPlanDefinitionProvider,
)
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalReceipt,
)
from apps.portfolio.infrastructure.transition_plan_definition_provider import (
    DjangoExactTransitionPlanDefinitionProvider,
)
from apps.portfolio.infrastructure.transition_plan_inactive_approval_repository import (
    DjangoTransitionPlanInactiveApprovalRepository,
)


class DjangoExactActiveTransitionPlanDefinitionAdapter:
    """Narrow exact-active adapter over the canonical plan definition provider."""

    __slots__ = ("__provider",)

    def __init__(
        self,
        *,
        using: str = "default",
        provider: ExactActiveTransitionPlanDefinitionProvider | None = None,
    ) -> None:
        self.__provider = (
            provider
            if provider is not None
            else DjangoExactTransitionPlanDefinitionProvider(using=using)
        )

    def get_exact(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> TransitionPlanDefinition | None:
        """Delegate the unchanged identity/version/PIT selector to its owner."""

        return self.__provider.get_exact(
            plan_id=plan_id,
            plan_version=plan_version,
            as_of=as_of,
        )


class DjangoExactInactiveTransitionPlanApprovalReceiptAdapter:
    """Expose only identity-winner reads from the inactive approval ledger."""

    __slots__ = ("__repository",)

    def __init__(
        self,
        *,
        using: str = "default",
        repository: ExactInactiveTransitionPlanApprovalReceiptRepository | None = None,
    ) -> None:
        self.__repository = (
            repository
            if repository is not None
            else DjangoTransitionPlanInactiveApprovalRepository(using=using)
        )

    def get_receipt_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> TransitionPlanApprovalReceipt | None:
        """Read one sealed identity winner without accepting a caller hash."""

        return self.__repository.get_receipt_winner(
            receipt_id=receipt_id,
            receipt_version=receipt_version,
            as_of=as_of,
        )


def build_django_exact_active_transition_plan_definition_adapter(
    using: str,
) -> ExactActiveTransitionPlanDefinitionProvider:
    """Build the read-only exact plan-definition adapter for one database alias."""

    return DjangoExactActiveTransitionPlanDefinitionAdapter(using=using)


def build_django_exact_inactive_transition_plan_receipt_adapter(
    using: str,
) -> ExactInactiveTransitionPlanApprovalReceiptRepository:
    """Build the read-only receipt identity-winner adapter for one database alias."""

    return DjangoExactInactiveTransitionPlanApprovalReceiptAdapter(using=using)


__all__ = [
    "DjangoExactActiveTransitionPlanDefinitionAdapter",
    "DjangoExactInactiveTransitionPlanApprovalReceiptAdapter",
    "build_django_exact_active_transition_plan_definition_adapter",
    "build_django_exact_inactive_transition_plan_receipt_adapter",
]
