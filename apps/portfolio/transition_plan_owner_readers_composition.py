"""Portfolio composition for exact transition-plan owner readers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from apps.portfolio.application.transition_plan_inactive_receipt_reader import (
    ExactInactiveTransitionPlanApprovalReceiptRepository,
    GetExactInactiveTransitionPlanApprovalReceipt,
)
from apps.portfolio.application.transition_plan_order_reader import (
    ExactActiveTransitionPlanDefinitionProvider,
    GetExactActiveTransitionPlanOrder,
)

PlanDefinitionProviderFactory = Callable[[str], ExactActiveTransitionPlanDefinitionProvider]
InactiveReceiptRepositoryFactory = Callable[
    [str], ExactInactiveTransitionPlanApprovalReceiptRepository
]


class TransitionPlanOwnerReadersCompositionUnavailable(RuntimeError):
    """The owner reader composition lacks one required trusted factory."""


@dataclass(frozen=True, slots=True)
class TransitionPlanOwnerReaderRuntime:
    """Two read-only Portfolio Application facades with no write capability."""

    plan_order_reader: GetExactActiveTransitionPlanOrder
    inactive_receipt_reader: GetExactInactiveTransitionPlanApprovalReceipt


def build_transition_plan_owner_reader_runtime(
    *,
    using: str = "default",
    plan_provider_factory: PlanDefinitionProviderFactory | None = None,
    receipt_repository_factory: InactiveReceiptRepositoryFactory | None = None,
) -> TransitionPlanOwnerReaderRuntime:
    """Build injected owner readers or fail before constructing a partial graph."""

    if not using or using.strip() != using:
        raise ValueError("using must be a non-empty canonical database alias")
    if plan_provider_factory is None or receipt_repository_factory is None:
        raise TransitionPlanOwnerReadersCompositionUnavailable(
            "transition_plan_owner_reader_factories_unconfigured"
        )
    plan_provider = plan_provider_factory(using)
    receipt_repository = receipt_repository_factory(using)
    if plan_provider is None or receipt_repository is None:
        raise TransitionPlanOwnerReadersCompositionUnavailable(
            "transition_plan_owner_reader_factory_returned_none"
        )
    return TransitionPlanOwnerReaderRuntime(
        plan_order_reader=GetExactActiveTransitionPlanOrder(plan_provider),
        inactive_receipt_reader=GetExactInactiveTransitionPlanApprovalReceipt(receipt_repository),
    )


def build_django_transition_plan_owner_reader_runtime(
    *, using: str = "default"
) -> TransitionPlanOwnerReaderRuntime:
    """Build production Portfolio readers from owner Django adapters."""

    from apps.portfolio.infrastructure.transition_plan_owner_reader_adapters import (
        build_django_exact_active_transition_plan_definition_adapter,
        build_django_exact_inactive_transition_plan_receipt_adapter,
    )

    return build_transition_plan_owner_reader_runtime(
        using=using,
        plan_provider_factory=build_django_exact_active_transition_plan_definition_adapter,
        receipt_repository_factory=build_django_exact_inactive_transition_plan_receipt_adapter,
    )


__all__ = [
    "InactiveReceiptRepositoryFactory",
    "PlanDefinitionProviderFactory",
    "TransitionPlanOwnerReaderRuntime",
    "TransitionPlanOwnerReadersCompositionUnavailable",
    "build_django_transition_plan_owner_reader_runtime",
    "build_transition_plan_owner_reader_runtime",
]
