"""Behavior tests for auto-advisor application provider boundaries."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.account.application.portfolio_api_services import PortfolioNotFoundError
from apps.decision_rhythm.application.advisor_contracts import (
    AdvisorAccessError,
    AdvisorHoldingSnapshot,
    AdvisorOrderIntent,
    get_manual_trade_portfolio_id_for_account,
)
from apps.decision_rhythm.application.advisor_providers import (
    AccountHoldingSnapshotProvider,
    DataCenterAssetExposureProvider,
    DecisionExecutionTrackingProvider,
    DecisionRhythmExecutionGuardProvider,
    RegimePolicyAttributionContextProvider,
    RiskCenterAdvisorGateProvider,
    WorkspaceRecommendationProvider,
)


def _intent(
    *,
    side: str = "BUY",
    blocking_status: str = "OK",
) -> AdvisorOrderIntent:
    return AdvisorOrderIntent(
        order_intent_id="intent-1",
        account_id="7",
        asset_code="000001.SZ",
        asset_name="平安银行",
        side=side,
        current_quantity=Decimal("100"),
        target_quantity=Decimal("200"),
        delta_quantity=Decimal("100"),
        estimated_price=Decimal("10"),
        estimated_amount=Decimal("1000"),
        current_weight=Decimal("0.1"),
        target_weight=Decimal("0.2"),
        priority=1,
        price_band={},
        reason="test",
        risk_notes=[],
        invalidation_rule="price below 8",
        execution_hint="limit",
        source_recommendation_id="rec-1",
        blocking_status=blocking_status,
    )


def _holding() -> AdvisorHoldingSnapshot:
    return AdvisorHoldingSnapshot(
        asset_code="000001.SZ",
        asset_name="平安银行",
        asset_class="equity",
        quantity=Decimal("100"),
        market_value=Decimal("1000"),
        current_weight=Decimal("0.1"),
        avg_cost=Decimal("9"),
        current_price=Decimal("10"),
        unrealized_pnl=Decimal("100"),
        unrealized_pnl_pct=Decimal("0.1"),
        data_source="simulated",
        price_time="2026-07-24T00:00:00+00:00",
    )


def test_manual_trade_portfolio_id_uses_account_portfolio_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy bridge returns the integer portfolio id for an account."""
    repository = SimpleNamespace(
        get_portfolio_for_account=lambda account_id: SimpleNamespace(id=str(account_id + 5))
    )
    monkeypatch.setattr(
        "apps.account.application.repository_provider.get_portfolio_api_repository",
        lambda: repository,
    )

    assert get_manual_trade_portfolio_id_for_account(7) == 12


def test_manual_trade_portfolio_id_returns_none_without_linked_portfolio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy bridge preserves an explicit missing-portfolio result."""
    repository = SimpleNamespace(get_portfolio_for_account=lambda _account_id: None)
    monkeypatch.setattr(
        "apps.account.application.repository_provider.get_portfolio_api_repository",
        lambda: repository,
    )

    assert get_manual_trade_portfolio_id_for_account(7) is None


def test_workspace_recommendation_provider_enforces_stable_query_contract(
    monkeypatch,
) -> None:
    """The provider requests only active, non-ignored recommendations."""
    calls = {}

    def list_recommendations(**kwargs):
        calls.update(kwargs)
        return (["recommendation"], 1)

    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.list_workspace_recommendations",
        list_recommendations,
    )

    result = WorkspaceRecommendationProvider().list_recommendations(account_id="7")

    assert result == ["recommendation"]
    assert calls == {
        "account_id": "7",
        "status": None,
        "user_action": None,
        "security_code": None,
        "include_ignored": False,
        "recommendation_id": None,
        "page": 1,
        "page_size": 50,
    }


@pytest.mark.parametrize(
    ("side", "expected_status"),
    [("BUY", "BLOCKED"), ("SELL", "REVIEW")],
)
def test_risk_gate_fails_closed_when_policy_is_unavailable(
    side: str,
    expected_status: str,
) -> None:
    """Missing risk policy blocks added exposure and reviews reductions."""
    result = RiskCenterAdvisorGateProvider().evaluate_order(
        account={},
        intent=_intent(side=side),
        holdings=[],
        policy_context={"unavailable": True, "version": "policy-v1"},
    )

    assert result["status"] == expected_status
    assert result["code"] == "risk_policy_unavailable"
    assert result["policy_version"] == "policy-v1"


def test_risk_gate_skips_non_actionable_intent() -> None:
    """A pre-blocked recommendation never reaches the trade risk evaluator."""
    result = RiskCenterAdvisorGateProvider().evaluate_order(
        account={},
        intent=_intent(blocking_status="BLOCKED"),
        holdings=[],
        policy_context={"unavailable": False, "version": "policy-v2"},
    )

    assert result == {
        "status": "SKIPPED",
        "code": "not_actionable",
        "messages": [],
        "policy_version": "policy-v2",
        "metrics": {},
    }


def test_risk_gate_maps_pass_with_warning_to_review(monkeypatch) -> None:
    """Risk warnings require review even when hard constraints pass."""
    captured = {}

    class _RiskUseCase:
        def execute(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                passed=True,
                violations=[],
                warnings=["concentration near limit"],
                metrics={"position_ratio": 0.2},
            )

    monkeypatch.setattr(
        "apps.risk_center.application.trade_guard.EvaluatePreTradeRiskUseCase",
        _RiskUseCase,
    )
    result = RiskCenterAdvisorGateProvider().evaluate_order(
        account={
            "total_asset": "10000",
            "available_cash": "2000",
            "market_value": "8000",
        },
        intent=_intent(),
        holdings=[_holding()],
        policy_context={"version": "policy-v3"},
    )

    assert result["status"] == "REVIEW"
    assert result["code"] == "risk_gate_passed"
    assert result["messages"] == ["concentration near limit"]
    assert captured["current_symbol_position_value"] == 1000.0
    assert captured["side"] == "buy"


def test_execution_guard_skips_non_actionable_and_blocks_failed_check(
    monkeypatch,
) -> None:
    """Execution checks distinguish skipped intents from explicit failures."""
    provider = DecisionRhythmExecutionGuardProvider()

    assert (
        provider.evaluate(
            recommendation=None,
            intent=_intent(),
            resolution=None,
        )["status"]
        == "SKIPPED"
    )

    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.build_recommendation_risk_checks",
        lambda recommendation, price: {
            "valuation": {"passed": False, "reason": "price above band"}
        },
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.get_signal_payloads",
        lambda signal_ids: [],
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers._failed_execution_checks",
        lambda checks: [{"reason": "price above band"}],
    )

    blocked = provider.evaluate(
        recommendation=SimpleNamespace(signal_id=3),
        intent=_intent(),
        resolution={"source_signal_ids": [3]},
    )

    assert blocked["status"] == "BLOCKED"
    assert blocked["code"] == "execution_guard_failed"
    assert blocked["messages"] == ["price above band"]


def test_asset_exposure_provider_deduplicates_and_preserves_missing_assets(
    monkeypatch,
) -> None:
    """Asset resolution is deterministic and missing masters remain explicit."""
    responses = {
        "000001.SZ": {
            "sector": "金融",
            "industry": "银行",
            "asset_type": "equity",
        },
        "MISSING": None,
    }
    monkeypatch.setattr(
        "apps.data_center.application.public.resolve_asset_payload",
        lambda code: responses[code],
    )

    result = DataCenterAssetExposureProvider().get_asset_exposures(
        asset_codes=["000001.SZ", "000001.SZ", "MISSING"],
    )

    assert result == {
        "000001.SZ": {
            "sector": "金融",
            "industry": "银行",
            "asset_type": "equity",
        },
        "MISSING": {},
    }


def test_execution_tracking_filters_other_recommendations_and_keeps_empty_groups(
    monkeypatch,
) -> None:
    """Tracking cannot leak links belonging to another recommendation."""
    monkeypatch.setattr(
        "core.integration.decision_execution_links.list_decision_execution_links",
        lambda **kwargs: [
            {"recommendation_id": "rec-1", "transaction_id": "tx-1"},
            {"recommendation_id": "other", "transaction_id": "tx-2"},
        ],
    )
    user = SimpleNamespace(id=11, is_staff=False, is_superuser=False)

    result = DecisionExecutionTrackingProvider().get_execution_links(
        account_id="7",
        recommendation_ids=["rec-1", "rec-2"],
        user=user,
    )

    assert result == {
        "rec-1": [{"recommendation_id": "rec-1", "transaction_id": "tx-1"}],
        "rec-2": [],
    }


def test_attribution_context_reports_partial_failure_and_caches_result(
    monkeypatch,
) -> None:
    """A policy failure is visible while the successful regime value is retained."""
    calls = {"regime": 0, "policy": 0}

    def regime_payload(*, as_of_date):
        calls["regime"] += 1
        return {"data": {"dominant_regime": "recovery", "confidence": "0.8"}}

    def policy_payload(*, as_of_date):
        calls["policy"] += 1
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(
        "apps.regime.application.interface_services.get_regime_current_payload",
        regime_payload,
    )
    monkeypatch.setattr(
        "apps.policy.application.query_services.get_policy_status_payload",
        policy_payload,
    )
    provider = RegimePolicyAttributionContextProvider()
    target = date(2026, 7, 24)

    first = provider.get_context(
        recommendation_date=target,
        outcome_date=None,
    )
    second = provider.get_context(
        recommendation_date=target,
        outcome_date=target,
    )

    assert first["recommendation"]["status"] == "PARTIAL"
    assert first["recommendation"]["regime"] == "recovery"
    assert first["recommendation"]["policy_level"] is None
    assert first["recommendation"]["errors"] == ["policy:policy unavailable"]
    assert first["outcome"]["status"] == "DATE_UNAVAILABLE"
    assert second["recommendation"] == second["outcome"]
    assert calls == {"regime": 1, "policy": 1}


def test_account_snapshot_denies_cross_user_access(monkeypatch) -> None:
    """An account ownership failure is propagated with the boundary status code."""
    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.get_account_access",
        lambda user, account_id, action: SimpleNamespace(
            allowed=False,
            error="forbidden",
            status_code=403,
            account=None,
        ),
    )

    with pytest.raises(AdvisorAccessError) as exc_info:
        AccountHoldingSnapshotProvider().get_snapshot(
            account_id="7",
            user=SimpleNamespace(id=11),
        )

    assert str(exc_info.value) == "forbidden"
    assert exc_info.value.status_code == 403


def test_account_snapshot_surfaces_partial_position_sources(monkeypatch) -> None:
    """Unavailable simulated/manual positions become warnings, not silent success."""
    account = SimpleNamespace(
        current_cash=Decimal("1000"),
        total_value=Decimal("0"),
        current_market_value=Decimal("0"),
        account_type="paper",
        account_name="Test",
        is_active=True,
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.get_account_access",
        lambda user, account_id, action: SimpleNamespace(
            allowed=True,
            error=None,
            status_code=None,
            account=account,
        ),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.get_simulated_position_snapshots",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("simulated down")),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.get_manual_trade_portfolio_id_for_account",
        lambda account_id: 99,
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.get_portfolio_positions_read_payload",
        lambda **kwargs: (_ for _ in ()).throw(PortfolioNotFoundError("portfolio missing")),
    )

    snapshot = AccountHoldingSnapshotProvider().get_snapshot(
        account_id="7",
        user=SimpleNamespace(id=11),
    )

    assert snapshot.baseline == "empty_positions"
    assert snapshot.account_summary["total_asset"] == 1000
    assert snapshot.warnings == [
        "simulated_positions_unavailable:simulated down",
        "manual_portfolio_unavailable:portfolio missing",
    ]
