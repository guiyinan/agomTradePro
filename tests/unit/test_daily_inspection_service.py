"""Daily inspection safety and normalization tests."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskPolicyQualification,
    RiskQualificationState,
)
from apps.simulated_trading.application import (
    daily_inspection_service,
    interface_services,
    temporary_target_access,
)
from apps.simulated_trading.application.daily_inspection_service import (
    DailyInspectionService,
    InspectionSelection,
)
from apps.simulated_trading.application.rebalance_preview_context import (
    build_rebalance_plan_risk_context,
)
from apps.simulated_trading.application.temporary_target_checks import (
    attach_temporary_target_checks,
)
from apps.simulated_trading.application.temporary_target_entry import (
    parse_temporary_security_targets,
)
from apps.simulated_trading.domain.entities import (
    AccountType,
    Position,
    SimulatedAccount,
)
from apps.simulated_trading.domain.temporary_rebalance_targets import (
    TemporaryTargetValidationError,
)
from apps.strategy.application.execution_gateway import (
    InspectionSelection as StrategyInspectionSelection,
)


class PositionRepo:
    def __init__(self, positions: list[Position]) -> None:
        self.positions = positions

    def get_by_account(self, account_id: int) -> list[Position]:
        return self.positions


class StrategyGateway:
    def evaluate_position_rule(
        self,
        rule_id: int,
        context: dict[str, object],
    ) -> None:
        return None


class TrackingStrategyGateway:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate_position_rule(
        self,
        rule_id: int,
        context: dict[str, object],
    ) -> dict[str, object]:
        self.calls += 1
        return {"rule_id": rule_id, "entry_price": context["entry_price"]}


class TrackingAccountRepo:
    def __init__(
        self,
        account: SimulatedAccount | None,
        *,
        owner_user_id: int | None = 73,
    ) -> None:
        self.account = account
        self.owner_user_id = owner_user_id
        self.get_by_id_calls = 0

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        self.get_by_id_calls += 1
        return self.account

    def get_owner_id(self, *, account_id: int) -> int | None:
        return (
            self.owner_user_id if self.account and self.account.account_id == account_id else None
        )


class TrackingProposalRepo:
    def __init__(self) -> None:
        self.create_calls = 0
        self.payload: dict[str, object] | None = None
        self.report_defaults: dict[str, object] | None = None

    def upsert_report(
        self,
        account_id: int,
        inspection_date: date,
        defaults: dict[str, object],
    ) -> dict[str, object]:
        self.report_defaults = defaults
        return {"report_id": 9, **defaults}

    def create_rebalance_proposal(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.create_calls += 1
        self.payload = payload
        return {"proposal_id": 41}


class TrackingPositionRepo(PositionRepo):
    def __init__(self, positions: list[Position]) -> None:
        super().__init__(positions)
        self.get_by_account_calls = 0

    def get_by_account(self, account_id: int) -> list[Position]:
        self.get_by_account_calls += 1
        return super().get_by_account(account_id)


class TrackingTemporaryTargetOwnerRepo:
    def __init__(self, account_row: object | None) -> None:
        self.account_row = account_row
        self.calls: list[tuple[int, int]] = []

    def get_account_model_for_user(self, account_id: int, user_id: int) -> object | None:
        self.calls.append((account_id, user_id))
        return self.account_row


def _install_temporary_target_owner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account_id: int,
    user_id: int,
) -> TrackingTemporaryTargetOwnerRepo:
    """Install an exact owner row for direct temporary-target application calls."""

    repository = TrackingTemporaryTargetOwnerRepo(
        SimpleNamespace(
            id=account_id,
            user_id=user_id,
            is_active=True,
            account_type=AccountType.SIMULATED.value,
        )
    )
    monkeypatch.setattr(
        temporary_target_access,
        "get_simulated_account_repository",
        lambda: repository,
    )
    return repository


@pytest.mark.parametrize(
    ("user_id", "account_row", "reason_code", "owner_query_count"),
    [
        (None, None, "TARGET_OWNER_REQUIRED", 0),
        (23, None, "TARGET_ACCOUNT_NOT_OWNED", 1),
        (
            23,
            SimpleNamespace(
                id=1,
                user_id=24,
                is_active=True,
                account_type=AccountType.SIMULATED.value,
            ),
            "TARGET_ACCOUNT_NOT_OWNED",
            1,
        ),
        (
            23,
            SimpleNamespace(
                id=1,
                user_id=23,
                is_active=False,
                account_type=AccountType.SIMULATED.value,
            ),
            "TARGET_ACCOUNT_INACTIVE",
            1,
        ),
        (
            23,
            SimpleNamespace(
                id=1,
                user_id=23,
                is_active=True,
                account_type="real",
            ),
            "TARGET_ACCOUNT_NOT_SIMULATED",
            1,
        ),
    ],
)
def test_direct_temporary_target_run_requires_owner_before_data_or_audit_reads(
    monkeypatch: pytest.MonkeyPatch,
    user_id: int | None,
    account_row: object | None,
    reason_code: str,
    owner_query_count: int,
) -> None:
    account = _account()
    account_repo = TrackingAccountRepo(account)
    position_repo = TrackingPositionRepo([])
    inspection_repo = TrackingProposalRepo()
    owner_repo = TrackingTemporaryTargetOwnerRepo(account_row)
    selection_reads: list[int] = []
    monkeypatch.setattr(DailyInspectionService, "account_repo", account_repo)
    monkeypatch.setattr(DailyInspectionService, "position_repo", position_repo)
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", inspection_repo)
    monkeypatch.setattr(
        DailyInspectionService,
        "_select_strategy_and_rule",
        staticmethod(lambda **kwargs: selection_reads.append(1)),
    )
    monkeypatch.setattr(
        temporary_target_access,
        "get_simulated_account_repository",
        lambda: owner_repo,
    )

    with pytest.raises(TemporaryTargetValidationError) as error:
        DailyInspectionService.run(
            account_id=account.account_id,
            temporary_targets=parse_temporary_security_targets("600000.SH,50"),
            user_id=user_id,
        )

    assert error.value.reason_code == reason_code
    assert len(owner_repo.calls) == owner_query_count
    assert account_repo.get_by_id_calls == 0
    assert position_repo.get_by_account_calls == 0
    assert selection_reads == []
    assert inspection_repo.report_defaults is None


def test_direct_temporary_target_run_without_owner_is_rejected_before_any_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _account()
    account_repo = TrackingAccountRepo(account)
    position_repo = TrackingPositionRepo([])
    inspection_repo = TrackingProposalRepo()
    selection_reads: list[int] = []
    monkeypatch.setattr(DailyInspectionService, "account_repo", account_repo)
    monkeypatch.setattr(DailyInspectionService, "position_repo", position_repo)
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", inspection_repo)
    monkeypatch.setattr(
        DailyInspectionService,
        "_select_strategy_and_rule",
        staticmethod(
            lambda **kwargs: selection_reads.append(1)
            or InspectionSelection(strategy_id=None, rule_id=None, rule_metadata={})
        ),
    )
    monkeypatch.setattr(DailyInspectionService, "_latest_regime", staticmethod(lambda: "Recovery"))
    monkeypatch.setattr(DailyInspectionService, "_latest_policy_gear", staticmethod(lambda: "P0"))
    monkeypatch.setattr(
        DailyInspectionService,
        "_latest_pulse_context",
        staticmethod(lambda as_of: DailyInspectionService._empty_pulse_context()),
    )
    monkeypatch.setattr(
        DailyInspectionService,
        "_build_checks",
        staticmethod(lambda **kwargs: []),
    )

    try:
        DailyInspectionService.run(
            account_id=account.account_id,
            temporary_targets=parse_temporary_security_targets("600000.SH,50"),
        )
    except TemporaryTargetValidationError as error:
        assert error.reason_code == "TARGET_OWNER_REQUIRED"
    except Exception as error:
        pytest.fail(f"Expected a target-owner business error, got {type(error).__name__}: {error}")
    else:
        pytest.fail(
            "Direct target call completed without owner proof after "
            f"account_reads={account_repo.get_by_id_calls}, "
            f"position_reads={position_repo.get_by_account_calls}, "
            f"selection_reads={len(selection_reads)}, "
            f"audit_written={inspection_repo.report_defaults is not None}"
        )

    assert account_repo.get_by_id_calls == 0
    assert position_repo.get_by_account_calls == 0
    assert selection_reads == []
    assert inspection_repo.report_defaults is None


def _account() -> SimulatedAccount:
    return SimulatedAccount(
        account_id=1,
        account_name="inspection",
        account_type=AccountType.SIMULATED,
        initial_capital=100_000.0,
        current_cash=50_000.0,
        current_market_value=50_000.0,
        total_value=100_000.0,
    )


def _position() -> Position:
    return Position(
        account_id=1,
        asset_code="abc.sz",
        asset_name="test asset",
        asset_type="equity",
        quantity=10_000.0,
        available_quantity=10_000.0,
        avg_cost=5.0,
        total_cost=50_000.0,
        current_price=0.0,
        market_value=50_000.0,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 1, 1),
        last_update_date=date(2026, 1, 1),
    )


def _disable_asset_class_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        DailyInspectionService,
        "_build_asset_class_checks",
        staticmethod(lambda **kwargs: []),
    )
    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_inspection_service."
        "get_strategy_execution_gateway",
        lambda: StrategyGateway(),
    )


def test_asset_targets_normalize_codes_without_creating_duplicate_buy(
    monkeypatch,
) -> None:
    _disable_asset_class_checks(monkeypatch)
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([_position()]))
    selection = InspectionSelection(
        strategy_id=None,
        rule_id=None,
        rule_metadata={
            "rebalance": {
                "target_weights": {" ABC.SZ ": 0.30},
                "drift_threshold": 0.05,
            }
        },
    )

    checks = DailyInspectionService._build_checks(
        account=_account(),
        selection=selection,
        macro_regime="Recovery",
        policy_gear="P0",
        pulse_context=DailyInspectionService._empty_pulse_context(),
    )

    assert len(checks) == 1
    assert checks[0]["target_weight"] == 0.30
    assert checks[0]["rebalance_action"] == "sell"
    assert checks[0]["rebalance_qty_suggest"] == 0
    assert checks[0]["quantity_available"] is False


def test_invalid_target_weights_do_not_generate_trade_advice(monkeypatch) -> None:
    _disable_asset_class_checks(monkeypatch)
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([_position()]))
    selection = InspectionSelection(
        strategy_id=None,
        rule_id=None,
        rule_metadata={
            "rebalance": {
                "target_weights": {
                    "ABC.SZ": float("nan"),
                    "OTHER.SZ": -0.2,
                },
                "drift_threshold": -1,
            }
        },
    )

    checks = DailyInspectionService._build_checks(
        account=_account(),
        selection=selection,
        macro_regime="Recovery",
        policy_gear="P0",
        pulse_context=DailyInspectionService._empty_pulse_context(),
    )

    assert len(checks) == 1
    assert checks[0]["target_weight"] is None
    assert checks[0]["rebalance_action"] == "hold"


def test_position_rule_is_blocked_for_unknown_cost_basis(monkeypatch) -> None:
    """An old numeric average cost cannot be passed as a known rule entry price."""
    _disable_asset_class_checks(monkeypatch)
    gateway = TrackingStrategyGateway()
    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_inspection_service."
        "get_strategy_execution_gateway",
        lambda: gateway,
    )
    position = _position()
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([position]))

    checks = DailyInspectionService._build_checks(
        account=_account(),
        selection=InspectionSelection(
            strategy_id=None,
            rule_id=17,
            rule_metadata={},
        ),
        macro_regime="Recovery",
        policy_gear="P0",
        pulse_context=DailyInspectionService._empty_pulse_context(),
    )

    assert gateway.calls == 0
    assert checks[0]["rule_eval"] is None
    assert checks[0]["rule_eval_blocked_reason_code"] == "POSITION_COST_BASIS_UNKNOWN"
    assert checks[0]["cost_basis_status"] == "unknown"


def test_position_rule_uses_cost_basis_only_when_explicitly_known(monkeypatch) -> None:
    """An explicitly complete basis preserves the existing rule evaluation path."""
    _disable_asset_class_checks(monkeypatch)
    gateway = TrackingStrategyGateway()
    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_inspection_service."
        "get_strategy_execution_gateway",
        lambda: gateway,
    )
    position = replace(_position(), cost_basis_known=True)
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([position]))

    checks = DailyInspectionService._build_checks(
        account=_account(),
        selection=InspectionSelection(
            strategy_id=None,
            rule_id=17,
            rule_metadata={},
        ),
        macro_regime="Recovery",
        policy_gear="P0",
        pulse_context=DailyInspectionService._empty_pulse_context(),
    )

    assert gateway.calls == 1
    assert checks[0]["rule_eval"] == {"rule_id": 17, "entry_price": 5.0}
    assert checks[0]["rule_eval_blocked_reason_code"] is None
    assert checks[0]["cost_basis_status"] == "known"


def test_temporary_target_run_keeps_strategy_risk_context_and_unknown_trade_facts(
    monkeypatch,
) -> None:
    account = _account()
    position = replace(_position(), asset_code="600000.SH")
    pulse = {
        "available": True,
        "composite_score": 0.73,
        "regime_strength": "strong",
        "data_source": "bound-account-pulse",
    }
    source_checks: list[dict[str, object]] = [
        {
            "scope": "asset_class",
            "asset_code": "asset_class:equity",
            "asset_class": "equity",
            "target_weight": 0.7,
            "risk_profile": "growth",
            "pulse": pulse,
            "rebalance_action": "buy",
            "drift": -0.2,
            "rebalance_qty_suggest": 20,
            "suggested_amount": 200.0,
            "drift_threshold": 0.05,
        },
        {
            "scope": "asset",
            "asset_code": "600000.SH",
            "asset_name": "浦发银行",
            "asset_class": "equity",
            "quantity": 100,
            "current_price": 10.0,
            "market_value": 1000.0,
            "weight": 0.01,
            "target_weight": 0.4,
            "drift": -0.39,
            "rebalance_action": "buy",
            "rebalance_qty_suggest": 39,
            "suggested_amount": 390.0,
            "drift_threshold": 0.05,
            "quantity_available": True,
        },
    ]
    inspection_repo = TrackingProposalRepo()

    monkeypatch.setattr(DailyInspectionService, "account_repo", TrackingAccountRepo(account))
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([position]))
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", inspection_repo)
    monkeypatch.setattr(
        DailyInspectionService,
        "_select_strategy_and_rule",
        staticmethod(
            lambda account_id, strategy_id, user_id=None: InspectionSelection(
                strategy_id=None,
                rule_id=None,
                rule_metadata={},
            )
        ),
    )
    monkeypatch.setattr(DailyInspectionService, "_latest_regime", staticmethod(lambda: "Recovery"))
    monkeypatch.setattr(DailyInspectionService, "_latest_policy_gear", staticmethod(lambda: "P0"))
    monkeypatch.setattr(
        DailyInspectionService,
        "_latest_pulse_context",
        staticmethod(lambda as_of: pulse),
    )
    monkeypatch.setattr(
        DailyInspectionService,
        "_build_checks",
        staticmethod(lambda **kwargs: source_checks),
    )

    _install_temporary_target_owner(
        monkeypatch,
        account_id=account.account_id,
        user_id=23,
    )
    result = DailyInspectionService.run(
        account_id=account.account_id,
        temporary_targets=parse_temporary_security_targets("600000.SH,90"),
        user_id=23,
    )

    summary = result["summary"]
    assert result["status"] == "warning"
    assert summary["rebalance_required_count"] is None
    assert summary["asset_class_rebalance_required_count"] is None
    assert summary["asset_rebalance_required_count"] is None
    assert summary["max_abs_drift"] is None
    assert summary["target_allocation"] is None
    assert summary["strategy_target_allocation"] == {"equity": 0.7}
    assert summary["risk_profile"] == "growth"
    assert summary["pulse"] == pulse
    assert summary["temporary_target"] == {
        "source": "user_entered_temporary",
        "target_weights": {"600000.SH": "0.9"},
        "security_count": 1,
        "security_weight_total": "0.9",
        "residual_cash_weight": "0.1",
        "assessment": "delegated_to_read_only_preview",
        "rebalance_status": "unknown_until_preview",
        "quantity_status": "unknown_until_preview",
    }
    target_check = next(check for check in result["checks"] if check["scope"] == "asset")
    assert target_check["strategy_rebalance_action"] == "buy"
    assert target_check["strategy_rebalance_qty_suggest"] == 39
    assert target_check["strategy_suggested_amount"] == 390.0
    assert target_check["rebalance_action"] is None
    assert target_check["rebalance_qty_suggest"] is None
    assert target_check["suggested_amount"] is None
    assert target_check["drift"] is None
    assert target_check["drift_threshold"] == 0.05
    assert target_check["strategy_drift_threshold"] == 0.05
    assert inspection_repo.create_calls == 0


def test_temporary_target_run_counts_snapshot_positions_and_keeps_exact_weights(
    monkeypatch,
) -> None:
    account = _account()
    inspection_repo = TrackingProposalRepo()
    monkeypatch.setattr(DailyInspectionService, "account_repo", TrackingAccountRepo(account))
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([]))
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", inspection_repo)
    _disable_asset_class_checks(monkeypatch)
    monkeypatch.setattr(
        DailyInspectionService,
        "_select_strategy_and_rule",
        staticmethod(
            lambda account_id, strategy_id, user_id=None: InspectionSelection(
                strategy_id=None,
                rule_id=None,
                rule_metadata={},
            )
        ),
    )
    monkeypatch.setattr(DailyInspectionService, "_latest_regime", staticmethod(lambda: "Recovery"))
    monkeypatch.setattr(DailyInspectionService, "_latest_policy_gear", staticmethod(lambda: "P0"))
    monkeypatch.setattr(
        DailyInspectionService,
        "_latest_pulse_context",
        staticmethod(lambda as_of: DailyInspectionService._empty_pulse_context()),
    )

    with localcontext() as context:
        context.prec = 4
        targets = parse_temporary_security_targets("000001.SZ,12.345678\n600000.SH,12.345678")
        _install_temporary_target_owner(
            monkeypatch,
            account_id=account.account_id,
            user_id=23,
        )
        result = DailyInspectionService.run(
            account_id=account.account_id,
            temporary_targets=targets,
            user_id=23,
        )

    summary = result["summary"]
    assert summary["positions_count"] == 0
    assert summary["temporary_target"] == {
        "source": "user_entered_temporary",
        "target_weights": {
            "000001.SZ": "0.12345678",
            "600000.SH": "0.12345678",
        },
        "security_count": 2,
        "security_weight_total": "0.24691356",
        "residual_cash_weight": "0.75308644",
        "assessment": "delegated_to_read_only_preview",
        "rebalance_status": "unknown_until_preview",
        "quantity_status": "unknown_until_preview",
    }
    assert inspection_repo.report_defaults is not None
    assert inspection_repo.report_defaults["summary"] == summary


def test_temporary_target_new_security_keeps_unobserved_valuation_unknown() -> None:
    checks = attach_temporary_target_checks(
        [],
        positions=[],
        targets=parse_temporary_security_targets("000001.SZ,25"),
    )

    security_check = next(check for check in checks if check.get("scope") == "asset")
    for field in (
        "asset_class",
        "quantity",
        "current_price",
        "market_value",
        "weight",
        "drift",
        "rebalance_action",
        "rebalance_qty_suggest",
        "suggested_amount",
        "quantity_available",
    ):
        assert security_check[field] is None
    assert security_check["target_weight"] == "0.25"
    assert security_check["temporary_target_source"] == "user_entered_temporary"
    assert security_check["drift_threshold"] is None
    assert security_check["strategy_drift_threshold"] is None


def test_temporary_target_without_class_allocation_keeps_known_profile_pulse_and_limits(
    monkeypatch,
) -> None:
    account = replace(
        _account(),
        max_position_pct=18.0,
        max_total_position_pct=82.0,
        stop_loss_pct=7.0,
    )
    position = replace(_position(), asset_code="600000.SH")
    pulse: dict[str, object] = {
        "available": True,
        "composite_score": 0.61,
        "regime_strength": "rising",
        "data_source": "known-run-pulse",
    }
    selection = InspectionSelection(
        strategy_id=None,
        rule_id=None,
        rule_metadata={"allocation": {"risk_profile": "growth"}},
        max_position_pct=61.0,
        max_total_position_pct=94.0,
        stop_loss_pct=11.0,
    )
    inspection_repo = TrackingProposalRepo()
    monkeypatch.setattr(
        DailyInspectionService,
        "account_repo",
        TrackingAccountRepo(account),
    )
    monkeypatch.setattr(
        DailyInspectionService,
        "position_repo",
        PositionRepo([position]),
    )
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", inspection_repo)
    monkeypatch.setattr(
        DailyInspectionService,
        "_select_strategy_and_rule",
        staticmethod(lambda **kwargs: selection),
    )
    monkeypatch.setattr(
        DailyInspectionService,
        "_latest_regime",
        staticmethod(lambda: "Recovery"),
    )
    monkeypatch.setattr(
        DailyInspectionService,
        "_latest_policy_gear",
        staticmethod(lambda: "P0"),
    )
    monkeypatch.setattr(
        DailyInspectionService,
        "_latest_pulse_context",
        staticmethod(lambda as_of: pulse),
    )

    def allocation_target_unavailable(
        _regime: str,
        _risk_profile: str,
        _policy_level: str | None = None,
    ) -> None:
        raise ValueError("allocation target unavailable")

    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_inspection_service.get_allocation_target",
        allocation_target_unavailable,
    )
    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_inspection_service.get_strategy_execution_gateway",
        lambda: StrategyGateway(),
    )

    _install_temporary_target_owner(
        monkeypatch,
        account_id=account.account_id,
        user_id=23,
    )
    result = DailyInspectionService.run(
        account_id=account.account_id,
        temporary_targets=parse_temporary_security_targets("600000.SH,90"),
        user_id=23,
    )

    summary = result["summary"]
    assert summary["target_allocation"] is None
    assert summary["strategy_target_allocation"] == {}
    assert summary["risk_profile"] == "growth"
    assert summary["pulse"] == pulse
    assert result["max_position_pct"] == 61.0
    assert result["max_total_position_pct"] == 94.0
    assert result["stop_loss_pct"] == 11.0

    risk_context = build_rebalance_plan_risk_context(
        summary=summary,
        strategy_id=selection.strategy_id,
        position_rule_id=selection.rule_id,
        strategy_name=selection.strategy_name,
        strategy_type=selection.strategy_type,
        strategy_version=selection.strategy_version,
        rule_name=selection.rule_name,
        max_position_pct=Decimal("61"),
        max_total_position_pct=Decimal("94"),
        stop_loss_pct=Decimal("11"),
        strategy_selection_state=selection.selection_state,
        account_max_position_pct=Decimal("18"),
        account_max_total_position_pct=Decimal("82"),
        account_stop_loss_pct=Decimal("7"),
        risk_policy_qualification=M1RiskPolicyQualification(
            state=RiskQualificationState.MISSING,
            reason_codes=("M1_RISK_POLICY_VERSION_UNKNOWN",),
            revision=None,
        ),
        macro_regime=result["macro_regime"],
        policy_gear=result["policy_gear"],
    ).to_payload()
    assert risk_context["strategy_selection_state"] == "unavailable"
    assert risk_context["strategy_policy_applicability"] == "unknown"
    assert risk_context["risk_policy_qualification_status"] == "missing"
    assert risk_context["risk_policy_reason_codes"] == ["M1_RISK_POLICY_VERSION_UNKNOWN"]
    assert risk_context["risk_policy_version"] is None
    assert risk_context["risk_falsification"]["status"] == "unknown"
    risk_context_values = {
        key: risk_context[key]
        for key in (
            "account_max_position_pct",
            "account_max_total_position_pct",
            "account_stop_loss_pct",
            "strategy_max_position_pct",
            "strategy_max_total_position_pct",
            "strategy_stop_loss_pct",
        )
    }
    assert all(type(value) is str for value in risk_context_values.values())
    assert {
        key: Decimal(value) for key, value in risk_context_values.items() if type(value) is str
    } == {
        "account_max_position_pct": Decimal("18"),
        "account_max_total_position_pct": Decimal("82"),
        "account_stop_loss_pct": Decimal("7"),
        "strategy_max_position_pct": Decimal("61"),
        "strategy_max_total_position_pct": Decimal("94"),
        "strategy_stop_loss_pct": Decimal("11"),
    }
    unknown_context = DailyInspectionService._strategy_summary_context(
        [],
        rule_metadata={},
        pulse_context=pulse,
    )
    assert unknown_context["risk_profile"] is None
    assert unknown_context["pulse"] == pulse


@pytest.mark.parametrize(
    "inspection_result",
    [
        {"summary": {"temporary_target": {}}, "checks": []},
        {"summary": {}, "checks": [{"scope": "temporary_target_entry"}]},
        {"summary": {}, "checks": [{"source": "user_entered_temporary"}]},
        {"summary": {}, "checks": [{"temporary_target_source": "user_entered_temporary"}]},
    ],
)
def test_temporary_target_proposal_is_rejected_before_repository_side_effects(
    monkeypatch,
    inspection_result: dict[str, object],
) -> None:
    account_repo = TrackingAccountRepo(_account())
    proposal_repo = TrackingProposalRepo()
    monkeypatch.setattr(DailyInspectionService, "account_repo", account_repo)
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", proposal_repo)

    with pytest.raises(TemporaryTargetValidationError) as error:
        DailyInspectionService.create_rebalance_proposal(
            account_id=1,
            inspection_result=inspection_result,
        )

    assert error.value.reason_code == "TARGET_PROPOSAL_FORBIDDEN"
    assert account_repo.get_by_id_calls == 0
    assert proposal_repo.create_calls == 0


def test_account_only_rebalance_proposal_path_remains_available(monkeypatch) -> None:
    account_repo = TrackingAccountRepo(_account())
    proposal_repo = TrackingProposalRepo()
    monkeypatch.setattr(DailyInspectionService, "account_repo", account_repo)
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", proposal_repo)
    inspection_result: dict[str, object] = {
        "report_id": 12,
        "account_id": 1,
        "strategy_id": None,
        "inspection_date": "2026-10-22",
        "macro_regime": "Recovery",
        "policy_gear": "P0",
        "summary": {
            "rebalance_required_count": 1,
            "total_value": 100_000.0,
            "current_cash": 20_000.0,
            "current_market_value": 80_000.0,
            "rebalance_assets": ["600000.SH"],
            "risk_profile": "moderate",
            "target_allocation": {"equity": 0.8},
        },
        "checks": [
            {
                "scope": "asset",
                "asset_code": "600000.SH",
                "asset_name": "浦发银行",
                "asset_class": "equity",
                "quantity": 100,
                "current_price": 10.0,
                "market_value": 1000.0,
                "weight": 0.01,
                "target_weight": 0.8,
                "drift": -0.79,
                "rebalance_action": "buy",
                "rebalance_qty_suggest": 79,
                "suggested_amount": 790.0,
            }
        ],
    }

    result = DailyInspectionService.create_rebalance_proposal(
        account_id=1,
        inspection_result=inspection_result,
    )

    assert result == {"proposal_id": 41}
    assert account_repo.get_by_id_calls == 1
    assert proposal_repo.create_calls == 1


@pytest.mark.parametrize("auto_create_proposal", [False, True])
def test_run_daily_inspection_forwards_authenticated_user_id(
    monkeypatch: pytest.MonkeyPatch,
    auto_create_proposal: bool,
) -> None:
    """Keep the authenticated owner available to selection on both ordinary API paths."""

    captured: dict[str, object] = {}
    inspection_result: dict[str, object] = {"report_id": 9}

    def run(cls: type[DailyInspectionService], **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return inspection_result

    def run_and_create_proposal(
        cls: type[DailyInspectionService], **kwargs: object
    ) -> dict[str, object]:
        captured.update(kwargs)
        return inspection_result

    monkeypatch.setattr(DailyInspectionService, "run", classmethod(run))
    monkeypatch.setattr(
        DailyInspectionService,
        "run_and_create_proposal",
        classmethod(run_and_create_proposal),
    )

    result = interface_services.run_daily_inspection(
        account_id=1,
        inspection_date=date(2026, 10, 26),
        strategy_id=17,
        auto_create_proposal=auto_create_proposal,
        user_id=73,
    )

    assert result is inspection_result
    assert captured["user_id"] == 73


def test_foreign_strategy_selection_never_reaches_inspection_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreign private Strategy cannot influence checks or the persisted report."""

    account = _account()
    inspection_repo = TrackingProposalRepo()
    foreign_selection = StrategyInspectionSelection(
        strategy_id=987,
        position_rule_id=654,
        rule_metadata={
            "rebalance": {
                "target_weights": {"PRIVATE.SECRET": 0.75},
                "drift_threshold": 0.05,
            }
        },
        strategy_name="other owner's private strategy",
        strategy_type="rule_based",
        strategy_version=9,
        rule_name="private rule name",
        max_position_pct=12.0,
        max_total_position_pct=38.0,
        stop_loss_pct=6.0,
        selection_state="configured",
    )

    class LegacyGlobalStrategyGateway:
        def get_inspection_selection(
            self,
            account_id: int,
            strategy_id: int | None = None,
        ) -> StrategyInspectionSelection:
            return foreign_selection

        def evaluate_position_rule(
            self,
            rule_id: int | None,
            context: dict[str, object],
        ) -> None:
            return None

    class DenyAllOwnerScopedReader:
        def get_owner_inspection_selection(
            self,
            account_id: int,
            owner_user_id: int,
            strategy_id: int | None = None,
        ) -> StrategyInspectionSelection:
            return StrategyInspectionSelection(
                strategy_id=None,
                position_rule_id=None,
                rule_metadata={},
                selection_state="unavailable",
            )

    monkeypatch.setattr(DailyInspectionService, "account_repo", TrackingAccountRepo(account))
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([]))
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", inspection_repo)
    monkeypatch.setattr(DailyInspectionService, "_latest_regime", staticmethod(lambda: "Recovery"))
    monkeypatch.setattr(DailyInspectionService, "_latest_policy_gear", staticmethod(lambda: "P0"))
    monkeypatch.setattr(
        DailyInspectionService,
        "_latest_pulse_context",
        staticmethod(lambda as_of: DailyInspectionService._empty_pulse_context()),
    )
    monkeypatch.setattr(
        DailyInspectionService,
        "_build_asset_class_checks",
        staticmethod(lambda **kwargs: []),
    )
    monkeypatch.setattr(
        daily_inspection_service,
        "get_strategy_execution_gateway",
        lambda: LegacyGlobalStrategyGateway(),
    )
    monkeypatch.setattr(
        daily_inspection_service,
        "get_daily_inspection_strategy_selection_reader",
        lambda: DenyAllOwnerScopedReader(),
        raising=False,
    )

    result = DailyInspectionService.run(account_id=account.account_id, strategy_id=987, user_id=73)

    stored = inspection_repo.report_defaults
    assert stored is not None
    assert result["strategy_id"] is None
    assert result["position_rule_id"] is None
    assert result["strategy_name"] is None
    assert result["strategy_version"] is None
    assert result["rule_name"] is None
    assert stored["strategy_id"] is None
    assert stored["position_rule_id"] is None
    assert "PRIVATE.SECRET" not in str(result["checks"])
    assert "PRIVATE.SECRET" not in str(stored["checks"])
    assert "other owner's private strategy" not in str(result)
    assert "private rule name" not in str(stored)


def test_strategy_selection_uses_account_owner_and_rejects_another_request_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _account()
    account_repo = TrackingAccountRepo(account, owner_user_id=73)
    reader_calls: list[tuple[int, int, int | None]] = []

    class OwnerReader:
        def get_owner_inspection_selection(
            self,
            account_id: int,
            owner_user_id: int,
            strategy_id: int | None = None,
        ) -> StrategyInspectionSelection:
            reader_calls.append((account_id, owner_user_id, strategy_id))
            return StrategyInspectionSelection(
                strategy_id=17,
                position_rule_id=None,
                rule_metadata={},
                max_position_pct=20.0,
                max_total_position_pct=95.0,
                selection_state="configured",
            )

    monkeypatch.setattr(DailyInspectionService, "account_repo", account_repo)
    monkeypatch.setattr(
        daily_inspection_service,
        "get_daily_inspection_strategy_selection_reader",
        lambda: OwnerReader(),
    )

    denied = DailyInspectionService._select_strategy_and_rule(
        account_id=account.account_id,
        strategy_id=987,
        user_id=74,
    )

    assert denied.selection_state == "unavailable"
    assert denied.strategy_id is None
    assert reader_calls == []

    allowed = DailyInspectionService._select_strategy_and_rule(
        account_id=account.account_id,
        strategy_id=17,
        user_id=73,
    )

    assert allowed.strategy_id == 17
    assert allowed.selection_state == "configured"
    assert reader_calls == [(account.account_id, 73, 17)]

    background = DailyInspectionService._select_strategy_and_rule(
        account_id=account.account_id,
        strategy_id=None,
    )

    assert background.strategy_id == 17
    assert reader_calls == [
        (account.account_id, 73, 17),
        (account.account_id, 73, None),
    ]


def test_user_id_maps_to_distinct_profile_id_before_strategy_query() -> None:
    from apps.account.application.owner_profile_identity import (
        AccountOwnerProfileIdentity,
        GetAccountOwnerProfileIdentityUseCase,
    )
    from apps.simulated_trading.infrastructure.m1_risk_policy_strategy_source_reader import (
        AccountProfileScopedStrategyM1RiskSourceReader,
    )

    class OwnerProfileRepository:
        def get_for_user(
            self,
            *,
            user_id: int,
        ) -> AccountOwnerProfileIdentity | None:
            return AccountOwnerProfileIdentity(user_id=user_id, profile_id=900)

    class StrategyGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int | None]] = []

        def get_profile_scoped_inspection_selection(
            self,
            account_id: int,
            owner_profile_id: int,
            strategy_id: int | None = None,
        ) -> StrategyInspectionSelection:
            self.calls.append((account_id, owner_profile_id, strategy_id))
            return StrategyInspectionSelection(
                strategy_id=17,
                position_rule_id=None,
                rule_metadata={},
                strategy_name="owner strategy",
                max_position_pct=20.0,
                max_total_position_pct=95.0,
                selection_state="configured",
            )

    strategy_gateway = StrategyGateway()
    reader = AccountProfileScopedStrategyM1RiskSourceReader(
        owner_profile_identity=GetAccountOwnerProfileIdentityUseCase(OwnerProfileRepository()),
        strategy_gateway=strategy_gateway,
    )

    selection = reader.get_owner_inspection_selection(
        account_id=1,
        owner_user_id=73,
        strategy_id=17,
    )

    assert selection.strategy_name == "owner strategy"
    assert strategy_gateway.calls == [(1, 900, 17)]


def test_default_inspection_date_uses_china_local_date_across_utc_midnight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    utc_date = date(2026, 10, 22)
    china_date = date(2026, 10, 23)
    requested_date = date(2026, 10, 21)
    fixed_utc_now = datetime(2026, 10, 22, 16, 30, tzinfo=UTC)
    inspection_repo = TrackingProposalRepo()
    monkeypatch.setattr(daily_inspection_service.timezone, "now", lambda: fixed_utc_now)
    monkeypatch.setattr(
        daily_inspection_service,
        "date",
        SimpleNamespace(today=lambda: utc_date),
    )
    monkeypatch.setattr(DailyInspectionService, "account_repo", TrackingAccountRepo(_account()))
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([]))
    monkeypatch.setattr(DailyInspectionService, "inspection_repo", inspection_repo)
    monkeypatch.setattr(
        DailyInspectionService,
        "_select_strategy_and_rule",
        staticmethod(
            lambda **kwargs: InspectionSelection(
                strategy_id=None,
                rule_id=None,
                rule_metadata={},
            )
        ),
    )
    monkeypatch.setattr(DailyInspectionService, "_latest_regime", staticmethod(lambda: "Recovery"))
    monkeypatch.setattr(DailyInspectionService, "_latest_policy_gear", staticmethod(lambda: "P0"))
    monkeypatch.setattr(
        DailyInspectionService,
        "_latest_pulse_context",
        staticmethod(lambda as_of: DailyInspectionService._empty_pulse_context()),
    )
    monkeypatch.setattr(
        DailyInspectionService,
        "_build_checks",
        staticmethod(lambda **kwargs: []),
    )

    with timezone.override("Asia/Shanghai"):
        default_result = DailyInspectionService.run(account_id=1)
        explicit_result = DailyInspectionService.run(
            account_id=1,
            inspection_date=requested_date,
        )

    assert default_result["inspection_date"] == china_date.isoformat()
    assert explicit_result["inspection_date"] == requested_date.isoformat()
    assert inspection_repo.report_defaults is not None
