"""Account compatibility facade for governed Risk Center stress scenarios.

Account no longer owns scenario definitions, market-data access, portfolio
notionals, risk calculations, or recommendation thresholds.  This module keeps
the historical Account-facing DTOs and method names while delegating every
business input to typed application ports owned by Risk Center and Portfolio.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from apps.risk_center.application.scenario_dtos import (
    PortfolioSnapshotDTO,
    ScenarioRunRequestDTO,
    ScenarioSummaryDTO,
)
from apps.risk_center.application.scenario_ports import (
    PortfolioSnapshotProviderProtocol as RiskCenterPortfolioSnapshotProviderProtocol,
)
from apps.risk_center.application.scenario_ports import (
    ScenarioMarketDataProviderProtocol,
    ScenarioQueryRepositoryProtocol,
)
from apps.risk_center.application.scenario_repository_provider import (
    get_scenario_query_repository,
)
from apps.risk_center.application.scenario_use_cases import (
    GetScenarioRevisionUseCase,
    ListScenarioDefinitionsUseCase,
    PreviewScenarioImpactUseCase,
    ScenarioNotFoundError,
)
from apps.risk_center.domain.scenarios import (
    HistoricalWindowParameters,
    ScenarioImpact,
    ScenarioType,
)


class StressTestingConfigurationError(RuntimeError):
    """Raised when a required compatibility-facade port is not configured."""


class PortfolioSnapshotProviderProtocol(
    RiskCenterPortfolioSnapshotProviderProtocol,
    Protocol,
):
    """Portfolio-owned provider for exact and latest immutable snapshots."""

    def get_latest_snapshot_for_portfolio(
        self,
        portfolio_id: int,
        *,
        as_of_time: datetime,
    ) -> PortfolioSnapshotDTO | None:
        """Return the latest published snapshot visible at ``as_of_time``."""


@dataclass(frozen=True)
class StressRecommendationPolicyDecision:
    """Recommendations returned by one immutable policy revision."""

    policy_version: str
    recommendations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("recommendation policy_version is required")
        if any(not item.strip() for item in self.recommendations):
            raise ValueError("recommendations cannot contain blank messages")


class StressRecommendationPolicyQueryProtocol(Protocol):
    """Risk Center-owned port for versioned stress recommendations."""

    def evaluate(
        self,
        *,
        scenario_revision_id: str,
        scenario_content_hash: str,
        impact: ScenarioImpact,
    ) -> StressRecommendationPolicyDecision:
        """Return already-evaluated advice and its exact policy version."""


@dataclass(frozen=True)
class StressTestRuntimeBindings:
    """Version bindings required by the Risk Center preview request."""

    allocation_policy_version: str
    code_version: str

    def __post_init__(self) -> None:
        if not self.allocation_policy_version.strip():
            raise ValueError("allocation_policy_version is required")
        if not self.code_version.strip():
            raise ValueError("code_version is required")


@dataclass(frozen=True)
class StressTestScenario:
    """Historical scenario projection retained for Account callers."""

    scenario_id: str
    name: str
    description: str
    start_date: date
    end_date: date
    revision_id: str = ""
    version: int = 0
    content_hash: str = ""


@dataclass(frozen=True)
class StressTestResult:
    """Account-compatible projection of a Risk Center scenario impact."""

    scenario_id: str
    scenario_name: str
    initial_value: Decimal
    final_value: Decimal
    total_return: Decimal
    max_drawdown: float
    recovery_days: int
    volatility: float
    var_95: float
    var_99: float
    recommendations: list[str]
    scenario_revision_id: str = ""
    recommendation_policy_version: str = ""
    result_hash: str = ""


class HistoricalScenarioService:
    """Repository-backed historical scenario catalog compatibility service."""

    def __init__(self, repository: ScenarioQueryRepositoryProtocol) -> None:
        self._repository = repository
        self._list = ListScenarioDefinitionsUseCase(repository)
        self._get = GetScenarioRevisionUseCase(repository)

    @staticmethod
    def _project(summary: ScenarioSummaryDTO) -> StressTestScenario:
        """Project one typed Risk Center summary without a static fallback."""

        parameters = summary.revision.parameters
        if not isinstance(parameters, HistoricalWindowParameters):
            raise ValueError("Account historical stress testing requires a historical window")
        return StressTestScenario(
            scenario_id=summary.definition.scenario_key,
            name=summary.definition.name,
            description=summary.definition.description or parameters.event_description,
            start_date=parameters.start_date,
            end_date=parameters.end_date,
            revision_id=summary.revision.revision_id,
            version=summary.revision.version,
            content_hash=summary.revision.content_hash,
        )

    def get_scenario(self, identifier: str) -> StressTestScenario:
        """Resolve a current historical revision by id, key, or legacy alias."""

        revision = self._get.execute(identifier)
        if revision.scenario_type is not ScenarioType.HISTORICAL_WINDOW:
            raise ScenarioNotFoundError(f"historical stress scenario not found: {identifier}")
        for summary in self._list.execute(scenario_type=ScenarioType.HISTORICAL_WINDOW):
            if summary.revision.revision_id == revision.revision_id:
                return self._project(summary)
        raise ScenarioNotFoundError(f"historical stress scenario not found: {identifier}")

    def get_all_scenarios(self) -> list[StressTestScenario]:
        """Return repository-ordered current historical scenarios."""

        return [
            self._project(summary)
            for summary in self._list.execute(scenario_type=ScenarioType.HISTORICAL_WINDOW)
        ]


class StressTestingUseCase:
    """Compatibility facade delegating stress calculation to Risk Center."""

    def __init__(
        self,
        scenario_repository: ScenarioQueryRepositoryProtocol | None = None,
        portfolio_snapshot_provider: PortfolioSnapshotProviderProtocol | None = None,
        market_data_provider: ScenarioMarketDataProviderProtocol | None = None,
        recommendation_policy: StressRecommendationPolicyQueryProtocol | None = None,
        runtime_bindings: StressTestRuntimeBindings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._scenario_repository = scenario_repository or get_scenario_query_repository()
        self._scenario_catalog = HistoricalScenarioService(self._scenario_repository)
        self._portfolio_snapshots = portfolio_snapshot_provider
        self._market_data = market_data_provider
        self._recommendation_policy = recommendation_policy
        self._runtime_bindings = runtime_bindings
        self._clock = clock or (lambda: datetime.now(UTC))

    def _as_of_time(self) -> datetime:
        """Return an aware knowledge boundary for one compatibility request."""

        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise StressTestingConfigurationError("stress-test clock must be timezone-aware")
        return value

    def _required_ports(
        self,
    ) -> tuple[
        PortfolioSnapshotProviderProtocol,
        ScenarioMarketDataProviderProtocol,
        StressRecommendationPolicyQueryProtocol,
        StressTestRuntimeBindings,
    ]:
        """Fail closed instead of inventing snapshots, prices, advice, or versions."""

        if self._portfolio_snapshots is None:
            raise StressTestingConfigurationError(
                "immutable portfolio snapshot provider is not configured"
            )
        if self._market_data is None:
            raise StressTestingConfigurationError("scenario market-data provider is not configured")
        if self._recommendation_policy is None:
            raise StressTestingConfigurationError(
                "versioned stress recommendation policy is not configured"
            )
        if self._runtime_bindings is None:
            raise StressTestingConfigurationError("stress-test runtime versions are not configured")
        return (
            self._portfolio_snapshots,
            self._market_data,
            self._recommendation_policy,
            self._runtime_bindings,
        )

    def _run_scenario(
        self,
        *,
        portfolio_id: int,
        requested_identifier: str,
        scenario: StressTestScenario,
        as_of_time: datetime,
    ) -> StressTestResult:
        """Run one already-resolved revision through typed owner ports."""

        snapshot_provider, market_data, recommendation_policy, bindings = self._required_ports()
        snapshot = snapshot_provider.get_latest_snapshot_for_portfolio(
            portfolio_id,
            as_of_time=as_of_time,
        )
        if snapshot is None:
            raise ValueError(f"组合 {portfolio_id} 缺少可用的不可变快照")

        request = ScenarioRunRequestDTO(
            scenario_revision_id=scenario.revision_id,
            portfolio_snapshot_id=snapshot.snapshot_id,
            as_of_time=as_of_time,
            allocation_policy_version=bindings.allocation_policy_version,
            code_version=bindings.code_version,
        )
        impact = PreviewScenarioImpactUseCase(
            self._scenario_repository,
            snapshot_provider,
            market_data,
        ).execute(request)
        advice = recommendation_policy.evaluate(
            scenario_revision_id=scenario.revision_id,
            scenario_content_hash=scenario.content_hash,
            impact=impact,
        )
        return StressTestResult(
            scenario_id=requested_identifier,
            scenario_name=scenario.name,
            initial_value=impact.initial_value,
            final_value=impact.final_value,
            total_return=impact.total_return,
            max_drawdown=float(impact.max_drawdown),
            recovery_days=impact.recovery_periods,
            volatility=float(impact.volatility),
            var_95=float(impact.var_95),
            var_99=float(impact.var_99),
            recommendations=list(advice.recommendations),
            scenario_revision_id=scenario.revision_id,
            recommendation_policy_version=advice.policy_version,
            result_hash=impact.result_hash,
        )

    def run_historical_scenario_test(
        self,
        portfolio_id: int,
        scenario_id: str,
    ) -> StressTestResult:
        """Run a current governed historical scenario, including legacy aliases."""

        try:
            scenario = self._scenario_catalog.get_scenario(scenario_id)
        except ScenarioNotFoundError as exc:
            raise ValueError(f"情景 {scenario_id} 不存在") from exc
        return self._run_scenario(
            portfolio_id=portfolio_id,
            requested_identifier=scenario_id,
            scenario=scenario,
            as_of_time=self._as_of_time(),
        )

    def run_all_scenarios(self, portfolio_id: int) -> list[StressTestResult]:
        """Run every repository-current historical revision in catalog order."""

        scenarios = self._scenario_catalog.get_all_scenarios()
        as_of_time = self._as_of_time()
        return [
            self._run_scenario(
                portfolio_id=portfolio_id,
                requested_identifier=scenario.scenario_id,
                scenario=scenario,
                as_of_time=as_of_time,
            )
            for scenario in scenarios
        ]


__all__ = [
    "HistoricalScenarioService",
    "PortfolioSnapshotProviderProtocol",
    "StressRecommendationPolicyDecision",
    "StressRecommendationPolicyQueryProtocol",
    "StressTestResult",
    "StressTestRuntimeBindings",
    "StressTestScenario",
    "StressTestingConfigurationError",
    "StressTestingUseCase",
]
