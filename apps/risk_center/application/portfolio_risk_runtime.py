"""Public DI boundary for simulation portfolio risk and existing Scenario storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.risk_center.application.portfolio_baseline_risk import PortfolioBaselinePolicyReader
from apps.risk_center.application.portfolio_exit_pressure_ports import (
    PortfolioPressureProjectionProviderProtocol,
    ScenarioPressureClockProtocol,
)
from apps.risk_center.application.portfolio_exit_pressure_use_cases import (
    RunPortfolioExitPressureUseCase,
)
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetsReader
from apps.risk_center.application.portfolio_risk_execution_evidence import (
    PortfolioRiskExecutionEvidenceWriter,
)
from apps.risk_center.application.portfolio_risk_policy import PortfolioRiskPolicyReader
from apps.risk_center.application.scenario_ports import (
    PortfolioSnapshotProviderProtocol,
    ScenarioRunEvidenceReadWriteRepositoryProtocol,
)
from core.exceptions import MissingConfigError


class PortfolioPressureApplicationFactory(Protocol):
    """Build the existing Scenario integration without importing consumer Apps."""

    def build(
        self,
        *,
        portfolio_provider: PortfolioSnapshotProviderProtocol,
        projection_provider: PortfolioPressureProjectionProviderProtocol,
        clock: ScenarioPressureClockProtocol,
    ) -> RunPortfolioExitPressureUseCase:
        """Bind exact server-side inputs to the owning Scenario repositories."""
        ...


@dataclass(frozen=True, slots=True)
class PortfolioRiskRuntime:
    """Risk-owned ports, including the existing read/write Scenario evidence repository."""

    policy_reader: PortfolioRiskPolicyReader
    assets_reader: PortfolioRiskAssetsReader
    baseline_reader: PortfolioBaselinePolicyReader
    execution_evidence_writer: PortfolioRiskExecutionEvidenceWriter
    pressure_factory: PortfolioPressureApplicationFactory
    pressure_evidence_repository: ScenarioRunEvidenceReadWriteRepositoryProtocol


class PortfolioRiskRuntimeFactory(Protocol):
    """Build risk-owned adapters within the consumer's declared database scope."""

    def __call__(self, *, using: str, environment: str) -> PortfolioRiskRuntime:
        """Return lazy ports; construction must not create financial/configuration rows."""
        ...


_factory: PortfolioRiskRuntimeFactory | None = None


def configure_portfolio_risk_runtime(factory: PortfolioRiskRuntimeFactory) -> None:
    """Register the owner composition root without evaluating risk or placing orders."""

    global _factory
    _factory = factory


def get_portfolio_risk_runtime(*, using: str, environment: str) -> PortfolioRiskRuntime:
    """Resolve public risk-owned ports without importing any Infrastructure class."""

    if _factory is None:
        raise MissingConfigError(code="PORTFOLIO_RISK_RUNTIME_NOT_CONFIGURED")
    return _factory(using=using, environment=environment)
