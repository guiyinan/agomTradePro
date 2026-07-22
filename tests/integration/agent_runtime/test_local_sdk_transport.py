"""Integration coverage for socket-free SDK calls inside Django."""

from unittest.mock import patch

import pytest

from apps.account.infrastructure.models import PortfolioModel, TransactionModel
from apps.agent_runtime.domain.entities import (
    AgentProposal,
    ApprovalStatus,
    ProposalStatus,
    RiskLevel,
)
from apps.agent_runtime.infrastructure.mcp_proposal_executor import (
    ApprovedMcpCapabilityExecutor,
)
from apps.agent_runtime.infrastructure.models import AgentTaskModel
from shared.infrastructure.django_sdk_transport import DjangoSdkTransport


@pytest.mark.django_db
def test_local_sdk_transport_creates_agent_task_without_http(django_user_model):
    """The embedded SDK transport must preserve the real API contract locally."""

    from agomtradepro import AgomTradeProClient
    from agomtradepro.transport import use_request_transport

    user = django_user_model.objects.create_user(username="embedded-sdk-operator")
    transport = DjangoSdkTransport(actor={"user_id": user.pk})

    with use_request_transport(transport), patch(
        "requests.Session.request",
        side_effect=AssertionError("network HTTP must not be used"),
    ):
        client = AgomTradeProClient(
            base_url="http://testserver",
            username="local-transport",
            password="not-used",
        )
        result = client.agent_runtime.create_task(
            task_domain="research",
            task_type="embedded_transport_test",
            input_payload={"source": "test"},
        )

    assert result["task"]["task_type"] == "embedded_transport_test"


@pytest.mark.django_db(transaction=True)
def test_approved_mcp_execution_uses_no_business_or_audit_http(django_user_model):
    """The complete approval stage/resume path remains inside the Django process."""

    user = django_user_model.objects.create_user(
        username="embedded-mcp-approver",
        is_staff=True,
    )
    proposal = AgentProposal(
        id=17,
        request_id="apr_embedded_transport",
        proposal_type="terminal_mcp_capability",
        status=ProposalStatus.APPROVED,
        risk_level=RiskLevel.HIGH,
        approval_required=True,
        approval_status=ApprovalStatus.APPROVED,
        proposal_payload={
            "capability_key": "agent_task.create.task",
            "arguments": {
                "task_domain": "research",
                "task_type": "approved_embedded_transport",
                "input_payload": {"source": "approval-test"},
                "idempotency_key": "approval-transport-test-1",
            },
        },
        created_by=user.pk,
    )

    with patch(
        "requests.Session.request",
        side_effect=AssertionError("network HTTP must not be used"),
    ):
        result = ApprovedMcpCapabilityExecutor().execute(
            proposal=proposal,
            actor={
                "user_id": user.pk,
                "username": user.get_username(),
                "is_staff": True,
                "roles": ["admin"],
            },
            context={},
        )

    assert result["ok"] is True
    assert AgentTaskModel._default_manager.filter(
        task_type="approved_embedded_transport",
        created_by=user,
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_governed_broker_import_uses_local_multipart_without_http(django_user_model):
    """A current governed multipart capability must execute without a socket."""

    user = django_user_model.objects.create_superuser(
        username="embedded-broker-importer",
        email="embedded@example.com",
        password="test-only-password",
    )
    portfolio = PortfolioModel._default_manager.create(user=user, name="本地导入组合")
    proposal = AgentProposal(
        id=18,
        request_id="apr_embedded_multipart",
        proposal_type="terminal_mcp_capability",
        status=ProposalStatus.APPROVED,
        risk_level=RiskLevel.HIGH,
        approval_required=True,
        approval_status=ApprovalStatus.APPROVED,
        proposal_payload={
            "capability_key": "account.import.broker_trades",
            "arguments": {
                "portfolio_id": portfolio.pk,
                "broker_name": "embedded-test",
                "trades": [
                    {
                        "traded_at": "2026-07-18T10:00:00+08:00",
                        "action": "buy",
                        "asset_code": "000001.SZ",
                        "shares": 100,
                        "price": 10,
                        "external_trade_id": "embedded-trade-1",
                    }
                ],
                "idempotency_key": "approval-multipart-test-1",
            },
        },
        created_by=user.pk,
    )

    with patch(
        "requests.Session.request",
        side_effect=AssertionError("network HTTP must not be used"),
    ):
        result = ApprovedMcpCapabilityExecutor().execute(
            proposal=proposal,
            actor={
                "user_id": user.pk,
                "username": user.get_username(),
                "is_staff": True,
                "roles": ["admin"],
            },
            context={},
        )

    assert result["ok"] is True
    assert result["result"]["imported_rows"] == 1
    assert TransactionModel._default_manager.filter(
        portfolio=portfolio,
        external_trade_id="embedded-trade-1",
    ).exists()
