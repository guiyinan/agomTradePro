"""Runtime M1 risk observations, qualification defaults, and BUY fail-closed gate."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.risk_center.application.m1_rebalance_risk_policy import (
    GetM1RiskPolicyQualificationUseCase,
    M1RiskPolicyQualification,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskFalsification,
    M1RiskObservation,
    RiskApplicability,
    RiskQualificationState,
    evaluate_falsification,
)
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    M1RiskPolicyAccountSourceReader,
    StrategyM1RiskSourceReader,
    build_m1_risk_source_snapshot,
    unknown_m1_risk_source_snapshot,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreviewItem,
)
from apps.simulated_trading.application.rebalance_preview_valuation import (
    _decimal_value,
    _normalized_code,
    _price_decimal,
)
from apps.simulated_trading.domain.entities import Position, SimulatedAccount
from apps.strategy.application.execution_gateway import StrategySelectionState


def unavailable_m1_risk_qualification(reason_code: str) -> M1RiskPolicyQualification:
    """Create an explicit missing-read-port result for local/legacy builders."""

    return M1RiskPolicyQualification(
        state=RiskQualificationState.MISSING,
        reason_codes=(reason_code,),
        revision=None,
    )


def qualify_m1_risk_policy(
    *,
    risk_policy_qualifier: GetM1RiskPolicyQualificationUseCase | None,
    account_source_reader: M1RiskPolicyAccountSourceReader | None,
    strategy_source_reader: StrategyM1RiskSourceReader | None,
    account: SimulatedAccount,
    user_id: int,
    as_of: datetime,
    strategy_id: int | None,
    position_rule_id: int | None,
    strategy_name: str | None,
    strategy_type: str | None,
    strategy_version: int | None,
    max_position_pct: Decimal | None,
    max_total_position_pct: Decimal | None,
    stop_loss_pct: Decimal | None,
    strategy_selection_state: StrategySelectionState,
) -> M1RiskPolicyQualification:
    """Read and revalidate the active revision against each live owner source."""

    if (
        risk_policy_qualifier is None
        or account_source_reader is None
        or strategy_source_reader is None
    ):
        return unavailable_m1_risk_qualification("M1_RISK_POLICY_READ_PORT_UNAVAILABLE")
    account_source = account_source_reader.read_owner_source(account_id=account.account_id)
    if account_source is None or account_source.account_id != account.account_id:
        source_snapshot = unknown_m1_risk_source_snapshot(account_id=account.account_id)
        qualification = risk_policy_qualifier.execute(
            account_id=account.account_id,
            as_of=as_of,
            current_source=source_snapshot,
        )
        return M1RiskPolicyQualification(
            state=RiskQualificationState.UNKNOWN,
            reason_codes=("M1_RISK_ACCOUNT_SOURCE_UNKNOWN",),
            revision=qualification.revision,
        )
    if account_source.owner_user_id != user_id or account_source.is_active is not True:
        source_snapshot = unknown_m1_risk_source_snapshot(account_id=account.account_id)
        qualification = risk_policy_qualifier.execute(
            account_id=account.account_id,
            as_of=as_of,
            current_source=source_snapshot,
        )
        return M1RiskPolicyQualification(
            state=RiskQualificationState.UNKNOWN,
            reason_codes=("M1_RISK_ACCOUNT_OWNER_SOURCE_MISMATCH",),
            revision=qualification.revision,
        )
    strategy_selection = strategy_source_reader.get_owner_inspection_selection(
        account.account_id,
        user_id,
        strategy_id,
    )
    source_snapshot = build_m1_risk_source_snapshot(
        account_source=account_source,
        strategy_selection=strategy_selection,
    )
    qualification = risk_policy_qualifier.execute(
        account_id=account.account_id,
        as_of=as_of,
        current_source=source_snapshot,
    )
    strategy_source_matches = (
        strategy_selection.validated_selection_state == strategy_selection_state
        and strategy_selection.strategy_id == strategy_id
        and strategy_selection.position_rule_id == position_rule_id
        and strategy_selection.strategy_name == strategy_name
        and strategy_selection.strategy_type == strategy_type
        and strategy_selection.strategy_version == strategy_version
        and _decimal_value(strategy_selection.max_position_pct) == max_position_pct
        and _decimal_value(strategy_selection.max_total_position_pct) == max_total_position_pct
        and _decimal_value(strategy_selection.stop_loss_pct) == stop_loss_pct
    )
    account_source_matches = (
        account_source.account_type == "simulated"
        and account_source.max_single_position_pct == _decimal_value(account.max_position_pct)
        and account_source.max_total_position_pct == _decimal_value(account.max_total_position_pct)
        and account_source.stop_loss_pct == _decimal_value(account.stop_loss_pct)
    )
    if not strategy_source_matches or not account_source_matches:
        return M1RiskPolicyQualification(
            state=RiskQualificationState.SOURCE_CHANGED,
            reason_codes=("M1_RISK_POLICY_SOURCE_DIFFERS_FROM_PREVIEW",),
            revision=qualification.revision,
        )
    return qualification


def stop_loss_observation(
    *,
    positions: tuple[Position, ...],
    prices: dict[str, MarketPriceResult | None],
) -> M1RiskObservation:
    """Measure the largest current drawdown only from known held cost bases."""

    quantities = tuple(_decimal_value(position.quantity) for position in positions)
    if any(quantity is None or quantity < 0 for quantity in quantities):
        return M1RiskObservation(
            dimension="max_stop_loss",
            applicability=RiskApplicability.UNKNOWN,
            observed_pct=None,
        )
    held_positions = tuple(
        position
        for position, quantity in zip(positions, quantities, strict=True)
        if quantity is not None and quantity > 0
    )
    if not held_positions:
        return M1RiskObservation(
            dimension="max_stop_loss",
            applicability=RiskApplicability.NOT_APPLICABLE,
            observed_pct=None,
        )
    observed_losses: list[Decimal] = []
    for position in held_positions:
        if position.cost_basis_known is not True:
            return M1RiskObservation(
                dimension="max_stop_loss",
                applicability=RiskApplicability.UNKNOWN,
                observed_pct=None,
            )
        average_cost = _decimal_value(position.avg_cost)
        quote = prices.get(_normalized_code(position.asset_code) or "")
        current_price = _price_decimal(quote)
        if average_cost is None or average_cost <= 0 or current_price is None:
            return M1RiskObservation(
                dimension="max_stop_loss",
                applicability=RiskApplicability.UNKNOWN,
                observed_pct=None,
            )
        loss_pct = max(
            Decimal("0"),
            (average_cost - current_price) * Decimal("100") / average_cost,
        )
        observed_losses.append(loss_pct)
    return M1RiskObservation(
        dimension="max_stop_loss",
        applicability=RiskApplicability.APPLICABLE,
        observed_pct=max(observed_losses),
    )


def single_position_observation(
    *,
    items: tuple[RebalancePlanPreviewItem, ...],
    projected_position_pct_by_asset: Mapping[str, Decimal] | None,
) -> M1RiskObservation:
    """Measure every BUY security from the final projected same-security exposure.

    The caller supplies current holdings plus accepted open-BUY reservations and
    this preview's proposed notional, all valued against the same portfolio
    snapshot.  Missing or malformed projections remain UNKNOWN; a target row
    alone cannot stand in for the final same-security exposure.
    """

    buy_items = tuple(item for item in items if item.scope == "asset" and item.action == "buy")
    if not buy_items:
        return M1RiskObservation(
            dimension="max_single_position",
            applicability=RiskApplicability.NOT_APPLICABLE,
            observed_pct=None,
        )
    if projected_position_pct_by_asset is None:
        return M1RiskObservation(
            dimension="max_single_position",
            applicability=RiskApplicability.UNKNOWN,
            observed_pct=None,
        )
    projected_pcts: list[Decimal] = []
    for item in buy_items:
        code = _normalized_code(item.asset_code)
        projected_pct = projected_position_pct_by_asset.get(code or "")
        if (
            projected_pct is None
            or type(projected_pct) is not Decimal
            or not projected_pct.is_finite()
            or projected_pct < Decimal("0")
        ):
            return M1RiskObservation(
                dimension="max_single_position",
                applicability=RiskApplicability.UNKNOWN,
                observed_pct=None,
            )
        projected_pcts.append(projected_pct)
    return M1RiskObservation(
        dimension="max_single_position",
        applicability=RiskApplicability.APPLICABLE,
        observed_pct=max(projected_pcts),
    )


def projected_buy_position_percentages(
    *,
    projected_buy_position_amount_by_asset: Mapping[str, Decimal] | None,
    projected_equity: Decimal | None,
) -> dict[str, Decimal]:
    """Use the same known post-fee equity denominator as total-position risk."""

    if (
        projected_buy_position_amount_by_asset is None
        or type(projected_equity) is not Decimal
        or not projected_equity.is_finite()
        or projected_equity <= 0
    ):
        return {}
    projections: dict[str, Decimal] = {}
    seen_codes: set[str] = set()
    for raw_code, amount in projected_buy_position_amount_by_asset.items():
        code = _normalized_code(raw_code)
        if code is None or code in seen_codes:
            if code is not None:
                projections.pop(code, None)
                seen_codes.add(code)
            continue
        seen_codes.add(code)
        if type(amount) is not Decimal or not amount.is_finite() or amount < 0:
            continue
        try:
            observed_pct = amount * Decimal("100") / projected_equity
        except (ArithmeticError, TypeError, ValueError):
            continue
        if observed_pct.is_finite() and observed_pct >= 0:
            projections[code] = observed_pct
    return projections


def total_position_observation(
    *,
    has_buy: bool,
    projected_position_amount: Decimal | None,
    projected_equity: Decimal | None,
) -> M1RiskObservation:
    """Measure projected total position percentage with fees included in equity."""

    if not has_buy:
        return M1RiskObservation(
            dimension="max_total_position",
            applicability=RiskApplicability.NOT_APPLICABLE,
            observed_pct=None,
        )
    if projected_position_amount is None or projected_equity is None or projected_equity <= 0:
        return M1RiskObservation(
            dimension="max_total_position",
            applicability=RiskApplicability.UNKNOWN,
            observed_pct=None,
        )
    return M1RiskObservation(
        dimension="max_total_position",
        applicability=RiskApplicability.APPLICABLE,
        observed_pct=projected_position_amount * Decimal("100") / projected_equity,
    )


def build_m1_risk_falsification(
    *,
    qualification: M1RiskPolicyQualification,
    observations: tuple[M1RiskObservation, ...],
) -> M1RiskFalsification:
    """Evaluate the exact revision predicates against current typed observations."""

    return evaluate_falsification(qualification=qualification, observations=observations)


def block_buys_for_m1_risk(
    *,
    items: list[RebalancePlanPreviewItem],
    qualification: M1RiskPolicyQualification,
    falsification: M1RiskFalsification,
) -> list[RebalancePlanPreviewItem]:
    """Clear BUY action quantities whenever a version, source, or test is unknown."""

    reasons = list(qualification.reason_codes)
    if falsification.status == "falsified":
        reasons.append("M1_RISK_FALSIFICATION_TRIGGERED")
    elif falsification.status == "unknown":
        reasons.append("M1_RISK_FALSIFICATION_UNKNOWN")
    elif falsification.status == "not_applicable":
        reasons.append("M1_RISK_POLICY_HAS_NO_APPLICABLE_BUY_OBSERVATION")
    if not qualification.ready_for_buy:
        reasons.append("M1_RISK_POLICY_NOT_QUALIFIED")
    if not reasons:
        return items
    stable_reasons = tuple(dict.fromkeys(reasons))
    return [
        (
            replace(
                item,
                actionable_amount=None,
                actionable_quantity=None,
                remaining_quantity=item.suggested_quantity,
                status="blocked",
                reason_codes=tuple(dict.fromkeys((*item.reason_codes, *stable_reasons))),
            )
            if item.scope == "asset" and item.action == "buy"
            else item
        )
        for item in items
    ]


def m1_risk_falsification_payload(
    evidence: M1RiskFalsification | None,
) -> dict[str, object] | None:
    """Serialize versioned conditions and observed results without inventing fields."""

    if evidence is None:
        return None
    return {
        "risk_policy_version": evidence.risk_policy_version,
        "effective_from": (
            evidence.effective_from.isoformat() if evidence.effective_from is not None else None
        ),
        "effective_until": (
            evidence.effective_until.isoformat() if evidence.effective_until is not None else None
        ),
        "known_at": evidence.known_at.isoformat() if evidence.known_at is not None else None,
        "revoked_at": evidence.revoked_at.isoformat() if evidence.revoked_at is not None else None,
        "status": evidence.status,
        "reason_codes": list(evidence.reason_codes),
        "conditions": [
            {
                "dimension": condition.dimension,
                "policy_applicability": condition.policy_applicability.value,
                "observation_applicability": condition.observation_applicability.value,
                "predicate": condition.predicate,
                "threshold_pct": (
                    str(condition.threshold_pct) if condition.threshold_pct is not None else None
                ),
                "observed_pct": (
                    str(condition.observed_pct) if condition.observed_pct is not None else None
                ),
                "outcome": condition.outcome.value,
            }
            for condition in evidence.conditions
        ],
    }


__all__: tuple[str, ...] = (
    "block_buys_for_m1_risk",
    "build_m1_risk_falsification",
    "m1_risk_falsification_payload",
    "projected_buy_position_percentages",
    "single_position_observation",
    "stop_loss_observation",
    "total_position_observation",
    "unavailable_m1_risk_qualification",
)
