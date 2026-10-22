"""Read and validate the source evidence needed by rebalance preview rows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from apps.risk_center.application.execution_settlement_v3 import (
    ExecutionSettlementV3Corruption,
    ExecutionSettlementV3InputError,
    ExecutionSettlementV3Unavailable,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_trading_constraints import AShareExecutionRule
from apps.simulated_trading.application.execution_current_reference_classification import (
    CurrentReferenceClassificationReader,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionFeePolicyReader,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.fee_policy_v2 import FeePolicyVersionStorageUnavailable
from apps.simulated_trading.application.manual_trade_execution import (
    CurrentReferenceManualIdentityReader,
)
from apps.simulated_trading.application.rebalance_preview_context import datetime_text
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    IdentityEvidenceValidationError,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide


class ExecutionQuantityRuleReader(Protocol):
    """Read the Risk-owned effective quantity terms at the preview cutoff."""

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        """Return the sealed source-backed settlement bundle for one security."""


class PositionRuleEvaluator(Protocol):
    """Evaluate the existing Strategy position rule against one current-price context."""

    def evaluate_position_rule(
        self,
        rule_id: int | None,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return the existing Strategy position-rule result or explicit unknown."""


class RebalancePreviewExecutionEvidenceReader:
    """Validate current identity, execution constraints, and exact fee evidence."""

    def __init__(
        self,
        *,
        identity_reader: CurrentReferenceManualIdentityReader,
        classification_reader: CurrentReferenceClassificationReader,
        fee_policy_reader: ExecutionFeePolicyReader,
        quantity_rule_reader: ExecutionQuantityRuleReader,
    ) -> None:
        """Bind the existing typed source readers used by preview rows."""

        self._identity_reader = identity_reader
        self._classification_reader = classification_reader
        self._fee_policy_reader = fee_policy_reader
        self._quantity_rule_reader = quantity_rule_reader

    def read_identity(self, *, asset_code: str, as_of: datetime) -> dict[str, object] | None:
        """Preserve current-purpose V2 source facts without qualifying nested V1."""

        try:
            evidence = self._identity_reader.resolve_current_reference_identity(
                asset_code=asset_code,
                as_of=as_of,
            )
            if evidence is None or type(evidence) is not ExecutionInstrumentIdentityEvidenceV2:
                return None
            ExecutionInstrumentIdentityEvidenceV2.__post_init__(evidence)
            evidence.validate_at(as_of=as_of)
            if evidence.asset_code != asset_code or evidence.selection.selected_at != as_of:
                return None
            source = evidence.source_evidence
            return {
                "security_id": evidence.security_id,
                "source_code": source.source_code,
                "source_exchange": source.source_exchange,
                "purpose": evidence.selection.purpose,
                "rule_market": evidence.rule_market,
                "board": evidence.board,
                "source_observed_at": datetime_text(source.source_observed_at),
                "source_available_at": datetime_text(source.source_available_at),
                "must_not_use_for_decision": source.must_not_use_for_decision,
                "must_not_execute": source.must_not_execute,
                "identity_hash": evidence.content_hash,
                "mapping_id": source.mapping_id,
                "mapping_version": source.mapping_version,
                "mapping_content_hash": source.mapping_content_hash,
            }
        except (
            ArithmeticError,
            AttributeError,
            IdentityEvidenceValidationError,
            SimulatedTradeExecutionBlocked,
            TypeError,
            ValueError,
        ):
            return None

    def read_quantity_rule(
        self,
        *,
        identity: dict[str, object],
        as_of: datetime,
    ) -> tuple[AShareExecutionRule | None, dict[str, object] | None]:
        """Read exact security quantity terms and preserve their sealed provenance."""

        security_id = identity.get("security_id")
        market = identity.get("rule_market")
        board = identity.get("board")
        if type(security_id) is not str or type(market) is not str or type(board) is not str:
            return None, None

        try:
            bundle = self._quantity_rule_reader.execute(security_id=security_id, as_of=as_of)
            if type(bundle) is not ExecutionSettlementBundleV3:
                return None, None
            ExecutionSettlementBundleV3.__post_init__(bundle)
            rule = bundle.execution_submission_v2.execution_rule_v1
            if type(rule) is not AShareExecutionRule:
                return None, None
            AShareExecutionRule.__post_init__(rule)
            if (rule.security_id, rule.market, rule.board) != (security_id, market, board):
                return None, None
            if not (
                bundle.latest_source_observed_at <= as_of
                and bundle.source_available_at <= as_of
                and bundle.effective_from <= as_of < bundle.valid_until
            ):
                return None, None
            payload: dict[str, object] = {
                "rule_id": rule.rule_id,
                "rule_version": rule.rule_version,
                "content_hash": rule.content_hash,
                "security_id": rule.security_id,
                "market": rule.market,
                "board": rule.board,
                "buy": rule.buy_quantity.to_payload(),
                "sell": rule.sell_quantity.to_payload(),
                "sell_odd_lot_mode": rule.sell_odd_lot_mode.value,
                "price_tick": str(rule.price_tick),
                "bundle": {
                    "bundle_id": bundle.bundle_id,
                    "bundle_version": bundle.bundle_version,
                    "content_hash": bundle.content_hash,
                    "latest_source_observed_at": bundle.latest_source_observed_at.isoformat(),
                    "source_available_at": bundle.source_available_at.isoformat(),
                    "effective_from": bundle.effective_from.isoformat(),
                    "valid_until": bundle.valid_until.isoformat(),
                },
                "execution_rule": {
                    "effective_from": rule.effective_from.isoformat(),
                    "valid_until": rule.valid_until.isoformat(),
                    "source_observed_at": rule.source_observed_at.isoformat(),
                    "source_available_at": rule.source_available_at.isoformat(),
                },
            }
            return rule, payload
        except (
            ArithmeticError,
            AttributeError,
            ExecutionSettlementV3Corruption,
            ExecutionSettlementV3InputError,
            ExecutionSettlementV3Unavailable,
            TypeError,
            ValueError,
        ):
            return None, None

    def read_asset_type_classification(
        self,
        *,
        identity: dict[str, object],
        asset_code: str,
        as_of: datetime,
    ) -> tuple[str | None, dict[str, object] | None]:
        """Resolve an operator-selected type only for the exact current V2 identity."""

        security_id = identity.get("security_id")
        if type(security_id) is not str:
            return None, None
        try:
            evidence = self._classification_reader.resolve_simulated_instrument_classification(
                security_id=security_id,
                asset_code=asset_code,
                as_of=as_of,
            )
            if (
                evidence is None
                or type(evidence) is not SimulatedInstrumentClassificationEvidenceV1
            ):
                return None, None
            SimulatedInstrumentClassificationEvidenceV1.__post_init__(evidence)
            evidence.validate_at(as_of=as_of)
            identity_evidence = evidence.identity_evidence
            asset_type = evidence.simulated_asset_type
            if (
                identity_evidence.security_id != security_id
                or identity_evidence.asset_code != asset_code
                or identity_evidence.selection.selected_at != as_of
                or identity_evidence.content_hash != identity.get("identity_hash")
                or type(asset_type) is not str
                or not asset_type.strip()
            ):
                return None, None
            source = identity_evidence.source_evidence
            payload: dict[str, object] = {
                "content_hash": evidence.content_hash,
                "read_at": datetime_text(evidence.read_at),
                "simulated_asset_type": asset_type,
                "purpose": identity_evidence.selection.purpose,
                "must_not_use_for_decision": source.must_not_use_for_decision,
                "must_not_execute": source.must_not_execute,
                "evidence": evidence.to_payload(),
            }
            return asset_type, payload
        except (
            ArithmeticError,
            AttributeError,
            IdentityEvidenceValidationError,
            SimulatedTradeExecutionBlocked,
            TypeError,
            ValueError,
        ):
            return None, None

    def estimate_fee(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_type: str,
        identity: dict[str, object],
        action: str,
        notional: Decimal,
        as_of: datetime,
    ) -> dict[str, object] | None:
        """Estimate only from one exact effective V2 case for the mapped identity."""

        market = identity.get("rule_market")
        board = identity.get("board")
        if type(market) is not str or type(board) is not str:
            return None
        side = SimulatedTradeSide.BUY if action == "buy" else SimulatedTradeSide.SELL
        try:
            policy = self._fee_policy_reader.get_execution_fee_policy(
                account_id=account_id,
                user_id=user_id,
                asset_type=asset_type,
                market=market,
                board=board,
                side=side,
                as_of=as_of,
            )
            if policy is None or type(policy) is not SimulatedFeePolicyV2:
                return None
            SimulatedFeePolicyV2.__post_init__(policy)
            policy.validate_at(as_of)
            case = policy.case_for(
                asset_type=asset_type,
                market=market,
                board=board,
                side=side,
                as_of=as_of,
            )
            fees = policy.calculate_for(
                asset_type=asset_type,
                market=market,
                board=board,
                side=side,
                amount=notional,
                as_of=as_of,
            )
            return {
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
                "content_hash": policy.content_hash,
                "transaction_case": case.to_payload(),
                "commission": str(fees.commission),
                "transfer_fee": str(fees.transfer_fee),
                "stamp_duty": str(fees.stamp_duty),
                "slippage": str(fees.slippage),
                "total": str(fees.total_fee),
            }
        except (
            ArithmeticError,
            AttributeError,
            FeePolicyVersionStorageUnavailable,
            TypeError,
            ValueError,
        ):
            return None


__all__: tuple[str, ...] = (
    "ExecutionQuantityRuleReader",
    "PositionRuleEvaluator",
    "RebalancePreviewExecutionEvidenceReader",
)
