"""Inputs bound to a broker order version at each live-order checkpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from apps.broker_execution.domain.entities import OrderApprovalSnapshot
from apps.broker_execution.domain.order_approval_artifact import BrokerOrderApprovalArtifact
from apps.broker_execution.domain.plan_order_binding import BrokerPlanOrderBinding
from apps.broker_execution.domain.portfolio_broker_account_binding import (
    BrokerPortfolioAccountNamespaceBinding,
)
from apps.broker_execution.domain.pre_risk_execution_scope import BrokerPreRiskExecutionScope
from apps.broker_execution.domain.rules import build_approval_digest

from .use_case_errors import BrokerExecutionConflictError


@dataclass(frozen=True, slots=True)
class BrokerCheckpointIntent:
    """Trusted workflow scope and the proposed or persisted order's actual economics."""

    client_order_id: UUID
    order_version: int
    plan_id: str
    plan_version: int
    plan_order_ordinal: int
    broker_account_namespace: str
    owner_user_id: int
    snapshot: OrderApprovalSnapshot
    sources: BrokerCheckpointSources

    def __post_init__(self) -> None:
        if (
            type(self.client_order_id) is not UUID
            or type(self.snapshot) is not OrderApprovalSnapshot
        ):
            raise ValueError("checkpoint requires exact order identity and snapshot")
        for value in (
            self.order_version,
            self.plan_version,
            self.owner_user_id,
            self.snapshot.account_id,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("checkpoint versions and account identities must be positive")
        if type(self.plan_order_ordinal) is not int or self.plan_order_ordinal < 0:
            raise ValueError("checkpoint plan ordinal must be nonnegative")
        for token in (self.plan_id, self.broker_account_namespace):
            if type(token) is not str or not token or token.strip() != token or len(token) > 192:
                raise ValueError("checkpoint source selector is invalid")


@dataclass(frozen=True, slots=True)
class BrokerCheckpointSources:
    """Verified upstream identities. These inactive Broker records do not grant execution."""

    order: BrokerOrderApprovalArtifact
    plan: BrokerPlanOrderBinding
    account: BrokerPortfolioAccountNamespaceBinding
    pre_risk: BrokerPreRiskExecutionScope

    def require_matches(self, intent: BrokerCheckpointIntent, as_of: datetime) -> None:
        """Reject a crossed source, stale receipt, altered economics or unbound plan."""
        order, plan, account, pre_risk = self.order, self.plan, self.account, self.pre_risk
        if not (
            order.client_order_id
            == str(intent.client_order_id)
            == pre_risk.order_artifact_id
            == plan.order_artifact_id
            and order.order_version
            == intent.order_version
            == plan.order_version
            == pre_risk.order_version
            and order.account_id
            == intent.snapshot.account_id
            == plan.broker_account_id
            == pre_risk.broker_account_id
            == account.broker_account_id
            and order.approval_snapshot == intent.snapshot
            and order.approval_digest
            == build_approval_digest(intent.snapshot)
            == plan.order_approval_digest
            == pre_risk.order_approval_digest
            and order.content_hash
            == plan.order_artifact_content_hash
            == pre_risk.order_artifact_content_hash
            and order.artifact_version
            == plan.order_artifact_version
            == pre_risk.order_artifact_version
            and order.identity_hash
            == plan.order_artifact_identity_hash
            == pre_risk.order_artifact_identity_hash
            and order.valid_until == plan.order_artifact_valid_until == pre_risk.order_valid_until
            and plan.portfolio_plan_id == pre_risk.plan_id == intent.plan_id
            and plan.portfolio_plan_version == pre_risk.plan_version == intent.plan_version
            and plan.plan_order_ordinal == intent.plan_order_ordinal
            and plan.portfolio_account_id
            == account.portfolio_account_id
            == pre_risk.portfolio_account_id
            and account.owner_user_id == intent.owner_user_id
            and account.broker_account_namespace == intent.broker_account_namespace
            and plan.portfolio_plan_content_hash == pre_risk.plan_content_hash
            and plan.portfolio_plan_valid_until == pre_risk.plan_valid_until
            and plan.portfolio_receipt_id == pre_risk.portfolio_receipt_id
            and plan.portfolio_receipt_version == pre_risk.portfolio_receipt_version
            and plan.portfolio_receipt_content_hash == pre_risk.portfolio_receipt_content_hash
            and plan.portfolio_receipt_valid_until == pre_risk.portfolio_receipt_valid_until
            and plan.portfolio_subject_id == pre_risk.portfolio_subject_id
            and plan.portfolio_subject_version == pre_risk.portfolio_subject_version
            and plan.portfolio_subject_content_hash == pre_risk.portfolio_subject_content_hash
            and pre_risk.order_risk_policy_version == intent.snapshot.risk_policy_version
            and as_of
            < min(order.valid_until, plan.valid_until, account.valid_until, pre_risk.valid_until)
        ):
            raise BrokerExecutionConflictError("broker_checkpoint_source_mismatch")
