"""Behavior contracts for the Account-to-Risk-Center stress-test facade."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.account.application.stress_testing_use_cases import (
    HistoricalScenarioService,
    StressRecommendationPolicyDecision,
    StressTestingConfigurationError,
    StressTestingUseCase,
    StressTestRuntimeBindings,
)
from apps.risk_center.application.scenario_dtos import (
    PortfolioPositionDTO,
    PortfolioSnapshotDTO,
    ScenarioMarketDataDTO,
)
from apps.risk_center.application.scenario_use_cases import ScenarioConfigurationError
from apps.risk_center.domain.scenarios import (
    AssetReturnSeries,
    HistoricalReturnPoint,
    HistoricalWindowParameters,
    ScenarioDefinition,
    ScenarioDefinitionStatus,
    ScenarioImpact,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSetRevision,
    ScenarioSourceType,
    ScenarioType,
)

AS_OF = datetime(2026, 8, 5, 9, 30, tzinfo=UTC)


def _scenario(
    *,
    scenario_key: str,
    name: str,
    revision_id: str,
    legacy_aliases: tuple[str, ...] = (),
) -> tuple[ScenarioDefinition, ScenarioRevision]:
    definition = ScenarioDefinition(
        scenario_key=scenario_key,
        name=name,
        category="historical",
        owner="risk_center",
        status=ScenarioDefinitionStatus.ACTIVE,
        description=f"{name} dynamic description",
        legacy_aliases=legacy_aliases,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    revision = ScenarioRevision(
        revision_id=revision_id,
        scenario_key=scenario_key,
        version=4,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.HISTORICAL_WINDOW,
        parameters=HistoricalWindowParameters(
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 3),
            source="data_center.published_price_bars",
            event_description=f"{name} replay window",
        ),
        assumptions=("published close-to-close returns",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="risk-owner",
        change_reason="test governed scenario",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    return definition, revision


class _ScenarioRepository:
    def __init__(
        self,
        pairs: tuple[tuple[ScenarioDefinition, ScenarioRevision], ...],
    ) -> None:
        self._pairs = pairs

    def list_definitions(
        self,
        *,
        include_retired: bool = False,
    ) -> tuple[ScenarioDefinition, ...]:
        assert include_retired is False
        return tuple(item[0] for item in self._pairs)

    def list_current_revisions(
        self,
        *,
        scenario_type: ScenarioType | None = None,
        include_inactive: bool = False,
    ) -> tuple[ScenarioRevision, ...]:
        assert include_inactive is False
        return tuple(
            revision
            for _, revision in self._pairs
            if scenario_type is None or revision.scenario_type is scenario_type
        )

    def get_revision(
        self,
        identifier: str,
        *,
        version: int | None = None,
    ) -> ScenarioRevision | None:
        for definition, revision in self._pairs:
            identifiers = {
                definition.scenario_key,
                revision.revision_id,
                *definition.legacy_aliases,
            }
            if identifier in identifiers and (version is None or revision.version == version):
                return revision
        return None

    def list_revisions(self, identifier: str) -> tuple[ScenarioRevision, ...]:
        revision = self.get_revision(identifier)
        return () if revision is None else (revision,)

    def get_active_set_revision(
        self,
        *,
        environment: str,
        purpose: str,
    ) -> ScenarioSetRevision | None:
        assert environment
        assert purpose
        return None


class _PortfolioSnapshots:
    def __init__(self, snapshot: PortfolioSnapshotDTO | None) -> None:
        self.snapshot = snapshot
        self.requested_portfolio_ids: list[int] = []

    def get_latest_snapshot_for_portfolio(
        self,
        portfolio_id: int,
        *,
        as_of_time: datetime,
    ) -> PortfolioSnapshotDTO | None:
        assert as_of_time == AS_OF
        self.requested_portfolio_ids.append(portfolio_id)
        return self.snapshot

    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        as_of_time: datetime,
    ) -> PortfolioSnapshotDTO | None:
        assert as_of_time == AS_OF
        if self.snapshot is None or snapshot_id != self.snapshot.snapshot_id:
            return None
        return self.snapshot


class _MarketData:
    def __init__(self) -> None:
        self.revision_ids: list[str] = []

    def get_market_data(
        self,
        revision: ScenarioRevision,
        *,
        asset_codes: tuple[str, ...],
        as_of_time: datetime,
    ) -> ScenarioMarketDataDTO:
        assert asset_codes == ("000001.SZ", "000002.SZ")
        assert as_of_time == AS_OF
        self.revision_ids.append(revision.revision_id)
        return ScenarioMarketDataDTO(
            return_series=(
                AssetReturnSeries(
                    asset_code="000001.SZ",
                    points=(
                        HistoricalReturnPoint(date(2024, 1, 2), Decimal("-0.10")),
                        HistoricalReturnPoint(date(2024, 1, 3), Decimal("0.05")),
                    ),
                ),
                AssetReturnSeries(
                    asset_code="000002.SZ",
                    points=(
                        HistoricalReturnPoint(date(2024, 1, 2), Decimal("0.10")),
                        HistoricalReturnPoint(date(2024, 1, 3), Decimal("-0.05")),
                    ),
                ),
            ),
            evidence_ids=("price-publication:2024-01-03",),
            observed_at=datetime(2024, 1, 3, tzinfo=UTC),
            published_at=datetime(2024, 1, 4, tzinfo=UTC),
        )


class _RecommendationPolicy:
    def __init__(self) -> None:
        self.received_impacts: list[ScenarioImpact] = []

    def evaluate(
        self,
        *,
        scenario_revision_id: str,
        scenario_content_hash: str,
        impact: ScenarioImpact,
    ) -> StressRecommendationPolicyDecision:
        assert scenario_revision_id
        assert len(scenario_content_hash) == 64
        self.received_impacts.append(impact)
        return StressRecommendationPolicyDecision(
            policy_version="risk-advice.v7",
            recommendations=("使用已审批策略版本返回的建议",),
        )


def _snapshot() -> PortfolioSnapshotDTO:
    return PortfolioSnapshotDTO(
        snapshot_id="portfolio-7@2026-08-05T09:00Z",
        account_id="portfolio-7",
        as_of_time=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
        net_asset_value=Decimal("2500000"),
        cash_value=Decimal("625000"),
        positions=(
            PortfolioPositionDTO("000001.SZ", Decimal("1250000")),
            PortfolioPositionDTO("000002.SZ", Decimal("625000")),
        ),
    )


def _use_case(
    repository: _ScenarioRepository,
    *,
    snapshot: PortfolioSnapshotDTO | None = None,
) -> tuple[StressTestingUseCase, _PortfolioSnapshots, _MarketData, _RecommendationPolicy]:
    snapshots = _PortfolioSnapshots(snapshot if snapshot is not None else _snapshot())
    market_data = _MarketData()
    recommendations = _RecommendationPolicy()
    return (
        StressTestingUseCase(
            scenario_repository=repository,
            portfolio_snapshot_provider=snapshots,
            market_data_provider=market_data,
            recommendation_policy=recommendations,
            runtime_bindings=StressTestRuntimeBindings(
                allocation_policy_version="allocation.v12",
                code_version="agomtradepro.test",
            ),
            clock=lambda: AS_OF,
        ),
        snapshots,
        market_data,
        recommendations,
    )


def test_legacy_alias_uses_repository_revision_snapshot_nav_and_policy_advice() -> None:
    repository = _ScenarioRepository(
        (
            _scenario(
                scenario_key="historical.cn_equity_2015",
                name="动态股灾回放",
                revision_id="scenario-revision-v4",
                legacy_aliases=("2015_crash",),
            ),
        )
    )
    use_case, snapshots, market_data, recommendations = _use_case(repository)

    result = use_case.run_historical_scenario_test(7, "2015_crash")

    assert result.scenario_id == "2015_crash"
    assert result.scenario_name == "动态股灾回放"
    assert result.scenario_revision_id == "scenario-revision-v4"
    assert result.initial_value == Decimal("2500000")
    assert result.final_value != Decimal("1000000")
    assert result.recommendations == ["使用已审批策略版本返回的建议"]
    assert result.recommendation_policy_version == "risk-advice.v7"
    assert len(result.result_hash) == 64
    assert snapshots.requested_portfolio_ids == [7]
    assert market_data.revision_ids == ["scenario-revision-v4"]
    assert len(recommendations.received_impacts) == 1


def test_catalog_and_run_all_are_repository_driven_without_fixed_count_or_order() -> None:
    repository = _ScenarioRepository(
        (
            _scenario(
                scenario_key="historical.second",
                name="Second from repository",
                revision_id="revision-second",
            ),
            _scenario(
                scenario_key="historical.first",
                name="First from repository",
                revision_id="revision-first",
            ),
        )
    )
    service = HistoricalScenarioService(repository)
    assert [item.scenario_id for item in service.get_all_scenarios()] == [
        "historical.second",
        "historical.first",
    ]
    use_case, _, market_data, _ = _use_case(repository)

    results = use_case.run_all_scenarios(7)

    assert [item.scenario_id for item in results] == [
        "historical.second",
        "historical.first",
    ]
    assert market_data.revision_ids == ["revision-second", "revision-first"]


def test_empty_scenario_catalog_fails_closed() -> None:
    use_case, _, _, _ = _use_case(_ScenarioRepository(()))

    with pytest.raises(ScenarioConfigurationError, match="catalog is empty"):
        use_case.run_all_scenarios(7)


def test_missing_snapshot_fails_closed_instead_of_using_default_principal() -> None:
    repository = _ScenarioRepository(
        (
            _scenario(
                scenario_key="historical.only",
                name="Only scenario",
                revision_id="revision-only",
            ),
        )
    )
    snapshots = _PortfolioSnapshots(None)
    use_case = StressTestingUseCase(
        scenario_repository=repository,
        portfolio_snapshot_provider=snapshots,
        market_data_provider=_MarketData(),
        recommendation_policy=_RecommendationPolicy(),
        runtime_bindings=StressTestRuntimeBindings("allocation.v12", "test"),
        clock=lambda: AS_OF,
    )

    with pytest.raises(ValueError, match="不可变快照"):
        use_case.run_historical_scenario_test(7, "historical.only")


def test_missing_ports_and_naive_clock_fail_closed() -> None:
    repository = _ScenarioRepository(
        (
            _scenario(
                scenario_key="historical.only",
                name="Only scenario",
                revision_id="revision-only",
            ),
        )
    )
    unconfigured = StressTestingUseCase(
        scenario_repository=repository,
        clock=lambda: AS_OF,
    )
    with pytest.raises(StressTestingConfigurationError, match="snapshot provider"):
        unconfigured.run_historical_scenario_test(7, "historical.only")

    configured = StressTestingUseCase(
        scenario_repository=repository,
        portfolio_snapshot_provider=_PortfolioSnapshots(_snapshot()),
        market_data_provider=_MarketData(),
        recommendation_policy=_RecommendationPolicy(),
        runtime_bindings=StressTestRuntimeBindings("allocation.v12", "test"),
        clock=lambda: datetime(2026, 8, 5, 9, 30),
    )
    with pytest.raises(StressTestingConfigurationError, match="timezone-aware"):
        configured.run_historical_scenario_test(7, "historical.only")


def test_unknown_scenario_keeps_legacy_value_error_contract() -> None:
    use_case, _, _, _ = _use_case(_ScenarioRepository(()))

    with pytest.raises(ValueError, match="情景 missing 不存在"):
        use_case.run_historical_scenario_test(7, "missing")
