"""Authoritative risk and four-dimensional reconciliation tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionValidationError,
)
from apps.broker_execution.application.use_cases import (
    CreateLiveOrderFromExecutionPlanUseCase,
    CreateLiveOrdersFromAdvisorExecutionPlanUseCase,
    PreviewOrCreateAdvisorLiveOrdersUseCase,
)
from apps.broker_execution.infrastructure.models import (
    BrokerAccountAccessModel,
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentModel,
    BrokerExecutionAlertModel,
    BrokerExecutionDailyReportModel,
    BrokerPositionSnapshotModel,
    LiveOrderModel,
    ReconciliationDifferenceModel,
    ReconciliationRunModel,
    TradingControlModel,
)
from apps.broker_execution.infrastructure.repositories import (
    DjangoBrokerExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


class _CreateRepository:
    def __init__(self) -> None:
        self.payload = None

    def has_account_access(self, **_kwargs) -> bool:
        return True

    def get_bound_account_owner_id(self, **_kwargs) -> int:
        return 1

    def create_live_order(self, **kwargs):
        self.payload = kwargs["payload"]
        return {"created": True, "risk_snapshot": kwargs["payload"]["risk_snapshot"]}


class _RiskEvaluator:
    def __init__(self, *, passed: bool) -> None:
        self.passed = passed

    def execute(self, **_kwargs):
        return {
            "passed": self.passed,
            "violations": [] if self.passed else ["max_total_position_pct exceeded"],
            "warnings": [],
            "effective_policy": {"version": "server-risk-v2"},
            "metrics": {"projected_total_position_pct": 0.42},
        }


def _projection(**_kwargs):
    return {
        "account_id": 7,
        "account_type": "real",
        "is_active": True,
        "total_asset": 100000,
        "cash_available": 50000,
        "total_position_value": 50000,
        "positions": [],
    }


def _quote(_asset_code: str) -> dict:
    return {
        "current_price": 3.9,
        "is_stale": False,
        "must_not_use_for_decision": False,
        "snapshot_at": timezone.now().isoformat(),
    }


def _plan() -> dict:
    return {
        "account_id": 7,
        "asset_code": "510300.sh",
        "side": "BUY",
        "quantity": "100",
        "limit_price": "3.90",
        "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        "source_recommendation_ids": ["recommendation-1"],
        # A caller-supplied pass must never be treated as authoritative.
        "risk_snapshot": {"passed": True, "source": "caller"},
    }


class _OrderCreator:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return {"client_order_id": f"order-{len(self.calls)}"}


def test_advisor_execution_plan_maps_only_to_governed_order_drafts() -> None:
    creator = _OrderCreator()
    use_case = CreateLiveOrdersFromAdvisorExecutionPlanUseCase(order_creator=creator)
    result = use_case.execute(
        actor=object(),
        execution_plan={
            "status": "READY_FOR_CONFIRMATION",
            "orders": [
                {
                    "order_intent_id": "intent-1",
                    "account_id": 7,
                    "asset_code": "510300.SH",
                    "side": "ADD",
                    "suggested_quantity": 100,
                    "estimated_price": 3.9,
                    "source_recommendation_ids": ["recommendation-1"],
                }
            ],
        },
        idempotency_prefix="advisor-sheet-1",
    )

    assert result["created_count"] == 1
    assert creator.calls[0]["plan"]["side"] == "BUY"
    assert creator.calls[0]["idempotency_key"] == "advisor-sheet-1:intent-1"


@pytest.mark.django_db
def test_current_advisor_sheet_requires_matching_preview_digest() -> None:
    actor = User.objects.create_user(username="advisor-bridge-owner", password="test123")
    actor.account_profile.rbac_role = "owner"
    actor.account_profile.save(update_fields=["rbac_role", "updated_at"])
    execution_plan = {
        "status": "READY_FOR_CONFIRMATION",
        "execution_mode": "real_confirm_only",
        "orders_count": 1,
        "orders": [
            {
                "order_intent_id": "intent-1",
                "account_id": 7,
                "asset_code": "510300.SH",
                "side": "ADD",
                "suggested_quantity": Decimal("100"),
                "estimated_price": Decimal("3.9"),
                "source_recommendation_ids": ["recommendation-1"],
            }
        ],
    }
    creator = _OrderCreator()
    plan_creator = CreateLiveOrdersFromAdvisorExecutionPlanUseCase(order_creator=creator)

    def provider(**_kwargs):
        return {"execution_plan": execution_plan}

    use_case = PreviewOrCreateAdvisorLiveOrdersUseCase(
        sheet_provider=provider,
        order_creator=plan_creator,
    )

    preview = use_case.execute(
        actor=actor,
        account_id=7,
        preview_only=True,
    )
    committed = use_case.execute(
        actor=actor,
        account_id=7,
        preview_only=False,
        expected_plan_digest=preview["plan_digest"],
        idempotency_key="advisor-bridge-1",
    )

    assert preview["orders_count"] == 1
    assert committed["created_count"] == 1
    assert creator.calls[0]["plan"]["asset_code"] == "510300.SH"
    with pytest.raises(BrokerExecutionValidationError, match="changed after preview"):
        use_case.execute(
            actor=actor,
            account_id=7,
            preview_only=False,
            expected_plan_digest="0" * 64,
            idempotency_key="advisor-bridge-2",
        )


@pytest.mark.django_db
def test_live_order_creation_replaces_caller_risk_with_server_result() -> None:
    actor = User.objects.create_user(username="risk-owner", password="test123")
    actor.account_profile.rbac_role = "owner"
    actor.account_profile.save(update_fields=["rbac_role", "updated_at"])
    repository = _CreateRepository()
    result = CreateLiveOrderFromExecutionPlanUseCase(
        repository,
        account_projection_provider=_projection,
        risk_evaluator=_RiskEvaluator(passed=True),
        latest_quote_provider=_quote,
    ).execute(actor=actor, plan=_plan(), idempotency_key="risk-order-1")

    assert result["created"] is True
    assert repository.payload["asset_code"] == "510300.SH"
    assert repository.payload["risk_snapshot"]["effective_policy"]["version"] == "server-risk-v2"
    assert repository.payload["risk_snapshot"].get("source") is None


@pytest.mark.django_db
def test_live_order_creation_fails_closed_on_server_risk_rejection() -> None:
    actor = User.objects.create_user(username="risk-rejected", password="test123")
    actor.account_profile.rbac_role = "owner"
    actor.account_profile.save(update_fields=["rbac_role", "updated_at"])
    repository = _CreateRepository()

    result = CreateLiveOrderFromExecutionPlanUseCase(
        repository,
        account_projection_provider=_projection,
        risk_evaluator=_RiskEvaluator(passed=False),
        latest_quote_provider=_quote,
    ).execute(actor=actor, plan=_plan(), idempotency_key="risk-order-2")

    assert result["created"] is True
    assert repository.payload["initial_status"] == "RISK_REJECTED"
    assert repository.payload["risk_snapshot"]["violations"]


@pytest.mark.django_db
def test_authorized_trader_uses_real_account_owner_projection_for_draft() -> None:
    owner = User.objects.create_user(username="delegated-draft-owner", password="test123")
    owner.account_profile.rbac_role = "owner"
    owner.account_profile.save(update_fields=["rbac_role", "updated_at"])
    trader = User.objects.create_user(username="delegated-draft-trader", password="test123")
    trader.account_profile.rbac_role = "trader"
    trader.account_profile.save(update_fields=["rbac_role", "updated_at"])
    SimulatedAccountModel.objects.create(
        id=95,
        user=owner,
        account_name="Delegated real account",
        account_type="real",
        initial_capital=Decimal("100000"),
        current_cash=Decimal("100000"),
        current_market_value=Decimal("0"),
        total_value=Decimal("100000"),
    )
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="delegated-draft-agent",
        display_name="Delegated Agent",
    )
    BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=95,
        agent=agent,
        broker_account_ref="broker-95",
        allowed_symbols=["510300.SH"],
        max_single_order_amount=Decimal("100000"),
        daily_order_amount_limit=Decimal("500000"),
    )
    BrokerAccountAccessModel.objects.create(
        user=trader,
        account_id=95,
        can_trade=True,
    )
    plan = _plan() | {"account_id": 95}

    result = CreateLiveOrderFromExecutionPlanUseCase(
        risk_evaluator=_RiskEvaluator(passed=True),
        latest_quote_provider=_quote,
    ).execute(actor=trader, plan=plan, idempotency_key="delegated-draft-1")

    order = LiveOrderModel.objects.get(client_order_id=result["order"]["client_order_id"])
    assert order.user_id == owner.id
    assert order.account_id == 95


@pytest.mark.django_db
def test_four_dimension_reconciliation_is_idempotent_and_auto_stops_on_p0() -> None:
    owner = User.objects.create_user(username="recon-owner", password="test123")
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="recon-agent",
        display_name="Reconciliation Agent",
    )
    BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=77,
        agent=agent,
        broker_account_ref="broker-77",
        auto_execution_enabled=True,
        max_single_order_amount=Decimal("100000"),
        daily_order_amount_limit=Decimal("500000"),
        allowed_symbols=["510300.SH"],
    )
    captured_at = timezone.now()
    snapshot = BrokerAccountSnapshotModel.objects.create(
        user=owner,
        agent=agent,
        account_id=77,
        captured_at=captured_at,
        cash_available=Decimal("900"),
        total_asset=Decimal("1000"),
        payload={
            "orders": [
                {
                    "broker_order_id": "QMT-UNKNOWN-1",
                    "client_order_id": "",
                    "status": "SUBMITTED",
                }
            ],
            "trades": [{"broker_trade_id": "QMT-TRADE-UNKNOWN-1"}],
        },
    )
    BrokerPositionSnapshotModel.objects.create(
        user=owner,
        agent=agent,
        account_id=77,
        asset_code="510300.SH",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        captured_at=captured_at,
    )
    projection = {
        "cash_available": "800",
        "total_asset": "1000",
        "positions": [{"asset_code": "510300.SH", "quantity": "50"}],
    }
    repository = DjangoBrokerExecutionRepository()

    first = repository.generate_reconciliation_runs(account_projections={77: projection})
    second = repository.generate_reconciliation_runs(account_projections={77: projection})

    assert first["created_runs"] == 1
    assert second["created_runs"] == 0
    assert second["duplicate_runs"] == 1
    run = ReconciliationRunModel.objects.get(summary__snapshot_id=snapshot.pk)
    assert set(
        ReconciliationDifferenceModel.objects.filter(run=run).values_list("dimension", flat=True)
    ) == {"order", "fill", "cash", "position"}
    assert TradingControlModel.objects.get(user=owner, account_id=77).kill_switch_active
    assert BrokerExecutionAlertModel.objects.get(account_id=77).auto_stop_applied
    assert BrokerExecutionDailyReportModel.objects.get(account_id=77).status == "critical"


@pytest.mark.django_db
def test_escalated_reconciliation_remains_a_resume_blocker() -> None:
    owner = User.objects.create_user(username="recon-escalation-owner")
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="recon-escalation-agent",
        display_name="Escalation QMT",
    )
    BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=78,
        agent=agent,
        broker_account_ref="broker-78",
        allowed_symbols=["510300.SH"],
    )
    run = ReconciliationRunModel.objects.create(
        user=owner,
        account_id=78,
        status="review",
        started_at=timezone.now(),
    )
    difference = ReconciliationDifferenceModel.objects.create(
        run=run,
        dimension="cash",
        difference_key="cash_available",
        severity="P0",
        expected={"cash_available": "100"},
        actual={"cash_available": "90"},
        reason="cash differs",
    )
    alert = BrokerExecutionAlertModel.objects.create(
        user=owner,
        account_id=78,
        fingerprint="recon-escalation-alert",
        code="P0_RECONCILIATION_DIFFERENCE",
        severity="P0",
        title="difference",
        message="difference",
        payload={"run_id": run.pk},
    )
    repository = DjangoBrokerExecutionRepository()

    result = repository.resolve_reconciliation(
        actor_id=owner.pk,
        is_admin=False,
        run_id=run.pk,
        resolution="escalate",
        reason="needs broker investigation",
        idempotency_key="recon-escalate-78",
        request_digest="digest-escalate-78",
    )

    run.refresh_from_db()
    difference.refresh_from_db()
    alert.refresh_from_db()
    assert result["status"] == "escalated"
    assert run.status == "escalated"
    assert run.completed_at is None
    assert difference.status == "escalated"
    assert alert.status == "open"
