"""Build an owner-scoped, read-only view of daily inspection adjustments."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

from apps.account.application.market_price_contracts import MarketPriceProvider, MarketPriceResult
from apps.risk_center.application.m1_rebalance_risk_policy import (
    GetM1RiskPolicyQualificationUseCase,
)
from apps.simulated_trading.application.execution_current_reference_classification import (
    CurrentReferenceClassificationReader,
)
from apps.simulated_trading.application.execution_settlement_uow import ExecutionFeePolicyReader
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    M1RiskPolicyAccountSourceReader,
    StrategyM1RiskSourceReader,
)
from apps.simulated_trading.application.manual_trade_execution import (
    CurrentReferenceManualIdentityReader,
)
from apps.simulated_trading.application.rebalance_plan_preview_assembly import (
    empty_rebalance_plan_preview,
    finish_rebalance_plan_preview,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
    RebalancePlanRiskContext,
    StrategyPolicyApplicability,
    TargetMode,
)
from apps.simulated_trading.application.rebalance_preview_context import (
    build_rebalance_plan_risk_context,
    normalize_cutoff,
    quantity_unit,
    string_tuple,
)
from apps.simulated_trading.application.rebalance_preview_execution_evidence import (
    ExecutionQuantityRuleReader,
    PositionRuleEvaluator,
    RebalancePreviewExecutionEvidenceReader,
)
from apps.simulated_trading.application.rebalance_preview_m1_risk import (
    qualify_m1_risk_policy,
    stop_loss_observation,
)
from apps.simulated_trading.application.rebalance_preview_reference_close import (
    PricePublicationReference,
    ReferenceClosePriceReader,
    ReferencePriceBasis,
)
from apps.simulated_trading.application.rebalance_preview_resources import (
    active_buy_notional_for_asset,
    projected_buy_position_amount_by_asset,
    projected_position_amount,
    resource_snapshot_matches,
    snapshot_cash_values,
)
from apps.simulated_trading.application.rebalance_preview_rule_evaluation import (
    evaluate_current_position_rule,
)
from apps.simulated_trading.application.rebalance_preview_valuation import (
    CurrentRebalanceValuationReader,
    _decimal_value,
    _normalized_code,
    _optional_text,
    _price_decimal,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    ActiveRebalanceReservation,
    RebalanceResourceSnapshotReader,
)
from apps.simulated_trading.application.rebalance_target_selection import (
    resolve_rebalance_target_selection,
)
from apps.simulated_trading.domain.entities import AccountType, Position, SimulatedAccount
from apps.simulated_trading.domain.rebalance_preview_math import (
    account_position_cap_reason,
    account_stop_loss_reason,
    calculate_amount_adjustment,
    calculate_asset_adjustment,
    calculate_user_target_difference,
    constrain_buy_quantity,
    constrain_sell_quantity,
    round_cny_amount,
    strategy_position_cap_reason,
    strategy_stop_loss_reason,
)
from apps.simulated_trading.domain.temporary_rebalance_targets import TemporarySecurityTargets
from apps.strategy.application.execution_gateway import StrategySelectionState


class ReadOnlyRebalancePlanPreviewBuilder:
    """Build a read-only inspection preview from exact current source ports."""

    def __init__(
        self,
        *,
        price_reader: MarketPriceProvider,
        identity_reader: CurrentReferenceManualIdentityReader,
        classification_reader: CurrentReferenceClassificationReader,
        fee_policy_reader: ExecutionFeePolicyReader,
        quantity_rule_reader: ExecutionQuantityRuleReader,
        resource_snapshot_reader: RebalanceResourceSnapshotReader,
        position_rule_evaluator: PositionRuleEvaluator,
        risk_policy_qualifier: GetM1RiskPolicyQualificationUseCase | None = None,
        risk_policy_account_source_reader: M1RiskPolicyAccountSourceReader | None = None,
        strategy_risk_source_reader: StrategyM1RiskSourceReader | None = None,
        reference_close_reader: ReferenceClosePriceReader | None = None,
        reference_price_basis: ReferencePriceBasis = "market",
    ) -> None:
        """Bind the formal price, current-reference identity and FeeV2 ports."""

        if reference_price_basis not in {"market", "published_close"}:
            raise ValueError("Unsupported rebalance preview reference price basis")
        self._valuation_reader = CurrentRebalanceValuationReader(
            price_reader,
            reference_close_reader=reference_close_reader,
        )
        self._execution_evidence = RebalancePreviewExecutionEvidenceReader(
            identity_reader=identity_reader,
            classification_reader=classification_reader,
            fee_policy_reader=fee_policy_reader,
            quantity_rule_reader=quantity_rule_reader,
        )
        self._resource_snapshot_reader = resource_snapshot_reader
        self._position_rule_evaluator = position_rule_evaluator
        self._risk_policy_qualifier = risk_policy_qualifier
        self._risk_policy_account_source_reader = risk_policy_account_source_reader
        self._strategy_risk_source_reader = strategy_risk_source_reader
        self._reference_price_basis = reference_price_basis

    def build(
        self,
        *,
        account: SimulatedAccount,
        user_id: int,
        positions: tuple[Position, ...],
        checks: tuple[Mapping[str, object], ...],
        summary: Mapping[str, object],
        strategy_id: int | None,
        position_rule_id: int | None,
        strategy_name: str | None,
        strategy_type: str | None,
        strategy_version: int | None,
        rule_name: str | None,
        max_position_pct: Decimal | None,
        max_total_position_pct: Decimal | None,
        stop_loss_pct: Decimal | None,
        macro_regime: str,
        policy_gear: str,
        as_of: datetime,
        inspection_date: date,
        current_local_date: date,
        strategy_selection_state: StrategySelectionState = "unavailable",
        temporary_targets: TemporarySecurityTargets | None = None,
    ) -> RebalancePlanPreview:
        """Calculate supported target rows without persisting or submitting orders."""

        cutoff = normalize_cutoff(as_of)
        target_selection = resolve_rebalance_target_selection(
            strategy_selection_state=strategy_selection_state,
            strategy_id=strategy_id,
            position_rule_id=position_rule_id,
            strategy_name=strategy_name,
            strategy_type=strategy_type,
            strategy_version=strategy_version,
            rule_name=rule_name,
            max_position_pct=max_position_pct,
            max_total_position_pct=max_total_position_pct,
            stop_loss_pct=stop_loss_pct,
            temporary_targets=temporary_targets,
            checks=checks,
            summary=summary,
            positions=positions,
        )
        risk_policy_qualification = qualify_m1_risk_policy(
            risk_policy_qualifier=self._risk_policy_qualifier,
            account_source_reader=self._risk_policy_account_source_reader,
            strategy_source_reader=self._strategy_risk_source_reader,
            account=account,
            user_id=user_id,
            as_of=cutoff,
            strategy_id=strategy_id,
            position_rule_id=position_rule_id,
            strategy_name=strategy_name,
            strategy_type=strategy_type,
            strategy_version=strategy_version,
            max_position_pct=max_position_pct,
            max_total_position_pct=max_total_position_pct,
            stop_loss_pct=stop_loss_pct,
            strategy_selection_state=target_selection.strategy_selection_state,
        )
        risk_context = build_rebalance_plan_risk_context(
            summary=summary,
            strategy_id=strategy_id,
            position_rule_id=position_rule_id,
            strategy_name=strategy_name,
            strategy_type=strategy_type,
            strategy_version=strategy_version,
            rule_name=rule_name,
            max_position_pct=max_position_pct,
            max_total_position_pct=max_total_position_pct,
            stop_loss_pct=stop_loss_pct,
            strategy_selection_state=target_selection.strategy_selection_state,
            account_max_position_pct=_decimal_value(account.max_position_pct),
            account_max_total_position_pct=_decimal_value(account.max_total_position_pct),
            account_stop_loss_pct=_decimal_value(account.stop_loss_pct),
            risk_policy_qualification=risk_policy_qualification,
            macro_regime=macro_regime,
            policy_gear=policy_gear,
            reference_price_basis=self._reference_price_basis,
        )
        if target_selection.block_reason_code is not None:
            return empty_rebalance_plan_preview(
                cutoff,
                "blocked",
                target_selection.block_reason_code,
                risk_context,
            )
        if account.account_type is not AccountType.SIMULATED:
            return empty_rebalance_plan_preview(
                cutoff,
                "blocked",
                "ACCOUNT_NOT_SIMULATED",
                risk_context,
            )
        if type(user_id) is not int or user_id <= 0:
            return empty_rebalance_plan_preview(
                cutoff,
                "blocked",
                "OWNER_ID_INVALID",
                risk_context,
            )
        if inspection_date != current_local_date:
            return empty_rebalance_plan_preview(
                cutoff,
                "blocked",
                "HISTORICAL_INSPECTION_NOT_CURRENT_PLAN",
                risk_context,
            )

        resource_snapshot = self._resource_snapshot_reader.read_account_snapshot(
            account_id=account.account_id,
            user_id=user_id,
        )
        if resource_snapshot is None or resource_snapshot.owner_user_id != user_id:
            return empty_rebalance_plan_preview(
                cutoff,
                "blocked",
                "ACCOUNT_RESOURCE_SNAPSHOT_UNAVAILABLE",
                risk_context,
            )
        if not resource_snapshot_matches(
            requested_account=account,
            requested_positions=positions,
            snapshot=resource_snapshot,
        ):
            return empty_rebalance_plan_preview(
                cutoff,
                "blocked",
                "LEDGER_SNAPSHOT_CHANGED",
                risk_context,
                financial_snapshot_read_at=resource_snapshot.read_at,
            )
        account = resource_snapshot.account
        positions = resource_snapshot.positions
        ledger_cash, reserved_cash, available_cash = snapshot_cash_values(
            account=account,
            active_reservations=resource_snapshot.active_reservations,
        )

        position_by_code: dict[str, Position] = {}
        position_codes_valid = True
        for position in positions:
            if type(position) is not Position or position.account_id != account.account_id:
                position_codes_valid = False
                continue
            code = _normalized_code(position.asset_code)
            if code is None or code in position_by_code:
                position_codes_valid = False
                continue
            position_by_code[code] = position

        targets: dict[str, Mapping[str, object]] = {}
        allocation_checks: list[Mapping[str, object]] = []
        configuration_reasons: list[str] = []
        for check in checks:
            scope = check.get("scope")
            if scope == "asset_class":
                allocation_checks.append(check)
                continue
            if scope == "asset_target_configuration":
                configuration_reasons.extend(string_tuple(check.get("reason_codes")))
                continue
            if scope != "asset":
                continue
            code = _normalized_code(check.get("asset_code"))
            target_weight = _decimal_value(check.get("target_weight"))
            if code is None or target_weight is None or target_weight < 0:
                continue
            if code in targets:
                position_codes_valid = False
                continue
            targets[code] = check

        if configuration_reasons:
            return _blocked_preview(
                as_of=cutoff,
                financial_snapshot_read_at=resource_snapshot.read_at,
                reason_codes=tuple(dict.fromkeys(configuration_reasons)),
                risk_context=risk_context,
                allocation_items=(),
            )
        valuation = self._valuation_reader.read(
            asset_codes={position.asset_code for position in positions}
            | {str(check.get("asset_code") or "") for check in targets.values()},
            account=account,
            positions=positions,
            checks=checks,
            position_codes_valid=position_codes_valid,
            cutoff=cutoff,
            current_local_date=current_local_date,
            reference_price_basis=self._reference_price_basis,
        )
        price_results = valuation.prices
        price_reasons = valuation.price_reasons
        portfolio_value = valuation.portfolio_value
        class_amounts = valuation.class_amounts
        allocation_items = self._allocation_items(
            allocation_checks=allocation_checks,
            account=account,
            class_amounts=class_amounts,
            position_codes_valid=position_codes_valid,
            portfolio_value=portfolio_value,
        )
        if not targets:
            return RebalancePlanPreview(
                status="no_explicit_asset_targets",
                reason_codes=(
                    ("NO_POSITIONS", "NO_EXPLICIT_ASSET_TARGETS")
                    if not positions
                    else ("NO_EXPLICIT_ASSET_TARGETS",)
                ),
                as_of=cutoff,
                financial_snapshot_read_at=resource_snapshot.read_at,
                portfolio_value=portfolio_value,
                cash_before=ledger_cash,
                reserved_cash=reserved_cash,
                available_cash_before=available_cash,
                projected_cash_after_sells=available_cash,
                estimated_sell_gross=Decimal("0.00"),
                estimated_sell_fees=Decimal("0.00"),
                estimated_sell_net=Decimal("0.00"),
                estimated_buy_gross=Decimal("0.00"),
                estimated_buy_fees=Decimal("0.00"),
                estimated_buy_total=Decimal("0.00"),
                projected_cash_after_buys=available_cash,
                funding_status="known" if available_cash is not None else "unknown",
                sell_before_buy={
                    "required": False,
                    "sell_asset_codes": [],
                    "buy_asset_codes": [],
                    "sequence": "sell_then_buy",
                },
                risk_context=risk_context,
                allocation_items=allocation_items,
                asset_items=(),
            )
        items: list[RebalancePlanPreviewItem] = []
        for code, check in sorted(targets.items()):
            position_for_code = position_by_code.get(code)
            raw_asset_code = (
                position_for_code.asset_code
                if position_for_code is not None
                else str(check.get("asset_code") or "")
            )
            quote = price_results.get(code)
            items.append(
                self._asset_item(
                    account=account,
                    user_id=user_id,
                    position=position_for_code,
                    check=check,
                    asset_code=raw_asset_code,
                    quote=quote,
                    quote_reason=price_reasons.get(code),
                    portfolio_value=portfolio_value,
                    max_position_pct=risk_context.max_position_pct,
                    account_max_position_pct=risk_context.account_max_position_pct,
                    account_stop_loss_pct=risk_context.account_stop_loss_pct,
                    strategy_stop_loss_pct=risk_context.stop_loss_pct,
                    position_rule_id=position_rule_id,
                    active_reservations=resource_snapshot.active_reservations,
                    as_of=cutoff,
                    strategy_policy_applicability=(target_selection.strategy_policy_applicability),
                    target_mode=target_selection.target_mode,
                    price_publication=valuation.price_publications.get(code),
                )
            )

        projected_amount = projected_position_amount(
            positions=positions,
            targets=targets,
            items=items,
            prices=price_results,
            portfolio_value=portfolio_value,
            active_reservations=resource_snapshot.active_reservations,
        )
        projected_buy_amount_by_asset = projected_buy_position_amount_by_asset(
            items=items,
            active_reservations=resource_snapshot.active_reservations,
        )

        m1_stop_loss_observation = stop_loss_observation(
            positions=positions,
            prices=price_results,
        )

        return finish_rebalance_plan_preview(
            cutoff=cutoff,
            financial_snapshot_read_at=resource_snapshot.read_at,
            reason_codes=(),
            portfolio_value=portfolio_value,
            cash_before=ledger_cash,
            reserved_cash=reserved_cash,
            available_cash_before=available_cash,
            projected_position_amount=projected_amount,
            max_total_position_pct=risk_context.max_total_position_pct,
            account_max_total_position_pct=risk_context.account_max_total_position_pct,
            strategy_policy_applicability=target_selection.strategy_policy_applicability,
            allocation_items=allocation_items,
            items=items,
            risk_context=risk_context,
            risk_policy_qualification=risk_policy_qualification,
            m1_stop_loss_observation=m1_stop_loss_observation,
            projected_buy_position_amount_by_asset=projected_buy_amount_by_asset,
        )

    def _allocation_items(
        self,
        *,
        allocation_checks: list[Mapping[str, object]],
        account: SimulatedAccount,
        class_amounts: dict[str, Decimal | None],
        position_codes_valid: bool,
        portfolio_value: Decimal | None,
    ) -> tuple[RebalancePlanPreviewItem, ...]:
        """Keep asset-class recommendations as amounts with no synthetic units."""

        results: list[RebalancePlanPreviewItem] = []
        for check in allocation_checks:
            reasons: list[str] = []
            asset_class = _optional_text(check.get("asset_class")) or ""
            current_amount = class_amounts.get(asset_class)
            target_weight = _decimal_value(check.get("target_weight"))
            threshold = _decimal_value(check.get("drift_threshold"))
            if not position_codes_valid:
                reasons.append("POSITION_SNAPSHOT_INVALID")
            if portfolio_value is None:
                reasons.append("PORTFOLIO_VALUE_UNKNOWN")
            if not account.cash_known:
                reasons.append("CASH_BALANCE_UNKNOWN")
            if current_amount is None:
                reasons.append("ASSET_CLASS_VALUE_UNKNOWN")
            if target_weight is None or not Decimal("0") <= target_weight <= Decimal("1"):
                reasons.append("ASSET_CLASS_TARGET_WEIGHT_UNKNOWN")
            if threshold is None or threshold < 0:
                reasons.append("ASSET_CLASS_DRIFT_THRESHOLD_UNKNOWN")
            adjustment = calculate_amount_adjustment(
                current_amount=current_amount,
                portfolio_value=portfolio_value,
                target_weight=target_weight,
                drift_threshold=threshold,
            )
            if adjustment is None:
                reasons.append("ASSET_CLASS_ADJUSTMENT_UNAVAILABLE")
            results.append(
                RebalancePlanPreviewItem(
                    scope="asset_class",
                    action=(
                        adjustment.action
                        if adjustment is not None and adjustment.action is not None and not reasons
                        else "blocked"
                    ),
                    asset_code=str(check.get("asset_code") or ""),
                    asset_name=str(check.get("asset_name") or ""),
                    asset_type=None,
                    currency_unit=None,
                    quantity_unit="unknown",
                    current_weight=adjustment.current_weight if adjustment is not None else None,
                    target_weight=target_weight,
                    portfolio_value=portfolio_value,
                    current_amount=current_amount,
                    target_amount=adjustment.target_amount if adjustment is not None else None,
                    suggested_amount=(
                        adjustment.suggested_amount if adjustment is not None else None
                    ),
                    actionable_amount=None,
                    current_quantity=None,
                    target_quantity=None,
                    suggested_quantity=None,
                    actionable_quantity=None,
                    remaining_quantity=None,
                    sellable_quantity=None,
                    reference_price=None,
                    price_source=None,
                    price_as_of=None,
                    price_freshness=None,
                    price_is_fallback=None,
                    price_observed_at=None,
                    identity=None,
                    fee=None,
                    drift_threshold=threshold,
                    risk_rule_result=None,
                    risk_rule_reason_code=None,
                    risk_rule_entry_price_basis=None,
                    status="amount_only" if not reasons else "blocked",
                    reason_codes=tuple(reasons),
                )
            )
        return tuple(results)

    def _asset_item(
        self,
        *,
        account: SimulatedAccount,
        user_id: int,
        position: Position | None,
        check: Mapping[str, object],
        asset_code: str,
        quote: MarketPriceResult | None,
        quote_reason: str | None,
        portfolio_value: Decimal | None,
        max_position_pct: Decimal | None,
        account_max_position_pct: Decimal | None,
        account_stop_loss_pct: Decimal | None,
        strategy_stop_loss_pct: Decimal | None,
        position_rule_id: int | None,
        active_reservations: tuple[ActiveRebalanceReservation, ...],
        as_of: datetime,
        strategy_policy_applicability: StrategyPolicyApplicability,
        target_mode: TargetMode,
        price_publication: PricePublicationReference | None,
    ) -> RebalancePlanPreviewItem:
        """Build one asset row and leave action quantities unavailable on missing evidence."""

        reasons: list[str] = []
        if target_mode == "user_target_difference":
            risk_rule_result, risk_reason_code, risk_entry_price_basis = None, None, None
            if strategy_policy_applicability != "not_applicable":
                reasons.append("STRATEGY_POLICY_APPLICABILITY_MISMATCH")
        elif strategy_policy_applicability == "applicable":
            risk_rule_result, risk_reason_code, risk_entry_price_basis = (
                evaluate_current_position_rule(
                    evaluator=self._position_rule_evaluator,
                    position_rule_id=position_rule_id,
                    position=position,
                    price=_price_decimal(quote),
                    portfolio_value=portfolio_value,
                )
            )
        else:
            risk_rule_result, risk_reason_code, risk_entry_price_basis = None, None, None
            reasons.append("STRATEGY_POLICY_APPLICABILITY_UNKNOWN")
        target_weight = _decimal_value(check.get("target_weight"))
        if target_weight is None or target_weight < 0:
            reasons.append("TARGET_WEIGHT_INVALID")
        price = _price_decimal(quote)
        if quote is None or price is None:
            reasons.append(quote_reason or "QUOTE_UNAVAILABLE")
        if portfolio_value is None:
            reasons.append("PORTFOLIO_VALUE_UNKNOWN")
        asset_type = position.asset_type if position is not None else None
        current_quantity = (
            _decimal_value(position.quantity) if position is not None else Decimal("0")
        )
        if current_quantity is None or current_quantity < 0:
            reasons.append("POSITION_QUANTITY_INVALID")
            current_quantity = None
        sellable_quantity = (
            _decimal_value(position.available_quantity)
            if position is not None and position.available_quantity_known is True
            else None
        )
        normalized_asset_code = _normalized_code(asset_code)
        matching_reservations = tuple(
            row
            for row in active_reservations
            if _normalized_code(row.asset_code) == normalized_asset_code
        )
        matching_sell_reservations = tuple(
            row for row in matching_reservations if row.side == "sell"
        )
        reserved_sell_quantity = sum(
            (row.remaining_shares for row in matching_sell_reservations),
            Decimal("0.000000"),
        )
        if sellable_quantity is not None:
            sellable_quantity -= reserved_sell_quantity
            if sellable_quantity < 0:
                reasons.append("ACTIVE_SELL_RESERVATION_EXCEEDS_SELLABLE")
                sellable_quantity = None
        reservation_security_ids = {row.security_id for row in matching_reservations}
        if position is not None and position.account_id != account.account_id:
            reasons.append("POSITION_ACCOUNT_MISMATCH")

        threshold_key = (
            "strategy_drift_threshold"
            if check.get("temporary_target_source") == "user_entered_temporary"
            and target_mode == "strategy_rule"
            else "drift_threshold"
        )
        threshold = (
            None
            if target_mode == "user_target_difference"
            else _decimal_value(check.get(threshold_key))
        )
        if target_mode == "user_target_difference":
            adjustment = calculate_user_target_difference(
                current_quantity=current_quantity,
                reference_price=price,
                portfolio_value=portfolio_value,
                target_weight=target_weight,
            )
        else:
            if threshold is None or threshold < 0:
                reasons.append("DRIFT_THRESHOLD_INVALID")
            adjustment = calculate_asset_adjustment(
                current_quantity=current_quantity,
                reference_price=price,
                portfolio_value=portfolio_value,
                target_weight=target_weight,
                drift_threshold=threshold,
            )
        if adjustment is None:
            reasons.append("REBALANCE_INPUT_INVALID")
            current_amount = None
            current_weight = None
            target_amount = None
            target_quantity = None
            suggested_amount = None
            suggested_quantity = None
            action = "blocked"
        else:
            current_amount = adjustment.current_amount
            current_weight = adjustment.current_weight
            target_amount = adjustment.target_amount
            target_quantity = adjustment.target_quantity
            suggested_amount = adjustment.suggested_amount
            suggested_quantity = adjustment.suggested_quantity
            action = adjustment.action or "blocked"
            if risk_reason_code is not None and action in {"buy", "sell"}:
                reasons.append(risk_reason_code)
            if risk_rule_result is not None and action == "buy":
                if risk_rule_result.get("should_buy") is not True:
                    reasons.append("POSITION_RULE_BUY_NOT_TRIGGERED")
            if risk_rule_result is not None and action == "sell":
                if risk_rule_result.get("should_sell") is not True:
                    reasons.append("POSITION_RULE_SELL_NOT_TRIGGERED")
            has_positive_holding = current_quantity is not None and current_quantity > 0
            stop_loss_reason = account_stop_loss_reason(
                action=action,
                current_price=price,
                average_cost=(
                    _decimal_value(position.avg_cost)
                    if position is not None
                    and has_positive_holding
                    and position.cost_basis_known is True
                    else None
                ),
                stop_loss_pct=(
                    account_stop_loss_pct if position is not None and has_positive_holding else None
                ),
            )
            if stop_loss_reason is not None:
                reasons.append(stop_loss_reason)
            strategy_stop_reason = (
                strategy_stop_loss_reason(
                    action=action,
                    current_price=price,
                    average_cost=(
                        _decimal_value(position.avg_cost)
                        if position is not None
                        and has_positive_holding
                        and position.cost_basis_known is True
                        else None
                    ),
                    stop_loss_pct=(
                        strategy_stop_loss_pct
                        if position is not None and has_positive_holding
                        else None
                    ),
                )
                if strategy_policy_applicability == "applicable"
                else None
            )
            if strategy_stop_reason is not None:
                reasons.append(strategy_stop_reason)
            asset_active_buy_notional = (
                active_buy_notional_for_asset(
                    asset_code=asset_code,
                    active_reservations=active_reservations,
                )
                if action == "buy"
                else Decimal("0.00")
            )
            cap_reason = (
                strategy_position_cap_reason(
                    action=action,
                    target_weight=target_weight,
                    max_position_pct=max_position_pct,
                    active_buy_notional=asset_active_buy_notional,
                    portfolio_value=portfolio_value,
                )
                if strategy_policy_applicability == "applicable"
                else None
            )
            if cap_reason is not None:
                reasons.append(cap_reason)
            account_cap_reason = account_position_cap_reason(
                action=action,
                target_weight=target_weight,
                max_position_pct=account_max_position_pct,
                active_buy_notional=asset_active_buy_notional,
                portfolio_value=portfolio_value,
            )
            if account_cap_reason is not None:
                reasons.append(account_cap_reason)
            if portfolio_value is None and target_weight == Decimal("0") and action == "sell":
                reasons = [reason for reason in reasons if reason != "PORTFOLIO_VALUE_UNKNOWN"]
            if action == "hold" and not reasons:
                return RebalancePlanPreviewItem(
                    scope="asset",
                    action="hold",
                    asset_code=asset_code,
                    asset_name=str(check.get("asset_name") or asset_code),
                    asset_type=asset_type,
                    currency_unit=None,
                    quantity_unit=quantity_unit(asset_type),
                    current_weight=current_weight,
                    target_weight=target_weight,
                    portfolio_value=portfolio_value,
                    current_amount=current_amount,
                    target_amount=target_amount,
                    suggested_amount=Decimal("0.00"),
                    actionable_amount=Decimal("0.00"),
                    current_quantity=current_quantity,
                    target_quantity=target_quantity,
                    suggested_quantity=Decimal("0.000000"),
                    actionable_quantity=Decimal("0.000000"),
                    remaining_quantity=Decimal("0.000000"),
                    sellable_quantity=sellable_quantity,
                    reference_price=price,
                    price_source=quote.source if quote is not None else None,
                    price_as_of=quote.as_of if quote is not None else None,
                    price_freshness=quote.freshness if quote is not None else None,
                    price_is_fallback=quote.is_fallback if quote is not None else None,
                    price_observed_at=quote.observed_at if quote is not None else None,
                    identity=None,
                    fee=None,
                    drift_threshold=threshold,
                    risk_rule_result=risk_rule_result,
                    risk_rule_reason_code=risk_reason_code,
                    risk_rule_entry_price_basis=risk_entry_price_basis,
                    status="no_rebalance_required",
                    reason_codes=tuple(reasons),
                    reserved_sell_quantity=reserved_sell_quantity,
                    target_mode=target_mode,
                    price_publication=price_publication,
                )
            if action == "hold":
                action = "blocked"

        if action == "sell" and position is not None:
            if position.available_quantity_known is not True:
                reasons.append("SELLABLE_QUANTITY_UNKNOWN")
        if action == "sell" and position is None:
            reasons.append("SELL_POSITION_MISSING")

        actionable_quantity: Decimal | None = None
        remaining_quantity: Decimal | None = suggested_quantity
        identity_payload: dict[str, object] | None = None
        classification_evidence: dict[str, object] | None = None
        fee_payload: dict[str, object] | None = None
        quantity_rule_payload: dict[str, object] | None = None
        if action in {"buy", "sell"}:
            identity_payload = self._execution_evidence.read_identity(
                asset_code=asset_code,
                as_of=as_of,
            )
            if identity_payload is None:
                reasons.append("CURRENT_IDENTITY_UNAVAILABLE")
            elif position is None and action == "buy":
                asset_type, classification_evidence = (
                    self._execution_evidence.read_asset_type_classification(
                        identity=identity_payload,
                        asset_code=asset_code,
                        as_of=as_of,
                    )
                )
                if asset_type is None:
                    reasons.append("ASSET_TYPE_CLASSIFICATION_UNAVAILABLE")
        if action in {"buy", "sell"} and (type(asset_type) is not str or not asset_type.strip()):
            reasons.append("ASSET_TYPE_UNKNOWN")
        if type(asset_type) is str and asset_type.strip() and action in {"buy", "sell"}:
            if identity_payload is not None:
                identity_security_id = identity_payload.get("security_id")
                if reservation_security_ids and (
                    len(reservation_security_ids) != 1
                    or identity_security_id not in reservation_security_ids
                ):
                    reasons.append("ACTIVE_RESERVATION_IDENTITY_CONFLICT")
                execution_rule, quantity_rule_payload = self._execution_evidence.read_quantity_rule(
                    identity=identity_payload,
                    as_of=as_of,
                )
                if execution_rule is None:
                    reasons.append("EXECUTION_QUANTITY_RULE_UNAVAILABLE")
                elif suggested_quantity is None or suggested_quantity <= 0:
                    reasons.append("SUGGESTED_QUANTITY_UNKNOWN")
                elif action == "buy":
                    constrained = constrain_buy_quantity(
                        desired_quantity=suggested_quantity,
                        minimum=execution_rule.buy_quantity.minimum,
                        step=execution_rule.buy_quantity.step,
                        maximum=execution_rule.buy_quantity.maximum,
                    )
                    actionable_quantity = constrained.quantity
                    remaining_quantity = constrained.remaining_quantity
                    if constrained.reason_code is not None:
                        reasons.append(constrained.reason_code)
                elif action == "sell":
                    if position is None or position.available_quantity_known is not True:
                        reasons.append("SELLABLE_QUANTITY_UNKNOWN")
                    elif (
                        sellable_quantity is None
                        or sellable_quantity < 0
                        or current_quantity is None
                        or sellable_quantity > current_quantity
                    ):
                        reasons.append("SELLABLE_QUANTITY_INVALID")
                    else:
                        constrained = constrain_sell_quantity(
                            desired_quantity=suggested_quantity,
                            sellable_quantity=sellable_quantity,
                            current_quantity=current_quantity,
                            minimum=execution_rule.sell_quantity.minimum,
                            step=execution_rule.sell_quantity.step,
                            maximum=execution_rule.sell_quantity.maximum,
                            odd_lot_mode=execution_rule.sell_odd_lot_mode.value,
                        )
                        actionable_quantity = constrained.quantity
                        remaining_quantity = constrained.remaining_quantity
                        if constrained.reason_code is not None:
                            reasons.append(constrained.reason_code)
                        if (
                            actionable_quantity is not None
                            and actionable_quantity < suggested_quantity
                            and sellable_quantity < suggested_quantity
                        ):
                            reasons.append("SELLABLE_QUANTITY_PARTIAL")

            nonblocking_reasons = {
                "SELLABLE_QUANTITY_PARTIAL",
                "BUY_QUANTITY_MAXIMUM_LIMITED",
                "SELL_QUANTITY_LIMITED_BY_RULE",
            }
            if action == "sell":
                nonblocking_reasons.add("STRATEGY_MAX_POSITION_LIMIT_EXCEEDED")
            if (
                identity_payload is not None
                and actionable_quantity is not None
                and actionable_quantity > 0
                and price is not None
                and not any(reason not in nonblocking_reasons for reason in reasons)
            ):
                notional = round_cny_amount(actionable_quantity * price)
                if notional is None or notional <= 0:
                    reasons.append("ACTIONABLE_NOTIONAL_INVALID")
                else:
                    fee_payload = self._execution_evidence.estimate_fee(
                        account_id=account.account_id,
                        user_id=user_id,
                        asset_type=asset_type,
                        identity=identity_payload,
                        action=action,
                        notional=notional,
                        as_of=as_of,
                    )
                if notional is not None and notional > 0 and fee_payload is None:
                    reasons.append("FEE_POLICY_UNAVAILABLE")
        elif action in {"buy", "sell"}:
            reasons.append("ASSET_TYPE_UNKNOWN")

        if action in {"buy", "sell"} and fee_payload is None:
            actionable_quantity = None
            if remaining_quantity is None:
                remaining_quantity = suggested_quantity
        actionable_amount = (
            round_cny_amount(actionable_quantity * price)
            if actionable_quantity is not None and price is not None
            else None
        )
        nonblocking_reasons = {
            "SELLABLE_QUANTITY_PARTIAL",
            "BUY_QUANTITY_MAXIMUM_LIMITED",
            "SELL_QUANTITY_LIMITED_BY_RULE",
        }
        if action == "sell":
            nonblocking_reasons.add("STRATEGY_MAX_POSITION_LIMIT_EXCEEDED")
            nonblocking_reasons.add("ACCOUNT_MAX_POSITION_LIMIT_EXCEEDED")
        blocking_reasons = tuple(reason for reason in reasons if reason not in nonblocking_reasons)
        if blocking_reasons:
            status = "blocked"
        elif (
            remaining_quantity is not None and remaining_quantity > 0
        ) or "SELLABLE_QUANTITY_PARTIAL" in reasons:
            status = "partial"
        else:
            status = "ready"

        if blocking_reasons:
            actionable_quantity = None
            actionable_amount = None
            remaining_quantity = suggested_quantity

        return RebalancePlanPreviewItem(
            scope="asset",
            action=action,
            asset_code=asset_code,
            asset_name=str(check.get("asset_name") or asset_code),
            asset_type=asset_type,
            currency_unit=None,
            quantity_unit=quantity_unit(asset_type),
            current_weight=current_weight,
            target_weight=target_weight,
            portfolio_value=portfolio_value,
            current_amount=current_amount,
            target_amount=target_amount,
            suggested_amount=suggested_amount,
            actionable_amount=actionable_amount,
            current_quantity=current_quantity,
            target_quantity=target_quantity,
            suggested_quantity=suggested_quantity,
            actionable_quantity=actionable_quantity,
            remaining_quantity=remaining_quantity,
            sellable_quantity=sellable_quantity,
            reference_price=price,
            price_source=quote.source if quote is not None else None,
            price_as_of=quote.as_of if quote is not None else None,
            price_freshness=quote.freshness if quote is not None else None,
            price_is_fallback=quote.is_fallback if quote is not None else None,
            price_observed_at=quote.observed_at if quote is not None else None,
            identity=identity_payload,
            fee=fee_payload,
            drift_threshold=threshold,
            risk_rule_result=risk_rule_result,
            risk_rule_reason_code=risk_reason_code,
            risk_rule_entry_price_basis=risk_entry_price_basis,
            status=status,
            reason_codes=tuple(dict.fromkeys(reasons)),
            quantity_rule=quantity_rule_payload,
            reserved_sell_quantity=reserved_sell_quantity,
            classification_evidence=classification_evidence,
            target_mode=target_mode,
            price_publication=price_publication,
        )


def _blocked_preview(
    *,
    as_of: datetime,
    financial_snapshot_read_at: datetime | None = None,
    reason_codes: tuple[str, ...],
    risk_context: RebalancePlanRiskContext,
    allocation_items: tuple[RebalancePlanPreviewItem, ...],
) -> RebalancePlanPreview:
    """Keep invalid target configuration visible without inventing asset rows."""

    return RebalancePlanPreview(
        status="blocked",
        reason_codes=reason_codes,
        as_of=as_of,
        financial_snapshot_read_at=financial_snapshot_read_at,
        portfolio_value=None,
        cash_before=None,
        reserved_cash=None,
        available_cash_before=None,
        projected_cash_after_sells=None,
        estimated_sell_gross=None,
        estimated_sell_fees=None,
        estimated_sell_net=None,
        estimated_buy_gross=None,
        estimated_buy_fees=None,
        estimated_buy_total=None,
        projected_cash_after_buys=None,
        funding_status="unknown",
        sell_before_buy={
            "required": False,
            "sell_asset_codes": [],
            "buy_asset_codes": [],
            "sequence": "sell_then_buy",
        },
        risk_context=risk_context,
        allocation_items=allocation_items,
        asset_items=(),
    )


__all__: tuple[str, ...] = (
    "ReadOnlyRebalancePlanPreviewBuilder",
    "RebalancePlanPreview",
    "RebalancePlanPreviewItem",
)
