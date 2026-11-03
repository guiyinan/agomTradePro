"""Read-only simulated portfolio risk projection and explained assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload
from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
)
from apps.risk_center.application.portfolio_risk_report import (
    build_portfolio_risk_report,
)
from apps.risk_center.domain.portfolio_capacity import (
    CapacityOrderUsage,
    CapacityUsageSnapshot,
    CapacityValue,
    PortfolioCapacityDecision,
    evaluate_portfolio_capacity,
)
from apps.risk_center.domain.portfolio_exposure import assess_portfolio_industry_exposure
from apps.risk_center.domain.portfolio_exposure_types import (
    PortfolioExposureProjection,
    PortfolioIndustryExposureAssessment,
    PortfolioRiskAsset,
)
from apps.risk_center.domain.portfolio_risk_snapshot import (
    AccountSnapshot,
    ExecutedUsage,
    HeldPosition,
    OpenOrder,
    ProposedOrder,
    exact_decimal_product,
    exact_decimal_sum,
    project_gross_asset_exposure,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)


@dataclass(frozen=True, slots=True)
class PortfolioRiskAssessmentResult:
    """Typed result with the read-only report and underlying domain assessments."""

    report_payload: PortfolioRiskReportPayload
    exposure_projection: PortfolioExposureProjection | None
    industry_assessment: PortfolioIndustryExposureAssessment | None
    capacity_decisions: tuple[PortfolioCapacityDecision, ...]
    all_source_evidence: tuple[PortfolioRiskSourceEvidence, ...]
    reason_codes: tuple[str, ...]


def assess_simulated_portfolio_risk(
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    policy: PortfolioRiskPolicyBundle | None,
    asset_inputs: PortfolioRiskAssetsReadResult,
    as_of: datetime,
    business_date: date,
    capacity_requested_purpose: str,
) -> PortfolioRiskAssessmentResult:
    """Build a fail-closed simulation-only report from exact account and source facts.

    The pre-trade NAV contains only actual cash and settled holdings. Projected
    exposure adds every active and proposed BUY at its larger accepted/current
    notional, while SELLs remain gross until the simulated ledger settles them.
    Capacity is evaluated separately from exposure and keeps execution session,
    active BUY/SELL reservations, and proposals gross and source-qualified.
    """

    if type(snapshot) is not AccountSnapshot:
        raise TypeError("snapshot must be AccountSnapshot")
    if type(proposals) is not tuple or any(type(item) is not ProposedOrder for item in proposals):
        raise TypeError("proposals must be a tuple of ProposedOrder")
    if policy is not None and type(policy) is not PortfolioRiskPolicyBundle:
        raise TypeError("policy must be PortfolioRiskPolicyBundle or None")
    if type(asset_inputs) is not PortfolioRiskAssetsReadResult:
        raise TypeError("asset_inputs must be PortfolioRiskAssetsReadResult")
    _require_aware(as_of, "as_of")
    if type(business_date) is not date:
        raise TypeError("business_date must be a date")
    _require_token(capacity_requested_purpose, "capacity_requested_purpose")

    evidence = _collect_source_evidence(asset_inputs)
    scope_reasons = _scope_reasons(
        snapshot=snapshot,
        proposals=proposals,
        policy=policy,
        asset_inputs=asset_inputs,
        as_of=as_of,
        business_date=business_date,
    )
    identity_basis, resolved_assets, identity_reasons = _resolve_asset_inputs(
        snapshot=snapshot,
        proposals=proposals,
        policy=policy,
        asset_inputs=asset_inputs,
    )
    scope_reasons.extend(identity_reasons)
    code_reasons: list[str] = []
    projection: PortfolioExposureProjection | None = None
    industry: PortfolioIndustryExposureAssessment | None = None
    pre_trade_nav: Decimal | None = None
    actual_holdings_value: Decimal | None = None

    projection_ready = (
        policy is not None
        and not scope_reasons
        and set(resolved_assets) >= _requested_asset_codes(snapshot, proposals)
        and all(
            resolved_assets[code].kind is not None
            for code in _requested_asset_codes(snapshot, proposals)
        )
    )
    if policy is not None:
        actual_holdings_value, pre_trade_nav, nav_reasons = _project_pre_trade_nav(
            snapshot=snapshot,
            policy=policy,
            resolved_assets=resolved_assets,
            source_reference_bindings=asset_inputs.source_reference_bindings,
            business_date=business_date,
            as_of=as_of,
        )
        code_reasons.extend(nav_reasons)
        if projection_ready:
            projected_assets = _project_risk_assets(
                snapshot=snapshot,
                proposals=proposals,
                policy=policy,
                resolved_assets=resolved_assets,
                source_reference_bindings=asset_inputs.source_reference_bindings,
                business_date=business_date,
                as_of=as_of,
                reasons=code_reasons,
            )
            projection = PortfolioExposureProjection(
                portfolio_snapshot_id=snapshot.snapshot_id,
                as_of=as_of,
                business_date=business_date,
                portfolio_market_value=pre_trade_nav,
                assets=projected_assets,
            )
            industry = assess_portfolio_industry_exposure(
                policy=policy.industry_policy,
                projection=projection,
            )
    else:
        code_reasons.append("PORTFOLIO_RISK_POLICY_UNCONFIGURED")

    capacity_decisions, capacity_reasons = _assess_capacities(
        snapshot=snapshot,
        proposals=proposals,
        policy=policy,
        resolved_assets=resolved_assets,
        source_reference_bindings=asset_inputs.source_reference_bindings,
        as_of=as_of,
        business_date=business_date,
        requested_purpose=capacity_requested_purpose,
    )
    code_reasons.extend(capacity_reasons)

    report_result = build_portfolio_risk_report(
        snapshot=snapshot,
        proposals=proposals,
        policy=policy,
        asset_inputs=asset_inputs,
        all_source_evidence=evidence,
        as_of=as_of,
        business_date=business_date,
        capacity_requested_purpose=capacity_requested_purpose,
        scope_reasons=tuple(dict.fromkeys(scope_reasons)),
        calculation_reasons=tuple(dict.fromkeys(code_reasons)),
        pre_trade_nav=pre_trade_nav,
        actual_holdings_value=actual_holdings_value,
        industry=industry,
        capacity_decisions=capacity_decisions,
        capacity_reasons=tuple(dict.fromkeys(capacity_reasons)),
        identity_basis=identity_basis,
    )
    return PortfolioRiskAssessmentResult(
        report_payload=report_result.payload,
        exposure_projection=projection,
        industry_assessment=industry,
        capacity_decisions=capacity_decisions,
        all_source_evidence=evidence,
        reason_codes=report_result.reason_codes,
    )


def _scope_reasons(
    *,
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    policy: PortfolioRiskPolicyBundle | None,
    asset_inputs: PortfolioRiskAssetsReadResult,
    as_of: datetime,
    business_date: date,
) -> list[str]:
    reasons: list[str] = []
    if snapshot.read_at > as_of:
        reasons.append("PORTFOLIO_SNAPSHOT_AFTER_CUTOFF")
    order_ids = tuple(item.order_id for item in snapshot.active_orders) + tuple(
        item.order_id for item in proposals
    )
    if len(order_ids) != len(set(order_ids)):
        reasons.append("PORTFOLIO_ORDER_ID_DUPLICATE")
    if policy is None:
        reasons.append("PORTFOLIO_RISK_POLICY_UNCONFIGURED")
    else:
        if policy.as_of != as_of or policy.business_date != business_date:
            reasons.append("PORTFOLIO_POLICY_CUTOFF_MISMATCH")
        if snapshot.account_id not in policy.account_ids:
            reasons.append("PORTFOLIO_POLICY_ACCOUNT_NOT_ALLOWED")
        if (
            asset_inputs.policy_snapshot_id != policy.snapshot_id
            or asset_inputs.policy_snapshot_hash != policy.snapshot_hash
        ):
            reasons.append("PORTFOLIO_ASSET_READER_POLICY_SNAPSHOT_MISMATCH")
        if any(
            binding not in policy.source_references
            for binding in asset_inputs.source_reference_bindings
        ):
            reasons.append("PORTFOLIO_ASSET_SOURCE_REFERENCE_BINDING_MISMATCH")
        if snapshot.money_unit is None:
            reasons.append("PORTFOLIO_MONEY_UNIT_UNKNOWN")
        elif snapshot.money_unit != policy.ledger_money_unit:
            reasons.append("PORTFOLIO_MONEY_UNIT_POLICY_MISMATCH")
    if asset_inputs.status == "blocked":
        reasons.extend(asset_inputs.reason_codes or ("RISK_INPUTS_BLOCKED",))
    return reasons


def _resolve_asset_inputs(
    *,
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    policy: PortfolioRiskPolicyBundle | None,
    asset_inputs: PortfolioRiskAssetsReadResult,
) -> tuple[dict[str, str], dict[str, PortfolioRiskAssetInputs], list[str]]:
    reasons: list[str] = []
    identities: dict[str, set[str]] = {}
    pinned_codes: set[str] = set()
    for holding in snapshot.holdings:
        if holding.quantity == 0:
            continue
        if holding.security_id is not None:
            identities.setdefault(holding.asset_code, set()).add(holding.security_id)
        else:
            pinned_codes.add(holding.asset_code)
    for active_order in snapshot.active_orders:
        identities.setdefault(active_order.asset_code, set()).add(active_order.security_id)
    for proposed_order in proposals:
        identities.setdefault(proposed_order.asset_code, set()).add(proposed_order.security_id)

    policy_refs = policy.source_references if policy is not None else ()
    resolved_ids: dict[str, str] = {}
    identity_basis: dict[str, str] = {}
    for asset_code in sorted(_requested_asset_codes(snapshot, proposals)):
        known_ids = identities.get(asset_code, set())
        all_reference_ids = {
            reference.security_id for reference in policy_refs if reference.asset_code == asset_code
        }
        valuation_ids = {
            reference.security_id
            for reference in policy_refs
            if reference.kind == "valuation" and reference.asset_code == asset_code
        }
        if len(known_ids) > 1 or len(valuation_ids) > 1 or len(all_reference_ids) > 1:
            reasons.append("PORTFOLIO_ASSET_SECURITY_ID_CONFLICT")
            continue
        if asset_code in pinned_codes:
            if len(valuation_ids) != 1:
                reasons.append(
                    "PORTFOLIO_ASSET_IDENTITY_PIN_AMBIGUOUS"
                    if valuation_ids
                    else "PORTFOLIO_ASSET_IDENTITY_PIN_MISSING"
                )
                continue
            security_id = next(iter(valuation_ids))
            if known_ids and known_ids != {security_id}:
                reasons.append("PORTFOLIO_ASSET_SECURITY_ID_CONFLICT")
                continue
            identity_basis[asset_code] = "pinned_policy_source_mapping"
        elif known_ids:
            security_id = next(iter(known_ids))
            if valuation_ids != {security_id}:
                reasons.append("PORTFOLIO_ASSET_SOURCE_REFERENCE_MISMATCH")
                continue
            identity_basis[asset_code] = "ledger_order_identity"
        else:
            reasons.append("PORTFOLIO_ASSET_IDENTITY_MISSING")
            continue
        resolved_ids[asset_code] = security_id

    rows_by_code: dict[str, list[PortfolioRiskAssetInputs]] = {}
    for asset in asset_inputs.assets:
        rows_by_code.setdefault(asset.asset_code, []).append(asset)
    resolved: dict[str, PortfolioRiskAssetInputs] = {}
    for asset_code, security_id in resolved_ids.items():
        rows = rows_by_code.get(asset_code, [])
        if len(rows) != 1:
            reasons.append(
                "PORTFOLIO_ASSET_READER_INPUT_MISSING"
                if not rows
                else "PORTFOLIO_ASSET_SECURITY_ID_CONFLICT"
            )
            continue
        asset = rows[0]
        if asset.security_id != security_id:
            reasons.append("PORTFOLIO_ASSET_SOURCE_REFERENCE_MISMATCH")
            continue
        if policy is None or not _valuation_reference_matches(
            asset=asset,
            references=policy.source_references,
            source_reference_bindings=asset_inputs.source_reference_bindings,
        ):
            reasons.append("PORTFOLIO_ASSET_SOURCE_REFERENCE_MISMATCH")
            continue
        if policy is None or not _asset_source_bindings_match(
            asset=asset,
            references=policy.source_references,
            source_reference_bindings=asset_inputs.source_reference_bindings,
        ):
            reasons.append("PORTFOLIO_ASSET_SOURCE_REFERENCE_BINDING_MISMATCH")
            continue
        resolved[asset_code] = asset
    return identity_basis, resolved, list(dict.fromkeys(reasons))


def _valuation_reference_matches(
    *,
    asset: PortfolioRiskAssetInputs,
    references: tuple[PortfolioRiskSourceReference, ...],
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
) -> bool:
    """Require an exact manifest pin and separately require original body hash evidence."""

    evidence = asset.valuation_evidence
    if (
        evidence is None
        or asset.security_id is None
        or evidence.original_payload_sha256 is None
        or not evidence.source_record_id
    ):
        return False
    return _source_reference_is_bound(
        kind="valuation",
        asset_code=asset.asset_code,
        security_id=asset.security_id,
        source_record_id=evidence.source_record_id,
        references=references,
        source_reference_bindings=source_reference_bindings,
    )


def _asset_source_bindings_match(
    *,
    asset: PortfolioRiskAssetInputs,
    references: tuple[PortfolioRiskSourceReference, ...],
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
) -> bool:
    """Require each source fact used by one asset to have its exact policy pin."""

    requirements: list[tuple[str, str, str | None, str]] = []
    if asset.industry_membership is not None:
        requirements.append(
            (
                "industry_membership",
                asset.asset_code,
                asset.security_id,
                asset.industry_membership.source_evidence.source_record_id,
            )
        )
    if asset.etf_report is not None:
        requirements.append(
            (
                "etf_report",
                asset.asset_code,
                asset.security_id,
                asset.etf_report.source_evidence.source_record_id,
            )
        )
        for constituent in asset.etf_report.constituents:
            membership = constituent.industry_membership
            if membership is not None:
                requirements.append(
                    (
                        "industry_membership",
                        constituent.asset_code,
                        None,
                        membership.source_evidence.source_record_id,
                    )
                )
    if asset.capacity_observation is not None:
        requirements.append(
            (
                "capacity_window",
                asset.asset_code,
                asset.security_id,
                asset.capacity_observation.source_evidence.source_record_id,
            )
        )
        state_evidence = asset.capacity_observation.execution_session_state_evidence
        if state_evidence is not None:
            requirements.append(
                (
                    "execution_session_state",
                    asset.asset_code,
                    asset.security_id,
                    state_evidence.source_record_id,
                )
            )
    return all(
        _source_reference_is_bound(
            kind=kind,
            asset_code=asset_code,
            security_id=security_id,
            source_record_id=source_record_id,
            references=references,
            source_reference_bindings=source_reference_bindings,
        )
        for kind, asset_code, security_id, source_record_id in requirements
    )


def _source_reference_is_bound(
    *,
    kind: str,
    asset_code: str,
    security_id: str | None,
    source_record_id: str,
    references: tuple[PortfolioRiskSourceReference, ...],
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
) -> bool:
    """Match one source record to a unique current-policy manifest reference."""

    candidates = tuple(
        reference
        for reference in references
        if reference.kind == kind
        and reference.asset_code == asset_code
        and (security_id is None or reference.security_id == security_id)
        and reference.source_record_id == source_record_id
    )
    return len(candidates) == 1 and candidates[0] in source_reference_bindings


def _project_pre_trade_nav(
    *,
    snapshot: AccountSnapshot,
    policy: PortfolioRiskPolicyBundle,
    resolved_assets: dict[str, PortfolioRiskAssetInputs],
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
    business_date: date,
    as_of: datetime,
) -> tuple[Decimal | None, Decimal | None, list[str]]:
    reasons: list[str] = []
    values: list[Decimal] = []
    holdings_by_code: dict[str, list[HeldPosition]] = {}
    for holding in snapshot.holdings:
        holdings_by_code.setdefault(holding.asset_code, []).append(holding)
    for asset_code, holdings in holdings_by_code.items():
        quantity = exact_decimal_sum(tuple(item.quantity for item in holdings))
        if quantity == 0:
            values.append(Decimal("0"))
            continue
        asset = resolved_assets.get(asset_code)
        price = _qualified_current_price(
            asset=asset,
            policy=policy,
            source_reference_bindings=source_reference_bindings,
            business_date=business_date,
            as_of=as_of,
        )
        if asset is None or price is None:
            reasons.append("PORTFOLIO_ACTUAL_HOLDING_VALUE_UNKNOWN")
            return None, None, reasons
        values.append(exact_decimal_product(quantity, price))
    if snapshot.cash is None:
        reasons.append("PORTFOLIO_CASH_UNKNOWN")
        return exact_decimal_sum(tuple(values)), None, reasons
    if snapshot.money_unit != policy.ledger_money_unit:
        reasons.append("PORTFOLIO_MONEY_UNIT_POLICY_MISMATCH")
        return exact_decimal_sum(tuple(values)), None, reasons
    actual_holdings = exact_decimal_sum(tuple(values))
    nav = exact_decimal_sum((snapshot.cash, actual_holdings))
    if nav <= 0:
        reasons.append("PORTFOLIO_NAV_NON_POSITIVE")
        return actual_holdings, None, reasons
    return actual_holdings, nav, reasons


def _project_risk_assets(
    *,
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    policy: PortfolioRiskPolicyBundle,
    resolved_assets: dict[str, PortfolioRiskAssetInputs],
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
    business_date: date,
    as_of: datetime,
    reasons: list[str],
) -> tuple[PortfolioRiskAsset, ...]:
    holdings_by_code: dict[str, list[HeldPosition]] = {}
    active_by_code: dict[str, list[OpenOrder]] = {}
    proposals_by_code: dict[str, list[ProposedOrder]] = {}
    for held_position in snapshot.holdings:
        holdings_by_code.setdefault(held_position.asset_code, []).append(held_position)
    for active_order in snapshot.active_orders:
        active_by_code.setdefault(active_order.asset_code, []).append(active_order)
    for proposed_order in proposals:
        proposals_by_code.setdefault(proposed_order.asset_code, []).append(proposed_order)

    projected: list[PortfolioRiskAsset] = []
    for asset_code in sorted(_requested_asset_codes(snapshot, proposals)):
        asset = resolved_assets.get(asset_code)
        if asset is None or asset.kind is None:
            reasons.append("PORTFOLIO_ASSET_KIND_UNKNOWN")
            continue
        price = _qualified_current_price(
            asset=asset,
            policy=policy,
            source_reference_bindings=source_reference_bindings,
            business_date=business_date,
            as_of=as_of,
        )
        if price is None and (
            any(item.quantity > 0 for item in holdings_by_code.get(asset_code, ()))
            or any(item.side == "buy" for item in active_by_code.get(asset_code, ()))
            or any(item.side == "buy" for item in proposals_by_code.get(asset_code, ()))
        ):
            reasons.append("PORTFOLIO_PROJECTED_ASSET_VALUE_UNKNOWN")
        held_quantity = exact_decimal_sum(
            tuple(item.quantity for item in holdings_by_code.get(asset_code, ()))
        )
        market_value = project_gross_asset_exposure(
            held_quantity=held_quantity,
            active_orders=tuple(active_by_code.get(asset_code, ())),
            proposed_orders=tuple(proposals_by_code.get(asset_code, ())),
            qualified_current_price=price,
        )
        projected.append(
            PortfolioRiskAsset(
                asset_code=asset_code,
                kind=asset.kind,
                projected_market_value=market_value,
                valuation_evidence=asset.valuation_evidence,
                industry_membership=asset.industry_membership,
                etf_report=asset.etf_report,
            )
        )
    if not snapshot.active_orders_complete:
        reasons.append("PORTFOLIO_ACTIVE_ORDER_SNAPSHOT_INCOMPLETE")
    return tuple(projected)


def _qualified_current_price(
    *,
    asset: PortfolioRiskAssetInputs | None,
    policy: PortfolioRiskPolicyBundle,
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
    business_date: date,
    as_of: datetime,
) -> Decimal | None:
    if (
        asset is None
        or asset.price is None
        or asset.price <= 0
        or asset.quantity_unit is None
        or asset.price_unit != policy.ledger_money_unit
        or asset.valuation_evidence is None
        or not _valuation_reference_matches(
            asset=asset,
            references=policy.source_references,
            source_reference_bindings=source_reference_bindings,
        )
    ):
        return None
    evidence = asset.valuation_evidence
    qualification = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose=policy.industry_policy.requested_purpose,
        allowed_observation_precisions=policy.industry_policy.allowed_observation_precisions,
        as_of=as_of,
        allowed_restrictions=policy.industry_policy.allowed_source_restrictions,
    )
    if not qualification.eligible:
        return None
    if evidence.observation_precision is SourceObservationPrecision.TIMESTAMP:
        if evidence.observed_at is None or evidence.observed_at > as_of:
            return None
        if as_of - evidence.observed_at > timedelta(
            seconds=policy.source_max_timestamp_age_seconds
        ):
            return None
    elif evidence.observation_precision is SourceObservationPrecision.DATE:
        if (
            evidence.observed_on is None
            or evidence.decision_date_cutoff != business_date
            or evidence.observed_on > business_date
            or policy.industry_policy.requested_purpose
            not in policy.industry_policy.date_precision_purposes
        ):
            return None
        if (business_date - evidence.observed_on).days > policy.source_max_date_age_days:
            return None
    else:
        return None
    if evidence.effective_on is not None and evidence.effective_on > business_date:
        return None
    if evidence.effective_until is not None and evidence.effective_until < business_date:
        return None
    return asset.price


def _assess_capacities(
    *,
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    policy: PortfolioRiskPolicyBundle | None,
    resolved_assets: dict[str, PortfolioRiskAssetInputs],
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
    as_of: datetime,
    business_date: date,
    requested_purpose: str,
) -> tuple[tuple[PortfolioCapacityDecision, ...], list[str]]:
    decisions: list[PortfolioCapacityDecision] = []
    reasons: list[str] = []
    target_pairs: set[tuple[str, str]] = {
        (order.asset_code, order.security_id) for order in snapshot.active_orders
    }
    target_pairs.update((order.asset_code, order.security_id) for order in proposals)
    for holding in snapshot.holdings:
        if holding.quantity == 0:
            continue
        asset = resolved_assets.get(holding.asset_code)
        if asset is None or asset.security_id is None:
            reasons.append("CAPACITY_ASSET_IDENTITY_UNRESOLVED")
            continue
        target_pairs.add((holding.asset_code, asset.security_id))
    if not target_pairs:
        return (), reasons
    if policy is None:
        reasons.append("CAPACITY_POLICY_UNCONFIGURED")
        return (), list(dict.fromkeys(reasons))
    for asset_code, security_id in sorted(target_pairs):
        asset = resolved_assets.get(asset_code)
        if asset is None or asset.security_id != security_id:
            reasons.append("CAPACITY_ASSET_IDENTITY_UNRESOLVED")
            continue
        observation = asset.capacity_observation
        if observation is None:
            reasons.append("CAPACITY_OBSERVATION_MISSING")
            continue
        local_usage, usage_reasons = _capacity_usage_for_pair(
            snapshot=snapshot,
            proposals=proposals,
            policy=policy,
            asset=asset,
            source_reference_bindings=source_reference_bindings,
            as_of=as_of,
            business_date=business_date,
        )
        reasons.extend(usage_reasons)
        decisions.append(
            evaluate_portfolio_capacity(
                observation=observation,
                policy=policy.capacity_policy,
                usage=local_usage,
                requested_purpose=requested_purpose,
                business_date=business_date,
                as_of=as_of,
            )
        )
    return tuple(decisions), list(dict.fromkeys(reasons))


def _capacity_usage_for_pair(
    *,
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    policy: PortfolioRiskPolicyBundle,
    asset: PortfolioRiskAssetInputs,
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
    as_of: datetime,
    business_date: date,
) -> tuple[CapacityUsageSnapshot, list[str]]:
    reasons: list[str] = []
    security_id = asset.security_id
    if security_id is None:
        raise ValueError("capacity usage requires a resolved security identity")
    active = tuple(
        _capacity_order(
            item,
            snapshot,
            policy,
            asset,
            source_reference_bindings,
            as_of,
            business_date,
        )
        for item in snapshot.active_orders
        if item.asset_code == asset.asset_code and item.security_id == security_id
    )
    proposed = tuple(
        _capacity_proposed_order(
            item,
            snapshot,
            policy,
            asset,
            source_reference_bindings,
            as_of,
            business_date,
        )
        for item in proposals
        if item.asset_code == asset.asset_code and item.security_id == security_id
    )
    used_volume, used_amount, usage_complete, usage_reasons = _executed_capacity_values(
        snapshot=snapshot,
        asset=asset,
    )
    reasons.extend(usage_reasons)
    volume_unit = asset.quantity_unit
    amount_unit = snapshot.money_unit
    volume = (
        CapacityValue(used_volume, volume_unit)
        if used_volume is not None and volume_unit
        else CapacityValue(None, None)
    )
    amount = (
        CapacityValue(used_amount, amount_unit)
        if used_amount is not None and amount_unit
        else CapacityValue(None, None)
    )
    order_snapshot = CapacityUsageSnapshot(
        account_id=snapshot.account_id,
        security_id=security_id,
        asset_code=asset.asset_code,
        capacity_date=snapshot.execution_session,
        snapshot_read_at=snapshot.read_at,
        volume=volume,
        amount=amount,
        executed_usage_complete=usage_complete,
        active_orders_complete=snapshot.active_orders_complete,
        active_orders=active,
        proposed_orders=proposed,
    )
    return order_snapshot, reasons


def _capacity_order(
    item: OpenOrder,
    snapshot: AccountSnapshot,
    policy: PortfolioRiskPolicyBundle,
    asset: PortfolioRiskAssetInputs,
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
    as_of: datetime,
    business_date: date,
) -> CapacityOrderUsage:
    volume = _capacity_value(item.remaining_quantity, asset.quantity_unit)
    amount_value: Decimal | None = item.remaining_amount
    price = _qualified_current_price(
        asset=asset,
        policy=policy,
        source_reference_bindings=source_reference_bindings,
        business_date=business_date,
        as_of=as_of,
    )
    if amount_value is not None and item.remaining_quantity is not None and price is not None:
        amount_value = max(amount_value, exact_decimal_product(item.remaining_quantity, price))
    elif amount_value is not None:
        amount_value = None
    amount = _capacity_value(amount_value, snapshot.money_unit)
    return CapacityOrderUsage(
        order_id=item.order_id,
        account_id=snapshot.account_id,
        asset_code=item.asset_code,
        security_id=item.security_id,
        side=item.side,
        volume=volume,
        amount=amount,
    )


def _capacity_proposed_order(
    item: ProposedOrder,
    snapshot: AccountSnapshot,
    policy: PortfolioRiskPolicyBundle,
    asset: PortfolioRiskAssetInputs,
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...],
    as_of: datetime,
    business_date: date,
) -> CapacityOrderUsage:
    volume = _capacity_value(item.quantity, asset.quantity_unit)
    price = _qualified_current_price(
        asset=asset,
        policy=policy,
        source_reference_bindings=source_reference_bindings,
        business_date=business_date,
        as_of=as_of,
    )
    amount_value = (
        max(
            exact_decimal_product(item.quantity, item.price),
            exact_decimal_product(item.quantity, price),
        )
        if price is not None
        else None
    )
    return CapacityOrderUsage(
        order_id=item.order_id,
        account_id=snapshot.account_id,
        asset_code=item.asset_code,
        security_id=item.security_id,
        side=item.side,
        volume=volume,
        amount=_capacity_value(amount_value, snapshot.money_unit),
    )


def _executed_capacity_values(
    *,
    snapshot: AccountSnapshot,
    asset: PortfolioRiskAssetInputs,
) -> tuple[Decimal | None, Decimal | None, bool, list[str]]:
    reasons: list[str] = []
    if asset.security_id is None:
        return None, None, False, ["CAPACITY_ASSET_IDENTITY_UNRESOLVED"]
    if not snapshot.executed_usage_complete:
        return None, None, False, ["CAPACITY_EXECUTED_USAGE_SNAPSHOT_INCOMPLETE"]
    matching: list[ExecutedUsage] = []
    complete = True
    for item in snapshot.executed_usage:
        if item.asset_code != asset.asset_code:
            continue
        if (
            item.execution_session is not None
            and item.execution_session != snapshot.execution_session
        ):
            continue
        if item.security_id is not None and item.security_id != asset.security_id:
            complete = False
            reasons.append("CAPACITY_EXECUTED_USAGE_SECURITY_ID_MISMATCH")
            continue
        if item.security_id is None or item.execution_session is None or not item.complete:
            complete = False
            reasons.append("CAPACITY_EXECUTED_USAGE_SCOPE_UNKNOWN")
            continue
        matching.append(item)
    if not complete:
        return None, None, False, list(dict.fromkeys(reasons))
    quantity_values = tuple(item.quantity for item in matching)
    amount_values = tuple(item.amount for item in matching)
    quantity = (
        exact_decimal_sum(tuple(value for value in quantity_values if value is not None))
        if all(value is not None for value in quantity_values)
        else None
    )
    amount = (
        exact_decimal_sum(tuple(value for value in amount_values if value is not None))
        if all(value is not None for value in amount_values)
        else None
    )
    if not matching:
        return Decimal("0"), Decimal("0"), True, reasons
    return quantity, amount, True, reasons


def _capacity_value(value: Decimal | None, unit: str | None) -> CapacityValue:
    if value is None or unit is None:
        return CapacityValue(None, None)
    return CapacityValue(value, unit)


def _collect_source_evidence(
    asset_inputs: PortfolioRiskAssetsReadResult,
) -> tuple[PortfolioRiskSourceEvidence, ...]:
    evidence: set[PortfolioRiskSourceEvidence] = set(asset_inputs.all_source_evidence)
    for asset in asset_inputs.assets:
        if asset.valuation_evidence is not None:
            evidence.add(asset.valuation_evidence)
        if asset.industry_membership is not None:
            evidence.add(asset.industry_membership.source_evidence)
        if asset.etf_report is not None:
            evidence.add(asset.etf_report.source_evidence)
            for row in asset.etf_report.constituents:
                if row.industry_membership is not None:
                    evidence.add(row.industry_membership.source_evidence)
        if asset.capacity_observation is not None:
            evidence.add(asset.capacity_observation.source_evidence)
            if asset.capacity_observation.execution_session_state_evidence is not None:
                evidence.add(asset.capacity_observation.execution_session_state_evidence)
    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                item.source_id,
                item.source_record_id,
                item.original_payload_sha256 or "",
                item.observation_precision.value,
                item.decision_cutoff.isoformat(),
            ),
        )
    )


def _requested_asset_codes(
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
) -> set[str]:
    return (
        {item.asset_code for item in snapshot.holdings if item.quantity > 0}
        | {item.asset_code for item in snapshot.active_orders}
        | {item.asset_code for item in proposals}
    )


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _require_token(value: str, name: str) -> None:
    if type(value) is not str or not value.strip() or value.strip() != value:
        raise ValueError(f"{name} must be a nonempty trimmed token")


__all__ = (
    "AccountSnapshot",
    "ExecutedUsage",
    "HeldPosition",
    "OpenOrder",
    "PortfolioRiskAssessmentResult",
    "ProposedOrder",
    "assess_simulated_portfolio_risk",
    "exact_decimal_product",
    "exact_decimal_sum",
    "project_gross_asset_exposure",
)
