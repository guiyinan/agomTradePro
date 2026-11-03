"""Build one source-bound exit-pressure projection from real risk inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import cast

from apps.risk_center.application.portfolio_exit_pressure_dtos import PortfolioPressureProjection
from apps.risk_center.application.portfolio_pressure_factor_projection import (
    PressureHeldAsset,
    build_scenario_factor_attributes,
    portfolio_scenario_factor_targets,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.application.portfolio_risk_snapshot import (
    PortfolioRiskAssessmentResult,
)
from apps.risk_center.application.scenario_dtos import (
    PortfolioPositionDTO,
    PortfolioSnapshotDTO,
)
from apps.risk_center.domain.portfolio_capacity import PortfolioCapacityDecision
from apps.risk_center.domain.portfolio_exit_pressure import (
    ExitCapacityWindow,
    ExitPressurePosition,
)
from apps.risk_center.domain.portfolio_exit_pressure_projection import (
    calculate_current_exit_capacity_window,
    calculate_future_exit_capacity_window,
    matching_exit_pressure_shocks,
    pending_exit_order_quantity,
)
from apps.risk_center.domain.portfolio_risk_identity import (
    PortfolioRiskIdentityBinding,
)
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_snapshot import (
    AccountSnapshot,
    exact_decimal_product,
    exact_decimal_sum,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
)
from apps.risk_center.domain.scenarios import (
    ParametricShock,
    PortfolioExposure,
    ScenarioRevision,
    ScenarioRevisionStatus,
)


@dataclass(frozen=True, slots=True)
class PortfolioPressureProjectionBuildResult:
    """A ready-to-run projection and the matching actual-holdings snapshot."""

    projection: PortfolioPressureProjection | None
    portfolio_snapshot: PortfolioSnapshotDTO | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Keep successful outputs paired and failures explicitly explained."""

        if (self.projection is None) != (self.portfolio_snapshot is None):
            raise ValueError("projection and portfolio_snapshot must be present together")
        if type(self.reason_codes) is not tuple or len(self.reason_codes) != len(
            set(self.reason_codes)
        ):
            raise ValueError("reason_codes must be a tuple of unique stable codes")
        if any(type(code) is not str or not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must contain nonempty strings")


def build_portfolio_pressure_projection(
    *,
    account_snapshot: AccountSnapshot,
    native_account_limits: PortfolioRiskNativeAccountLimits,
    identity_bindings: tuple[PortfolioRiskIdentityBinding, ...],
    assessment: PortfolioRiskAssessmentResult,
    asset_inputs: PortfolioRiskAssetsReadResult,
    scenario_revision: ScenarioRevision,
    open_sessions: tuple[date, ...] | None,
    as_of_time: datetime,
    risk_policy_version: str,
    policy_binding_sha256: str,
    allocation_policy_version: str,
    code_version: str,
    calendar_evidence_json: str | None = None,
) -> PortfolioPressureProjectionBuildResult:
    """Bind approved Scenario assumptions to actual holdings and risk capacity.

    Current capacity comes only from an exact, source-qualified same-session
    ``PortfolioCapacityDecision``. Future windows use only explicit exit shocks
    and dates supplied by a real exchange calendar. Calendar source evidence is
    retained as canonical JSON; a bare date tuple cannot support future capacity.
    ``risk_policy_version`` is the ConfigCenter profile key/version shown in the
    report, while ``allocation_policy_version`` remains the composite binding
    used by the Scenario run and its retained evidence. The latter is checked
    against the separately supplied binding digest from the prepared context.
    """

    _validate_arguments(
        account_snapshot=account_snapshot,
        native_account_limits=native_account_limits,
        identity_bindings=identity_bindings,
        assessment=assessment,
        asset_inputs=asset_inputs,
        scenario_revision=scenario_revision,
        open_sessions=open_sessions,
        as_of_time=as_of_time,
        risk_policy_version=risk_policy_version,
        policy_binding_sha256=policy_binding_sha256,
        allocation_policy_version=allocation_policy_version,
        code_version=code_version,
        calendar_evidence_json=calendar_evidence_json,
    )
    preflight = _preflight_reasons(
        account_snapshot=account_snapshot,
        assessment=assessment,
        asset_inputs=asset_inputs,
        scenario_revision=scenario_revision,
        as_of_time=as_of_time,
        risk_policy_version=risk_policy_version,
        policy_binding_sha256=policy_binding_sha256,
        allocation_policy_version=allocation_policy_version,
        identity_bindings=identity_bindings,
    )
    try:
        evidence, evidence_reasons = _collect_evidence(
            assessment=assessment,
            asset_inputs=asset_inputs,
            as_of_time=as_of_time,
        )
    except ValueError:
        return _failed(("PORTFOLIO_PRESSURE_SOURCE_IDENTITY_CONFLICT",))
    blockers = _ordered_unique((*preflight, *evidence_reasons))
    if blockers:
        return _failed(blockers)

    projected = assessment.exposure_projection
    if projected is None or projected.portfolio_market_value is None:
        return _failed(("PORTFOLIO_PRESSURE_VALUATION_UNAVAILABLE",))
    try:
        source_by_asset = _assets_by_code(asset_inputs.assets)
    except ValueError:
        return _failed(("PORTFOLIO_PRESSURE_ASSET_INPUT_IDENTITY_CONFLICT",))
    projected_by_asset = {item.asset_code: item for item in projected.assets}
    identity_by_asset = {item.asset_code: item for item in identity_bindings}
    holdings_by_asset = _aggregate_held_positions(account_snapshot)
    if not holdings_by_asset:
        return _failed(("PORTFOLIO_PRESSURE_POSITIONS_EMPTY",))

    held_assets: list[PressureHeldAsset] = []
    position_blockers: list[str] = []
    for asset_code in sorted(holdings_by_asset):
        quantity, available_quantity = holdings_by_asset[asset_code]
        if quantity <= 0:
            continue
        if available_quantity is not None and available_quantity > quantity:
            position_blockers.append("PORTFOLIO_PRESSURE_AVAILABLE_QUANTITY_EXCEEDS_HOLDING")
            continue
        asset = source_by_asset.get(asset_code)
        exposure_asset = projected_by_asset.get(asset_code)
        binding = identity_by_asset.get(asset_code)
        if asset is None or exposure_asset is None or binding is None:
            position_blockers.append("PORTFOLIO_PRESSURE_HELD_ASSET_INPUT_MISSING")
            continue
        if not _asset_identity_matches(
            account_snapshot=account_snapshot,
            asset_code=asset_code,
            asset=asset,
            binding=binding,
        ):
            position_blockers.append("PORTFOLIO_PRESSURE_ASSET_IDENTITY_MISMATCH")
            continue
        if (
            asset.kind is None
            or exposure_asset.kind is not asset.kind
            or exposure_asset.projected_market_value is None
            or asset.valuation_evidence is None
            or exposure_asset.valuation_evidence != asset.valuation_evidence
            or asset.price is None
            or asset.price <= 0
            or asset.price_unit != account_snapshot.money_unit
            or asset.quantity_unit is None
        ):
            position_blockers.append("PORTFOLIO_PRESSURE_HELD_ASSET_VALUATION_UNKNOWN")
            continue
        market_value = exact_decimal_product(quantity, asset.price)
        if market_value <= 0:
            position_blockers.append("PORTFOLIO_PRESSURE_HELD_ASSET_VALUATION_UNKNOWN")
            continue
        held_assets.append(
            PressureHeldAsset(
                asset_code=asset_code,
                quantity=quantity,
                available_quantity=available_quantity,
                market_value=market_value,
                quantity_unit=asset.quantity_unit,
                asset_input=asset,
                scenario_attributes=(),
            )
        )
    if position_blockers:
        return _failed(_ordered_unique(tuple(position_blockers)))
    if not held_assets:
        return _failed(("PORTFOLIO_PRESSURE_POSITIONS_EMPTY",))

    factor_targets, factor_reasons = portfolio_scenario_factor_targets(scenario_revision)
    scenario_attributes, factor_blockers = build_scenario_factor_attributes(
        held_assets=tuple(held_assets),
        factor_targets=factor_targets,
        assessment=assessment,
        as_of_time=as_of_time,
    )
    if factor_reasons or factor_blockers:
        return _failed(_ordered_unique((*factor_reasons, *factor_blockers)))
    held_assets = [
        PressureHeldAsset(
            asset_code=item.asset_code,
            quantity=item.quantity,
            available_quantity=item.available_quantity,
            market_value=item.market_value,
            quantity_unit=item.quantity_unit,
            asset_input=item.asset_input,
            scenario_attributes=scenario_attributes[item.asset_code],
        )
        for item in held_assets
    ]

    actual_holdings_value = exact_decimal_sum(tuple(item.market_value for item in held_assets))
    if account_snapshot.cash is None or account_snapshot.cash < 0:
        return _failed(("PORTFOLIO_PRESSURE_CASH_UNKNOWN_OR_NEGATIVE",))
    net_asset_value = exact_decimal_sum((account_snapshot.cash, actual_holdings_value))
    if net_asset_value <= 0 or net_asset_value != projected.portfolio_market_value:
        return _failed(("PORTFOLIO_PRESSURE_PRETRADE_NAV_MISMATCH",))
    portfolio_snapshot = PortfolioSnapshotDTO(
        snapshot_id=account_snapshot.snapshot_id,
        account_id=str(account_snapshot.account_id),
        as_of_time=as_of_time,
        net_asset_value=net_asset_value,
        cash_value=account_snapshot.cash,
        positions=tuple(
            PortfolioPositionDTO(
                asset_code=item.asset_code,
                market_value=item.market_value,
                attributes=item.scenario_attributes,
            )
            for item in held_assets
        ),
    )

    pressure_positions, capacity_reasons = _build_pressure_positions(
        account_snapshot=account_snapshot,
        held_assets=tuple(held_assets),
        decisions=assessment.capacity_decisions,
        evidence=evidence,
        scenario_revision=scenario_revision,
        open_sessions=open_sessions,
        as_of_time=as_of_time,
        business_date=projected.business_date,
        calendar_evidence_json=calendar_evidence_json,
    )
    if not pressure_positions:
        return _failed(capacity_reasons or ("PORTFOLIO_PRESSURE_POSITIONS_EMPTY",))
    try:
        projection = PortfolioPressureProjection(
            portfolio_snapshot_id=account_snapshot.snapshot_id,
            allocation_policy_version=allocation_policy_version,
            code_version=code_version,
            scenario_revision_id=scenario_revision.revision_id,
            scenario_revision_hash=scenario_revision.content_hash,
            positions=pressure_positions,
            source_evidence_ids=tuple(
                f"{item.source_id}:{item.source_record_id}" for item in evidence
            ),
            source_evidence=evidence,
            account_snapshot=account_snapshot,
            identity_bindings=identity_bindings,
            native_account_limits=native_account_limits,
            money_unit_basis=(
                "native_simulated_ledger_config"
                if account_snapshot.money_unit is not None
                else "unknown"
            ),
            calendar_evidence_json=calendar_evidence_json,
        )
    except ValueError:
        return _failed(("PORTFOLIO_PRESSURE_PROJECTION_BINDING_INVALID",))
    return PortfolioPressureProjectionBuildResult(
        projection=projection,
        portfolio_snapshot=portfolio_snapshot,
        reason_codes=_ordered_unique(tuple(capacity_reasons)),
    )


def _validate_arguments(
    *,
    account_snapshot: AccountSnapshot,
    native_account_limits: PortfolioRiskNativeAccountLimits,
    identity_bindings: tuple[PortfolioRiskIdentityBinding, ...],
    assessment: PortfolioRiskAssessmentResult,
    asset_inputs: PortfolioRiskAssetsReadResult,
    scenario_revision: ScenarioRevision,
    open_sessions: tuple[date, ...] | None,
    as_of_time: datetime,
    risk_policy_version: str,
    policy_binding_sha256: str,
    allocation_policy_version: str,
    code_version: str,
    calendar_evidence_json: str | None,
) -> None:
    """Reject programming errors before producing a partial business result."""

    expected = (
        (account_snapshot, AccountSnapshot, "account_snapshot"),
        (native_account_limits, PortfolioRiskNativeAccountLimits, "native_account_limits"),
        (assessment, PortfolioRiskAssessmentResult, "assessment"),
        (asset_inputs, PortfolioRiskAssetsReadResult, "asset_inputs"),
        (scenario_revision, ScenarioRevision, "scenario_revision"),
    )
    for value, expected_type, field_name in expected:
        if type(value) is not expected_type:
            raise TypeError(f"{field_name} must be {expected_type.__name__}")
    if type(identity_bindings) is not tuple or any(
        type(item) is not PortfolioRiskIdentityBinding for item in identity_bindings
    ):
        raise TypeError("identity_bindings must be a tuple of typed identity proof values")
    if open_sessions is not None and (
        type(open_sessions) is not tuple
        or any(type(item) is not date for item in open_sessions)
        or len(open_sessions) != len(set(open_sessions))
    ):
        raise TypeError("open_sessions must be unique actual calendar dates or None")
    _require_aware(as_of_time, "as_of_time")
    _require_token(risk_policy_version, "risk_policy_version")
    _require_sha256(policy_binding_sha256, "policy_binding_sha256")
    _require_token(allocation_policy_version, "allocation_policy_version")
    _require_token(code_version, "code_version")
    if calendar_evidence_json is not None:
        if type(calendar_evidence_json) is not str or not calendar_evidence_json:
            raise TypeError("calendar_evidence_json must be canonical JSON text or None")
        try:
            calendar_payload: object = json.loads(calendar_evidence_json)
        except json.JSONDecodeError as error:
            raise ValueError("calendar evidence must be valid canonical JSON") from error
        if not isinstance(calendar_payload, dict) or any(
            type(key) is not str for key in calendar_payload
        ):
            raise ValueError("calendar evidence must be a JSON object")
        calendar_mapping = cast(Mapping[str, object], calendar_payload)
        if canonical_portfolio_risk_json(calendar_mapping) != calendar_evidence_json:
            raise ValueError("calendar evidence must use the canonical portfolio-risk encoding")


def _preflight_reasons(
    *,
    account_snapshot: AccountSnapshot,
    assessment: PortfolioRiskAssessmentResult,
    asset_inputs: PortfolioRiskAssetsReadResult,
    scenario_revision: ScenarioRevision,
    as_of_time: datetime,
    risk_policy_version: str,
    policy_binding_sha256: str,
    allocation_policy_version: str,
    identity_bindings: tuple[PortfolioRiskIdentityBinding, ...],
) -> tuple[str, ...]:
    """Check the shared snapshot, report, approval, and cutoff bindings."""

    reasons: list[str] = []
    if scenario_revision.status not in {
        ScenarioRevisionStatus.APPROVED,
        ScenarioRevisionStatus.ACTIVE,
    }:
        reasons.append("PORTFOLIO_PRESSURE_SCENARIO_NOT_APPROVED")
    if account_snapshot.read_at > as_of_time:
        reasons.append("PORTFOLIO_PRESSURE_ACCOUNT_SNAPSHOT_AFTER_CUTOFF")
    if not account_snapshot.snapshot_id.startswith(
        f"simulated-account:{account_snapshot.account_id}:"
    ):
        reasons.append("PORTFOLIO_PRESSURE_SNAPSHOT_NAMESPACE_MISMATCH")
    projected = assessment.exposure_projection
    if (
        projected is None
        or projected.portfolio_snapshot_id != account_snapshot.snapshot_id
        or projected.as_of != as_of_time
    ):
        reasons.append("PORTFOLIO_PRESSURE_RISK_ASSESSMENT_SNAPSHOT_MISMATCH")
    report = assessment.report_payload
    if report["account_id"] != account_snapshot.account_id:
        reasons.append("PORTFOLIO_PRESSURE_RISK_REPORT_ACCOUNT_MISMATCH")
    if report["as_of"] != as_of_time.isoformat():
        reasons.append("PORTFOLIO_PRESSURE_RISK_REPORT_CUTOFF_MISMATCH")
    if report["policy_version"] != risk_policy_version:
        reasons.append("PORTFOLIO_PRESSURE_POLICY_VERSION_MISMATCH")
    if allocation_policy_version != f"portfolio-risk-binding:{policy_binding_sha256}":
        reasons.append("PORTFOLIO_PRESSURE_POLICY_BINDING_MISMATCH")
    if report["scope"] != "simulation_only" or report["must_not_execute"] is not True:
        reasons.append("PORTFOLIO_PRESSURE_RISK_REPORT_SCOPE_MISMATCH")
    if asset_inputs.status == "blocked":
        reasons.extend(asset_inputs.reason_codes or ("PORTFOLIO_PRESSURE_ASSET_INPUTS_BLOCKED",))
    if asset_inputs.policy_snapshot_id is None or asset_inputs.policy_snapshot_hash is None:
        reasons.append("PORTFOLIO_PRESSURE_POLICY_SNAPSHOT_UNBOUND")
    binding_by_asset = {item.asset_code: item for item in identity_bindings}
    if len(binding_by_asset) != len(identity_bindings):
        reasons.append("PORTFOLIO_PRESSURE_IDENTITY_BINDING_DUPLICATE")
    for holding in account_snapshot.holdings:
        binding = binding_by_asset.get(holding.asset_code)
        if binding is None:
            reasons.append("PORTFOLIO_PRESSURE_HELD_IDENTITY_UNBOUND")
        elif holding.security_id is None:
            if (
                binding.basis != "pinned_policy_source_mapping"
                or binding.ledger_security_id is not None
            ):
                reasons.append("PORTFOLIO_PRESSURE_HELD_IDENTITY_BASIS_MISMATCH")
        elif (
            binding.basis != "ledger"
            or binding.ledger_security_id != holding.security_id
            or binding.source_security_id != holding.security_id
        ):
            reasons.append("PORTFOLIO_PRESSURE_HELD_IDENTITY_MISMATCH")
    for order in account_snapshot.active_orders:
        binding = binding_by_asset.get(order.asset_code)
        if binding is None or (
            binding.basis != "ledger"
            or binding.ledger_security_id != order.security_id
            or binding.source_security_id != order.security_id
        ):
            reasons.append("PORTFOLIO_PRESSURE_ACTIVE_ORDER_IDENTITY_MISMATCH")
    for usage in account_snapshot.executed_usage:
        if usage.security_id is None:
            continue
        binding = binding_by_asset.get(usage.asset_code)
        if binding is None or (
            binding.basis != "ledger"
            or binding.ledger_security_id != usage.security_id
            or binding.source_security_id != usage.security_id
        ):
            reasons.append("PORTFOLIO_PRESSURE_EXECUTED_USAGE_IDENTITY_MISMATCH")
    return _ordered_unique(tuple(reasons))


def _collect_evidence(
    *,
    assessment: PortfolioRiskAssessmentResult,
    asset_inputs: PortfolioRiskAssetsReadResult,
    as_of_time: datetime,
) -> tuple[tuple[PortfolioRiskSourceEvidence, ...], tuple[str, ...]]:
    """Retain all source records referenced by this risk assessment and its inputs."""

    by_identity: dict[tuple[str, str], PortfolioRiskSourceEvidence] = {}
    for source_evidence in (*assessment.all_source_evidence, *asset_inputs.all_source_evidence):
        _add_evidence(by_identity, source_evidence)
    for asset in asset_inputs.assets:
        for evidence in _asset_evidence(asset):
            _add_evidence(by_identity, evidence)
    reasons: list[str] = []
    retained_evidence = tuple(
        sorted(
            by_identity.values(),
            key=lambda item: (item.source_id, item.source_record_id),
        )
    )
    for item in retained_evidence:
        if item.decision_cutoff != as_of_time:
            reasons.append("PORTFOLIO_PRESSURE_SOURCE_CUTOFF_MISMATCH")
    if reasons:
        return retained_evidence, _ordered_unique(tuple(reasons))
    return retained_evidence, ()


def _add_evidence(
    evidence_by_identity: dict[tuple[str, str], PortfolioRiskSourceEvidence],
    evidence: PortfolioRiskSourceEvidence,
) -> None:
    """Keep duplicate source-record identities only when every field agrees."""

    if type(evidence) is not PortfolioRiskSourceEvidence:
        raise TypeError("risk evidence collections must contain typed source records")
    identity = (evidence.source_id, evidence.source_record_id)
    existing = evidence_by_identity.get(identity)
    if existing is not None and existing != evidence:
        raise ValueError("one source record identity has conflicting retained evidence")
    evidence_by_identity[identity] = evidence


def _asset_evidence(asset: PortfolioRiskAssetInputs) -> tuple[PortfolioRiskSourceEvidence, ...]:
    """Return every valuation, membership, ETF, and capacity record on one asset."""

    evidence: list[PortfolioRiskSourceEvidence] = []
    if asset.valuation_evidence is not None:
        evidence.append(asset.valuation_evidence)
    if asset.industry_membership is not None:
        evidence.append(asset.industry_membership.source_evidence)
    if asset.etf_report is not None:
        evidence.append(asset.etf_report.source_evidence)
        for row in asset.etf_report.constituents:
            if row.industry_membership is not None:
                evidence.append(row.industry_membership.source_evidence)
    if asset.capacity_observation is not None:
        evidence.append(asset.capacity_observation.source_evidence)
        state = asset.capacity_observation.execution_session_state_evidence
        if state is not None:
            evidence.append(state)
    return tuple(evidence)


def _assets_by_code(
    assets: tuple[PortfolioRiskAssetInputs, ...],
) -> dict[str, PortfolioRiskAssetInputs]:
    """Index unique code-level inputs for the actual held asset set."""

    result: dict[str, PortfolioRiskAssetInputs] = {}
    for asset in assets:
        if asset.asset_code in result:
            raise ValueError("risk asset inputs must be unique by asset code")
        result[asset.asset_code] = asset
    return result


def _aggregate_held_positions(
    account_snapshot: AccountSnapshot,
) -> dict[str, tuple[Decimal, Decimal | None]]:
    """Aggregate holdings and preserve availability only when every row is known."""

    positions: dict[str, list[tuple[Decimal, Decimal | None]]] = {}
    for holding in account_snapshot.holdings:
        positions.setdefault(holding.asset_code, []).append(
            (holding.quantity, holding.available_quantity)
        )
    return {
        asset_code: (
            exact_decimal_sum(tuple(quantity for quantity, _ in rows)),
            (
                exact_decimal_sum(
                    tuple(available for _, available in rows if available is not None)
                )
                if all(available is not None for _, available in rows)
                else None
            ),
        )
        for asset_code, rows in positions.items()
    }


def _aggregate_held_quantities(account_snapshot: AccountSnapshot) -> dict[str, Decimal]:
    """Aggregate duplicate ledger rows once per asset without duplicating ETFs."""

    return {
        asset_code: quantity
        for asset_code, (quantity, _) in _aggregate_held_positions(account_snapshot).items()
    }


def _asset_identity_matches(
    *,
    account_snapshot: AccountSnapshot,
    asset_code: str,
    asset: PortfolioRiskAssetInputs,
    binding: PortfolioRiskIdentityBinding,
) -> bool:
    """Check actual ledger identity or the explicit policy-pinned mapping."""

    known_ids = {
        item.security_id
        for item in account_snapshot.holdings
        if item.asset_code == asset_code and item.security_id is not None
    }
    known_ids.update(
        item.security_id for item in account_snapshot.active_orders if item.asset_code == asset_code
    )
    if len(known_ids) > 1 or asset.security_id != binding.source_security_id:
        return False
    if known_ids:
        return (
            binding.basis == "ledger"
            and binding.ledger_security_id == next(iter(known_ids))
            and binding.source_security_id == next(iter(known_ids))
        )
    return binding.basis == "pinned_policy_source_mapping" and binding.ledger_security_id is None


def _build_pressure_positions(
    *,
    account_snapshot: AccountSnapshot,
    held_assets: tuple[PressureHeldAsset, ...],
    decisions: tuple[PortfolioCapacityDecision, ...],
    evidence: tuple[PortfolioRiskSourceEvidence, ...],
    scenario_revision: ScenarioRevision,
    open_sessions: tuple[date, ...] | None,
    as_of_time: datetime,
    business_date: date,
    calendar_evidence_json: str | None = None,
) -> tuple[tuple[ExitPressurePosition, ...], tuple[str, ...]]:
    """Make per-holding windows from same-session capacity and explicit shocks."""

    evidence_by_id = {f"{item.source_id}:{item.source_record_id}": item for item in evidence}
    positions: list[ExitPressurePosition] = []
    reasons: list[str] = []
    for item in held_assets:
        pending_sell, pending_unknown = _pending_sell_quantity(
            account_snapshot=account_snapshot,
            asset_code=item.asset_code,
        )
        window, base_quantity, source_ids, window_reasons = _current_capacity_window(
            account_snapshot=account_snapshot,
            held_asset=item,
            decisions=decisions,
            evidence_by_id=evidence_by_id,
            business_date=business_date,
        )
        windows = [window]
        reasons.extend(window_reasons)
        scenario_asset = PortfolioExposure(
            asset_code=item.asset_code,
            weight=Decimal("1"),
            attributes=item.scenario_attributes,
        )
        exit_shocks = _matching_exit_shocks(scenario_revision, scenario_asset)
        if exit_shocks and open_sessions is None:
            current_reasons = _ordered_unique(
                (*window.reason_codes, "PORTFOLIO_PRESSURE_FUTURE_CALENDAR_MISSING")
            )
            windows[0] = ExitCapacityWindow(
                session_date=window.session_date,
                exitable_quantity=None,
                quantity_unit=window.quantity_unit,
                reason_codes=current_reasons,
                source_evidence_ids=window.source_evidence_ids,
            )
            reasons.append("PORTFOLIO_PRESSURE_FUTURE_CALENDAR_MISSING")
        elif exit_shocks and open_sessions is not None:
            max_horizon = max(shock.horizon_days for shock in exit_shocks)
            last_day = account_snapshot.execution_session + timedelta(days=max_horizon)
            future_sessions = tuple(
                day
                for day in sorted(open_sessions)
                if day > account_snapshot.execution_session and day <= last_day
            )
            for session_date in future_sessions:
                if calendar_evidence_json is None:
                    future_window = ExitCapacityWindow(
                        session_date=session_date,
                        exitable_quantity=None,
                        quantity_unit=item.quantity_unit,
                        reason_codes=(
                            "PORTFOLIO_PRESSURE_CAPACITY_BY_APPROVED_SCENARIO_ASSUMPTION",
                            "PORTFOLIO_PRESSURE_CALENDAR_EVIDENCE_MISSING",
                        ),
                        source_evidence_ids=source_ids,
                    )
                    windows.append(future_window)
                    reasons.extend(future_window.reason_codes)
                    continue
                active = tuple(
                    shock
                    for shock in exit_shocks
                    if (session_date - account_snapshot.execution_session).days
                    <= shock.horizon_days
                )
                future_window = _future_capacity_window(
                    session_date=session_date,
                    quantity_unit=item.quantity_unit,
                    base_quantity=base_quantity,
                    held_quantity=item.quantity,
                    available_quantity=item.available_quantity,
                    source_evidence_ids=source_ids,
                    shocks=active,
                )
                windows.append(future_window)
                reasons.extend(future_window.reason_codes)

        if pending_unknown:
            for index, existing in enumerate(windows):
                if existing.exitable_quantity == Decimal("0") and any(
                    code
                    in {
                        "SCENARIO_EXIT_HALT_ASSUMED",
                        "SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED",
                        "CURRENT_SESSION_TRADING_SUSPENDED",
                        "CURRENT_POSITION_AVAILABLE_QUANTITY_ZERO",
                    }
                    for code in existing.reason_codes
                ):
                    continue
                windows[index] = ExitCapacityWindow(
                    session_date=existing.session_date,
                    exitable_quantity=None,
                    quantity_unit=existing.quantity_unit,
                    reason_codes=_ordered_unique(
                        (
                            *existing.reason_codes,
                            "PORTFOLIO_PRESSURE_PENDING_SELL_QUANTITY_UNKNOWN",
                        )
                    ),
                    source_evidence_ids=existing.source_evidence_ids,
                )
            reasons.append("PORTFOLIO_PRESSURE_PENDING_SELL_QUANTITY_UNKNOWN")
        if pending_sell > item.quantity:
            reasons.append("PORTFOLIO_PRESSURE_PENDING_SELL_EXCEEDS_HOLDING")
            continue
        positions.append(
            ExitPressurePosition(
                asset_code=item.asset_code,
                quantity=item.quantity,
                quantity_unit=item.quantity_unit,
                market_value=item.market_value,
                pending_sell_quantity=pending_sell,
                capacity_windows=tuple(windows),
            )
        )
    if "PORTFOLIO_PRESSURE_PENDING_SELL_EXCEEDS_HOLDING" in reasons:
        return (), _ordered_unique(tuple(reasons))
    return tuple(positions), _ordered_unique(tuple(reasons))


def _current_capacity_window(
    *,
    account_snapshot: AccountSnapshot,
    held_asset: PressureHeldAsset,
    decisions: tuple[PortfolioCapacityDecision, ...],
    evidence_by_id: dict[str, PortfolioRiskSourceEvidence],
    business_date: date,
) -> tuple[ExitCapacityWindow, Decimal | None, tuple[str, ...], tuple[str, ...]]:
    """Adapt typed risk asset inputs to the Domain capacity calculation."""

    return calculate_current_exit_capacity_window(
        account_snapshot=account_snapshot,
        asset_code=held_asset.asset_code,
        security_id=held_asset.asset_input.security_id,
        held_quantity=held_asset.quantity,
        available_quantity=held_asset.available_quantity,
        quantity_unit=held_asset.quantity_unit,
        price=held_asset.asset_input.price,
        price_unit=held_asset.asset_input.price_unit,
        money_unit=account_snapshot.money_unit,
        capacity_observation=held_asset.asset_input.capacity_observation,
        decisions=decisions,
        evidence_by_id=evidence_by_id,
        business_date=business_date,
    )


def _matching_exit_shocks(
    revision: ScenarioRevision,
    exposure: PortfolioExposure,
) -> tuple[ParametricShock, ...]:
    """Adapt a Scenario revision to the pure Domain matching rule."""

    return matching_exit_pressure_shocks(revision, exposure)


def _future_capacity_window(
    *,
    session_date: date,
    quantity_unit: str,
    base_quantity: Decimal | None,
    held_quantity: Decimal,
    available_quantity: Decimal | None,
    source_evidence_ids: tuple[str, ...],
    shocks: tuple[ParametricShock, ...],
) -> ExitCapacityWindow:
    """Adapt one approved exit assumption to the pure Domain calculation."""

    return calculate_future_exit_capacity_window(
        session_date=session_date,
        quantity_unit=quantity_unit,
        base_quantity=base_quantity,
        held_quantity=held_quantity,
        available_quantity=available_quantity,
        source_evidence_ids=source_evidence_ids,
        shocks=shocks,
    )


def _pending_sell_quantity(
    *,
    account_snapshot: AccountSnapshot,
    asset_code: str,
) -> tuple[Decimal, bool]:
    """Adapt the exact account snapshot to the Domain SELL reservation summary."""

    return pending_exit_order_quantity(account_snapshot, asset_code)


def _failed(reason_codes: tuple[str, ...]) -> PortfolioPressureProjectionBuildResult:
    """Return a fully explained fail-closed projection result."""

    return PortfolioPressureProjectionBuildResult(
        projection=None,
        portfolio_snapshot=None,
        reason_codes=_ordered_unique(reason_codes),
    )


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    """Retain stable reason order while removing duplicates."""

    return tuple(dict.fromkeys(values))


def _require_aware(value: datetime, field_name: str) -> None:
    """Require an exact timezone-aware server timestamp."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_token(value: str, field_name: str) -> None:
    """Reject blank or whitespace-containing public identifiers."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a nonempty canonical token")


def _require_sha256(value: str, field_name: str) -> None:
    """Require a canonical lowercase SHA-256 digest for exact policy identity."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


__all__ = [
    "PortfolioPressureProjectionBuildResult",
    "build_portfolio_pressure_projection",
]
