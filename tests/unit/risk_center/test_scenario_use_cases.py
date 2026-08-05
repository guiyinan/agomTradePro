"""Application contracts using only injected fake scenario/data/portfolio ports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.application.scenario_dtos import (
    CreateScenarioRevisionCommandDTO,
    PortfolioPositionDTO,
    PortfolioSnapshotDTO,
    ScenarioMarketDataDTO,
    ScenarioRunRequestDTO,
)
from apps.risk_center.application.scenario_use_cases import (
    CreateScenarioRevisionDraftUseCase,
    ListScenarioDefinitionsUseCase,
    RunPortfolioStressTestUseCase,
    ScenarioConfigurationError,
    ScenarioRunBlockedError,
)
from apps.risk_center.domain.scenarios import (
    ParametricShock,
    ParametricShockParameters,
    ScenarioDefinition,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
)

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)


def _revision(*, version: int = 1, revision_id: str = "revision-1") -> ScenarioRevision:
    return ScenarioRevision(
        revision_id=revision_id,
        scenario_key="scenario.dynamic",
        version=version,
        based_on_version=version - 1 or None,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.PARAMETRIC_SHOCK,
        parameters=ParametricShockParameters(
            shocks=(
                ParametricShock(
                    target_kind="asset",
                    target="000001.SH",
                    shock_kind="return",
                    magnitude=Decimal("-0.25"),
                    unit=ShockUnit.PERCENT,
                    horizon_days=5,
                ),
            ),
            correlation_assumption="unchanged",
        ),
        assumptions=("explicit test shock",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="tester",
        change_reason="fake repository test",
        created_at=NOW,
    )


class FakeScenarioRepository:
    """Small mutable fake proving catalog behavior is repository-driven."""

    def __init__(self, revisions: tuple[ScenarioRevision, ...] = ()) -> None:
        self.definition = ScenarioDefinition(
            scenario_key="scenario.dynamic",
            name="Dynamic",
            category="test",
            owner="risk_center",
            created_at=NOW,
        )
        self.revisions = list(revisions)
        self.evidence: list[ScenarioRunEvidence] = []

    def list_definitions(self, *, include_retired: bool = False):  # type: ignore[no-untyped-def]
        return (self.definition,) if self.revisions else ()

    def list_current_revisions(
        self,
        *,
        scenario_type=None,  # type: ignore[no-untyped-def]
        include_inactive: bool = False,
    ):  # type: ignore[no-untyped-def]
        del include_inactive
        eligible = [
            item
            for item in self.revisions
            if scenario_type is None or item.scenario_type is scenario_type
        ]
        return tuple(sorted(eligible, key=lambda item: item.version, reverse=True)[:1])

    def get_revision(self, identifier: str, *, version: int | None = None):  # type: ignore[no-untyped-def]
        for item in self.revisions:
            if identifier in {item.revision_id, item.scenario_key} and (
                version is None or item.version == version
            ):
                return item
        return None

    def list_revisions(self, identifier: str):  # type: ignore[no-untyped-def]
        return tuple(
            sorted(
                (
                    item
                    for item in self.revisions
                    if identifier in {item.revision_id, item.scenario_key}
                ),
                key=lambda item: item.version,
                reverse=True,
            )
        )

    def get_active_set_revision(self, *, environment: str, purpose: str):  # type: ignore[no-untyped-def]
        return None

    def append_next_revision(
        self,
        command: CreateScenarioRevisionCommandDTO,
    ) -> ScenarioRevision:
        latest = max((item.version for item in self.revisions), default=0)
        if command.based_on_version != (latest or None):
            raise ValueError("version conflict")
        revision = ScenarioRevision(
            revision_id=f"revision-{latest + 1}",
            scenario_key=command.scenario_key,
            version=latest + 1,
            based_on_version=latest or None,
            status=command.status,
            scenario_type=command.scenario_type,
            parameters=command.parameters,
            assumptions=command.assumptions,
            source_type=command.source_type,
            created_by=command.created_by,
            change_reason=command.change_reason,
            created_at=NOW,
        )
        self.revisions.append(revision)
        return revision

    def save_revision(self, revision: ScenarioRevision) -> ScenarioRevision:
        self.revisions.append(revision)
        return revision

    def save_run_evidence(self, evidence: ScenarioRunEvidence) -> ScenarioRunEvidence:
        self.evidence.append(evidence)
        return evidence


class FakePortfolioProvider:
    def get_snapshot(self, snapshot_id: str, *, as_of_time: datetime):
        return PortfolioSnapshotDTO(
            snapshot_id=snapshot_id,
            account_id="account-7",
            as_of_time=as_of_time - timedelta(minutes=1),
            net_asset_value=Decimal("2000"),
            cash_value=Decimal("500"),
            positions=(PortfolioPositionDTO("000001.SH", Decimal("1500")),),
        )


class FakeMarketDataProvider:
    def __init__(self, *, observed_at: datetime = NOW - timedelta(days=1)) -> None:
        self.observed_at = observed_at

    def get_market_data(
        self,
        revision: ScenarioRevision,
        *,
        asset_codes: tuple[str, ...],
        as_of_time: datetime,
    ) -> ScenarioMarketDataDTO:
        assert asset_codes == ("000001.SH",)
        return ScenarioMarketDataDTO(
            return_series=(),
            evidence_ids=("publication:price-bars:v1",),
            observed_at=self.observed_at,
            published_at=self.observed_at + timedelta(hours=1),
        )


def test_fake_repository_drives_dynamic_catalog_and_empty_catalog_fails_closed() -> None:
    repository = FakeScenarioRepository()
    use_case = ListScenarioDefinitionsUseCase(repository)

    with pytest.raises(ScenarioConfigurationError, match="empty"):
        use_case.execute()

    repository.revisions.extend((_revision(), _revision(version=2, revision_id="revision-2")))
    summaries = use_case.execute()

    assert [item.revision.version for item in summaries] == [2]


def test_create_draft_allocates_next_version_in_repository() -> None:
    repository = FakeScenarioRepository((_revision(),))
    parameters = _revision().parameters
    command = CreateScenarioRevisionCommandDTO(
        scenario_key="scenario.dynamic",
        scenario_type=ScenarioType.PARAMETRIC_SHOCK,
        parameters=parameters,
        assumptions=("replacement",),
        source_type=ScenarioSourceType.AI_MCP,
        created_by="agent:scenario-proposer",
        change_reason="proposal",
        status=ScenarioRevisionStatus.PROPOSED,
        based_on_version=1,
    )

    saved = CreateScenarioRevisionDraftUseCase(repository).execute(command)

    assert saved.version == 2
    assert saved.based_on_version == 1
    assert saved.status is ScenarioRevisionStatus.PROPOSED


def test_stress_run_uses_snapshot_nav_and_persists_exact_evidence() -> None:
    repository = FakeScenarioRepository((_revision(),))
    request = ScenarioRunRequestDTO(
        scenario_revision_id="revision-1",
        portfolio_snapshot_id="portfolio-snapshot-1",
        as_of_time=NOW,
        allocation_policy_version="allocation-v3",
        code_version="git:abc123",
    )

    result = RunPortfolioStressTestUseCase(
        repository,
        repository,
        FakePortfolioProvider(),
        FakeMarketDataProvider(),
    ).execute(request)

    assert result.impact.initial_value == Decimal("2000")
    assert result.impact.total_return == Decimal("-0.1875")
    assert result.evidence.result_hash == result.impact.result_hash
    assert result.evidence.data_evidence_ids == ("publication:price-bars:v1",)
    assert repository.evidence == [result.evidence]


def test_future_market_observation_blocks_without_persisting_evidence() -> None:
    repository = FakeScenarioRepository((_revision(),))
    request = ScenarioRunRequestDTO(
        scenario_revision_id="revision-1",
        portfolio_snapshot_id="portfolio-snapshot-1",
        as_of_time=NOW,
        allocation_policy_version="allocation-v3",
        code_version="git:abc123",
    )

    with pytest.raises(ScenarioRunBlockedError, match="future"):
        RunPortfolioStressTestUseCase(
            repository,
            repository,
            FakePortfolioProvider(),
            FakeMarketDataProvider(observed_at=NOW + timedelta(days=1)),
        ).execute(request)

    assert repository.evidence == []
