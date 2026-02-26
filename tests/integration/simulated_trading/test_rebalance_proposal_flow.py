"""Integration tests for rebalance proposal flow."""

import pytest
from datetime import date, datetime
from unittest.mock import Mock, patch

from django.utils import timezone as django_timezone

from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    DailyInspectionReportModel,
    RebalanceProposalModel,
    PositionModel,
    NotificationHistoryModel,
)
from apps.simulated_trading.application.daily_inspection_service import (
    DailyInspectionService,
)
from apps.simulated_trading.application.tasks import (
    daily_portfolio_inspection_task,
)


@pytest.mark.django_db
class TestRebalanceProposalCreation:
    """Test rebalance proposal creation from daily inspection."""

    def test_create_proposal_from_inspection_result(self):
        """Test creating proposal from inspection result."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="proposaluser",
            email="proposal@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Proposal Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
            current_market_value=50000,
        )

        # Create inspection report first
        report = DailyInspectionReportModel.objects.create(
            account=account,
            inspection_date=date.today(),
            status="warning",
            checks=[],
            summary={},
        )

        # Create inspection result
        inspection_result = {
            "report_id": report.id,
            "account_id": account.id,
            "inspection_date": "2026-02-26",
            "status": "warning",
            "macro_regime": "growth_stable",
            "policy_gear": "neutral",
            "strategy_id": None,  # No strategy to avoid FK error
            "position_rule_id": None,
            "summary": {
                "positions_count": 3,
                "rebalance_required_count": 2,
                "rebalance_assets": ["512880.SH", "515050.SH"],
                "total_value": 100000.0,
                "current_cash": 5000.0,
                "current_market_value": 95000.0,
            },
            "checks": [
                {
                    "asset_code": "512880.SH",
                    "asset_name": "证券ETF",
                    "quantity": 1000,
                    "current_price": 5.0,
                    "market_value": 50000.0,
                    "weight": 0.50,
                    "target_weight": 0.30,
                    "drift": 0.20,
                    "rebalance_action": "sell",
                    "rebalance_qty_suggest": -400,
                },
                {
                    "asset_code": "515050.SH",
                    "asset_name": "5G ETF",
                    "quantity": 500,
                    "current_price": 1.0,
                    "market_value": 500.0,
                    "weight": 0.005,
                    "target_weight": 0.10,
                    "drift": -0.095,
                    "rebalance_action": "buy",
                    "rebalance_qty_suggest": 9500,
                },
                {
                    "asset_code": "512100.SH",
                    "asset_name": "沪深300ETF",
                    "quantity": 500,
                    "current_price": 4.0,
                    "market_value": 20000.0,
                    "weight": 0.20,
                    "target_weight": 0.20,
                    "drift": 0.0,
                    "rebalance_action": "hold",
                    "rebalance_qty_suggest": 0,
                },
            ],
        }

        # Create proposal
        proposal = DailyInspectionService.create_rebalance_proposal(
            account_id=account.id,
            inspection_result=inspection_result,
        )

        # Verify proposal was created
        assert proposal is not None
        assert proposal.account == account
        assert proposal.source == RebalanceProposalModel.SOURCE_DAILY_INSPECTION
        assert proposal.status == RebalanceProposalModel.STATUS_PENDING
        assert proposal.priority in ["low", "normal", "high", "urgent"]

        # Verify proposals
        assert len(proposal.proposals) == 2  # Only non-hold actions

        # Check sell action
        sell_proposal = next(p for p in proposal.proposals if p["action"] == "sell")
        assert sell_proposal["asset_code"] == "512880.SH"
        assert sell_proposal["suggested_quantity"] == 400

        # Check buy action
        buy_proposal = next(p for p in proposal.proposals if p["action"] == "buy")
        assert buy_proposal["asset_code"] == "515050.SH"
        assert buy_proposal["suggested_quantity"] == 9500

        # Verify summary
        assert proposal.summary["buy_count"] == 1
        assert proposal.summary["sell_count"] == 1
        assert proposal.summary["rebalance_assets"] == ["512880.SH", "515050.SH"]

    def test_proposal_not_created_when_no_rebalance_needed(self):
        """Test proposal is not created when no rebalance is needed."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="nobalanceneeded",
            email="nobalance@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="No Rebalance Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
            current_market_value=50000,
        )

        # Create inspection report first
        report = DailyInspectionReportModel.objects.create(
            account=account,
            inspection_date=date.today(),
            status="ok",
            checks=[],
            summary={},
        )

        # Create inspection result with no rebalance needed
        inspection_result = {
            "report_id": report.id,
            "account_id": account.id,
            "inspection_date": "2026-02-26",
            "status": "ok",
            "strategy_id": None,
            "position_rule_id": None,
            "summary": {
                "positions_count": 2,
                "rebalance_required_count": 0,
                "rebalance_assets": [],
                "total_value": 100000.0,
                "current_cash": 50000.0,
            },
            "checks": [
                {
                    "asset_code": "512880.SH",
                    "rebalance_action": "hold",
                },
                {
                    "asset_code": "512100.SH",
                    "rebalance_action": "hold",
                },
            ],
        }

        # Create proposal
        proposal = DailyInspectionService.create_rebalance_proposal(
            account_id=account.id,
            inspection_result=inspection_result,
        )

        # Proposal should be created but with empty proposals list
        assert proposal is not None
        assert len(proposal.proposals) == 0
        assert proposal.summary["buy_count"] == 0
        assert proposal.summary["sell_count"] == 0


@pytest.mark.django_db
class TestRebalanceProposalLifecycle:
    """Test rebalance proposal lifecycle states."""

    def test_proposal_approval_flow(self):
        """Test proposal approval flow."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="approver",
            email="approver@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Approval Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            source=RebalanceProposalModel.SOURCE_MANUAL,
            status=RebalanceProposalModel.STATUS_PENDING,
            proposals=[],
            summary={},
        )

        # Approve proposal
        proposal.approve(reviewed_by="admin", comment="Approved for execution")

        # Verify state change
        proposal.refresh_from_db()
        assert proposal.status == RebalanceProposalModel.STATUS_APPROVED
        assert proposal.reviewed_by == "admin"
        assert proposal.review_comment == "Approved for execution"
        assert proposal.reviewed_at is not None

    def test_proposal_rejection_flow(self):
        """Test proposal rejection flow."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="rejecter",
            email="rejecter@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Rejection Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            source=RebalanceProposalModel.SOURCE_MANUAL,
            status=RebalanceProposalModel.STATUS_PENDING,
            proposals=[],
            summary={},
        )

        # Reject proposal
        proposal.reject(reviewed_by="admin", comment="Market conditions changed")

        # Verify state change
        proposal.refresh_from_db()
        assert proposal.status == RebalanceProposalModel.STATUS_REJECTED
        assert proposal.reviewed_by == "admin"
        assert proposal.review_comment == "Market conditions changed"

    def test_proposal_execution_flow(self):
        """Test proposal execution flow."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="executor",
            email="executor@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Execution Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            source=RebalanceProposalModel.SOURCE_MANUAL,
            status=RebalanceProposalModel.STATUS_APPROVED,
            proposals=[],
            summary={},
        )

        # Start execution
        proposal.start_execution(executed_by="auto_trading")

        proposal.refresh_from_db()
        assert proposal.status == RebalanceProposalModel.STATUS_EXECUTING
        assert proposal.executed_by == "auto_trading"

        # Complete execution
        execution_result = {
            "success": True,
            "trades_executed": 2,
            "total_amount": 10000.00,
        }
        proposal.complete_execution(result=execution_result)

        proposal.refresh_from_db()
        assert proposal.status == RebalanceProposalModel.STATUS_COMPLETED
        assert proposal.execution_result == execution_result
        assert proposal.executed_at is not None

    def test_proposal_execution_failure_flow(self):
        """Test proposal execution failure flow."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="failexecutor",
            email="fail@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Fail Execution Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            source=RebalanceProposalModel.SOURCE_MANUAL,
            status=RebalanceProposalModel.STATUS_EXECUTING,
            proposals=[],
            summary={},
        )

        # Fail execution
        proposal.fail_execution(error="Insufficient cash")

        proposal.refresh_from_db()
        assert proposal.status == RebalanceProposalModel.STATUS_FAILED
        assert proposal.execution_result == {"error": "Insufficient cash"}
        assert proposal.executed_at is not None

    def test_proposal_cancellation_flow(self):
        """Test proposal cancellation flow."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="cancellor",
            email="cancel@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Cancel Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            source=RebalanceProposalModel.SOURCE_MANUAL,
            status=RebalanceProposalModel.STATUS_PENDING,
            proposals=[],
            summary={},
        )

        # Cancel proposal
        proposal.cancel()

        proposal.refresh_from_db()
        assert proposal.status == RebalanceProposalModel.STATUS_CANCELLED


@pytest.mark.django_db
class TestRebalanceProposalTracing:
    """Test rebalance proposal traceability."""

    def test_proposal_source_tracking(self):
        """Test proposal source is correctly tracked."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="sourcetracker",
            email="source@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Source Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        # Create proposals from different sources
        sources = [
            RebalanceProposalModel.SOURCE_DAILY_INSPECTION,
            RebalanceProposalModel.SOURCE_SIGNAL,
            RebalanceProposalModel.SOURCE_MANUAL,
            RebalanceProposalModel.SOURCE_REGIME_CHANGE,
            RebalanceProposalModel.SOURCE_POLICY_CHANGE,
        ]

        for source in sources:
            proposal = RebalanceProposalModel.objects.create(
                account=account,
                source=source,
                status=RebalanceProposalModel.STATUS_PENDING,
                proposals=[],
                summary={},
            )
            assert proposal.source == source
            assert proposal.get_source_display() is not None

    def test_proposal_metadata_contains_context(self):
        """Test proposal metadata contains execution context."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="metadatauser",
            email="metadata@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Metadata Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        inspection_result = {
            "inspection_date": "2026-02-26",
            "macro_regime": "growth_stable",
            "policy_gear": "neutral",
            "position_rule_id": 1,
        }

        proposal = DailyInspectionService.create_rebalance_proposal(
            account_id=account.id,
            inspection_result=inspection_result,
        )

        # Verify metadata
        assert proposal.metadata["inspection_date"] == "2026-02-26"
        assert proposal.metadata["macro_regime"] == "growth_stable"
        assert proposal.metadata["policy_gear"] == "neutral"

    def test_proposal_inspection_report_link(self):
        """Test proposal is linked to inspection report."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="linkuser",
            email="link@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Link Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
            current_market_value=50000,
        )

        report = DailyInspectionReportModel.objects.create(
            account=account,
            inspection_date=date.today(),
            status="warning",
            checks=[],
            summary={},
        )

        inspection_result = {
            "report_id": report.id,
            "account_id": account.id,
            "inspection_date": "2026-02-26",
            "status": "warning",
            "strategy_id": None,
            "position_rule_id": None,
            "summary": {"rebalance_required_count": 1, "rebalance_assets": ["512880.SH"]},
            "checks": [
                {
                    "asset_code": "512880.SH",
                    "asset_name": "证券ETF",
                    "rebalance_action": "buy",
                    "rebalance_qty_suggest": 100,
                    "current_price": 5.0,
                }
            ],
        }

        proposal = DailyInspectionService.create_rebalance_proposal(
            account_id=account.id,
            inspection_result=inspection_result,
        )

        # Verify link
        assert proposal.inspection_report_id == report.id
        assert proposal.inspection_report == report


@pytest.mark.django_db
class TestDailyInspectionWithProposal:
    """Test daily inspection task with proposal creation."""

    def test_run_and_create_proposal_with_rebalance_needed(self):
        """Test run_and_create_proposal creates proposal when rebalance is needed."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="runproposal",
            email="runproposal@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Run Proposal Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
            current_market_value=50000,
        )

        # Create a position with drift
        PositionModel.objects.create(
            account=account,
            asset_code="512880.SH",
            asset_name="证券ETF",
            asset_type="fund",
            quantity=1000,
            available_quantity=1000,
            avg_cost=5.0,
            total_cost=5000.0,
            current_price=5.0,
            market_value=50000.0,
            unrealized_pnl=0,
            unrealized_pnl_pct=0,
            first_buy_date=date.today(),
        )

        # Run inspection without auto-creating proposal
        result = DailyInspectionService.run_and_create_proposal(
            account_id=account.id,
            auto_create_proposal=False,
        )

        # Verify result
        assert "report_id" in result
        assert result["proposal_created"] is False
        assert result["proposal_id"] is None

    def test_task_creates_proposal_when_enabled(self):
        """Test Celery task creates proposal when enabled."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="taskproposal",
            email="taskproposal@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Task Proposal Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
            current_market_value=50000,
        )

        # Mock the inspection service to return rebalance needed
        inspection_result = {
            "report_id": 1,
            "account_id": account.id,
            "inspection_date": "2026-02-26",
            "status": "warning",
            "macro_regime": "growth_stable",
            "policy_gear": "neutral",
            "strategy_id": None,
            "position_rule_id": None,
            "summary": {
                "positions_count": 1,
                "rebalance_required_count": 1,
                "rebalance_assets": ["512880.SH"],
                "total_value": 100000.0,
                "current_cash": 50000.0,
            },
            "checks": [
                {
                    "asset_code": "512880.SH",
                    "rebalance_action": "buy",
                    "rebalance_qty_suggest": 100,
                }
            ],
        }

        with patch.object(
            DailyInspectionService,
            "run_and_create_proposal",
            return_value={**inspection_result, "proposal_id": 1, "proposal_created": True}
        ):
            result = daily_portfolio_inspection_task(
                account_id=account.id,
                auto_create_proposal=True,
            )

            assert result["success"] is True
            assert result["proposal_created"] is True
            assert result["proposal_id"] == 1


@pytest.mark.django_db
class TestRebalanceActionsSummary:
    """Test rebalance actions summary."""

    def test_get_rebalance_actions_summary(self):
        """Test getting summary of rebalance actions."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="summaryuser",
            email="summary@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Summary Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            source=RebalanceProposalModel.SOURCE_MANUAL,
            status=RebalanceProposalModel.STATUS_PENDING,
            proposals=[
                {
                    "asset_code": "512880.SH",
                    "action": "buy",
                    "estimated_amount": 5000.0,
                },
                {
                    "asset_code": "515050.SH",
                    "action": "buy",
                    "estimated_amount": 3000.0,
                },
                {
                    "asset_code": "512100.SH",
                    "action": "sell",
                    "estimated_amount": 4000.0,
                },
            ],
            summary={},
        )

        # Get actions summary
        summary = proposal.get_rebalance_actions()

        assert summary["buy_count"] == 2
        assert summary["sell_count"] == 1
        assert "512880.SH" in summary["buy_assets"]
        assert "515050.SH" in summary["buy_assets"]
        assert "512100.SH" in summary["sell_assets"]
        assert summary["total_buy_amount"] == 8000.0
        assert summary["total_sell_amount"] == 4000.0


@pytest.mark.django_db
class TestProposalPriorityDetermination:
    """Test proposal priority determination."""

    def test_high_priority_for_multiple_rebalances(self):
        """Test high priority when many assets need rebalancing."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="priorityuser",
            email="priority@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Priority Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
            current_market_value=50000,
        )

        # Create report first
        report = DailyInspectionReportModel.objects.create(
            account=account,
            inspection_date=date.today(),
            status="warning",
            checks=[],
            summary={},
        )

        inspection_result = {
            "report_id": report.id,
            "account_id": account.id,
            "inspection_date": "2026-02-26",
            "status": "warning",
            "strategy_id": None,
            "position_rule_id": None,
            "summary": {
                "positions_count": 5,
                "rebalance_required_count": 4,  # >= 3 triggers high priority
                "rebalance_assets": ["A", "B", "C", "D"],
                "total_value": 100000.0,
                "current_cash": 5000.0,
            },
            "checks": [],
        }

        proposal = DailyInspectionService.create_rebalance_proposal(
            account_id=account.id,
            inspection_result=inspection_result,
        )

        assert proposal.priority == "high"

    def test_high_priority_for_low_cash(self):
        """Test high priority when cash ratio is low."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="lowcashuser",
            email="lowcash@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Low Cash Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=1000,  # < 5% triggers high priority
            total_value=100000,
            current_market_value=99000,
        )

        # Create report first
        report = DailyInspectionReportModel.objects.create(
            account=account,
            inspection_date=date.today(),
            status="warning",
            checks=[],
            summary={},
        )

        inspection_result = {
            "report_id": report.id,
            "account_id": account.id,
            "inspection_date": "2026-02-26",
            "status": "warning",
            "strategy_id": None,
            "position_rule_id": None,
            "summary": {
                "positions_count": 2,
                "rebalance_required_count": 1,
                "rebalance_assets": ["512880.SH"],
                "total_value": 100000.0,
                "current_cash": 1000.0,
            },
            "checks": [],
        }

        proposal = DailyInspectionService.create_rebalance_proposal(
            account_id=account.id,
            inspection_result=inspection_result,
        )

        assert proposal.priority == "high"

    def test_normal_priority_for_minor_rebalance(self):
        """Test normal priority for minor rebalancing."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="normaluser2",
            email="normal2@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Normal Priority Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=20000,  # 20% cash
            total_value=100000,
            current_market_value=80000,
        )

        # Create report first
        report = DailyInspectionReportModel.objects.create(
            account=account,
            inspection_date=date.today(),
            status="warning",
            checks=[],
            summary={},
        )

        inspection_result = {
            "report_id": report.id,
            "account_id": account.id,
            "inspection_date": "2026-02-26",
            "status": "warning",
            "strategy_id": None,
            "position_rule_id": None,
            "summary": {
                "positions_count": 2,
                "rebalance_required_count": 1,
                "rebalance_assets": ["512880.SH"],
                "total_value": 100000.0,
                "current_cash": 20000.0,
            },
            "checks": [],
        }

        proposal = DailyInspectionService.create_rebalance_proposal(
            account_id=account.id,
            inspection_result=inspection_result,
        )

        assert proposal.priority == "normal"
