"""Pure tests for exact account snapshots and conservative BUY exposure projection."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_snapshot import (
    _assess_capacities,
    _capacity_usage_for_pair,
    _project_pre_trade_nav,
    _qualified_current_price,
    _requested_asset_codes,
    _resolve_asset_inputs,
    _valuation_reference_matches,
    assess_simulated_portfolio_risk,
)
from apps.risk_center.domain.portfolio_capacity import (
    CapacityUsageSnapshot,
    PortfolioCapacityDecision,
)
from apps.risk_center.domain.portfolio_risk_snapshot import (
    AccountSnapshot,
    ExecutedUsage,
    HeldPosition,
    OpenOrder,
    ProposedOrder,
    exact_decimal_product,
    exact_decimal_sum,
    project_gross_asset_exposure,
    value_held_quantity,
)

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 3)


def _policy_bundle(*, snapshot_id: str, snapshot_hash: str) -> PortfolioRiskPolicyBundle:
    """Parse one real typed policy bundle with caller-supplied runtime identity."""

    configuration: dict[str, object] = {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12],
        "industry": {
            "taxonomy_id": "industry-test-v1",
            "taxonomy_kind": "industry",
            "provider_id": "provider-test",
            "provider_version": "v1",
            "requested_purpose": "ash07_portfolio_exposure",
            "date_precision_purposes": ["ash07_portfolio_exposure"],
            "allowed_observation_precisions": ["timestamp", "date"],
            "allowed_source_restrictions": [],
            "coverage_precision_basis": "portfolio_weight",
            "max_industry_weight": "0.35",
            "max_security_weight": "0.15",
            "minimum_industry_coverage": "0.90",
            "minimum_etf_lookthrough_coverage": "0.80",
            "coverage_weight_tolerance": "0.01",
        },
        "capacity": {
            "measure": "volume",
            "unit": "share",
            "basis": "average_per_session",
            "usage_scope": "account_security_session",
            "date_basis": "execution_session",
            "max_participation": "0.08",
            "increment": "100",
            "window_kind": "rolling_sessions",
            "sessions": 5,
            "allowed_observation_precisions": ["timestamp"],
            "date_precision_purposes": [],
            "allowed_source_restrictions": [],
        },
        "source_max_timestamp_age_seconds": 1800,
        "source_max_date_age_days": 5,
        "source_references": [
            {
                "kind": "valuation",
                "asset_code": "600036",
                "security_id": "SSE:600036",
                "raw_payload_hash": "sha256:" + "a" * 64,
                "source_record_id": "valuation-record-1",
            },
        ],
    }
    created_at = _AS_OF - timedelta(minutes=5)
    effective_at = _AS_OF - timedelta(minutes=3)
    runtime_evidence = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=configuration,
        profile_id="runtime-profile-test",
        profile_key="risk-center-test",
        profile_version=12,
        profile_content_hash="e" * 64,
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        created_at=created_at,
        known_at=created_at,
        activated_at=effective_at,
        snapshot_generated_at=_AS_OF - timedelta(minutes=2),
        effective_at=effective_at,
        as_of=_AS_OF,
    )
    return parse_portfolio_risk_policy_bundle(
        runtime_evidence,
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )


def _cash_snapshot() -> AccountSnapshot:
    """Build one exact current-session cash-only simulated account snapshot."""

    return AccountSnapshot(
        account_id=12,
        owner_user_id=4,
        snapshot_id="account-snapshot-test",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(),
        active_orders=(),
        executed_usage=(),
        active_orders_complete=True,
        execution_session=_BUSINESS_DATE,
        executed_usage_complete=True,
    )


def test_pending_sell_does_not_reduce_gross_held_exposure() -> None:
    """An open SELL stays gross and cannot release held exposure before settlement."""

    value = project_gross_asset_exposure(
        held_quantity=Decimal("10"),
        active_orders=(
            OpenOrder(
                order_id="reservation-sell",
                asset_code="600036",
                security_id="SSE:600036",
                side="sell",
                remaining_quantity=Decimal("10"),
                remaining_amount=Decimal("50"),
            ),
        ),
        proposed_orders=(),
        qualified_current_price=Decimal("5"),
    )

    assert value == Decimal("50")


def test_pending_buy_uses_larger_accepted_or_current_notional() -> None:
    """A price gap is valued at the greater accepted/current gross notional."""

    proposed = ProposedOrder(
        order_id="proposal-1",
        asset_code="600036",
        security_id="SSE:600036",
        side="buy",
        quantity=Decimal("10"),
        price=Decimal("11"),
    )

    assert project_gross_asset_exposure(
        held_quantity=Decimal("2"),
        active_orders=(),
        proposed_orders=(proposed,),
        qualified_current_price=Decimal("12"),
    ) == Decimal("144")
    assert project_gross_asset_exposure(
        held_quantity=Decimal("2"),
        active_orders=(),
        proposed_orders=(proposed,),
        qualified_current_price=Decimal("9"),
    ) == Decimal("128")


def test_active_buy_with_partial_remaining_measures_stays_unknown() -> None:
    """An incomplete accepted order cannot be understated from only one measure."""

    order = OpenOrder(
        order_id="reservation-1",
        asset_code="600036",
        security_id="SSE:600036",
        side="buy",
        remaining_quantity=Decimal("4"),
        remaining_amount=None,
    )

    assert (
        project_gross_asset_exposure(
            held_quantity=Decimal("0"),
            active_orders=(order,),
            proposed_orders=(),
            qualified_current_price=Decimal("10"),
        )
        is None
    )


def test_active_buy_with_unknown_remaining_quantity_stays_unknown() -> None:
    """An accepted amount alone cannot bound a changed current notional."""

    order = OpenOrder(
        order_id="reservation-1",
        asset_code="600036",
        security_id="SSE:600036",
        side="buy",
        remaining_quantity=None,
        remaining_amount=Decimal("40"),
    )

    assert (
        project_gross_asset_exposure(
            held_quantity=Decimal("0"),
            active_orders=(order,),
            proposed_orders=(),
            qualified_current_price=Decimal("10"),
        )
        is None
    )


def test_current_holding_gets_usage_only_capacity_decision_without_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current-session use is evaluated for a held asset with no synthetic proposal."""

    policy = _policy_bundle(
        snapshot_id="runtime-snapshot-capacity-use",
        snapshot_hash="1" * 64,
    )
    snapshot = AccountSnapshot(
        account_id=12,
        owner_user_id=4,
        snapshot_id="account-snapshot-capacity-use",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code="600036",
                security_id="SSE:600036",
                quantity=Decimal("100"),
                available_quantity=Decimal("100"),
            ),
        ),
        active_orders=(),
        executed_usage=(
            ExecutedUsage(
                asset_code="600036",
                security_id="SSE:600036",
                execution_session=_BUSINESS_DATE,
                quantity=Decimal("3"),
                amount=Decimal("30"),
                complete=True,
            ),
        ),
        active_orders_complete=True,
        execution_session=_BUSINESS_DATE,
        executed_usage_complete=True,
    )
    asset = SimpleNamespace(
        asset_code="600036",
        security_id="SSE:600036",
        capacity_observation=object(),
        quantity_unit="share",
    )
    seen_usage: list[CapacityUsageSnapshot] = []

    def evaluate_usage_only(
        *,
        observation: object,
        policy: object,
        usage: CapacityUsageSnapshot,
        requested_purpose: str,
        business_date: date,
        as_of: datetime,
    ) -> PortfolioCapacityDecision:
        del observation, policy, requested_purpose, business_date, as_of
        seen_usage.append(usage)
        return cast(
            PortfolioCapacityDecision,
            SimpleNamespace(
                status="allowed",
                remaining_capacity=Decimal("700"),
                allowed_new_capacity=Decimal("0"),
            ),
        )

    monkeypatch.setattr(
        "apps.risk_center.application.portfolio_risk_snapshot.evaluate_portfolio_capacity",
        evaluate_usage_only,
    )
    decisions, reasons = _assess_capacities(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        resolved_assets=cast(dict[str, PortfolioRiskAssetInputs], {"600036": asset}),
        source_reference_bindings=(),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        requested_purpose="ash07_capacity_preflight",
    )

    assert reasons == []
    assert len(decisions) == 1
    assert decisions[0].remaining_capacity == Decimal("700")
    assert decisions[0].allowed_new_capacity == Decimal("0")
    assert len(seen_usage) == 1
    assert seen_usage[0].volume.value == Decimal("3")
    assert seen_usage[0].amount.value == Decimal("30")
    assert seen_usage[0].proposed_orders == ()


def test_current_holding_without_capacity_source_is_unknown_without_proposal() -> None:
    """A held asset remains a capacity target when its source observation is absent."""

    policy = _policy_bundle(
        snapshot_id="runtime-snapshot-capacity-missing",
        snapshot_hash="3" * 64,
    )
    snapshot = AccountSnapshot(
        account_id=12,
        owner_user_id=4,
        snapshot_id="account-snapshot-capacity-missing",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code="600036",
                security_id="SSE:600036",
                quantity=Decimal("100"),
                available_quantity=Decimal("100"),
            ),
        ),
        active_orders=(),
        executed_usage=(),
        active_orders_complete=True,
        execution_session=_BUSINESS_DATE,
        executed_usage_complete=True,
    )
    asset = PortfolioRiskAssetInputs(
        asset_code="600036",
        security_id="SSE:600036",
        kind=None,
        price=None,
        quantity_unit=None,
        price_unit=None,
        valuation_evidence=None,
        industry_membership=None,
        etf_report=None,
        capacity_observation=None,
    )

    decisions, reasons = _assess_capacities(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        resolved_assets={"600036": asset},
        source_reference_bindings=(),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        requested_purpose="ash07_capacity_preflight",
    )

    assert decisions == ()
    assert reasons == ["CAPACITY_OBSERVATION_MISSING"]


def test_complete_usage_collection_keeps_incomplete_row_local_to_its_asset() -> None:
    """A complete collection scopes an explicitly incomplete row to its asset."""

    snapshot = AccountSnapshot(
        account_id=12,
        owner_user_id=4,
        snapshot_id="account-snapshot-scoped-incomplete-usage",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code="600036",
                security_id="SSE:600036",
                quantity=Decimal("100"),
                available_quantity=Decimal("100"),
            ),
            HeldPosition(
                asset_code="601398",
                security_id="SSE:601398",
                quantity=Decimal("100"),
                available_quantity=Decimal("100"),
            ),
        ),
        active_orders=(),
        executed_usage=(
            ExecutedUsage(
                asset_code="600036",
                security_id=None,
                execution_session=None,
                quantity=Decimal("10"),
                amount=Decimal("100"),
                complete=False,
            ),
            ExecutedUsage(
                asset_code="600036",
                security_id="SSE:600036",
                execution_session=_BUSINESS_DATE,
                quantity=None,
                amount=None,
                complete=False,
            ),
            ExecutedUsage(
                asset_code="601398",
                security_id="SSE:601398",
                execution_session=_BUSINESS_DATE,
                quantity=Decimal("3"),
                amount=Decimal("30"),
                complete=True,
            ),
        ),
        active_orders_complete=True,
        execution_session=_BUSINESS_DATE,
        executed_usage_complete=True,
    )
    policy = _policy_bundle(
        snapshot_id="runtime-snapshot-scoped-incomplete-usage",
        snapshot_hash="7" * 64,
    )
    first_asset = PortfolioRiskAssetInputs(
        asset_code="600036",
        security_id="SSE:600036",
        kind=None,
        price=None,
        quantity_unit="share",
        price_unit=None,
        valuation_evidence=None,
        industry_membership=None,
        etf_report=None,
        capacity_observation=None,
    )
    second_asset = PortfolioRiskAssetInputs(
        asset_code="601398",
        security_id="SSE:601398",
        kind=None,
        price=None,
        quantity_unit="share",
        price_unit=None,
        valuation_evidence=None,
        industry_membership=None,
        etf_report=None,
        capacity_observation=None,
    )

    unresolved, unresolved_reasons = _capacity_usage_for_pair(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        asset=first_asset,
        source_reference_bindings=(),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
    )
    exact_other_asset, exact_other_reasons = _capacity_usage_for_pair(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        asset=second_asset,
        source_reference_bindings=(),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
    )

    assert unresolved_reasons == ["CAPACITY_EXECUTED_USAGE_SCOPE_UNKNOWN"]
    assert unresolved.volume.value is None
    assert unresolved.amount.value is None
    assert unresolved.executed_usage_complete is False
    assert exact_other_reasons == []
    assert exact_other_asset.volume.value == Decimal("3")
    assert exact_other_asset.amount.value == Decimal("30")
    assert exact_other_asset.executed_usage_complete is True


def test_global_usage_incomplete_blocks_even_when_one_known_asset_row_exists() -> None:
    """Known incomplete rows cannot prove that a globally incomplete read is exhaustive."""

    complete_snapshot = AccountSnapshot(
        account_id=12,
        owner_user_id=4,
        snapshot_id="account-snapshot-known-incomplete-usage",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(),
        active_orders=(),
        executed_usage=(
            ExecutedUsage(
                asset_code="600036",
                security_id=None,
                execution_session=None,
                quantity=Decimal("10"),
                amount=Decimal("100"),
                complete=False,
            ),
            ExecutedUsage(
                asset_code="601398",
                security_id="SSE:601398",
                execution_session=_BUSINESS_DATE,
                quantity=Decimal("3"),
                amount=Decimal("30"),
                complete=True,
            ),
        ),
        active_orders_complete=True,
        execution_session=_BUSINESS_DATE,
        executed_usage_complete=True,
    )
    global_incomplete_snapshot = replace(
        complete_snapshot,
        snapshot_id="account-snapshot-global-incomplete-known-row",
        executed_usage_complete=False,
    )
    policy = _policy_bundle(
        snapshot_id="runtime-snapshot-global-incomplete-known-row",
        snapshot_hash="9" * 64,
    )
    assets = (
        PortfolioRiskAssetInputs(
            asset_code="600036",
            security_id="SSE:600036",
            kind=None,
            price=None,
            quantity_unit="share",
            price_unit=None,
            valuation_evidence=None,
            industry_membership=None,
            etf_report=None,
            capacity_observation=None,
        ),
        PortfolioRiskAssetInputs(
            asset_code="601398",
            security_id="SSE:601398",
            kind=None,
            price=None,
            quantity_unit="share",
            price_unit=None,
            valuation_evidence=None,
            industry_membership=None,
            etf_report=None,
            capacity_observation=None,
        ),
    )

    results = tuple(
        _capacity_usage_for_pair(
            snapshot=global_incomplete_snapshot,
            proposals=(),
            policy=policy,
            asset=asset,
            source_reference_bindings=(),
            as_of=_AS_OF,
            business_date=_BUSINESS_DATE,
        )
        for asset in assets
    )

    assert tuple(result.executed_usage_complete for result, _reasons in results) == (
        False,
        False,
    )
    assert tuple(reasons for _result, reasons in results) == (
        ["CAPACITY_EXECUTED_USAGE_SNAPSHOT_INCOMPLETE"],
        ["CAPACITY_EXECUTED_USAGE_SNAPSHOT_INCOMPLETE"],
    )


@pytest.mark.parametrize(
    "usage",
    [
        (),
        (
            ExecutedUsage(
                asset_code="601398",
                security_id="SSE:601398",
                execution_session=date(2026, 11, 2),
                quantity=None,
                amount=None,
                complete=False,
            ),
        ),
    ],
)
def test_unscoped_execution_gap_remains_global_unknown(
    usage: tuple[ExecutedUsage, ...],
) -> None:
    """An unexplained global completeness failure cannot be inferred as zero."""

    snapshot = AccountSnapshot(
        account_id=12,
        owner_user_id=4,
        snapshot_id="account-snapshot-global-incomplete-usage",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(),
        active_orders=(),
        executed_usage=usage,
        active_orders_complete=True,
        execution_session=_BUSINESS_DATE,
        executed_usage_complete=False,
    )

    policy = _policy_bundle(
        snapshot_id="runtime-snapshot-global-incomplete-usage",
        snapshot_hash="8" * 64,
    )
    asset = PortfolioRiskAssetInputs(
        asset_code="601398",
        security_id="SSE:601398",
        kind=None,
        price=None,
        quantity_unit="share",
        price_unit=None,
        valuation_evidence=None,
        industry_membership=None,
        etf_report=None,
        capacity_observation=None,
    )
    result, reasons = _capacity_usage_for_pair(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        asset=asset,
        source_reference_bindings=(),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
    )

    assert result.volume.value is None
    assert result.amount.value is None
    assert result.executed_usage_complete is False
    assert reasons == ["CAPACITY_EXECUTED_USAGE_SNAPSHOT_INCOMPLETE"]


def test_zero_quantity_holding_does_not_request_unavailable_or_stale_sources() -> None:
    """A zero row makes no source request; empty source proof remains unqualified."""

    policy = _policy_bundle(
        snapshot_id="runtime-snapshot-zero-position",
        snapshot_hash="2" * 64,
    )
    snapshot = AccountSnapshot(
        account_id=12,
        owner_user_id=4,
        snapshot_id="account-snapshot-zero-position",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code="600036",
                quantity=Decimal("0"),
                available_quantity=None,
                security_id=None,
            ),
        ),
        active_orders=(),
        executed_usage=(),
        active_orders_complete=True,
        execution_session=_BUSINESS_DATE,
        executed_usage_complete=True,
    )
    no_requested_source_result = PortfolioRiskAssetsReadResult(
        status="complete",
        assets=(),
        all_source_evidence=(),
        reason_codes=(),
        policy_snapshot_id=policy.snapshot_id,
        policy_snapshot_hash=policy.snapshot_hash,
    )

    identity_basis, resolved, reasons = _resolve_asset_inputs(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        asset_inputs=no_requested_source_result,
    )

    assert snapshot.holdings[0].quantity == Decimal("0")
    assert _requested_asset_codes(snapshot, ()) == set()
    assert identity_basis == {}
    assert resolved == {}
    assert reasons == []

    result = assess_simulated_portfolio_risk(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        asset_inputs=no_requested_source_result,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity_preflight",
    )
    empty_snapshot_result = assess_simulated_portfolio_risk(
        snapshot=_cash_snapshot(),
        proposals=(),
        policy=policy,
        asset_inputs=no_requested_source_result,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity_preflight",
    )
    input_scope = next(
        check for check in result.report_payload["checks"] if check["dimension"] == "input_scope"
    )
    source_check = next(
        check for check in result.report_payload["checks"] if check["dimension"] == "source_inputs"
    )

    assert input_scope["status"] == "allowed"
    assert "PORTFOLIO_ASSET_READER_INPUT_MISSING" not in input_scope["reason_codes"]
    assert source_check["status"] == "unknown"
    assert "PORTFOLIO_REPORT_SOURCE_EVIDENCE_EMPTY" in source_check["reason_codes"]
    assert result.report_payload["freshness"] == "unknown"
    assert result.report_payload["must_not_use_for_decision"] is True
    assert (
        result.report_payload["resource_snapshot_hash"]
        != empty_snapshot_result.report_payload["resource_snapshot_hash"]
    )


def test_multiple_active_and_proposed_buys_are_added_gross() -> None:
    """Same-security reservations compete cumulatively and do not net by order."""

    active = (
        OpenOrder(
            order_id="reservation-1",
            asset_code="600036",
            security_id="SSE:600036",
            side="buy",
            remaining_quantity=Decimal("2"),
            remaining_amount=Decimal("19"),
        ),
        OpenOrder(
            order_id="reservation-2",
            asset_code="600036",
            security_id="SSE:600036",
            side="buy",
            remaining_quantity=Decimal("3"),
            remaining_amount=Decimal("27"),
        ),
    )
    proposed = (
        ProposedOrder(
            order_id="proposal-1",
            asset_code="600036",
            security_id="SSE:600036",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("9"),
        ),
    )

    assert project_gross_asset_exposure(
        held_quantity=Decimal("4"),
        active_orders=active,
        proposed_orders=proposed,
        qualified_current_price=Decimal("10"),
    ) == Decimal("100")


def test_unknown_price_does_not_zero_held_or_buy_value() -> None:
    """An unknown current price remains unknown for any nonzero held or BUY amount."""

    assert value_held_quantity(Decimal("1"), None) is None
    assert (
        project_gross_asset_exposure(
            held_quantity=Decimal("0"),
            active_orders=(),
            proposed_orders=(
                ProposedOrder(
                    order_id="proposal-1",
                    asset_code="600036",
                    security_id="SSE:600036",
                    side="buy",
                    quantity=Decimal("1"),
                    price=Decimal("10"),
                ),
            ),
            qualified_current_price=None,
        )
        is None
    )


def test_snapshot_keeps_unresolved_execution_scope_without_fabricated_values() -> None:
    """Legacy execution rows keep missing identity/session and fail completeness."""

    usage = ExecutedUsage(
        asset_code="600036",
        security_id=None,
        execution_session=None,
        quantity=None,
        amount=None,
        complete=False,
    )
    snapshot = AccountSnapshot(
        account_id=1,
        owner_user_id=2,
        snapshot_id="snap-1",
        read_at=datetime(2026, 11, 3, 1, 0, tzinfo=UTC),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code="600036",
                quantity=Decimal("1"),
                available_quantity=None,
            ),
        ),
        active_orders=(),
        executed_usage=(usage,),
        active_orders_complete=True,
        execution_session=date(2026, 11, 3),
        executed_usage_complete=True,
    )

    assert snapshot.executed_usage[0].security_id is None
    assert snapshot.executed_usage[0].execution_session is None
    assert snapshot.executed_usage[0].amount is None
    assert snapshot.executed_usage_complete is True


def test_snapshot_rejects_naive_read_clock_and_duplicate_active_order_ids() -> None:
    """Snapshot scope cannot use naive clocks or double-count an order identifier."""

    active_order = OpenOrder(
        order_id="same-order",
        asset_code="600036",
        security_id="SSE:600036",
        side="buy",
        remaining_quantity=Decimal("1"),
        remaining_amount=Decimal("10"),
    )
    with pytest.raises(ValueError):
        AccountSnapshot(
            account_id=1,
            owner_user_id=2,
            snapshot_id="snap-naive",
            read_at=datetime(2026, 11, 3, 1, 0),
            cash=Decimal("100"),
            money_unit="CNY",
            holdings=(),
            active_orders=(),
            executed_usage=(),
            active_orders_complete=True,
            execution_session=date(2026, 11, 3),
            executed_usage_complete=True,
        )
    with pytest.raises(ValueError):
        AccountSnapshot(
            account_id=1,
            owner_user_id=2,
            snapshot_id="snap-duplicate-order",
            read_at=datetime(2026, 11, 3, 1, 0, tzinfo=UTC),
            cash=Decimal("100"),
            money_unit="CNY",
            holdings=(),
            active_orders=(active_order, active_order),
            executed_usage=(),
            active_orders_complete=True,
            execution_session=date(2026, 11, 3),
            executed_usage_complete=True,
        )


def test_float_values_are_rejected_at_snapshot_boundary() -> None:
    """Exact financial measures never accept binary floats."""

    with pytest.raises(TypeError):
        HeldPosition(asset_code="600036", quantity=1.0, available_quantity=None)


def test_active_order_cash_and_proposed_fee_cap_are_retained_as_exact_inputs() -> None:
    """Baseline cash facts remain available and are part of the immutable DTO."""

    open_order = OpenOrder(
        order_id="reservation-cash",
        asset_code="600036",
        security_id="SSE:600036",
        side="buy",
        remaining_quantity=Decimal("1"),
        remaining_amount=Decimal("10"),
        remaining_cash=Decimal("12.01"),
    )
    proposal = ProposedOrder(
        order_id="proposal-fee",
        asset_code="600036",
        security_id="SSE:600036",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("10"),
        fee_cap=Decimal("0.03"),
    )

    assert open_order.remaining_cash == Decimal("12.01")
    assert proposal.fee_cap == Decimal("0.03")


def test_exact_decimal_arithmetic_does_not_use_context_rounded_float_math() -> None:
    """Risk projection preserves exact finite decimal products and sums."""

    assert exact_decimal_product(Decimal("0.1"), Decimal("0.2")) == Decimal("0.02")
    assert exact_decimal_sum((Decimal("0.1"), Decimal("0.2"))) == Decimal("0.3")


def test_missing_cash_stays_unknown_instead_of_becoming_zero_nav() -> None:
    """An empty known holdings set cannot turn missing cash into a valid NAV."""

    snapshot = AccountSnapshot(
        account_id=1,
        owner_user_id=2,
        snapshot_id="snap-cash-unknown",
        read_at=datetime(2026, 11, 3, 1, 0, tzinfo=UTC),
        cash=None,
        money_unit="CNY",
        holdings=(),
        active_orders=(),
        executed_usage=(),
        active_orders_complete=True,
        execution_session=date(2026, 11, 3),
        executed_usage_complete=True,
    )

    holdings_value, nav, reasons = _project_pre_trade_nav(
        snapshot=snapshot,
        policy=cast(PortfolioRiskPolicyBundle, None),
        resolved_assets={},
        source_reference_bindings=(),
        business_date=date(2026, 11, 3),
        as_of=datetime(2026, 11, 3, 1, 1, tzinfo=UTC),
    )

    assert holdings_value == Decimal("0")
    assert nav is None
    assert reasons == ["PORTFOLIO_CASH_UNKNOWN"]


def test_cash_with_nonmatching_money_unit_cannot_enter_nav() -> None:
    """The source account unit must match the explicit risk policy ledger unit."""

    snapshot = AccountSnapshot(
        account_id=1,
        owner_user_id=2,
        snapshot_id="snap-unit-mismatch",
        read_at=datetime(2026, 11, 3, 1, 0, tzinfo=UTC),
        cash=Decimal("100"),
        money_unit="USD",
        holdings=(),
        active_orders=(),
        executed_usage=(),
        active_orders_complete=True,
        execution_session=date(2026, 11, 3),
        executed_usage_complete=True,
    )

    holdings_value, nav, reasons = _project_pre_trade_nav(
        snapshot=snapshot,
        policy=cast(
            PortfolioRiskPolicyBundle,
            SimpleNamespace(ledger_money_unit="CNY"),
        ),
        resolved_assets={},
        source_reference_bindings=(),
        business_date=date(2026, 11, 3),
        as_of=datetime(2026, 11, 3, 1, 1, tzinfo=UTC),
    )

    assert holdings_value == Decimal("0")
    assert nav is None
    assert reasons == ["PORTFOLIO_MONEY_UNIT_POLICY_MISMATCH"]


def test_missing_valuation_source_or_wrong_price_unit_does_not_supply_price() -> None:
    """Missing price evidence and a mismatched money unit both remain unknown."""

    policy = cast(
        PortfolioRiskPolicyBundle,
        SimpleNamespace(ledger_money_unit="CNY"),
    )
    missing_source = SimpleNamespace(
        price=Decimal("10"),
        quantity_unit="share",
        price_unit="CNY",
        valuation_evidence=None,
        security_id="SSE:600036",
    )
    wrong_unit = SimpleNamespace(
        price=Decimal("10"),
        quantity_unit="share",
        price_unit="USD",
        valuation_evidence=None,
        security_id="SSE:600036",
    )
    as_of = datetime(2026, 11, 3, 1, 1, tzinfo=UTC)

    assert (
        _qualified_current_price(
            asset=missing_source,
            policy=policy,
            source_reference_bindings=(),
            business_date=date(2026, 11, 3),
            as_of=as_of,
        )
        is None
    )
    assert (
        _qualified_current_price(
            asset=wrong_unit,
            policy=policy,
            source_reference_bindings=(),
            business_date=date(2026, 11, 3),
            as_of=as_of,
        )
        is None
    )


def test_asset_inputs_from_a_different_policy_source_pin_are_rejected() -> None:
    """A reread cannot silently reuse a source record after its pin changes."""

    payload_hash = "a" * 64
    manifest_hash = "b" * 64
    asset = SimpleNamespace(
        asset_code="600036",
        security_id="SSE:600036",
        valuation_evidence=SimpleNamespace(
            original_payload_sha256=payload_hash,
            source_record_id="record-current",
        ),
    )
    old_reference = PortfolioRiskSourceReference(
        kind="valuation",
        asset_code="600036",
        security_id="SSE:600036",
        raw_payload_hash=f"sha256:{manifest_hash}",
        source_record_id="record-current",
    )
    changed_reference = PortfolioRiskSourceReference(
        kind="valuation",
        asset_code="600036",
        security_id="SSE:600036",
        raw_payload_hash=f"sha256:{'c' * 64}",
        source_record_id="record-current",
    )
    changed_record_reference = PortfolioRiskSourceReference(
        kind="valuation",
        asset_code="600036",
        security_id="SSE:600036",
        raw_payload_hash=f"sha256:{manifest_hash}",
        source_record_id="record-replaced",
    )

    assert _valuation_reference_matches(
        asset=asset,
        references=(old_reference,),
        source_reference_bindings=(old_reference,),
    )
    assert not _valuation_reference_matches(
        asset=asset,
        references=(changed_reference,),
        source_reference_bindings=(old_reference,),
    )
    assert not _valuation_reference_matches(
        asset=asset,
        references=(changed_record_reference,),
        source_reference_bindings=(changed_record_reference,),
    )


def test_aggregate_requires_reader_to_use_the_exact_active_policy_snapshot() -> None:
    """A result read under an older runtime snapshot cannot pass a newer policy."""

    policy = _policy_bundle(
        snapshot_id="runtime-snapshot-new",
        snapshot_hash="f" * 64,
    )
    matching_inputs = PortfolioRiskAssetsReadResult(
        status="complete",
        assets=(),
        all_source_evidence=(),
        reason_codes=(),
        policy_snapshot_id=policy.snapshot_id,
        policy_snapshot_hash=policy.snapshot_hash,
    )
    stale_id_inputs = PortfolioRiskAssetsReadResult(
        status="complete",
        assets=(),
        all_source_evidence=(),
        reason_codes=(),
        policy_snapshot_id="runtime-snapshot-old",
        policy_snapshot_hash=policy.snapshot_hash,
    )
    stale_hash_inputs = PortfolioRiskAssetsReadResult(
        status="complete",
        assets=(),
        all_source_evidence=(),
        reason_codes=(),
        policy_snapshot_id=policy.snapshot_id,
        policy_snapshot_hash="a" * 64,
    )
    matching = assess_simulated_portfolio_risk(
        snapshot=_cash_snapshot(),
        proposals=(),
        policy=policy,
        asset_inputs=matching_inputs,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity_preflight",
    )
    stale_id = assess_simulated_portfolio_risk(
        snapshot=_cash_snapshot(),
        proposals=(),
        policy=policy,
        asset_inputs=stale_id_inputs,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity_preflight",
    )
    stale_hash = assess_simulated_portfolio_risk(
        snapshot=_cash_snapshot(),
        proposals=(),
        policy=policy,
        asset_inputs=stale_hash_inputs,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity_preflight",
    )
    matching_scope = next(
        check for check in matching.report_payload["checks"] if check["dimension"] == "input_scope"
    )
    stale_id_scope = next(
        check for check in stale_id.report_payload["checks"] if check["dimension"] == "input_scope"
    )
    stale_hash_scope = next(
        check
        for check in stale_hash.report_payload["checks"]
        if check["dimension"] == "input_scope"
    )

    assert "PORTFOLIO_ASSET_READER_POLICY_SNAPSHOT_MISMATCH" not in matching_scope["reason_codes"]
    assert "PORTFOLIO_ASSET_READER_POLICY_SNAPSHOT_MISMATCH" in stale_id_scope["reason_codes"]
    assert "PORTFOLIO_ASSET_READER_POLICY_SNAPSHOT_MISMATCH" in stale_hash_scope["reason_codes"]
    assert stale_id.report_payload["outcome"] == "blocked"
    assert stale_hash.report_payload["outcome"] == "blocked"
    assert (
        stale_hash.report_payload["resource_snapshot_hash"]
        != matching.report_payload["resource_snapshot_hash"]
    )


def test_aggregate_blocks_reader_result_without_policy_identity() -> None:
    """Missing reader binding remains blocked even when the source read is partial."""

    policy = _policy_bundle(
        snapshot_id="runtime-snapshot-current",
        snapshot_hash="f" * 64,
    )
    unbound_inputs = PortfolioRiskAssetsReadResult(
        status="blocked",
        assets=(),
        all_source_evidence=(),
        reason_codes=("RISK_INPUTS_BLOCKED",),
    )

    result = assess_simulated_portfolio_risk(
        snapshot=_cash_snapshot(),
        proposals=(),
        policy=policy,
        asset_inputs=unbound_inputs,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity_preflight",
    )
    scope_check = next(
        check for check in result.report_payload["checks"] if check["dimension"] == "input_scope"
    )

    assert result.report_payload["outcome"] == "blocked"
    assert "PORTFOLIO_ASSET_READER_POLICY_SNAPSHOT_MISMATCH" in scope_check["reason_codes"]


def test_unconfigured_policy_accepts_only_the_blocked_unbound_reader_shape() -> None:
    """An absent policy stays blocked without inventing reader snapshot identity."""

    unbound_inputs = PortfolioRiskAssetsReadResult(
        status="blocked",
        assets=(),
        all_source_evidence=(),
        reason_codes=("SIMULATED_PORTFOLIO_RISK_POLICY_MISSING",),
    )

    result = assess_simulated_portfolio_risk(
        snapshot=_cash_snapshot(),
        proposals=(),
        policy=None,
        asset_inputs=unbound_inputs,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity_preflight",
    )
    scope_check = next(
        check for check in result.report_payload["checks"] if check["dimension"] == "input_scope"
    )

    assert result.report_payload["outcome"] == "blocked"
    assert "PORTFOLIO_RISK_POLICY_UNCONFIGURED" in scope_check["reason_codes"]
    assert "PORTFOLIO_ASSET_READER_POLICY_SNAPSHOT_MISMATCH" not in scope_check["reason_codes"]
