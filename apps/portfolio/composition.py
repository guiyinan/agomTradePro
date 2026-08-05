"""Portfolio composition root."""

from apps.portfolio.application.canonical_snapshots import (
    CanonicalPortfolioSnapshotQueryService,
    CreateCanonicalPortfolioSnapshotUseCase,
)
from apps.portfolio.application.use_cases import (
    BuildTransitionPlanUseCase,
    SubmitApprovedPlanUseCase,
    ValidateTransitionPlanUseCase,
)
from apps.portfolio.infrastructure.canonical_snapshot_repositories import (
    DjangoCanonicalPortfolioSnapshotRepository,
)
from apps.portfolio.infrastructure.repositories import (
    PortfolioPlanningPolicyRepository,
    PortfolioTransitionPlanRepository,
)


def make_build_transition_plan_use_case() -> BuildTransitionPlanUseCase:
    return BuildTransitionPlanUseCase(
        PortfolioTransitionPlanRepository(), PortfolioPlanningPolicyRepository()
    )


def make_validate_transition_plan_use_case() -> ValidateTransitionPlanUseCase:
    return ValidateTransitionPlanUseCase(PortfolioTransitionPlanRepository())


def make_submit_approved_plan_use_case() -> SubmitApprovedPlanUseCase:
    return SubmitApprovedPlanUseCase(PortfolioTransitionPlanRepository())


def make_create_canonical_portfolio_snapshot_use_case() -> CreateCanonicalPortfolioSnapshotUseCase:
    """Compose the Portfolio-owned canonical snapshot writer."""

    return CreateCanonicalPortfolioSnapshotUseCase(DjangoCanonicalPortfolioSnapshotRepository())


def make_canonical_portfolio_snapshot_query_service() -> CanonicalPortfolioSnapshotQueryService:
    """Compose the only supported cross-App snapshot read surface."""

    return CanonicalPortfolioSnapshotQueryService(DjangoCanonicalPortfolioSnapshotRepository())


def get_transition_plan(plan_id: str):  # type: ignore[no-untyped-def]
    """Read a transition plan through the composition boundary."""

    return PortfolioTransitionPlanRepository().get(plan_id)
