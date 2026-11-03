"""Focused contract tests for approved exit assumptions and bounded factor exposure."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from apps.risk_center.application.portfolio_pressure_factor_projection import (
    PressureHeldAsset,
    _source_usable_for_projection,
    etf_upper_industry_loading,
    validate_exit_shock_assumption,
)
from apps.risk_center.application.portfolio_pressure_projection_builder import (
    _aggregate_held_positions,
    _aggregate_held_quantities,
    _build_pressure_positions,
    _future_capacity_window,
    _matching_exit_shocks,
    _preflight_reasons,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload
from apps.risk_center.application.portfolio_risk_snapshot import PortfolioRiskAssessmentResult
from apps.risk_center.domain.portfolio_exposure_types import (
    ETFExposureBound,
    ETFIndustryExposureBound,
    PortfolioAssetKind,
    PortfolioExposureProjection,
)
from apps.risk_center.domain.portfolio_risk_snapshot import AccountSnapshot, HeldPosition
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from apps.risk_center.domain.scenarios import (
    ParametricShock,
    ParametricShockParameters,
    PortfolioExposure,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
    evaluate_scenario,
    scenario_factor_loading_attribute,
)


def _shock(
    kind: str,
    *,
    magnitude: str = "-1",
    target_kind: str = "asset",
    target: str = "ETF1",
) -> ParametricShock:
    return ParametricShock(
        target_kind=target_kind,
        target=target,
        shock_kind=kind,
        magnitude=Decimal(magnitude),
        unit=ShockUnit.PERCENT,
        horizon_days=5,
    )


def _revision(shock: ParametricShock) -> ScenarioRevision:
    return ScenarioRevision(
        revision_id="pressure-revision-1",
        scenario_key="pressure.test",
        version=1,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.PARAMETRIC_SHOCK,
        parameters=ParametricShockParameters(
            shocks=(shock,),
            correlation_assumption="explicit deterministic test assumption",
        ),
        assumptions=(),
        source_type=ScenarioSourceType.HUMAN,
        created_by="risk-owner",
        change_reason="approved pressure test",
    )


def _snapshot(*, holdings: tuple[HeldPosition, ...]) -> AccountSnapshot:
    return AccountSnapshot(
        account_id=7,
        owner_user_id=11,
        snapshot_id="simulated-account:7:0123456789abcdef",
        read_at=datetime(2026, 11, 2, 8, tzinfo=UTC),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=holdings,
        active_orders=(),
        executed_usage=(),
        active_orders_complete=True,
        execution_session=date(2026, 11, 2),
        executed_usage_complete=True,
    )


def _held_asset() -> PressureHeldAsset:
    asset = PortfolioRiskAssetInputs(
        asset_code="ETF1",
        security_id="security-1",
        kind=PortfolioAssetKind.ETF,
        price=None,
        quantity_unit="share",
        price_unit="CNY",
        valuation_evidence=None,
        industry_membership=None,
        etf_report=None,
        capacity_observation=None,
    )
    return PressureHeldAsset(
        asset_code="ETF1",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        market_value=Decimal("500"),
        quantity_unit="share",
        asset_input=asset,
        scenario_attributes=(
            ("asset_class", "etf"),
            scenario_factor_loading_attribute("banking", Decimal("0.40")),
        ),
    )


def _evidence(
    *,
    as_of: datetime,
    restrictions: tuple[str, ...] = (),
) -> PortfolioRiskSourceEvidence:
    return PortfolioRiskSourceEvidence(
        source_id="industry-source",
        source_record_id="record-1",
        original_payload_sha256="a" * 64,
        observation_precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=as_of - timedelta(minutes=1),
        observed_on=None,
        available_at=as_of - timedelta(minutes=1),
        known_at=as_of - timedelta(minutes=1),
        decision_cutoff=as_of,
        decision_date_cutoff=None,
        valid_until=as_of + timedelta(hours=1),
        source_purpose="industry_membership",
        allowed_purposes=("industry-risk",),
        restrictions=restrictions,
        must_not_use_for_decision=False,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis="full_weight",
            reported_weight_fraction=Decimal("1"),
        ),
    )


def test_pressure_preflight_separates_config_version_from_composite_binding() -> None:
    cutoff = datetime(2026, 11, 2, 8, tzinfo=UTC)
    snapshot = _snapshot(holdings=())
    report: PortfolioRiskReportPayload = {
        "account_id": snapshot.account_id,
        "as_of": cutoff.isoformat(),
        "outcome": "allowed",
        "policy_version": "ash07-simulation-profile@12",
        "resource_snapshot_hash": "sha256:" + "a" * 64,
        "checks": [],
        "sources": [],
        "freshness": "qualified_snapshot",
        "reliability": "source_bound",
        "must_not_use_for_decision": False,
        "scope": "simulation_only",
        "must_not_execute": True,
    }
    assessment = PortfolioRiskAssessmentResult(
        report_payload=report,
        exposure_projection=PortfolioExposureProjection(
            portfolio_snapshot_id=snapshot.snapshot_id,
            as_of=cutoff,
            business_date=cutoff.date(),
            portfolio_market_value=Decimal("1000"),
            assets=(),
        ),
        industry_assessment=None,
        capacity_decisions=(),
        all_source_evidence=(),
        reason_codes=(),
    )
    asset_inputs = PortfolioRiskAssetsReadResult(
        status="complete",
        assets=(),
        all_source_evidence=(),
        reason_codes=(),
        policy_snapshot_id="ash07-simulation-profile-snapshot-12",
        policy_snapshot_hash="b" * 64,
    )
    scenario_revision = _revision(_shock("return"))
    policy_binding_sha256 = "c" * 64
    composite_binding = f"portfolio-risk-binding:{policy_binding_sha256}"

    reasons = _preflight_reasons(
        account_snapshot=snapshot,
        assessment=assessment,
        asset_inputs=asset_inputs,
        scenario_revision=scenario_revision,
        as_of_time=cutoff,
        risk_policy_version="ash07-simulation-profile@12",
        policy_binding_sha256=policy_binding_sha256,
        allocation_policy_version=composite_binding,
        identity_bindings=(),
    )
    wrong_profile_reasons = _preflight_reasons(
        account_snapshot=snapshot,
        assessment=assessment,
        asset_inputs=asset_inputs,
        scenario_revision=scenario_revision,
        as_of_time=cutoff,
        risk_policy_version="different-simulation-profile@12",
        policy_binding_sha256=policy_binding_sha256,
        allocation_policy_version=composite_binding,
        identity_bindings=(),
    )
    wrong_composite_reasons = _preflight_reasons(
        account_snapshot=snapshot,
        assessment=assessment,
        asset_inputs=asset_inputs,
        scenario_revision=scenario_revision,
        as_of_time=cutoff,
        risk_policy_version="ash07-simulation-profile@12",
        policy_binding_sha256=policy_binding_sha256,
        allocation_policy_version="portfolio-risk-binding:" + "d" * 64,
        identity_bindings=(),
    )

    assert reasons == ()
    assert wrong_profile_reasons == ("PORTFOLIO_PRESSURE_POLICY_VERSION_MISMATCH",)
    assert wrong_composite_reasons == ("PORTFOLIO_PRESSURE_POLICY_BINDING_MISMATCH",)
    assert composite_binding != report["policy_version"]


def test_factor_return_uses_explicit_etf_upper_loading() -> None:
    shock = _shock("return", magnitude="-0.50", target_kind="factor", target="banking")
    revision = _revision(shock)
    exposure = PortfolioExposure(
        asset_code="ETF1",
        weight=Decimal("1"),
        attributes=(scenario_factor_loading_attribute("banking", Decimal("0.40")),),
    )

    impact = evaluate_scenario(
        revision,
        exposures=(exposure,),
        initial_value=Decimal("100"),
        return_series=(),
    )

    assert impact.total_return == Decimal("-0.20")


def test_factor_loading_attribute_preserves_all_decimal_digits() -> None:
    loading = Decimal("0.123456789012345678901234567890123456789")

    attribute = scenario_factor_loading_attribute("banking", loading)

    assert Decimal(attribute[1]) == loading


def test_legacy_exact_factor_match_remains_full_strength() -> None:
    revision = _revision(
        _shock("return", magnitude="-0.50", target_kind="factor", target="banking")
    )
    exposure = PortfolioExposure(
        asset_code="BANK1",
        weight=Decimal("1"),
        attributes=(("factor", "banking"),),
    )

    impact = evaluate_scenario(
        revision,
        exposures=(exposure,),
        initial_value=Decimal("100"),
        return_series=(),
    )

    assert impact.total_return == Decimal("-0.50")


def test_duplicate_ledger_rows_for_one_etf_are_aggregated_once() -> None:
    snapshot = _snapshot(
        holdings=(
            HeldPosition("ETF1", Decimal("40"), Decimal("40"), "security-1"),
            HeldPosition("ETF1", Decimal("60"), Decimal("60"), "security-1"),
        )
    )

    assert _aggregate_held_quantities(snapshot) == {"ETF1": Decimal("100")}
    assert _aggregate_held_positions(snapshot) == {"ETF1": (Decimal("100"), Decimal("100"))}


def test_duplicate_position_with_unknown_available_quantity_stays_unknown() -> None:
    positions = _aggregate_held_positions(
        _snapshot(
            holdings=(
                HeldPosition("ETF1", Decimal("40"), Decimal("40"), "security-1"),
                HeldPosition("ETF1", Decimal("60"), None, "security-1"),
            )
        )
    )

    assert positions == {"ETF1": (Decimal("100"), None)}


def test_etf_factor_loading_uses_upper_bound_including_unclassified_remainder() -> None:
    bound = ETFExposureBound(
        asset_code="ETF1",
        report_date=date(2026, 9, 30),
        coverage_status=CoverageStatus.PARTIAL,
        reported_coverage_fraction=Decimal("0.80"),
        known_industry_market_value=Decimal("60"),
        unknown_market_value=Decimal("20"),
        maximum_industry_market_value=Decimal("80"),
        industry_bounds=(
            ETFIndustryExposureBound(
                industry_code="banking",
                known_market_value=Decimal("60"),
                unknown_market_value=Decimal("20"),
                upper_market_value=Decimal("80"),
            ),
        ),
        known_security_market_value=Decimal("60"),
        unknown_security_market_value=Decimal("20"),
        maximum_security_market_value=Decimal("80"),
        source_id="etf-source",
        reason_codes=(),
    )

    loading = etf_upper_industry_loading(
        bound=bound,
        projected_market_value=Decimal("100"),
        industry_code="banking",
    )

    assert loading == Decimal("0.8")


def test_exit_liquidity_shock_reduces_only_the_future_approved_capacity() -> None:
    window = _future_capacity_window(
        session_date=date(2026, 11, 3),
        quantity_unit="share",
        base_quantity=Decimal("100"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=("capacity-source:record-1",),
        shocks=(_shock("exit_liquidity_change", magnitude="-0.25"),),
    )

    assert window.exitable_quantity == Decimal("75.00")
    assert "PORTFOLIO_PRESSURE_CAPACITY_BY_APPROVED_SCENARIO_ASSUMPTION" in window.reason_codes


def test_future_capacity_without_an_explicit_exit_assumption_stays_unknown() -> None:
    window = _future_capacity_window(
        session_date=date(2026, 11, 3),
        quantity_unit="share",
        base_quantity=Decimal("100"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=("capacity-source:record-1",),
        shocks=(),
    )

    assert window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_EXIT_ASSUMPTION_MISSING" in window.reason_codes


def test_domain_future_capacity_rejects_a_positive_liquidity_shock() -> None:
    window = _future_capacity_window(
        session_date=date(2026, 11, 3),
        quantity_unit="share",
        base_quantity=Decimal("100"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=("capacity-source:record-1",),
        shocks=(_shock("exit_liquidity_change", magnitude="0.10"),),
    )

    assert window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_EXIT_ASSUMPTION_INVALID" in window.reason_codes


def test_halt_and_continuous_limit_down_lock_are_known_zero_on_calendar_sessions() -> None:
    for shock_kind, expected_reason in (
        ("exit_halt", "SCENARIO_EXIT_HALT_ASSUMED"),
        ("exit_limit_down_lock", "SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED"),
    ):
        for session_date in (date(2026, 11, 3), date(2026, 11, 4)):
            window = _future_capacity_window(
                session_date=session_date,
                quantity_unit="share",
                base_quantity=Decimal("100"),
                held_quantity=Decimal("100"),
                available_quantity=Decimal("100"),
                source_evidence_ids=("capacity-source:record-1",),
                shocks=(_shock(shock_kind),),
            )
            assert window.exitable_quantity == Decimal("0")
            assert expected_reason in window.reason_codes


def test_missing_capacity_source_never_creates_positive_future_quantity() -> None:
    window = _future_capacity_window(
        session_date=date(2026, 11, 3),
        quantity_unit="share",
        base_quantity=Decimal("100"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        source_evidence_ids=(),
        shocks=(_shock("exit_liquidity_change", magnitude="-0.10"),),
    )

    assert window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CAPACITY_SOURCE_MISSING" in window.reason_codes


def test_future_capacity_does_not_assume_unavailable_shares_settle() -> None:
    window = _future_capacity_window(
        session_date=date(2026, 11, 3),
        quantity_unit="share",
        base_quantity=Decimal("100"),
        held_quantity=Decimal("100"),
        available_quantity=Decimal("0"),
        source_evidence_ids=("capacity-source:record-1",),
        shocks=(_shock("exit_liquidity_change", magnitude="-0.10"),),
    )

    assert window.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_FUTURE_AVAILABLE_QUANTITY_UNKNOWN" in window.reason_codes


def test_missing_calendar_keeps_explicit_future_horizon_unknown() -> None:
    cutoff = datetime(2026, 11, 2, 8, tzinfo=UTC)
    positions, reasons = _build_pressure_positions(
        account_snapshot=_snapshot(
            holdings=(HeldPosition("ETF1", Decimal("100"), Decimal("100"), "security-1"),)
        ),
        held_assets=(_held_asset(),),
        decisions=(),
        evidence=(),
        scenario_revision=_revision(_shock("exit_liquidity_change", magnitude="-0.10")),
        open_sessions=None,
        as_of_time=cutoff,
        business_date=date(2026, 11, 2),
    )

    assert len(positions) == 1
    assert len(positions[0].capacity_windows) == 1
    assert positions[0].capacity_windows[0].exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_FUTURE_CALENDAR_MISSING" in reasons


def test_open_session_dates_without_calendar_evidence_cannot_create_future_capacity() -> None:
    positions, _ = _build_pressure_positions(
        account_snapshot=_snapshot(
            holdings=(HeldPosition("ETF1", Decimal("100"), Decimal("100"), "security-1"),)
        ),
        held_assets=(_held_asset(),),
        decisions=(),
        evidence=(),
        scenario_revision=_revision(_shock("exit_liquidity_change", magnitude="-0.10")),
        open_sessions=(date(2026, 11, 3),),
        as_of_time=datetime(2026, 11, 2, 8, tzinfo=UTC),
        business_date=date(2026, 11, 2),
    )

    assert len(positions[0].capacity_windows) == 2
    future = positions[0].capacity_windows[1]
    assert future.exitable_quantity is None
    assert "PORTFOLIO_PRESSURE_CALENDAR_EVIDENCE_MISSING" in future.reason_codes


def test_return_shock_does_not_infer_an_exit_lock_or_future_capacity() -> None:
    positions, _ = _build_pressure_positions(
        account_snapshot=_snapshot(
            holdings=(HeldPosition("ETF1", Decimal("100"), Decimal("100"), "security-1"),)
        ),
        held_assets=(_held_asset(),),
        decisions=(),
        evidence=(),
        scenario_revision=_revision(_shock("return", magnitude="-0.10")),
        open_sessions=(date(2026, 11, 3), date(2026, 11, 4)),
        as_of_time=datetime(2026, 11, 2, 8, tzinfo=UTC),
        business_date=date(2026, 11, 2),
    )

    assert len(positions[0].capacity_windows) == 1
    assert positions[0].capacity_windows[0].exitable_quantity is None


def test_unapproved_exit_liquidity_increase_is_rejected() -> None:
    reasons = validate_exit_shock_assumption(_shock("exit_liquidity_change", magnitude="0.10"))

    assert reasons == ("PORTFOLIO_PRESSURE_EXIT_LIQUIDITY_CHANGE_INVALID",)


def test_etf_industry_factor_does_not_leak_to_unmatched_factor() -> None:
    loading = etf_upper_industry_loading(
        bound=ETFExposureBound(
            asset_code="ETF1",
            report_date=date(2026, 9, 30),
            coverage_status=CoverageStatus.COMPLETE,
            reported_coverage_fraction=Decimal("1"),
            known_industry_market_value=Decimal("100"),
            unknown_market_value=Decimal("0"),
            maximum_industry_market_value=Decimal("100"),
            industry_bounds=(
                ETFIndustryExposureBound(
                    industry_code="banking",
                    known_market_value=Decimal("100"),
                    unknown_market_value=Decimal("0"),
                    upper_market_value=Decimal("100"),
                ),
            ),
            known_security_market_value=Decimal("100"),
            unknown_security_market_value=Decimal("0"),
            maximum_security_market_value=Decimal("100"),
            source_id="etf-source",
            reason_codes=(),
        ),
        projected_market_value=Decimal("100"),
        industry_code="technology",
    )
    exposure = PortfolioExposure(
        asset_code="ETF1",
        weight=Decimal("1"),
        attributes=(scenario_factor_loading_attribute("technology", loading or Decimal("0")),),
    )

    assert loading == Decimal("0")
    assert (
        _matching_exit_shocks(
            _revision(_shock("exit_halt", target_kind="factor", target="technology")),
            exposure,
        )
        == ()
    )


def test_restricted_industry_source_cannot_supply_factor_loadings() -> None:
    as_of = datetime(2026, 11, 2, 8, tzinfo=UTC)

    assert not _source_usable_for_projection(
        evidence=_evidence(as_of=as_of, restrictions=("restricted-use",)),
        business_date=date(2026, 11, 2),
        as_of_time=as_of,
    )
