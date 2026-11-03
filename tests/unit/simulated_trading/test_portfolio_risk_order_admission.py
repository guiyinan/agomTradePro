"""Service contracts for SELL admission alongside a truthful risk overview."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import cast

import pytest

from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload
from apps.risk_center.application.portfolio_risk_order_admission import (
    portfolio_risk_order_admission_is_effective,
)
from apps.risk_center.domain.portfolio_capacity import CapacityValue
from apps.risk_center.domain.portfolio_risk_snapshot import ProposedOrder
from apps.simulated_trading.application import portfolio_risk_preview_gate as preview_gate_module
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.portfolio_risk_preview_gate import (
    ConfiguredPortfolioRiskPreviewGate,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskAccountAccessDenied,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    AccountSnapshotReadResult,
    PortfolioRiskAccountScope,
    PortfolioRiskIdentityIssue,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from tests.unit.simulated_trading import test_portfolio_risk_service as service_fixtures
from tests.unit.simulated_trading.test_portfolio_risk_service import (
    _AS_OF,
    _ASSET_CODE,
    _SESSION,
    _harness,
    _intent,
)
from tests.unit.simulated_trading.test_rebalance_preview_sell_integrity import (
    _finish,
    _preview_item,
)


def _sell_intent() -> service_fixtures.SimulatedTradeIntent:
    """Use the existing exact service fixture with a fresh SELL identity."""

    return replace(
        _intent(),
        idempotency_key="sell-test-01",
        side=SimulatedTradeSide.SELL,
    )


def _breach_legacy_buy_limits(harness: service_fixtures._Harness) -> None:
    """Set explicit persisted-like thresholds below current account values."""

    harness.baseline_reader.policy = replace(
        harness.baseline_reader.policy,
        max_total_weight=Decimal("0.05"),
        max_single_weight=Decimal("0.05"),
        min_cash_weight=Decimal("0.99"),
    )


def test_sell_is_admitted_over_known_legacy_limits_without_rewriting_report() -> None:
    harness = _harness()
    _breach_legacy_buy_limits(harness)

    intent = _sell_intent()
    qualification = harness.service.validate_order(
        intent=intent,
        fee_cap=Decimal("0.37"),
        as_of=_AS_OF,
        execution_session=_SESSION,
    )

    assert qualification.execution_session == _SESSION
    assert len(harness.writer.records) == 1
    report = harness.writer.records[0].report
    assert report["outcome"] == "blocked"
    assert report["must_not_use_for_decision"] is False
    baseline = next(item for item in report["checks"] if item["dimension"] == "baseline_risk")
    assert baseline["status"] == "blocked"
    admission = report["order_admission"]
    assert admission["side"] == "sell"
    assert admission["outcome"] == "allowed"
    assert admission["subject_id"] == intent.idempotency_key
    assert portfolio_risk_order_admission_is_effective(
        report,
        subject_id=intent.idempotency_key,
        side="sell",
        order_ids=(f"new:{intent.idempotency_key}",),
    )
    assert set(admission["waived_reason_codes"]) == {
        "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT",
        "PORTFOLIO_BASELINE_SINGLE_POSITION_LIMIT",
        "PORTFOLIO_BASELINE_CASH_FLOOR",
    }


def test_buy_remains_blocked_by_the_same_limits() -> None:
    harness = _harness()
    _breach_legacy_buy_limits(harness)

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.service.validate_order(
            intent=_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT" in error.value.details["reason_codes"]
    assert harness.writer.records == []


def test_sell_still_fails_hard_exclusion() -> None:
    harness = _harness(hard_exclusions=(_ASSET_CODE,))

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.service.validate_order(
            intent=_sell_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert "PORTFOLIO_BASELINE_HARD_EXCLUSION" in error.value.details["reason_codes"]
    assert harness.writer.records == []


def test_sell_still_requires_owner_write_scope() -> None:
    harness = _harness(
        scope=PortfolioRiskAccountScope(
            owner_user_id=4,
            can_read=True,
            can_write=False,
        )
    )

    with pytest.raises(PortfolioRiskAccountAccessDenied):
        harness.service.validate_order(
            intent=_sell_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert harness.writer.records == []


def test_foreign_sell_cannot_reach_legacy_limit_waiver() -> None:
    """A missing account grant rejects SELL before risk inputs or waiver evaluation."""

    harness = _harness()
    _breach_legacy_buy_limits(harness)
    harness.resources.scope = None

    with pytest.raises(PortfolioRiskAccountAccessDenied):
        harness.service.validate_order(
            intent=_sell_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert len(harness.resources.reads) == 1
    assert harness.assets_reader.requests == []
    assert harness.writer.records == []


def test_sell_still_fails_ledger_identity_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _harness()
    original_read = harness.resources.read_account_snapshot

    def read_account_snapshot(
        *,
        user_id: int,
        account_id: int,
        execution_session: date,
        money_unit: str | None,
    ) -> AccountSnapshotReadResult:
        result = original_read(
            user_id=user_id,
            account_id=account_id,
            execution_session=execution_session,
            money_unit=money_unit,
        )
        return replace(
            result,
            identity_issues=(PortfolioRiskIdentityIssue(_ASSET_CODE, "conflict"),),
        )

    monkeypatch.setattr(harness.resources, "read_account_snapshot", read_account_snapshot)

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.service.validate_order(
            intent=_sell_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert "PORTFOLIO_LEDGER_IDENTITY_CONFLICT" in error.value.details["reason_codes"]
    assert harness.writer.records == []


@pytest.mark.parametrize("source_mode", ("unknown", "expired"))
def test_sell_still_fails_unknown_or_expired_sources(source_mode: str) -> None:
    harness = _harness(source_mode=source_mode)

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.service.validate_order(
            intent=_sell_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert error.value.details["reason_codes"]
    assert harness.writer.records == []


def test_sell_still_fails_real_gross_capacity_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _harness()
    original_read_assets = harness.assets_reader.read_assets

    def read_assets(request: PortfolioRiskAssetsReadRequest) -> PortfolioRiskAssetsReadResult:
        result = original_read_assets(request)
        adjusted = []
        for asset in result.assets:
            observation = asset.capacity_observation
            assert observation is not None
            adjusted.append(
                replace(
                    asset,
                    capacity_observation=replace(
                        observation,
                        volume=CapacityValue(Decimal("10"), "share"),
                    ),
                )
            )
        return replace(result, assets=tuple(adjusted))

    monkeypatch.setattr(harness.assets_reader, "read_assets", read_assets)

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.service.validate_order(
            intent=_sell_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert any(reason.startswith("CAPACITY_") for reason in error.value.details["reason_codes"])
    assert harness.writer.records == []


def test_sell_still_fails_new_industry_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    original_configuration = service_fixtures._configuration

    def concentrated_industry_configuration(*, close_mode: bool = False) -> dict[str, object]:
        configuration = original_configuration(close_mode=close_mode)
        industry = cast(dict[str, object], configuration["industry"])
        configuration["industry"] = {**industry, "max_industry_weight": "0.05"}
        return configuration

    monkeypatch.setattr(
        service_fixtures,
        "_configuration",
        concentrated_industry_configuration,
    )
    harness = _harness()

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.service.validate_order(
            intent=_sell_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert "INDUSTRY_RISK_LIMIT_BREACHED" in error.value.details["reason_codes"]
    assert harness.writer.records == []


def test_unfilled_sell_does_not_add_proceeds_or_reduce_gross_exposure() -> None:
    harness = _harness()
    proposal = ProposedOrder(
        order_id="preview:sell:600036",
        asset_code=_ASSET_CODE,
        security_id="SSE:600036",
        side="sell",
        quantity=Decimal("10"),
        price=Decimal("9"),
        fee_cap=Decimal("0.37"),
    )

    before = harness.service._contexts.prepare(user_id=4, account_id=12).report
    with_sell = harness.service._contexts.prepare(
        user_id=4,
        account_id=12,
        proposals=(proposal,),
        execution_session=_SESSION,
    ).report

    before_baseline = next(
        item for item in before["checks"] if item["dimension"] == "baseline_risk"
    )
    sell_baseline = next(
        item for item in with_sell["checks"] if item["dimension"] == "baseline_risk"
    )
    assert Decimal(sell_baseline["details"]["projected_total_value"]) == Decimal(
        before_baseline["details"]["projected_total_value"]
    )
    sell_cash = Decimal(sell_baseline["details"]["cash_after_committed_demands"])
    before_cash = Decimal(before_baseline["details"]["cash_after_committed_demands"])
    assert sell_cash == before_cash - Decimal("0.37")
    assert sell_cash < Decimal("10000")
    assert with_sell["order_admission"]["outcome"] == "allowed"
    assert (
        "future_sell_proceeds"
        in next(item for item in with_sell["checks"] if item["dimension"] == "pre_trade_gross_nav")[
            "details"
        ]["excluded"]
    )


def test_preview_gate_uses_sell_admission_without_falsifying_risk_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = _finish(
        [
            _preview_item(
                action="sell",
                asset_code="600036.SH",
                status="ready",
                suggested=Decimal("10"),
                actionable=Decimal("10"),
                fee={"total": "1.00"},
                sellable=Decimal("10"),
            )
        ]
    )
    report: PortfolioRiskReportPayload = {
        "account_id": 12,
        "as_of": _AS_OF.isoformat(),
        "outcome": "blocked",
        "policy_version": "fixture@1",
        "resource_snapshot_hash": "a" * 64,
        "checks": [
            {
                "dimension": "baseline_risk",
                "status": "blocked",
                "reason_codes": ["PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT"],
                "summary": "existing holdings exceed a BUY-only limit",
                "details": {},
            }
        ],
        "sources": [],
        "freshness": "qualified_snapshot",
        "reliability": "source_bound",
        "must_not_use_for_decision": False,
        "order_admission": {
            "side": "sell",
            "order_ids": ["preview:600036.SH:sell"],
            "subject_id": None,
            "outcome": "allowed",
            "reason_codes": [],
            "waived_reason_codes": ["PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT"],
            "decisions": [
                {
                    "order_id": "preview:600036.SH:sell",
                    "side": "sell",
                    "outcome": "allowed",
                    "reason_codes": [],
                    "waived_reason_codes": ["PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT"],
                }
            ],
        },
        "scope": "simulation_only",
        "must_not_execute": True,
    }
    monkeypatch.setattr(
        preview_gate_module,
        "assess_owner_portfolio_preview",
        lambda **_kwargs: report,
    )

    result = ConfiguredPortfolioRiskPreviewGate().qualify_preview(
        preview=preview, user_id=4, account_id=12
    )

    assert result.status == preview.status
    assert result.portfolio_risk == report
    assert result.portfolio_risk is not None
    assert result.portfolio_risk["outcome"] == "blocked"
    assert "PORTFOLIO_RISK_NOT_QUALIFIED" not in result.reason_codes


def test_mixed_preview_keeps_admitted_sell_row_distinct_from_blocked_buy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = _finish(
        [
            _preview_item(
                action="sell",
                asset_code="600036.SH",
                status="ready",
                suggested=Decimal("10"),
                actionable=Decimal("10"),
                fee={"total": "1.00"},
                sellable=Decimal("10"),
            ),
            _preview_item(
                action="buy",
                asset_code="600300.SH",
                status="ready",
                suggested=Decimal("10"),
                actionable=Decimal("10"),
                fee={"total": "1.00"},
            ),
        ]
    )
    baseline_reason = "PORTFOLIO_BASELINE_TOTAL_POSITION_LIMIT"
    report: PortfolioRiskReportPayload = {
        "account_id": 12,
        "as_of": _AS_OF.isoformat(),
        "outcome": "blocked",
        "policy_version": "fixture@1",
        "resource_snapshot_hash": "b" * 64,
        "checks": [
            {
                "dimension": "baseline_risk",
                "status": "blocked",
                "reason_codes": [baseline_reason],
                "summary": "existing holdings exceed a BUY-only limit",
                "details": {},
            }
        ],
        "sources": [],
        "freshness": "qualified_snapshot",
        "reliability": "source_bound",
        "must_not_use_for_decision": False,
        "order_admission": {
            "side": "mixed",
            "order_ids": ["preview:600036.SH:sell", "preview:600300.SH:buy"],
            "subject_id": None,
            "outcome": "blocked",
            "reason_codes": [baseline_reason],
            "waived_reason_codes": [],
            "decisions": [
                {
                    "order_id": "preview:600036.SH:sell",
                    "side": "sell",
                    "outcome": "allowed",
                    "reason_codes": [],
                    "waived_reason_codes": [baseline_reason],
                },
                {
                    "order_id": "preview:600300.SH:buy",
                    "side": "buy",
                    "outcome": "blocked",
                    "reason_codes": [baseline_reason],
                    "waived_reason_codes": [],
                },
            ],
        },
        "scope": "simulation_only",
        "must_not_execute": True,
    }
    monkeypatch.setattr(
        preview_gate_module,
        "assess_owner_portfolio_preview",
        lambda **_kwargs: report,
    )

    result = ConfiguredPortfolioRiskPreviewGate().qualify_preview(
        preview=preview, user_id=4, account_id=12
    )

    sell_row = next(row for row in result.asset_items if row.action == "sell")
    buy_row = next(row for row in result.asset_items if row.action == "buy")
    assert result.status == "blocked"
    assert sell_row.status == "ready"
    assert buy_row.status == "blocked"
    assert result.portfolio_risk is not None
    assert result.portfolio_risk["outcome"] == "blocked"


def test_empty_preview_uses_qualified_read_without_requiring_order_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = _finish([])
    report: PortfolioRiskReportPayload = {
        "account_id": 12,
        "as_of": _AS_OF.isoformat(),
        "outcome": "allowed",
        "policy_version": "fixture@1",
        "resource_snapshot_hash": "c" * 64,
        "checks": [],
        "sources": [],
        "freshness": "qualified_snapshot",
        "reliability": "source_bound",
        "must_not_use_for_decision": False,
        "scope": "simulation_only",
        "must_not_execute": True,
    }
    monkeypatch.setattr(
        preview_gate_module,
        "assess_owner_portfolio_preview",
        lambda **_kwargs: report,
    )

    result = ConfiguredPortfolioRiskPreviewGate().qualify_preview(
        preview=preview, user_id=4, account_id=12
    )

    assert result.status == preview.status
    assert result.portfolio_risk == report
