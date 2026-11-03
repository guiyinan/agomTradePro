"""Contract tests for exact, single-call Scenario preview context retention."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.application.scenario_dtos import (
    PortfolioPositionDTO,
    PortfolioSnapshotDTO,
    ScenarioMarketDataDTO,
    ScenarioRunRequestDTO,
)
from apps.risk_center.application.scenario_use_cases import (
    PreviewScenarioImpactUseCase,
    ScenarioRunBlockedError,
    _validate_inputs,
)
from apps.risk_center.domain.portfolio_risk_sources import SourceObservationPrecision
from apps.risk_center.domain.scenarios import (
    AssetReturnSeries,
    HistoricalReturnPoint,
    ParametricShock,
    ParametricShockParameters,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
)

NOW = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)


def _revision() -> ScenarioRevision:
    """Return one approved finite scenario revision."""

    return ScenarioRevision(
        revision_id="revision-3",
        scenario_key="ash07.limit-down-pressure",
        version=3,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.PARAMETRIC_SHOCK,
        parameters=ParametricShockParameters(
            shocks=(
                ParametricShock(
                    target_kind="asset",
                    target="600000.SH",
                    shock_kind="return",
                    magnitude=Decimal("-0.2"),
                    unit=ShockUnit.PERCENT,
                    horizon_days=3,
                ),
            ),
            correlation_assumption="approved synchronous stress",
        ),
        assumptions=("finite scenario for application contract test",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="test-owner",
        change_reason="preview context contract",
        created_at=NOW,
    )


class _ScenarioRepository:
    """Return the exact immutable revision and record each lookup."""

    def __init__(self, revision: ScenarioRevision) -> None:
        self.revision = revision
        self.lookups: list[str] = []

    def get_revision(
        self,
        identifier: str,
        *,
        version: int | None = None,
    ) -> ScenarioRevision | None:
        self.lookups.append(identifier)
        if identifier != self.revision.revision_id or version is not None:
            return None
        return self.revision


class _PortfolioProvider:
    """Return one immutable simulated-account snapshot by exact snapshot id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime]] = []
        self.snapshot: PortfolioSnapshotDTO | None = None

    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        as_of_time: datetime,
    ) -> PortfolioSnapshotDTO | None:
        self.calls.append((snapshot_id, as_of_time))
        self.snapshot = PortfolioSnapshotDTO(
            snapshot_id=snapshot_id,
            account_id="simulated-account:42",
            as_of_time=as_of_time - timedelta(minutes=1),
            net_asset_value=Decimal("20000"),
            cash_value=Decimal("5000"),
            positions=(PortfolioPositionDTO("600000.SH", Decimal("15000")),),
        )
        return self.snapshot


class _MarketDataProvider:
    """Return a source-bound market series and retain the exact returned DTO."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...], datetime]] = []
        self.data: ScenarioMarketDataDTO | None = None

    def get_market_data(
        self,
        revision: ScenarioRevision,
        *,
        asset_codes: tuple[str, ...],
        as_of_time: datetime,
    ) -> ScenarioMarketDataDTO:
        self.calls.append((revision.revision_id, asset_codes, as_of_time))
        self.data = ScenarioMarketDataDTO(
            return_series=(
                AssetReturnSeries(
                    asset_code="600000.SH",
                    points=(
                        HistoricalReturnPoint(
                            observed_on=date(2026, 11, 2),
                            value=Decimal("0.01"),
                        ),
                    ),
                ),
            ),
            evidence_ids=("published-prices:v4:600000.SH",),
            observed_at=datetime(2026, 11, 2, 0, 0, tzinfo=UTC),
            published_at=datetime(2026, 11, 2, 1, 0, tzinfo=UTC),
        )
        return self.data


def _use_case() -> tuple[
    PreviewScenarioImpactUseCase,
    _ScenarioRepository,
    _PortfolioProvider,
    _MarketDataProvider,
    ScenarioRunRequestDTO,
]:
    """Assemble counting providers with one exact scenario request."""

    revision = _revision()
    scenarios = _ScenarioRepository(revision)
    portfolios = _PortfolioProvider()
    market_data = _MarketDataProvider()
    request = ScenarioRunRequestDTO(
        scenario_revision_id=revision.revision_id,
        portfolio_snapshot_id="simulated-account:42:snapshot:17",
        as_of_time=NOW,
        allocation_policy_version="allocation-v4",
        code_version="server-source-sha256:abc",
    )
    return (
        PreviewScenarioImpactUseCase(scenarios, portfolios, market_data),
        scenarios,
        portfolios,
        market_data,
        request,
    )


def test_preview_context_retains_exact_inputs_from_one_provider_call_each() -> None:
    """The result and evidence context share one revision, snapshot, and data read."""

    use_case, scenarios, portfolios, market_data, request = _use_case()

    context = use_case.execute_with_context(request)

    assert scenarios.lookups == [request.scenario_revision_id]
    assert portfolios.calls == [(request.portfolio_snapshot_id, request.as_of_time)]
    assert market_data.calls == [(request.scenario_revision_id, ("600000.SH",), request.as_of_time)]
    assert context.revision is scenarios.revision
    assert context.snapshot is portfolios.snapshot
    assert context.market_data is market_data.data
    assert context.request is request
    assert context.snapshot.content_hash
    assert context.revision.content_hash
    assert context.market_data.evidence_ids == ("published-prices:v4:600000.SH",)
    assert context.impact.scenario_revision_id == context.revision.revision_id


def test_legacy_execute_still_returns_the_same_scenario_impact() -> None:
    """The old public method remains a value-compatible impact-only API."""

    context_case, _scenarios, _portfolios, _market_data, request = _use_case()
    context_impact = context_case.execute_with_context(request).impact
    legacy_case, _scenarios, _portfolios, _market_data, legacy_request = _use_case()

    legacy_impact = legacy_case.execute(legacy_request)

    assert legacy_impact == context_impact


def test_date_only_observation_must_precede_cutoff_day_without_synthetic_time() -> None:
    """Date precision keeps its date and cannot stand in for midnight UTC."""

    use_case, _scenarios, _portfolios, _market_data, request = _use_case()
    context = use_case.execute_with_context(request)
    prior_day = replace(
        context.market_data,
        observed_at=None,
        observed_on=date(2026, 11, 2),
        observation_precision=SourceObservationPrecision.DATE,
    )
    same_day = replace(
        prior_day,
        observed_on=date(2026, 11, 3),
    )

    _validate_inputs(request, context.snapshot, prior_day)
    assert replace(context, market_data=prior_day).market_data is prior_day
    with pytest.raises(ScenarioRunBlockedError, match="date_not_before_cutoff"):
        _validate_inputs(request, context.snapshot, same_day)
    with pytest.raises(ValueError, match="not before cutoff"):
        replace(context, market_data=same_day)
