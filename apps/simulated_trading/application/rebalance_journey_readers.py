"""Read the existing owner preview and exact fee/rule inputs for plan preparation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from apps.risk_center.application.execution_settlement_v3 import ExecutionSettlementV3ReadRecord
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import ExecutionFeePolicyReader
from apps.simulated_trading.application.interface_services import run_daily_inspection
from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.portfolio_risk_public import (
    prepare_owned_portfolio_plan_context,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from apps.simulated_trading.application.rebalance_plan_capture import (
    CapturingRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide


class JourneyPreviewBuilderFactory(Protocol):
    """Bind the existing configured preview lane without changing its source purpose."""

    def __call__(
        self, *, reference_price_basis: Literal["market", "published_close"]
    ) -> ReadOnlyRebalancePlanPreviewBuilder:
        """Construct a fresh configured reader for this one inspection."""
        ...


class JourneyRuleRecordReader(Protocol):
    """Retain both the sealed rule bundle and its actual local knowledge clock."""

    def execute_record(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSettlementV3ReadRecord:
        """Return only a source-available and locally known exact rule record."""
        ...


class ServerRebalanceJourneyReads:
    """Keep all network/source preparation outside the later plan/order write lock."""

    def __init__(
        self,
        *,
        preview_builder_factory: JourneyPreviewBuilderFactory,
        fee_reader: ExecutionFeePolicyReader,
        quantity_rule_reader: JourneyRuleRecordReader,
        using: str,
    ) -> None:
        """Inject existing public source readers rather than accepting client market facts."""

        self._builder_factory = preview_builder_factory
        self._fee_reader = fee_reader
        self._rule_reader = quantity_rule_reader
        self._using = using

    def read_preview(
        self,
        *,
        user_id: int,
        account_id: int,
        target_weights: str,
        reference_price_basis: Literal["market", "published_close"],
    ) -> RebalancePlanPreview:
        """Capture the same typed preview the actual owned inspection publishes."""

        capture = CapturingRebalancePlanPreviewBuilder(
            self._builder_factory(reference_price_basis=reference_price_basis)
        )
        run_daily_inspection(
            account_id=account_id,
            user_id=user_id,
            inspection_date=None,
            strategy_id=None,
            auto_create_proposal=False,
            temporary_target_weights=target_weights,
            preview_builder=capture,
        )
        return capture.captured

    def read_risk(
        self, *, user_id: int, account_id: int, preview: RebalancePlanPreview
    ) -> PreparedPortfolioRisk:
        """Obtain the actual owner-qualified resources, source manifests and policy clocks."""

        return prepare_owned_portfolio_plan_context(
            user_id=user_id, account_id=account_id, preview=preview, using=self._using
        )

    def read_order_policies(
        self,
        *,
        row: RebalancePlanPreviewItem,
        prepared: PreparedPortfolioRisk,
    ) -> tuple[SimulatedFeePolicyV2, ExecutionSettlementV3ReadRecord]:
        """Return original exact policies only if the captured row pins still match."""

        if row.identity is None or row.fee is None or row.quantity_rule is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_ORDER_POLICY_MISSING")
        if row.action not in {"buy", "sell"} or type(row.asset_type) is not str:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_INSTRUMENT_UNQUALIFIED")
        security_id = _text(row.identity.get("security_id"))
        market = _text(row.identity.get("rule_market"))
        board = _text(row.identity.get("board"))
        side = SimulatedTradeSide.BUY if row.action == "buy" else SimulatedTradeSide.SELL
        fee = self._fee_reader.get_execution_fee_policy(
            account_id=prepared.snapshot.account_id,
            user_id=prepared.actor_user_id,
            asset_type=row.asset_type,
            market=market,
            board=board,
            side=side,
            as_of=prepared.as_of,
        )
        if type(fee) is not SimulatedFeePolicyV2:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_FEE_POLICY_MISSING")
        fee.validate_at(prepared.as_of)
        fee.case_for(
            asset_type=row.asset_type, market=market, board=board, side=side, as_of=prepared.as_of
        )
        if fee.content_hash != row.fee.get("content_hash"):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_FEE_POLICY_CHANGED")
        record = self._rule_reader.execute_record(security_id=security_id, as_of=prepared.as_of)
        if type(record) is not ExecutionSettlementV3ReadRecord:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RULE_RECORD_MISSING")
        record.__post_init__()
        if record.recorded_at > prepared.as_of:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RULE_NOT_KNOWN_AT_CUTOFF")
        bundle = record.bundle
        if type(bundle) is not ExecutionSettlementBundleV3:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RULE_BUNDLE_MISSING")
        bundle.__post_init__()
        captured = row.quantity_rule.get("bundle")
        if type(captured) is not dict or captured.get("content_hash") != bundle.content_hash:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RULE_BUNDLE_CHANGED")
        rule = bundle.execution_submission_v2.execution_rule_v1
        if (rule.security_id, rule.market, rule.board) != (security_id, market, board):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RULE_SCOPE_CHANGED")
        if not bundle.effective_from <= prepared.as_of < bundle.valid_until:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_RULE_BUNDLE_EXPIRED")
        return fee, record


def _text(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_IDENTITY_UNKNOWN")
    return value
