"""Contract tests for research-only fixed-income portfolio risk."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.fixed_income.domain.portfolio_risk import (
    CreditSpreadShock,
    FixedIncomePositionRiskInput,
    FixedIncomeRiskBudgetPolicy,
    KeyRateExposure,
    PITPublicationIdentity,
    PortfolioRiskBlockerCode,
    PortfolioRiskInputBundle,
    PortfolioRiskPITManifest,
    PortfolioRiskPublicationReference,
    PortfolioRiskStatus,
    PortfolioStressScenario,
    PublicationRole,
    RateShockKind,
    RateShockPoint,
    build_fixed_income_risk_budget_policy_hash,
    build_pit_manifest_hash,
    build_portfolio_risk_input_hash,
    evaluate_fixed_income_portfolio_risk,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
AS_OF = NOW - timedelta(hours=1)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _reference(
    instrument_id: str,
    role: PublicationRole,
    *,
    currency: str = "CNY",
    valid_until: datetime = NOW + timedelta(days=1),
) -> PortfolioRiskPublicationReference:
    suffix = f"{instrument_id}-{role.value}"
    owner = (
        "fixed_income"
        if role in {PublicationRole.INTEREST_RATE_ANALYTICS, PublicationRole.CREDIT_ANALYTICS}
        else "data_center"
    )
    return PortfolioRiskPublicationReference(
        role=role,
        owner=owner,
        subject_id=instrument_id,
        currency=currency,
        dataset_key=f"dataset-{suffix}",
        publication_id=f"publication-{suffix}",
        content_hash=_digest(suffix),
        observed_at=NOW - timedelta(hours=3),
        published_at=NOW - timedelta(hours=2),
        valid_until=valid_until,
    )


def _position(
    position_id: str,
    instrument_id: str,
    *,
    market_value: str,
    duration: str,
    convexity: str,
    spread_duration: str,
    liquidity_fraction: str,
    liquidity_cost_rate: str,
    key_rate_durations: tuple[str, str],
    key_rate_convexities: tuple[str, str],
    currency: str = "CNY",
    as_of: datetime = AS_OF,
) -> FixedIncomePositionRiskInput:
    references = tuple(
        _reference(instrument_id, role, currency=currency) for role in PublicationRole
    )
    return FixedIncomePositionRiskInput(
        position_id=position_id,
        instrument_id=instrument_id,
        currency=currency,
        as_of=as_of,
        market_value=Decimal(market_value),
        modified_duration_years=Decimal(duration),
        convexity_years_squared=Decimal(convexity),
        credit_bucket="credit-aa",
        credit_spread_duration_years=Decimal(spread_duration),
        liquidatable_fraction=Decimal(liquidity_fraction),
        liquidity_cost_rate=Decimal(liquidity_cost_rate),
        key_rate_exposures=(
            KeyRateExposure(
                tenor_years=Decimal("2"),
                duration_years=Decimal(key_rate_durations[0]),
                convexity_years_squared=Decimal(key_rate_convexities[0]),
            ),
            KeyRateExposure(
                tenor_years=Decimal("10"),
                duration_years=Decimal(key_rate_durations[1]),
                convexity_years_squared=Decimal(key_rate_convexities[1]),
            ),
        ),
        publication_references=references,
    )


def _positions() -> tuple[FixedIncomePositionRiskInput, ...]:
    return (
        _position(
            "position-1",
            "bond-1",
            market_value="100",
            duration="4",
            convexity="20",
            spread_duration="3",
            liquidity_fraction="0.8",
            liquidity_cost_rate="0.002",
            key_rate_durations=("1", "3"),
            key_rate_convexities=("5", "15"),
        ),
        _position(
            "position-2",
            "bond-2",
            market_value="200",
            duration="2",
            convexity="8",
            spread_duration="1",
            liquidity_fraction="0.9",
            liquidity_cost_rate="0.001",
            key_rate_durations=("0.5", "1.5"),
            key_rate_convexities=("2", "6"),
        ),
    )


def _scenario(
    scenario_id: str = "parallel-up",
    kind: RateShockKind = RateShockKind.PARALLEL,
    shocks: tuple[str, str] = ("100", "100"),
    credit_shock: str = "50",
) -> PortfolioStressScenario:
    return PortfolioStressScenario(
        scenario_id=scenario_id,
        scenario_version="stress-v1",
        rate_shock_kind=kind,
        rate_shocks=(
            RateShockPoint(Decimal("2"), Decimal(shocks[0])),
            RateShockPoint(Decimal("10"), Decimal(shocks[1])),
        ),
        credit_shocks=(CreditSpreadShock("credit-aa", Decimal(credit_shock)),),
    )


def _manifest(
    positions: tuple[FixedIncomePositionRiskInput, ...],
    *,
    as_of: datetime = AS_OF,
    valid_until: datetime = NOW + timedelta(days=1),
    identities: tuple[PITPublicationIdentity, ...] | None = None,
) -> PortfolioRiskPITManifest:
    selected = identities or tuple(
        PITPublicationIdentity(
            dataset_key=reference.dataset_key,
            publication_id=reference.publication_id,
            content_hash=reference.content_hash,
        )
        for position in positions
        for reference in position.publication_references
    )
    manifest_hash = build_pit_manifest_hash(
        manifest_id="pit-r5-portfolio-1",
        as_of=as_of,
        observed_at=NOW - timedelta(minutes=30),
        valid_until=valid_until,
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        publication_identities=selected,
    )
    return PortfolioRiskPITManifest(
        manifest_id="pit-r5-portfolio-1",
        manifest_hash=manifest_hash,
        as_of=as_of,
        observed_at=NOW - timedelta(minutes=30),
        valid_until=valid_until,
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        publication_identities=selected,
    )


def _bundle(
    *,
    positions: tuple[FixedIncomePositionRiskInput, ...] | None = None,
    manifest: PortfolioRiskPITManifest | None = None,
    scenarios: tuple[PortfolioStressScenario, ...] | None = None,
    currency: str = "CNY",
    as_of: datetime = AS_OF,
    valid_until: datetime = NOW + timedelta(days=1),
    budget_policy_hash: str | None = None,
    portfolio_snapshot_as_of: datetime | None = None,
) -> PortfolioRiskInputBundle:
    selected_positions = positions or _positions()
    selected_manifest = manifest or _manifest(selected_positions, as_of=as_of)
    selected_scenarios = scenarios or (_scenario(),)
    selected_policy_hash = budget_policy_hash or _policy().policy_hash
    snapshot_hash = _digest("portfolio-snapshot-1")
    digest = build_portfolio_risk_input_hash(
        bundle_id="fixed-income-risk-bundle-1",
        bundle_version="bundle-v1",
        portfolio_snapshot_id="portfolio-snapshot-1",
        portfolio_snapshot_owner="portfolio",
        portfolio_snapshot_hash=snapshot_hash,
        portfolio_snapshot_as_of=portfolio_snapshot_as_of or as_of,
        budget_policy_version="r5-risk-budget-v1",
        budget_policy_hash=selected_policy_hash,
        currency=currency,
        as_of=as_of,
        created_at=NOW - timedelta(minutes=15),
        valid_until=valid_until,
        pit_manifest=selected_manifest,
        positions=selected_positions,
        stress_scenarios=selected_scenarios,
    )
    return PortfolioRiskInputBundle(
        bundle_id="fixed-income-risk-bundle-1",
        bundle_version="bundle-v1",
        portfolio_snapshot_id="portfolio-snapshot-1",
        portfolio_snapshot_owner="portfolio",
        portfolio_snapshot_hash=snapshot_hash,
        portfolio_snapshot_as_of=portfolio_snapshot_as_of or as_of,
        budget_policy_version="r5-risk-budget-v1",
        budget_policy_hash=selected_policy_hash,
        currency=currency,
        as_of=as_of,
        created_at=NOW - timedelta(minutes=15),
        valid_until=valid_until,
        pit_manifest=selected_manifest,
        positions=selected_positions,
        stress_scenarios=selected_scenarios,
        input_hash=digest,
    )


def _policy(**changes: object) -> FixedIncomeRiskBudgetPolicy:
    values: dict[str, object] = {
        "policy_version": "r5-risk-budget-v1",
        "currency": "CNY",
        "activated_at": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=7),
        "maximum_absolute_dv01": Decimal("1"),
        "maximum_absolute_cs01": Decimal("1"),
        "maximum_convexity_exposure": Decimal("10000"),
        "minimum_liquidatable_fraction": Decimal("0.80"),
        "maximum_liquidity_cost": Decimal("1"),
        "maximum_stress_loss": Decimal("100"),
        "identity_tolerance": Decimal("0.00000001"),
    }
    values.update(changes)
    values["policy_hash"] = build_fixed_income_risk_budget_policy_hash(
        policy_version=str(values["policy_version"]),
        currency=str(values["currency"]),
        activated_at=values["activated_at"],  # type: ignore[arg-type]
        valid_until=values["valid_until"],  # type: ignore[arg-type]
        maximum_absolute_dv01=values["maximum_absolute_dv01"],  # type: ignore[arg-type]
        maximum_absolute_cs01=values["maximum_absolute_cs01"],  # type: ignore[arg-type]
        maximum_convexity_exposure=values["maximum_convexity_exposure"],  # type: ignore[arg-type]
        minimum_liquidatable_fraction=values["minimum_liquidatable_fraction"],  # type: ignore[arg-type]
        maximum_liquidity_cost=values["maximum_liquidity_cost"],  # type: ignore[arg-type]
        maximum_stress_loss=values["maximum_stress_loss"],  # type: ignore[arg-type]
        identity_tolerance=values["identity_tolerance"],  # type: ignore[arg-type]
    )
    return FixedIncomeRiskBudgetPolicy(**values)  # type: ignore[arg-type]


def _codes(bundle: PortfolioRiskInputBundle, policy: FixedIncomeRiskBudgetPolicy | None = None):
    report = evaluate_fixed_income_portfolio_risk(
        bundle,
        policy=policy or _policy(),
        evaluated_at=NOW,
    )
    return report, {item.code for item in report.blockers}


def test_gold_sample_preserves_risk_and_stress_contribution_identities() -> None:
    report, codes = _codes(_bundle())

    assert report.status is PortfolioRiskStatus.AVAILABLE
    assert codes == set()
    assert report.totals is not None
    assert report.totals.market_value == Decimal("300")
    assert report.totals.dv01 == Decimal("0.08")
    assert report.totals.cs01 == Decimal("0.05")
    assert report.totals.convexity_exposure == Decimal("3600")
    assert report.totals.liquidatable_value == Decimal("260.0")
    assert report.totals.liquidatable_fraction == Decimal("260.0") / Decimal("300")
    assert report.totals.liquidity_cost == Decimal("0.400")
    assert sum(item.dv01 for item in report.position_contributions) == report.totals.dv01
    assert sum(item.cs01 for item in report.position_contributions) == report.totals.cs01
    assert (
        sum(item.convexity_exposure for item in report.position_contributions)
        == report.totals.convexity_exposure
    )
    stress = report.stress_results[0]
    assert stress.rate_first_order_pnl == Decimal("-8.00")
    assert stress.rate_convexity_pnl == Decimal("0.180000")
    assert stress.credit_pnl == Decimal("-2.500")
    assert stress.total_pnl == Decimal("-10.320000")
    assert sum(item.total_pnl for item in stress.position_contributions) == stress.total_pnl
    assert report.research_only is True
    assert report.must_not_use_for_decision is True
    assert report.must_not_execute is True
    assert len(report.input_hash or "") == 64
    assert len(report.output_hash) == 64


def test_all_rate_shock_shapes_are_explicitly_injected() -> None:
    scenarios = (
        _scenario("parallel", RateShockKind.PARALLEL, ("50", "50")),
        _scenario("key-rate", RateShockKind.KEY_RATE, ("0", "75")),
        _scenario("steepener", RateShockKind.STEEPENER, ("-25", "50")),
        _scenario("flattening", RateShockKind.FLATTENING, ("50", "-25")),
    )

    report, codes = _codes(_bundle(scenarios=scenarios))

    assert codes == set()
    assert tuple(item.scenario_id for item in report.stress_results) == (
        "parallel",
        "key-rate",
        "steepener",
        "flattening",
    )


def test_every_budget_breach_has_a_stable_blocker() -> None:
    policy = _policy(
        maximum_absolute_dv01=Decimal("0.01"),
        maximum_absolute_cs01=Decimal("0.01"),
        maximum_convexity_exposure=Decimal("100"),
        minimum_liquidatable_fraction=Decimal("0.99"),
        maximum_liquidity_cost=Decimal("0.01"),
        maximum_stress_loss=Decimal("1"),
    )
    report, codes = _codes(_bundle(budget_policy_hash=policy.policy_hash), policy)

    assert report.status is PortfolioRiskStatus.BLOCKED
    assert codes == {
        PortfolioRiskBlockerCode.DV01_BUDGET_BREACHED,
        PortfolioRiskBlockerCode.CS01_BUDGET_BREACHED,
        PortfolioRiskBlockerCode.CONVEXITY_BUDGET_BREACHED,
        PortfolioRiskBlockerCode.LIQUIDITY_FRACTION_BREACHED,
        PortfolioRiskBlockerCode.LIQUIDITY_COST_BREACHED,
        PortfolioRiskBlockerCode.STRESS_LOSS_BUDGET_BREACHED,
    }


def test_exact_valid_until_is_stale_for_bundle_manifest_publication_and_policy() -> None:
    bundle = _bundle(valid_until=NOW)
    report = evaluate_fixed_income_portfolio_risk(bundle, policy=_policy(), evaluated_at=NOW)
    assert PortfolioRiskBlockerCode.BUNDLE_STALE in {item.code for item in report.blockers}

    positions = tuple(
        replace(
            position,
            publication_references=tuple(
                replace(reference, valid_until=NOW) for reference in position.publication_references
            ),
        )
        for position in _positions()
    )
    publication_report, publication_codes = _codes(_bundle(positions=positions))
    assert publication_report.status is PortfolioRiskStatus.BLOCKED
    assert PortfolioRiskBlockerCode.PUBLICATION_STALE in publication_codes

    manifest = _manifest(_positions(), valid_until=NOW)
    _, manifest_codes = _codes(_bundle(manifest=manifest))
    assert PortfolioRiskBlockerCode.PIT_MANIFEST_STALE in manifest_codes

    _, policy_codes = _codes(_bundle(), _policy(valid_until=NOW))
    assert PortfolioRiskBlockerCode.POLICY_INACTIVE in policy_codes


def test_hash_pit_as_of_currency_and_publication_identity_mismatches_fail_closed() -> None:
    report, codes = _codes(replace(_bundle(), input_hash="0" * 64))
    assert report.status is PortfolioRiskStatus.BLOCKED
    assert PortfolioRiskBlockerCode.INPUT_HASH_MISMATCH in codes

    manifest = replace(_manifest(_positions()), manifest_hash="0" * 64)
    _, codes = _codes(_bundle(manifest=manifest))
    assert PortfolioRiskBlockerCode.PIT_MANIFEST_HASH_MISMATCH in codes

    positions = (replace(_positions()[0], as_of=AS_OF - timedelta(days=1)), _positions()[1])
    _, codes = _codes(_bundle(positions=positions))
    assert PortfolioRiskBlockerCode.AS_OF_MISMATCH in codes

    positions = (replace(_positions()[0], currency="USD"), _positions()[1])
    _, codes = _codes(_bundle(positions=positions))
    assert PortfolioRiskBlockerCode.CURRENCY_MISMATCH in codes

    full_manifest = _manifest(_positions())
    identities = full_manifest.publication_identities[:-1]
    incomplete_manifest = _manifest(_positions(), identities=identities)
    _, codes = _codes(_bundle(manifest=incomplete_manifest))
    assert PortfolioRiskBlockerCode.PUBLICATION_IDENTITY_MISMATCH in codes

    _, codes = _codes(_bundle(portfolio_snapshot_as_of=AS_OF - timedelta(days=1)))
    assert PortfolioRiskBlockerCode.PORTFOLIO_SNAPSHOT_MISMATCH in codes


def test_policy_content_hash_is_bound_even_when_version_is_unchanged() -> None:
    policy = _policy(maximum_absolute_dv01=Decimal("2"))
    _, codes = _codes(_bundle(), policy)
    assert PortfolioRiskBlockerCode.POLICY_HASH_MISMATCH in codes

    with pytest.raises(ValueError, match="policy_hash mismatch"):
        replace(policy, maximum_absolute_dv01=Decimal("3"))


def test_future_incomplete_pit_and_missing_shock_coverage_fail_closed() -> None:
    future_manifest = replace(
        _manifest(_positions()),
        observed_at=NOW + timedelta(minutes=1),
    )
    future_manifest = replace(
        future_manifest,
        manifest_hash=build_pit_manifest_hash(
            manifest_id=future_manifest.manifest_id,
            as_of=future_manifest.as_of,
            observed_at=future_manifest.observed_at,
            valid_until=future_manifest.valid_until,
            coverage_ratio=future_manifest.coverage_ratio,
            missing_count=future_manifest.missing_count,
            estimated_count=future_manifest.estimated_count,
            unknown_count=future_manifest.unknown_count,
            publication_identities=future_manifest.publication_identities,
        ),
    )
    _, codes = _codes(_bundle(manifest=future_manifest))
    assert PortfolioRiskBlockerCode.EVIDENCE_FROM_FUTURE in codes

    incomplete = replace(_manifest(_positions()), coverage_ratio=Decimal("0.9"), missing_count=1)
    incomplete = replace(
        incomplete,
        manifest_hash=build_pit_manifest_hash(
            manifest_id=incomplete.manifest_id,
            as_of=incomplete.as_of,
            observed_at=incomplete.observed_at,
            valid_until=incomplete.valid_until,
            coverage_ratio=incomplete.coverage_ratio,
            missing_count=incomplete.missing_count,
            estimated_count=incomplete.estimated_count,
            unknown_count=incomplete.unknown_count,
            publication_identities=incomplete.publication_identities,
        ),
    )
    _, codes = _codes(_bundle(manifest=incomplete))
    assert PortfolioRiskBlockerCode.PIT_MANIFEST_INCOMPLETE in codes

    missing_tenor = replace(
        _scenario(),
        rate_shocks=(RateShockPoint(Decimal("2"), Decimal("100")),),
    )
    _, codes = _codes(_bundle(scenarios=(missing_tenor,)))
    assert PortfolioRiskBlockerCode.RATE_SHOCK_UNIVERSE_MISMATCH in codes

    missing_credit = replace(_scenario(), credit_shocks=())
    _, codes = _codes(_bundle(scenarios=(missing_credit,)))
    assert PortfolioRiskBlockerCode.CREDIT_SHOCK_UNIVERSE_MISMATCH in codes


def test_key_rate_and_convexity_exposure_identities_fail_closed() -> None:
    bad = replace(_positions()[0], modified_duration_years=Decimal("9"))
    report, codes = _codes(_bundle(positions=(bad, _positions()[1])))
    assert report.status is PortfolioRiskStatus.BLOCKED
    assert PortfolioRiskBlockerCode.KEY_RATE_DURATION_IDENTITY_FAILED in codes

    bad = replace(_positions()[0], convexity_years_squared=Decimal("99"))
    _, codes = _codes(_bundle(positions=(bad, _positions()[1])))
    assert PortfolioRiskBlockerCode.KEY_RATE_CONVEXITY_IDENTITY_FAILED in codes


def test_structural_invalid_values_duplicates_and_shock_shapes_are_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        replace(_positions()[0], market_value=Decimal("NaN"))
    with pytest.raises(ValueError, match="unique"):
        replace(_bundle(), positions=(_positions()[0], _positions()[0]))
    with pytest.raises(ValueError, match="unique"):
        replace(_bundle(), stress_scenarios=(_scenario(), _scenario()))
    with pytest.raises(ValueError, match="parallel"):
        _scenario("bad-parallel", RateShockKind.PARALLEL, ("10", "20"))
    with pytest.raises(ValueError, match="steepener"):
        _scenario("bad-steepener", RateShockKind.STEEPENER, ("20", "10"))
    with pytest.raises(ValueError, match="flattening"):
        _scenario("bad-flattening", RateShockKind.FLATTENING, ("10", "20"))


def test_output_hash_detects_report_tampering() -> None:
    report, _ = _codes(_bundle())
    assert report.totals is not None
    with pytest.raises(ValueError, match="output_hash"):
        replace(report, totals=replace(report.totals, dv01=Decimal("999")))
