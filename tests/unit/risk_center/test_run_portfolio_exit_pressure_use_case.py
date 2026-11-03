"""Application contracts for source-bound, idempotent pressure runs."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.application.portfolio_exit_pressure_dtos import (
    PortfolioPressureProjection,
    RunPortfolioExitPressureCommand,
)
from apps.risk_center.application.portfolio_exit_pressure_use_cases import (
    RunPortfolioExitPressureUseCase,
)
from apps.risk_center.application.portfolio_pressure_report import (
    decode_portfolio_risk_report_json,
)
from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskCheckPayload,
    PortfolioRiskReportPayload,
)
from apps.risk_center.application.portfolio_risk_order_admission import (
    build_portfolio_risk_order_admission,
)
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.risk_center.application.portfolio_risk_snapshot import AccountSnapshot, HeldPosition
from apps.risk_center.application.scenario_dtos import (
    PortfolioPositionDTO,
    PortfolioSnapshotDTO,
    ScenarioMarketDataDTO,
    ScenarioRunRequestDTO,
)
from apps.risk_center.application.scenario_impact_context import ScenarioImpactContext
from apps.risk_center.application.scenario_use_cases import ScenarioRunBlockedError
from apps.risk_center.domain.portfolio_exit_pressure import (
    ExitCapacityWindow,
    ExitPressurePosition,
)
from apps.risk_center.domain.portfolio_risk_identity import PortfolioRiskIdentityBinding
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from apps.risk_center.domain.scenarios import (
    AssetReturnSeries,
    HistoricalReturnPoint,
    ParametricShock,
    ParametricShockParameters,
    ScenarioImpact,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
    scenario_run_snapshot_hash,
)
from core.exceptions import DuplicateResourceError

NOW = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)
SNAPSHOT_ID = "simulated-account:42:" + ("e" * 64)


def _revision() -> ScenarioRevision:
    """Return one approved finite stress revision."""

    return ScenarioRevision(
        revision_id="scenario-revision-3",
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
                    magnitude=Decimal("-0.3"),
                    unit=ShockUnit.PERCENT,
                    horizon_days=3,
                ),
            ),
            correlation_assumption="synchronous stress",
        ),
        assumptions=("explicitly approved test revision",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="test-owner",
        change_reason="pressure use-case contract",
        created_at=NOW,
    )


def _source_evidence(
    *,
    cutoff: datetime = NOW,
    coverage_status: CoverageStatus = CoverageStatus.PARTIAL,
) -> PortfolioRiskSourceEvidence:
    """Return one source with original hash and distinct observation clocks."""

    return PortfolioRiskSourceEvidence(
        source_id="capacity-provider:daily-bars",
        source_record_id="daily-bars:2026-11-02",
        original_payload_sha256="a" * 64,
        observation_precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=datetime.fromisoformat("2026-11-02T08:00:00+08:00"),
        observed_on=None,
        available_at=datetime(2026, 11, 2, 1, 0, tzinfo=UTC),
        known_at=datetime(2026, 11, 2, 1, 5, tzinfo=UTC),
        decision_cutoff=cutoff,
        decision_date_cutoff=None,
        valid_until=datetime(2026, 11, 4, 0, 0, tzinfo=UTC),
        source_purpose="historical_liquidity",
        allowed_purposes=("scenario_exit_pressure",),
        restrictions=("historical_only",),
        must_not_use_for_decision=False,
        coverage=PortfolioRiskCoverage(
            status=coverage_status,
            precision_basis="reported_sessions",
            reported_weight_fraction=(
                Decimal("1")
                if coverage_status is CoverageStatus.COMPLETE
                else Decimal("0.750000000000000000000000000000001")
            ),
            expected_item_count=4,
            observed_item_count=(4 if coverage_status is CoverageStatus.COMPLETE else 3),
        ),
    )


def _position(*, capacity: Decimal = Decimal("600")) -> ExitPressurePosition:
    """Return one current position with an explicit source-bound capacity window."""

    return ExitPressurePosition(
        asset_code="600000.SH",
        quantity=Decimal("1000"),
        quantity_unit="shares",
        market_value=Decimal("15000"),
        pending_sell_quantity=Decimal("200"),
        capacity_windows=(
            ExitCapacityWindow(
                session_date=date(2026, 11, 3),
                exitable_quantity=capacity,
                quantity_unit="shares",
                reason_codes=("stress_liquidity_reduced_capacity",),
                source_evidence_ids=("capacity-provider:daily-bars:daily-bars:2026-11-02",),
            ),
        ),
    )


def _projection(
    *,
    position: ExitPressurePosition | None = None,
    source_evidence: tuple[PortfolioRiskSourceEvidence, ...] | None = None,
) -> PortfolioPressureProjection:
    """Build a locked account projection with real source evidence types."""

    base_check: PortfolioRiskCheckPayload = {
        "dimension": "baseline_risk",
        "status": "allowed",
        "reason_codes": [],
        "summary": "账户基础限制已核对",
        "details": {"basis": "source_bound"},
    }
    context_hash = portfolio_risk_content_hash(
        {"account_snapshot": _account_snapshot(), "as_of": NOW}
    )
    original_report: PortfolioRiskReportPayload = {
        "account_id": 42,
        "as_of": NOW.isoformat(),
        "outcome": "allowed",
        "policy_version": "profile@7",
        "resource_snapshot_hash": context_hash,
        "checks": [base_check],
        "sources": [],
        "freshness": "qualified_snapshot",
        "reliability": "source_bound",
        "must_not_use_for_decision": False,
        "scope": "simulation_only",
        "must_not_execute": True,
    }
    original_report["order_admission"] = build_portfolio_risk_order_admission(
        subjects=(("pressure-contract-order", "buy"),),
        checks=(base_check,),
        must_not_use_for_decision=False,
        subject_id="pressure-contract-subject",
    )
    return PortfolioPressureProjection(
        portfolio_snapshot_id=SNAPSHOT_ID,
        allocation_policy_version="portfolio-risk-binding:" + ("b" * 64),
        code_version="server-source-sha256:" + ("c" * 64),
        scenario_revision_id=_revision().revision_id,
        scenario_revision_hash=_revision().content_hash,
        positions=(position or _position(),),
        source_evidence_ids=("capacity-provider:daily-bars:daily-bars:2026-11-02",),
        source_evidence=source_evidence or (_source_evidence(),),
        account_snapshot=_account_snapshot(),
        identity_bindings=(
            PortfolioRiskIdentityBinding(
                asset_code="600000.SH",
                ledger_security_id="600000.SH",
                source_security_id="600000.SH",
                basis="ledger",
            ),
        ),
        native_account_limits=PortfolioRiskNativeAccountLimits(
            max_single_weight=Decimal("0.20"),
            max_total_weight=Decimal("0.95"),
            reason_codes=(),
            basis="simulated_account_percent_fields",
        ),
        money_unit_basis="native_simulated_ledger_config",
        calendar_evidence_json=canonical_portfolio_risk_json(
            {
                "provider": "test-calendar-provider",
                "evidence_hash": "d" * 64,
                "open_sessions": ["2026-11-03"],
            }
        ),
        original_report_json=canonical_portfolio_risk_json(original_report),
        scenario_label="连续跌停压力",
    )


def _account_snapshot(*, snapshot_id: str = SNAPSHOT_ID) -> AccountSnapshot:
    """Return exact owner account inputs retained by the pressure projection."""

    return AccountSnapshot(
        account_id=42,
        owner_user_id=77,
        snapshot_id=snapshot_id,
        read_at=NOW - timedelta(minutes=2),
        cash=Decimal("5000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code="600000.SH",
                quantity=Decimal("1000"),
                available_quantity=Decimal("800"),
                security_id="600000.SH",
            ),
        ),
        active_orders=(),
        executed_usage=(),
        active_orders_complete=True,
        execution_session=date(2026, 11, 3),
        executed_usage_complete=True,
    )


def _context(request: ScenarioRunRequestDTO, *, market_data: ScenarioMarketDataDTO | None = None):
    """Build the exact returned Scenario context without live data reads."""

    revision = _revision()
    snapshot = PortfolioSnapshotDTO(
        snapshot_id=SNAPSHOT_ID,
        account_id="simulated-account:42",
        as_of_time=request.as_of_time - timedelta(minutes=1),
        net_asset_value=Decimal("20000"),
        cash_value=Decimal("5000"),
        positions=(PortfolioPositionDTO("600000.SH", Decimal("15000")),),
    )
    data = market_data or ScenarioMarketDataDTO(
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
        evidence_ids=("published-price-bars:v4:600000.SH",),
        observed_at=datetime(2026, 11, 2, 0, 0, tzinfo=UTC),
        published_at=datetime(2026, 11, 2, 1, 0, tzinfo=UTC),
    )
    impact = ScenarioImpact(
        scenario_revision_id=revision.revision_id,
        initial_value=Decimal("20000"),
        final_value=Decimal("14000"),
        total_return=Decimal("-0.3"),
        max_drawdown=Decimal("0.3"),
        recovery_periods=0,
        volatility=Decimal("0"),
        var_95=Decimal("0.3"),
        var_99=Decimal("0.3"),
        period_start=None,
        period_end=None,
        result_hash="d" * 64,
    )
    return ScenarioImpactContext(
        request=request,
        revision=revision,
        snapshot=snapshot,
        market_data=data,
        impact=impact,
    )


class _Clock:
    """Supply one deterministic aware run cutoff."""

    def now(self) -> datetime:
        return NOW


class _ProjectionProvider:
    """Return the exact locked simulated-account projection and capture scope."""

    def __init__(self, projection: PortfolioPressureProjection | None = None) -> None:
        self.projection = projection or _projection()
        self.calls: list[tuple[int, int, str, datetime]] = []

    def get_pressure_projection(
        self,
        *,
        actor_user_id: int,
        account_id: int,
        scenario_revision_id: str,
        as_of_time: datetime,
    ) -> PortfolioPressureProjection | None:
        self.calls.append((actor_user_id, account_id, scenario_revision_id, as_of_time))
        return self.projection


class _Preview:
    """Return one exact context and count preview invocations."""

    def __init__(self) -> None:
        self.calls: list[ScenarioRunRequestDTO] = []

    def execute_with_context(self, request: ScenarioRunRequestDTO) -> ScenarioImpactContext:
        self.calls.append(request)
        return _context(request)


class _EvidenceRepository:
    """Mimic the existing append-only run idempotency behavior."""

    def __init__(self) -> None:
        self.evidence: list[ScenarioRunEvidence] = []

    def save_run_evidence(self, evidence: ScenarioRunEvidence) -> ScenarioRunEvidence:
        existing = next((item for item in self.evidence if item.run_id == evidence.run_id), None)
        if existing is not None:
            if (
                existing.result_hash != evidence.result_hash
                or existing.input_snapshot_json != evidence.input_snapshot_json
                or existing.result_snapshot_json != evidence.result_snapshot_json
            ):
                raise ValueError("scenario run id already exists with different evidence")
            return existing
        self.evidence.append(evidence)
        return evidence

    def get_run_evidence(self, run_id: str) -> ScenarioRunEvidence | None:
        """Return a previously saved evidence row by deterministic identity."""

        return next((item for item in self.evidence if item.run_id == run_id), None)


def _run_use_case(
    *,
    provider: _ProjectionProvider | None = None,
    preview: _Preview | None = None,
    evidence: _EvidenceRepository | None = None,
) -> tuple[RunPortfolioExitPressureUseCase, _ProjectionProvider, _Preview, _EvidenceRepository]:
    """Assemble a pressure use case from application ports only."""

    resolved_provider = provider or _ProjectionProvider()
    resolved_preview = preview or _Preview()
    resolved_evidence = evidence or _EvidenceRepository()
    use_case = RunPortfolioExitPressureUseCase(
        preview=resolved_preview,
        run_evidence_repository=resolved_evidence,
        projection_provider=resolved_provider,
        clock=_Clock(),
    )
    return use_case, resolved_provider, resolved_preview, resolved_evidence


def _command() -> RunPortfolioExitPressureCommand:
    """Return one explicitly confirmed user-scoped run command."""

    return RunPortfolioExitPressureCommand(
        actor_user_id=77,
        account_id=42,
        scenario_version_id="scenario-revision-3",
        idempotency_key="pressure-run-1",
        confirmed=True,
    )


def test_pressure_run_binds_context_sources_and_saves_one_idempotent_record() -> None:
    """A repeated same-content request returns the existing exact run evidence."""

    projection = _projection()
    use_case, provider, preview, evidence = _run_use_case(provider=_ProjectionProvider(projection))
    assert projection.original_report_json is not None

    first = use_case.execute(_command())
    second = use_case.execute(_command())

    assert provider.calls == [
        (77, 42, "scenario-revision-3", NOW),
        (77, 42, "scenario-revision-3", NOW),
    ]
    assert len(preview.calls) == 2
    assert len(evidence.evidence) == 1
    assert first.evidence == second.evidence
    assert first.evidence.portfolio_snapshot_id == SNAPSHOT_ID
    assert first.evidence.portfolio_snapshot_hash == first.context.snapshot.content_hash
    assert first.evidence.allocation_policy_version == _projection().allocation_policy_version
    assert "published-price-bars:v4:600000.SH" in first.evidence.data_evidence_ids
    assert "capacity-provider:daily-bars:daily-bars:2026-11-02" in first.evidence.data_evidence_ids
    assert first.evidence.input_snapshot_json is not None
    assert first.evidence.result_snapshot_json is not None
    saved_inputs = json.loads(first.evidence.input_snapshot_json)
    assert saved_inputs["original_report_json"] == projection.original_report_json
    assert saved_inputs["account_projection"]["original_report_json"] == (
        projection.original_report_json
    )
    assert saved_inputs["request"]["allocation_policy_version"] == (
        first.evidence.allocation_policy_version
    )
    assert saved_inputs["account_projection"]["allocation_policy_version"] == (
        first.evidence.allocation_policy_version
    )
    saved_report = json.loads(saved_inputs["original_report_json"])
    assert saved_report["policy_version"] == "profile@7"
    assert saved_report["policy_version"] != first.evidence.allocation_policy_version
    assert (
        saved_report["resource_snapshot_hash"]
        == json.loads(projection.original_report_json)["resource_snapshot_hash"]
    )
    assert saved_report["resource_snapshot_hash"] == portfolio_risk_content_hash(
        {"account_snapshot": _account_snapshot(), "as_of": NOW}
    )
    assert len(saved_report["resource_snapshot_hash"]) == 64
    assert saved_report["order_admission"]["subject_id"] == "pressure-contract-subject"
    assert saved_inputs["account_projection"]["calendar_evidence_json"] == (
        _projection().calendar_evidence_json
    )
    assert '"observed_at":"2026-11-02T08:00:00+08:00"' in first.evidence.input_snapshot_json
    assert (
        '"reported_weight_fraction":"0.750000000000000000000000000000001"'
        in first.evidence.input_snapshot_json
    )
    assert first.evidence.result_hash == scenario_run_snapshot_hash(
        input_snapshot_json=first.evidence.input_snapshot_json,
        result_snapshot_json=first.evidence.result_snapshot_json,
    )
    assert first.evidence.result_hash != first.assessment.result_hash
    assert saved_inputs["account_projection"]["account_snapshot"]["cash"] == "5000"
    assert (
        saved_inputs["account_projection"]["account_snapshot"]["holdings"][0]["security_id"]
        == "600000.SH"
    )
    native_limits = saved_inputs["account_projection"]["native_account_limits"]
    assert native_limits["max_single_weight"] == "0.20"
    assert native_limits["max_total_weight"] == "0.95"
    assert native_limits["basis"] == "simulated_account_percent_fields"
    saved_result = json.loads(first.evidence.result_snapshot_json)
    assert saved_result["public_report_template"]["order_admission"] == (
        saved_report["order_admission"]
    )
    assert saved_result["assessment"]["result_hash"] == first.assessment.result_hash
    assert first.assessment.scenario_market_data_hash
    assert first.assessment.source_manifest_hash
    assert first.assessment.findings[0].unreleased_exposure_quantity == Decimal("1000")
    assert first.public_report_template["must_not_use_for_decision"] is True
    assert first.public_report_template["checks"][-1]["status"] == "partial"
    assert first.public_report_template["checks"][-1]["details"]["run_evidence_persisted"] is True
    assert first.public_report_template["checks"][-1]["details"]["source_evidence_ids"] == [
        "capacity-provider:daily-bars:daily-bars:2026-11-02",
        "published-price-bars:v4:600000.SH",
    ]
    assert "public_report_template" in saved_result


def test_report_codec_accepts_legacy_and_preserves_optional_order_admission() -> None:
    """The report codec keeps old payloads and losslessly validates the typed extension."""

    projection = _projection()
    encoded = projection.original_report_json
    assert encoded is not None
    decoded = decode_portfolio_risk_report_json(encoded)
    assert decoded is not None
    assert decoded["order_admission"] == json.loads(encoded)["order_admission"]
    assert decoded["resource_snapshot_hash"] == json.loads(encoded)["resource_snapshot_hash"]

    prefixed_report: dict[str, object] = json.loads(encoded)
    prefixed_hash = "sha256:" + ("f" * 64)
    prefixed_report["resource_snapshot_hash"] = prefixed_hash
    prefixed_decoded = decode_portfolio_risk_report_json(
        canonical_portfolio_risk_json(prefixed_report)
    )
    assert prefixed_decoded is not None
    assert prefixed_decoded["resource_snapshot_hash"] == prefixed_hash

    legacy_report: dict[str, object] = json.loads(encoded)
    del legacy_report["order_admission"]
    legacy_encoded = canonical_portfolio_risk_json(legacy_report)
    legacy_decoded = decode_portfolio_risk_report_json(legacy_encoded)
    assert legacy_decoded is not None
    assert "order_admission" not in legacy_decoded

    invalid_report: dict[str, object] = json.loads(encoded)
    admission = invalid_report["order_admission"]
    assert isinstance(admission, dict)
    decisions = admission["decisions"]
    assert isinstance(decisions, list) and isinstance(decisions[0], dict)
    decisions[0]["side"] = "hold"
    assert decode_portfolio_risk_report_json(canonical_portfolio_risk_json(invalid_report)) is None


def test_snapshot_value_mismatch_blocks_before_any_scenario_evidence_write() -> None:
    """A pressure projection cannot be attached to a different valued snapshot."""

    wrong_position = ExitPressurePosition(
        asset_code="600000.SH",
        quantity=Decimal("1000"),
        quantity_unit="shares",
        market_value=Decimal("14000"),
        pending_sell_quantity=Decimal("0"),
        capacity_windows=(_position().capacity_windows[0],),
    )
    provider = _ProjectionProvider(_projection(position=wrong_position))
    use_case, _provider, _preview, evidence = _run_use_case(provider=provider)

    with pytest.raises(ScenarioRunBlockedError, match="position_value_mismatch"):
        use_case.execute(_command())

    assert evidence.evidence == []


def test_source_cutoff_mismatch_blocks_before_preview_or_evidence_write() -> None:
    """Source bundle cutoffs must equal the server-provided run cutoff."""

    stale_source = _source_evidence(cutoff=NOW - timedelta(seconds=1))
    provider = _ProjectionProvider(_projection(source_evidence=(stale_source,)))
    use_case, _provider, preview, evidence = _run_use_case(provider=provider)

    with pytest.raises(ScenarioRunBlockedError, match="source_cutoff_mismatch"):
        use_case.execute(_command())

    assert preview.calls == []
    assert evidence.evidence == []


def test_foreign_snapshot_namespace_blocks_before_preview_or_evidence_write() -> None:
    """An owner mismatch is rejected before reading market data for that snapshot."""

    foreign_id = "simulated-account:43:snapshot:x"
    foreign = replace(
        _projection(),
        portfolio_snapshot_id=foreign_id,
        account_snapshot=_account_snapshot(snapshot_id=foreign_id),
    )
    provider = _ProjectionProvider(foreign)
    use_case, _provider, preview, evidence = _run_use_case(provider=provider)

    with pytest.raises(ScenarioRunBlockedError, match="snapshot_namespace_mismatch"):
        use_case.execute(_command())

    assert preview.calls == []
    assert evidence.evidence == []


def test_projection_scenario_revision_hash_must_match_the_single_preview_context() -> None:
    """Capacity assumptions and the retained Scenario impact use the same revision."""

    wrong_revision = replace(_projection(), scenario_revision_hash="f" * 64)
    use_case, _provider, _preview, evidence = _run_use_case(
        provider=_ProjectionProvider(wrong_revision),
    )

    with pytest.raises(ScenarioRunBlockedError, match="scenario_revision_mismatch"):
        use_case.execute(_command())

    assert evidence.evidence == []


def test_policy_pinned_identity_preserves_missing_ledger_identity_in_evidence() -> None:
    """A pinned valuation identity never overwrites the account's unknown ledger id."""

    original_snapshot = _account_snapshot()
    unresolved_snapshot = replace(
        original_snapshot,
        holdings=(replace(original_snapshot.holdings[0], security_id=None),),
    )
    projection = replace(
        _projection(),
        account_snapshot=unresolved_snapshot,
        identity_bindings=(
            PortfolioRiskIdentityBinding(
                asset_code="600000.SH",
                ledger_security_id=None,
                source_security_id="600000.SH",
                basis="pinned_policy_source_mapping",
            ),
        ),
    )
    use_case, _provider, _preview, _evidence = _run_use_case(
        provider=_ProjectionProvider(projection),
    )

    result = use_case.execute(_command())

    assert result.evidence.input_snapshot_json is not None
    saved_inputs = json.loads(result.evidence.input_snapshot_json)
    saved_holding = saved_inputs["account_projection"]["account_snapshot"]["holdings"][0]
    saved_binding = saved_inputs["account_projection"]["identity_bindings"][0]
    assert saved_holding["security_id"] is None
    assert saved_binding["ledger_security_id"] is None
    assert saved_binding["basis"] == "pinned_policy_source_mapping"


def test_partial_pressure_result_cannot_be_marked_decision_usable() -> None:
    """A limited stress-capacity result is partial and must preserve the prohibition."""

    use_case, _provider, _preview, _evidence = _run_use_case()

    result = use_case.execute(_command())

    assert result.public_report_template["checks"][-1]["status"] == "partial"
    assert result.public_report_template["must_not_use_for_decision"] is True
    assert result.public_report_template["freshness"] == "qualified_snapshot"
    assert result.public_report_template["reliability"] == "source_bound"
    assert result.evidence.must_not_use_for_decision is True


def test_known_zero_exit_limit_remains_a_veto_without_becoming_unknown() -> None:
    """A known blocked result can veto without being mislabeled as missing evidence."""

    provider = _ProjectionProvider(
        _projection(
            position=_position(capacity=Decimal("0")),
            source_evidence=(_source_evidence(coverage_status=CoverageStatus.COMPLETE),),
        )
    )
    use_case, _provider, _preview, _evidence = _run_use_case(provider=provider)

    result = use_case.execute(_command())

    assert result.public_report_template["checks"][-1]["status"] == "blocked"
    assert result.public_report_template["must_not_use_for_decision"] is False
    assert result.evidence.must_not_use_for_decision is False


def test_changed_inputs_under_the_same_key_are_rejected_as_conflict() -> None:
    """Same idempotency identity cannot accept a changed capacity digest."""

    evidence = _EvidenceRepository()
    first_use_case, _provider, _preview, _evidence = _run_use_case(evidence=evidence)
    first_use_case.execute(_command())

    changed_provider = _ProjectionProvider(_projection(position=_position(capacity=Decimal("300"))))
    changed_use_case, _provider, _preview, _evidence = _run_use_case(
        provider=changed_provider,
        evidence=evidence,
    )

    with pytest.raises(DuplicateResourceError):
        changed_use_case.execute(_command())


def test_invalid_confirmation_cannot_construct_a_pressure_command() -> None:
    """The application command requires literal true before running the use case."""

    with pytest.raises(ValueError, match="literal confirmation"):
        RunPortfolioExitPressureCommand(
            actor_user_id=77,
            account_id=42,
            scenario_version_id="scenario-revision-3",
            idempotency_key="pressure-run-1",
            confirmed=False,
        )
