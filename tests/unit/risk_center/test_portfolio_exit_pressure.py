"""Pure contract tests for scenario-linked, non-executing exit pressure."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.risk_center.domain.portfolio_exit_pressure import (
    ExitCapacityWindow,
    ExitPressurePosition,
    ExitPressureStatus,
    PortfolioExitPressureInput,
    evaluate_portfolio_exit_pressure,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from apps.risk_center.domain.scenarios import (
    ParametricShock,
    ParametricShockParameters,
    ScenarioImpact,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
)

NOW = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)
SNAPSHOT_HASH = "a" * 64
IMPACT_HASH = "b" * 64


def _revision(
    *,
    status: ScenarioRevisionStatus = ScenarioRevisionStatus.APPROVED,
    revision_id: str = "scenario-revision-3",
) -> ScenarioRevision:
    """Build one approved revision with an explicit finite asset shock."""

    return ScenarioRevision(
        revision_id=revision_id,
        scenario_key="ash07.limit-down-pressure",
        version=3,
        status=status,
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
            correlation_assumption="stress co-movement per approved revision",
        ),
        assumptions=("test scenario only",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="test-owner",
        change_reason="scenario exit pressure contract",
        created_at=NOW,
    )


def _impact(revision: ScenarioRevision | None = None) -> ScenarioImpact:
    """Build a deterministic base Scenario impact for the same revision."""

    resolved_revision = revision or _revision()
    return ScenarioImpact(
        scenario_revision_id=resolved_revision.revision_id,
        initial_value=Decimal("20000"),
        final_value=Decimal("14000"),
        total_return=Decimal("-0.3"),
        max_drawdown=Decimal("-0.3"),
        recovery_periods=0,
        volatility=Decimal("0"),
        var_95=Decimal("0.3"),
        var_99=Decimal("0.3"),
        period_start=None,
        period_end=None,
        result_hash=IMPACT_HASH,
    )


def _window(
    session_date: date,
    exitable_quantity: Decimal | None,
    *,
    reason_codes: tuple[str, ...] = (),
    source_evidence_ids: tuple[str, ...] = ("capacity:window:source-1",),
) -> ExitCapacityWindow:
    """Build one source-bound session capacity window."""

    return ExitCapacityWindow(
        session_date=session_date,
        exitable_quantity=exitable_quantity,
        quantity_unit="shares",
        reason_codes=reason_codes,
        source_evidence_ids=source_evidence_ids,
    )


def _position(
    windows: tuple[ExitCapacityWindow, ...],
    *,
    pending_sell_quantity: Decimal = Decimal("0"),
) -> ExitPressurePosition:
    """Build one currently held position and its hypothetical capacities."""

    return ExitPressurePosition(
        asset_code="600000.SH",
        quantity=Decimal("1000"),
        quantity_unit="shares",
        market_value=Decimal("20000"),
        pending_sell_quantity=pending_sell_quantity,
        capacity_windows=windows,
    )


def _request(position: ExitPressurePosition) -> PortfolioExitPressureInput:
    """Build an immutable input bound to one snapshot and Scenario result."""

    revision = _revision()
    return PortfolioExitPressureInput(
        scenario_revision=revision,
        scenario_impact=_impact(revision),
        portfolio_snapshot_id="simulated-account:42:snapshot:17",
        portfolio_snapshot_hash=SNAPSHOT_HASH,
        as_of_time=NOW,
        allocation_policy_version="allocation-v4",
        code_version="server-source-sha256:abc",
        scenario_market_data_hash="c" * 64,
        source_evidence=(),
        source_evidence_ids=("portfolio-risk:source:1",),
        positions=(position,),
    )


def _risk_source(*, payload_hash: str = "d" * 64) -> PortfolioRiskSourceEvidence:
    """Build an A-source record with original hash, clocks, purpose, and coverage."""

    return PortfolioRiskSourceEvidence(
        source_id="capacity-provider:daily-bars",
        source_record_id="daily-bars:2026-11-02",
        original_payload_sha256=payload_hash,
        observation_precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=datetime(2026, 11, 2, 0, 0, tzinfo=UTC),
        observed_on=None,
        available_at=datetime(2026, 11, 2, 1, 0, tzinfo=UTC),
        known_at=datetime(2026, 11, 2, 1, 5, tzinfo=UTC),
        decision_cutoff=NOW,
        decision_date_cutoff=None,
        valid_until=datetime(2026, 11, 4, 0, 0, tzinfo=UTC),
        source_purpose="historical_liquidity",
        allowed_purposes=("scenario_exit_pressure",),
        restrictions=("historical_only",),
        must_not_use_for_decision=False,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.PARTIAL,
            precision_basis="reported_sessions",
            reported_weight_fraction=Decimal("0.75"),
            expected_item_count=4,
            observed_item_count=3,
        ),
    )


def test_locked_limit_down_then_reduced_liquidity_reports_partial_exit() -> None:
    """Locked sessions retain exposure; later capacity leaves a residual."""

    request = _request(
        _position(
            (
                _window(
                    date(2026, 11, 3),
                    Decimal("0"),
                    reason_codes=("continuous_limit_down_no_executable_volume",),
                ),
                _window(
                    date(2026, 11, 4),
                    Decimal("0"),
                    reason_codes=("continuous_limit_down_no_executable_volume",),
                ),
                _window(
                    date(2026, 11, 5),
                    Decimal("400"),
                    reason_codes=("stress_liquidity_reduced_capacity",),
                ),
            ),
            pending_sell_quantity=Decimal("300"),
        )
    )

    result = evaluate_portfolio_exit_pressure(request)

    finding = result.findings[0]
    assert result.status is ExitPressureStatus.LIMITED
    assert finding.status is ExitPressureStatus.LIMITED
    assert finding.hypothetical_exitable_quantity == Decimal("400")
    assert finding.stress_window_residual_quantity == Decimal("600")
    assert finding.unreleased_exposure_quantity == Decimal("1000")
    assert finding.current_market_value == Decimal("20000")
    assert finding.unreleased_exposure_market_value == Decimal("20000")
    assert finding.pending_sell_quantity == Decimal("300")
    assert "continuous_limit_down_no_executable_volume" in finding.reason_codes
    assert "stress_liquidity_reduced_capacity" in finding.reason_codes


def test_suspension_without_executable_capacity_is_blocked_and_explained() -> None:
    """Known zero capacity is distinct from an unknown capacity source."""

    result = evaluate_portfolio_exit_pressure(
        _request(
            _position(
                (
                    _window(
                        date(2026, 11, 3),
                        Decimal("0"),
                        reason_codes=("suspended_no_exit",),
                    ),
                    _window(
                        date(2026, 11, 4),
                        Decimal("0"),
                        reason_codes=("suspended_no_exit",),
                    ),
                )
            )
        )
    )

    finding = result.findings[0]
    assert result.status is ExitPressureStatus.BLOCKED
    assert finding.stress_window_residual_quantity == Decimal("1000")
    assert finding.hypothetical_exitable_quantity == Decimal("0")
    assert finding.reason_codes == ("suspended_no_exit",)


def test_unknown_capacity_stays_unknown_after_known_partial_capacity() -> None:
    """Missing future capacity cannot be replaced with zero or a full exit."""

    result = evaluate_portfolio_exit_pressure(
        _request(
            _position(
                (
                    _window(date(2026, 11, 3), Decimal("400")),
                    _window(
                        date(2026, 11, 4),
                        None,
                        reason_codes=("capacity_window_unknown",),
                        source_evidence_ids=(),
                    ),
                )
            )
        )
    )

    finding = result.findings[0]
    assert result.status is ExitPressureStatus.UNKNOWN
    assert finding.hypothetical_exitable_quantity == Decimal("400")
    assert finding.stress_window_residual_quantity is None
    assert finding.exit_sessions_required is None
    assert finding.unreleased_exposure_quantity == Decimal("1000")


def test_complete_capacity_reports_counterfactual_exit_without_releasing_exposure() -> None:
    """A full hypothetical exit is not treated as a settled account change."""

    result = evaluate_portfolio_exit_pressure(
        _request(
            _position(
                (
                    _window(date(2026, 11, 3), Decimal("300")),
                    _window(date(2026, 11, 4), Decimal("700")),
                    _window(date(2026, 11, 5), Decimal("700")),
                ),
                pending_sell_quantity=Decimal("500"),
            )
        )
    )

    finding = result.findings[0]
    assert result.status is ExitPressureStatus.EXITABLE
    assert finding.exit_sessions_required == 2
    assert finding.hypothetical_exitable_quantity == Decimal("1000")
    assert finding.stress_window_residual_quantity == Decimal("0")
    assert finding.unreleased_exposure_quantity == Decimal("1000")
    assert finding.pending_sell_quantity == Decimal("500")


def test_missing_capacity_windows_are_unknown_not_zero() -> None:
    """No capacity evidence never produces an unsupported blocked result."""

    result = evaluate_portfolio_exit_pressure(_request(_position(())))

    finding = result.findings[0]
    assert finding.status is ExitPressureStatus.UNKNOWN
    assert finding.stress_window_residual_quantity is None
    assert finding.reason_codes == ("exit_capacity_window_missing",)


def test_pressure_digest_binds_scenario_snapshot_and_findings() -> None:
    """Changing an input scenario or capacity must change the evidence digest."""

    blocked = _request(
        _position(
            (
                _window(
                    date(2026, 11, 3),
                    Decimal("0"),
                    reason_codes=("suspended_no_exit",),
                ),
            )
        )
    )
    limited = _request(_position((_window(date(2026, 11, 3), Decimal("200")),)))

    blocked_result = evaluate_portfolio_exit_pressure(blocked)
    limited_result = evaluate_portfolio_exit_pressure(limited)

    assert blocked_result.result_hash != limited_result.result_hash
    assert len(blocked_result.result_hash) == 64
    policy_changed = evaluate_portfolio_exit_pressure(
        replace(blocked, allocation_policy_version="allocation-v5")
    )
    assert blocked_result.result_hash != policy_changed.result_hash
    source_bound = evaluate_portfolio_exit_pressure(
        replace(blocked, source_evidence=(_risk_source(),))
    )
    source_hash_changed = evaluate_portfolio_exit_pressure(
        replace(blocked, source_evidence=(_risk_source(payload_hash="e" * 64),))
    )
    assert source_bound.source_manifest_hash != source_hash_changed.source_manifest_hash
    assert source_bound.result_hash != source_hash_changed.result_hash
    market_data_changed = evaluate_portfolio_exit_pressure(
        replace(blocked, scenario_market_data_hash="f" * 64)
    )
    assert blocked_result.result_hash != market_data_changed.result_hash


def test_scenario_impact_must_match_the_approved_revision() -> None:
    """An impact from another revision cannot be attached to this pressure run."""

    revision = _revision()
    request = PortfolioExitPressureInput(
        scenario_revision=revision,
        scenario_impact=_impact(_revision(revision_id="scenario-revision-4")),
        portfolio_snapshot_id="simulated-account:42:snapshot:17",
        portfolio_snapshot_hash=SNAPSHOT_HASH,
        as_of_time=NOW,
        allocation_policy_version="allocation-v4",
        code_version="server-source-sha256:abc",
        scenario_market_data_hash="c" * 64,
        source_evidence=(),
        source_evidence_ids=("portfolio-risk:source:1",),
        positions=(_position((_window(date(2026, 11, 3), Decimal("1000")),)),),
    )

    with pytest.raises(ValueError, match="scenario revision mismatch"):
        evaluate_portfolio_exit_pressure(request)


def test_unapproved_scenario_revision_cannot_produce_pressure() -> None:
    """Only approved or active immutable revisions may be assessed."""

    revision = _revision(status=ScenarioRevisionStatus.DRAFT)
    request = PortfolioExitPressureInput(
        scenario_revision=revision,
        scenario_impact=_impact(revision),
        portfolio_snapshot_id="simulated-account:42:snapshot:17",
        portfolio_snapshot_hash=SNAPSHOT_HASH,
        as_of_time=NOW,
        allocation_policy_version="allocation-v4",
        code_version="server-source-sha256:abc",
        scenario_market_data_hash="c" * 64,
        source_evidence=(),
        source_evidence_ids=("portfolio-risk:source:1",),
        positions=(_position((_window(date(2026, 11, 3), Decimal("1000")),)),),
    )

    with pytest.raises(ValueError, match="approved scenario revision"):
        evaluate_portfolio_exit_pressure(request)


def test_capacity_unit_must_match_position_unit() -> None:
    """Capacity from a different unit cannot be compared with position size."""

    with pytest.raises(ValueError, match="quantity_unit mismatch"):
        ExitPressurePosition(
            asset_code="600000.SH",
            quantity=Decimal("1000"),
            quantity_unit="shares",
            market_value=Decimal("20000"),
            pending_sell_quantity=Decimal("0"),
            capacity_windows=(
                ExitCapacityWindow(
                    session_date=date(2026, 11, 3),
                    exitable_quantity=Decimal("1000"),
                    quantity_unit="lots",
                    source_evidence_ids=("capacity:window:source-1",),
                ),
            ),
        )


def test_known_zero_capacity_requires_source_evidence() -> None:
    """A blocked exit conclusion needs evidence as well as a stable reason."""

    with pytest.raises(ValueError, match="known capacity requires source evidence"):
        ExitCapacityWindow(
            session_date=date(2026, 11, 3),
            exitable_quantity=Decimal("0"),
            quantity_unit="shares",
            reason_codes=("suspended_no_exit",),
        )


def test_zero_and_unknown_capacity_each_require_an_explanation() -> None:
    """A source ID alone cannot turn an unexplained zero or missing value into evidence."""

    with pytest.raises(ValueError, match="known zero capacity requires an explanatory reason"):
        ExitCapacityWindow(
            session_date=date(2026, 11, 3),
            exitable_quantity=Decimal("0"),
            quantity_unit="shares",
            source_evidence_ids=("capacity:window:source-1",),
        )

    with pytest.raises(ValueError, match="unknown capacity requires an explanatory reason"):
        ExitCapacityWindow(
            session_date=date(2026, 11, 3),
            exitable_quantity=None,
            quantity_unit="shares",
            source_evidence_ids=("capacity:window:source-1",),
        )


def test_exit_position_rejects_overreserved_sell_and_ambiguous_windows() -> None:
    """Pending sells stay bounded by holdings and capacity dates stay unique and ordered."""

    with pytest.raises(ValueError, match="pending sell quantity cannot exceed"):
        _position((), pending_sell_quantity=Decimal("1001"))

    with pytest.raises(ValueError, match="ordered by session_date"):
        _position(
            (
                _window(date(2026, 11, 4), Decimal("100")),
                _window(date(2026, 11, 3), Decimal("100")),
            )
        )

    with pytest.raises(ValueError, match="unique session_date"):
        _position(
            (
                _window(date(2026, 11, 3), Decimal("100")),
                _window(date(2026, 11, 3), Decimal("100")),
            )
        )


def test_pressure_input_rejects_duplicate_source_identity_and_mismatched_cutoff() -> None:
    """Evidence cannot be duplicated or silently carried across pressure cutoffs."""

    request = _request(_position(()))
    source = _risk_source()
    duplicate_source = replace(source, original_payload_sha256="e" * 64)

    with pytest.raises(ValueError, match="unique source and record identities"):
        replace(request, source_evidence=(source, duplicate_source))

    prior_cutoff_source = replace(
        source,
        decision_cutoff=NOW.replace(hour=1, minute=59),
    )
    with pytest.raises(ValueError, match="exact pressure cutoff"):
        replace(request, source_evidence=(prior_cutoff_source,))


def test_pressure_input_rejects_duplicate_asset_projection() -> None:
    """One holding cannot be counted twice under separate pressure positions."""

    position = _position(())
    duplicate_position = replace(position, market_value=Decimal("20001"))
    request = _request(position)

    with pytest.raises(ValueError, match="unique asset_code values"):
        replace(request, positions=(position, duplicate_position))


def test_pressure_input_rejects_unhashed_snapshot_and_naive_cutoff() -> None:
    """Result evidence requires a digest and an aware server cutoff."""

    request = _request(_position(()))

    with pytest.raises(ValueError, match="portfolio_snapshot_hash must be a SHA-256 digest"):
        replace(request, portfolio_snapshot_hash="not-a-digest")

    with pytest.raises(ValueError, match="must be timezone-aware"):
        replace(request, as_of_time=NOW.replace(tzinfo=None))
