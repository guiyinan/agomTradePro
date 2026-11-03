"""Risk Center owns portfolio policy/source/evidence adapter construction."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.risk_center.application.portfolio_exit_pressure_ports import (
    PortfolioPressureProjectionProviderProtocol,
    ScenarioPressureClockProtocol,
)
from apps.risk_center.application.portfolio_exit_pressure_use_cases import (
    RunPortfolioExitPressureUseCase,
)
from apps.risk_center.application.portfolio_risk_runtime import PortfolioRiskRuntime
from apps.risk_center.application.scenario_ports import PortfolioSnapshotProviderProtocol
from apps.risk_center.application.scenario_use_cases import PreviewScenarioImpactUseCase
from apps.risk_center.infrastructure.configured_portfolio_risk_policy_reader import (
    ConfiguredPortfolioRiskPolicyReader,
)
from apps.risk_center.infrastructure.portfolio_baseline_risk_repository import (
    DjangoPortfolioBaselinePolicyReader,
)
from apps.risk_center.infrastructure.portfolio_risk_execution_evidence_repository import (
    DjangoPortfolioRiskExecutionEvidenceWriter,
)
from apps.risk_center.infrastructure.retained_portfolio_risk_assets_reader import (
    RetainedPortfolioRiskAssetsReader,
)
from apps.risk_center.infrastructure.scenario_market_data_provider import (
    PublishedScenarioMarketDataProvider,
)
from apps.risk_center.infrastructure.scenario_repositories import DjangoScenarioRepository
from core.exceptions import MissingConfigError


class _PressureApplicationFactory:
    def __init__(self, *, using: str) -> None:
        self._using = using

    def build(
        self,
        *,
        portfolio_provider: PortfolioSnapshotProviderProtocol,
        projection_provider: PortfolioPressureProjectionProviderProtocol,
        clock: ScenarioPressureClockProtocol,
    ) -> RunPortfolioExitPressureUseCase:
        """Use the existing Scenario store only when its DB scope matches."""

        if self._using != DEFAULT_DB_ALIAS:
            raise MissingConfigError(code="SCENARIO_PRESSURE_DATABASE_SCOPE_UNAVAILABLE")
        repository = DjangoScenarioRepository()
        return RunPortfolioExitPressureUseCase(
            preview=PreviewScenarioImpactUseCase(
                scenario_repository=repository,
                portfolio_provider=portfolio_provider,
                market_data_provider=PublishedScenarioMarketDataProvider(),
            ),
            run_evidence_repository=repository,
            projection_provider=projection_provider,
            clock=clock,
        )


def build_portfolio_risk_runtime(*, using: str, environment: str) -> PortfolioRiskRuntime:
    """Build read-only adapters and explicit writes without changing runtime state."""

    return PortfolioRiskRuntime(
        policy_reader=ConfiguredPortfolioRiskPolicyReader(environment=environment),
        assets_reader=RetainedPortfolioRiskAssetsReader(),
        baseline_reader=DjangoPortfolioBaselinePolicyReader(using=using),
        execution_evidence_writer=DjangoPortfolioRiskExecutionEvidenceWriter(using=using),
        pressure_factory=_PressureApplicationFactory(using=using),
        pressure_evidence_repository=DjangoScenarioRepository(),
    )
