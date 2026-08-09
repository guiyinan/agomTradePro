"""Fail-closed production composition for governed R8 optimization research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.portfolio.application.governed_optimization import (
    AppendGovernedOptimizationLifecycleEventCommand,
    AssembleGovernedOptimizationCommand,
    AssembleGovernedOptimizationProblemUseCase,
    ExactPromotionProvider,
    GovernedOptimizationRunBundle,
    GovernedOptimizationUnavailable,
    RegisterGovernedOptimizationInputReceiptCommand,
    RunGovernedOptimizationResearchUseCase,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.infrastructure.deterministic_optimizer import (
    DeterministicConstrainedSearchAdapter,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationInputReceiptRepository,
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.optimization_research_repository import (
    DjangoGovernedOptimizationResearchRepository,
)


class _UnavailableExactPromotionProvider:
    """Deny R8 promotion claims until Research exposes an exact owner port."""

    def __init__(self, *, unit_of_work_key: str) -> None:
        self._unit_of_work_key = unit_of_work_key

    @property
    def unit_of_work_key(self) -> str:
        """Share the exact run UoW without exposing any evidence source."""

        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        capability_key: str,
        decision_id: str,
        evaluated_at: datetime,
    ) -> ExactPromotionAttestation | None:
        """Never accept caller-supplied R3/R4/R5/R8 promotion evidence."""

        return None


class UnavailableGovernedOptimizationInputReceiptRegistrationFacade:
    """Expose an inert ID-only registration boundary until owner ports exist."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterGovernedOptimizationInputReceiptCommand,
    ) -> None:
        """Revalidate lookup identity and fail closed without holding capabilities."""

        try:
            if type(command) is not RegisterGovernedOptimizationInputReceiptCommand:
                raise TypeError("registration command has an unexpected type")
            if type(command.input_set_id) is not str or type(command.input_set_version) is not str:
                raise TypeError("registration identity must use exact strings")
            RegisterGovernedOptimizationInputReceiptCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationUnavailable(
                "governed optimization input receipt registration command is invalid"
            ) from exc
        raise GovernedOptimizationUnavailable(
            "canonical governed optimization input receipt registration is unavailable"
        )


class UnavailableGovernedOptimizationLifecycleFacade:
    """Expose no lifecycle capability until exact owner providers are composed."""

    __slots__ = ()

    def execute(
        self,
        command: AppendGovernedOptimizationLifecycleEventCommand,
    ) -> None:
        """Revalidate the ID-only command and fail before any result or stream read."""

        try:
            if type(command) is not AppendGovernedOptimizationLifecycleEventCommand:
                raise TypeError("lifecycle command has an unexpected type")
            AppendGovernedOptimizationLifecycleEventCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationUnavailable("R8 lifecycle command is invalid") from exc
        raise GovernedOptimizationUnavailable(
            "canonical R8 lifecycle owner authorization is unavailable"
        )


class DjangoGovernedOptimizationRunFacade:
    """Create production run capabilities only inside one stateless call boundary."""

    __slots__ = ()

    def execute(
        self,
        *,
        command: AssembleGovernedOptimizationCommand,
        run_key: str,
        run_version: str,
    ) -> GovernedOptimizationRunBundle:
        """Run through a call-local composition and normalize boundary failures."""

        try:
            return _execute_django_governed_optimization_research(
                command=command,
                run_key=run_key,
                run_version=run_version,
            )
        except GovernedOptimizationUnavailable:
            raise
        except Exception as exc:
            raise GovernedOptimizationUnavailable(
                "canonical governed optimization production runtime is unavailable"
            ) from exc


@dataclass(frozen=True)
class DjangoGovernedOptimizationResearchRuntime:
    """Constructable R8 runtime whose missing owner sources fail before writes."""

    register_input_receipt: UnavailableGovernedOptimizationInputReceiptRegistrationFacade
    run: DjangoGovernedOptimizationRunFacade
    append_lifecycle: UnavailableGovernedOptimizationLifecycleFacade


def build_django_governed_optimization_research_runtime() -> (
    DjangoGovernedOptimizationResearchRuntime
):
    """Build the production runtime without fixture/default owner evidence."""

    return DjangoGovernedOptimizationResearchRuntime(
        register_input_receipt=UnavailableGovernedOptimizationInputReceiptRegistrationFacade(),
        run=DjangoGovernedOptimizationRunFacade(),
        append_lifecycle=UnavailableGovernedOptimizationLifecycleFacade(),
    )


def _execute_django_governed_optimization_research(
    *,
    command: AssembleGovernedOptimizationCommand,
    run_key: str,
    run_version: str,
) -> GovernedOptimizationRunBundle:
    """Construct and discard every database/write capability within one call."""

    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    input_receipt_provider = DjangoGovernedOptimizationInputReceiptRepository(
        unit_of_work=unit_of_work
    )
    repository = DjangoGovernedOptimizationResearchRepository(
        unit_of_work=unit_of_work,
        receipt_provider=input_receipt_provider,
    )
    promotion_provider: ExactPromotionProvider = _UnavailableExactPromotionProvider(
        unit_of_work_key=unit_of_work.unit_of_work_key
    )
    assembler = AssembleGovernedOptimizationProblemUseCase(
        input_set_provider=input_receipt_provider,
        promotion_provider=promotion_provider,
    )
    return RunGovernedOptimizationResearchUseCase(
        assembler=assembler,
        engine=DeterministicConstrainedSearchAdapter(),
        repository=repository,
        input_receipt_provider=input_receipt_provider,
        promotion_provider=promotion_provider,
    ).execute(
        command=command,
        run_key=run_key,
        run_version=run_version,
    )


__all__ = [
    "DjangoGovernedOptimizationResearchRuntime",
    "DjangoGovernedOptimizationRunFacade",
    "UnavailableGovernedOptimizationInputReceiptRegistrationFacade",
    "UnavailableGovernedOptimizationLifecycleFacade",
    "build_django_governed_optimization_research_runtime",
]
