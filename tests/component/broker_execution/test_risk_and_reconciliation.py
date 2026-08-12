"""Authoritative risk and four-dimensional reconciliation tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db.models.query import QuerySet
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
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
    def __init__(
        self,
        *,
        passed: bool,
        violations: list[str] | None = None,
    ) -> None:
        self.passed = passed
        self.violations = violations

    def execute(self, **_kwargs):
        return {
            "passed": self.passed,
            "violations": (
                self.violations
                if self.violations is not None
                else [] if self.passed else ["max_total_position_pct exceeded"]
            ),
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


def _repository_order_payload(account_id: int) -> dict:
    return {
        "account_id": account_id,
        "asset_code": "510300.SH",
        "side": "BUY",
        "quantity": "100",
        "limit_price": "3.90",
        "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        "source_recommendation_ids": ["recommendation-1"],
        "risk_snapshot": {
            "passed": True,
            "violations": [],
            "market_snapshot": {
                "current_price": "3.90",
                "must_not_use_for_decision": False,
            },
        },
        "initial_status": "WAITING_APPROVAL",
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
    with pytest.raises(BrokerExecutionConflictError, match="Evidence is integrated"):
        use_case.execute(
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

    assert creator.calls == []


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
    assert preview["orders_count"] == 1
    assert preview["commit_allowed"] is False
    assert preview["must_not_execute"] is True
    with pytest.raises(BrokerExecutionConflictError, match="Evidence is integrated"):
        use_case.execute(
            actor=actor,
            account_id=7,
            preview_only=False,
            expected_plan_digest=preview["plan_digest"],
            idempotency_key="advisor-bridge-1",
        )
    assert creator.calls == []


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
def test_live_order_creation_preserves_explicit_server_risk_rejection() -> None:
    """A false evaluator verdict remains authoritative even without detail text."""

    actor = User.objects.create_user(username="risk-explicit-false", password="test123")
    actor.account_profile.rbac_role = "owner"
    actor.account_profile.save(update_fields=["rbac_role", "updated_at"])
    repository = _CreateRepository()

    CreateLiveOrderFromExecutionPlanUseCase(
        repository,
        account_projection_provider=_projection,
        risk_evaluator=_RiskEvaluator(passed=False, violations=[]),
        latest_quote_provider=_quote,
    ).execute(actor=actor, plan=_plan(), idempotency_key="risk-order-explicit-false")

    assert repository.payload["initial_status"] == "RISK_REJECTED"
    assert repository.payload["risk_snapshot"]["passed"] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", float("nan")),
        ("quantity", float("inf")),
        ("quantity", 0),
        ("limit_price", float("-inf")),
        ("limit_price", -1),
    ],
)
def test_live_order_creation_rejects_nonfinite_or_nonpositive_numbers(
    field: str,
    value: float,
) -> None:
    """Invalid numeric inputs never reach risk evaluation or persistence."""

    actor = User.objects.create_user(
        username=f"risk-invalid-{field}-{str(value)}",
        password="test123",
    )
    actor.account_profile.rbac_role = "owner"
    actor.account_profile.save(update_fields=["rbac_role", "updated_at"])
    repository = _CreateRepository()
    plan = _plan()
    plan[field] = value

    with pytest.raises(BrokerExecutionValidationError, match="positive finite"):
        CreateLiveOrderFromExecutionPlanUseCase(
            repository,
            account_projection_provider=_projection,
            risk_evaluator=_RiskEvaluator(passed=True),
            latest_quote_provider=_quote,
        ).execute(actor=actor, plan=plan, idempotency_key=f"risk-invalid-{field}")

    assert repository.payload is None


@pytest.mark.django_db
def test_live_order_creation_marks_nonfinite_server_quote_as_risk_rejected() -> None:
    """A NaN market quote cannot turn into a passing server risk snapshot."""

    actor = User.objects.create_user(username="risk-nan-quote", password="test123")
    actor.account_profile.rbac_role = "owner"
    actor.account_profile.save(update_fields=["rbac_role", "updated_at"])
    repository = _CreateRepository()

    CreateLiveOrderFromExecutionPlanUseCase(
        repository,
        account_projection_provider=_projection,
        risk_evaluator=_RiskEvaluator(passed=True),
        latest_quote_provider=lambda _asset_code: {
            "current_price": float("nan"),
            "is_stale": False,
            "must_not_use_for_decision": False,
        },
    ).execute(actor=actor, plan=_plan(), idempotency_key="risk-nan-quote")

    assert repository.payload["initial_status"] == "RISK_REJECTED"
    assert "finite" in repository.payload["risk_snapshot"]["violations"][0]


@pytest.mark.django_db
def test_live_order_creation_rejects_nonfinite_account_projection() -> None:
    """Corrupt server-side account equity fails before risk evaluation."""

    actor = User.objects.create_user(
        username="risk-nan-account-projection",
        password="test123",
    )
    actor.account_profile.rbac_role = "owner"
    actor.account_profile.save(update_fields=["rbac_role", "updated_at"])
    repository = _CreateRepository()

    def _invalid_projection(**_kwargs):
        return _projection() | {"total_asset": float("nan")}

    with pytest.raises(BrokerExecutionValidationError, match="total_asset"):
        CreateLiveOrderFromExecutionPlanUseCase(
            repository,
            account_projection_provider=_invalid_projection,
            risk_evaluator=_RiskEvaluator(passed=True),
            latest_quote_provider=_quote,
        ).execute(
            actor=actor,
            plan=_plan(),
            idempotency_key="risk-nan-account-projection",
        )

    assert repository.payload is None


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
def test_live_order_revalidates_limits_after_lock_acquisition(monkeypatch) -> None:
    """A limit changed while waiting for the account lock must govern the order."""

    owner = User.objects.create_user(username="locked-order-limit-owner")
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="locked-order-limit-agent",
        display_name="Locked Limit Agent",
    )
    binding = BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=96,
        agent=agent,
        broker_account_ref="broker-96",
        allowed_symbols=["510300.SH"],
        max_single_order_amount=Decimal("100000"),
        daily_order_amount_limit=Decimal("500000"),
    )
    original_select_for_update = QuerySet.select_for_update
    limit_changed = False

    def _change_limit_before_lock(self, *args, **kwargs):
        nonlocal limit_changed
        if self.model is BrokerAccountBindingModel and not limit_changed:
            BrokerAccountBindingModel.objects.filter(pk=binding.pk).update(
                daily_order_amount_limit=Decimal("100")
            )
            limit_changed = True
        return original_select_for_update(self, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", _change_limit_before_lock)
    repository = DjangoBrokerExecutionRepository()

    with pytest.raises(BrokerExecutionConflictError, match="daily limit"):
        repository.create_live_order(
            user_id=owner.id,
            is_admin=False,
            payload=_repository_order_payload(96),
            idempotency_key="locked-limit-order",
            request_digest="locked-limit-digest",
        )

    assert limit_changed is True
    assert not LiveOrderModel.objects.filter(account_id=96).exists()


@pytest.mark.django_db
def test_live_order_rechecks_idempotency_after_lock(monkeypatch) -> None:
    """A concurrent winner discovered after the account lock is replayed."""

    owner = User.objects.create_user(username="locked-order-replay-owner")
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="locked-order-replay-agent",
        display_name="Locked Replay Agent",
    )
    BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=97,
        agent=agent,
        broker_account_ref="broker-97",
        allowed_symbols=["510300.SH"],
        max_single_order_amount=Decimal("100000"),
        daily_order_amount_limit=Decimal("500000"),
    )
    repository = DjangoBrokerExecutionRepository()
    replay_calls = 0
    stored = {"success": True, "idempotent_replay": True, "order": {"stored": True}}

    def _replay_after_lock(**_kwargs):
        nonlocal replay_calls
        replay_calls += 1
        return None if replay_calls == 1 else stored

    monkeypatch.setattr(repository, "_replay_or_conflict", _replay_after_lock)
    result = repository.create_live_order(
        user_id=owner.id,
        is_admin=False,
        payload=_repository_order_payload(97),
        idempotency_key="locked-replay-order",
        request_digest="locked-replay-digest",
    )

    assert result == stored
    assert replay_calls == 2
    assert not LiveOrderModel.objects.filter(account_id=97).exists()


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
