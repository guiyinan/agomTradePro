"""Assemble one exact owner/delegated-read portfolio risk context."""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from typing import Literal

from apps.risk_center.application.portfolio_baseline_risk import (
    assess_portfolio_baseline,
    intersect_native_account_limits,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetIdentity,
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskCheckPayload,
    PortfolioRiskOutcome,
    PortfolioRiskReportPayload,
)
from apps.risk_center.application.portfolio_risk_order_admission import (
    build_portfolio_risk_order_admission,
)
from apps.risk_center.application.portfolio_risk_runtime import PortfolioRiskRuntime
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.risk_center.application.portfolio_risk_snapshot import (
    AccountSnapshot,
    ProposedOrder,
    assess_simulated_portfolio_risk,
)
from apps.risk_center.domain.portfolio_risk_identity import PortfolioRiskIdentityBinding
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReader,
    PortfolioRiskCalendarReadRequest,
)
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PreparedPortfolioRisk,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskAccountAccessDenied,
    PortfolioRiskUnavailable,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    PortfolioRiskResourceSnapshotReaderProtocol,
)

CAPACITY_REQUESTED_PURPOSE = "simulation_portfolio_risk_capacity"


class PortfolioRiskContextBuilder:
    """Compose resource and policy reads while preserving their separate clocks."""

    def __init__(
        self,
        *,
        resources: PortfolioRiskResourceSnapshotReaderProtocol,
        runtime: PortfolioRiskRuntime,
        clock: PortfolioRiskClock,
        business_timezone: tzinfo,
        calendar_reader: PortfolioRiskCalendarReader,
    ) -> None:
        """Inject owners of data access, source rules and the actual server clock."""

        self._resources = resources
        self._runtime = runtime
        self._clock = clock
        self._business_timezone = business_timezone
        self._calendar_reader = calendar_reader

    def prepare(
        self,
        *,
        user_id: int,
        account_id: int,
        proposals: tuple[ProposedOrder, ...] = (),
        execution_session: date | None = None,
        require_write: bool = False,
        lower_bound: datetime | None = None,
    ) -> PreparedPortfolioRisk:
        """Read the account first, then capture a real server cutoff for its assessment."""

        before_read = self._clock.now()
        _aware(before_read)
        if lower_bound is not None and before_read < lower_bound:
            raise PortfolioRiskUnavailable(code="PORTFOLIO_RISK_SERVER_CLOCK_REGRESSED")
        initial_date = before_read.astimezone(self._business_timezone).date()
        session = execution_session if execution_session is not None else initial_date
        initial_policy = self._runtime.policy_reader.read_policy(
            account_id=account_id, as_of=before_read, business_date=initial_date
        )
        money_unit = (
            initial_policy.policy.ledger_money_unit if initial_policy.policy is not None else None
        )
        resources = self._resources.read_account_snapshot(
            user_id=user_id,
            account_id=account_id,
            execution_session=session,
            money_unit=money_unit,
        )
        if resources.scope is None or not resources.scope.can_read:
            raise PortfolioRiskAccountAccessDenied()
        if require_write and not resources.scope.can_write:
            raise PortfolioRiskAccountAccessDenied()
        snapshot = resources.snapshot
        if snapshot is None:
            raise PortfolioRiskUnavailable(details={"reason_codes": list(resources.reason_codes)})
        if (
            snapshot.account_id != account_id
            or snapshot.owner_user_id != resources.scope.owner_user_id
        ):
            raise PortfolioRiskUnavailable(code="PORTFOLIO_RISK_RESOURCE_SCOPE_MISMATCH")
        as_of = self._clock.now()
        _aware(as_of)
        if as_of < snapshot.read_at or as_of < before_read:
            raise PortfolioRiskUnavailable(code="PORTFOLIO_RISK_SERVER_CLOCK_REGRESSED")
        business_date = as_of.astimezone(self._business_timezone).date()
        policy_read = self._runtime.policy_reader.read_policy(
            account_id=account_id, as_of=as_of, business_date=business_date
        )
        policy = policy_read.policy
        if policy is None:
            assets = PortfolioRiskAssetsReadResult(
                status="blocked",
                assets=(),
                all_source_evidence=(),
                reason_codes=policy_read.reason_codes,
            )
        else:
            assets = self._runtime.assets_reader.read_assets(
                PortfolioRiskAssetsReadRequest(
                    policy=policy,
                    requested_assets=_requested_assets(snapshot, proposals),
                    as_of=as_of,
                    business_date=business_date,
                    execution_session=session,
                    capacity_requested_purpose=CAPACITY_REQUESTED_PURPOSE,
                )
            )
        assessment = assess_simulated_portfolio_risk(
            snapshot=snapshot,
            proposals=proposals,
            policy=policy,
            asset_inputs=assets,
            as_of=as_of,
            business_date=business_date,
            capacity_requested_purpose=CAPACITY_REQUESTED_PURPOSE,
        )
        calendar = self._calendar_reader.read_calendar(
            PortfolioRiskCalendarReadRequest(
                requested_assets=_resolved_calendar_assets(snapshot, proposals, assets),
                requested_session=session,
                as_of=as_of,
            )
        )
        baseline_source = self._runtime.baseline_reader.read_baseline_policy(
            account_id=account_id, as_of=as_of
        )
        native = resources.native_account_limits
        native_hash = portfolio_risk_content_hash({"native_account_limits": native})
        baseline = intersect_native_account_limits(baseline_source.policy, native, snapshot.read_at)
        baseline_assessment = assess_portfolio_baseline(
            policy=baseline,
            snapshot=snapshot,
            projection=assessment.exposure_projection,
            proposals=proposals,
            as_of=as_of,
        )
        checks = list(assessment.report_payload["checks"])
        checks.append(
            {
                "dimension": "execution_session",
                "status": "allowed" if calendar.requested_session_qualified else "unknown",
                "reason_codes": list(calendar.reason_codes),
                "summary": (
                    "交易日依据已核验"
                    if calendar.requested_session_qualified
                    else "交易日依据尚未对齐"
                ),
                "details": {
                    "requested_session": session.isoformat(),
                    "calendar_evidence_hash": calendar.evidence_hash,
                },
            }
        )
        if execution_session is None and initial_date != business_date:
            checks.append(
                _issue(
                    "execution_session", "unknown", "PORTFOLIO_RISK_DATE_CHANGED_DURING_READ", {}
                )
            )
        checks.append(
            {
                "dimension": "baseline_risk",
                "status": baseline_assessment.outcome,
                "reason_codes": list(
                    dict.fromkeys(
                        (
                            *baseline_source.reason_codes,
                            *baseline_assessment.reason_codes,
                            *(
                                native.reason_codes
                                if native is not None
                                else ("PORTFOLIO_NATIVE_LIMITS_UNKNOWN",)
                            ),
                        )
                    )
                ),
                "summary": (
                    "原有总仓、单仓、现金底线和排除约束已核验"
                    if baseline_assessment.outcome == "allowed"
                    else "原有账户风险约束尚未通过"
                ),
                "details": {
                    "nav_basis": "pre_trade_gross_nav",
                    "projected_total_value": _text(baseline_assessment.projected_total_value),
                    "cash_after_committed_demands": _text(
                        baseline_assessment.cash_after_committed_demands
                    ),
                    "baseline_source_sha256": (
                        baseline_source.policy.content_sha256 if baseline_source.policy else None
                    ),
                    "native_limits_basis": native.basis if native else None,
                    "native_single_weight": _text(native.max_single_weight) if native else None,
                    "native_total_weight": _text(native.max_total_weight) if native else None,
                    "money_unit_basis": resources.money_unit_basis,
                },
            }
        )
        conflicts = tuple(
            issue.asset_code for issue in resources.identity_issues if issue.kind == "conflict"
        )
        if conflicts:
            checks.append(
                _issue(
                    "resource_identity",
                    "blocked",
                    "PORTFOLIO_LEDGER_IDENTITY_CONFLICT",
                    {
                        "asset_codes": list(conflicts),
                    },
                )
            )
        if policy is not None and snapshot.money_unit != policy.ledger_money_unit:
            checks.append(
                _issue("resource_units", "unknown", "PORTFOLIO_RISK_UNIT_BINDING_CHANGED", {})
            )
        if resources.reason_codes:
            checks.append(
                _issue(
                    "resource_read",
                    "unknown",
                    "PORTFOLIO_RISK_RESOURCE_INCOMPLETE",
                    {
                        "reasons": list(resources.reason_codes),
                    },
                )
            )
        identity_bindings = _identity_bindings(snapshot, assets)
        binding = (
            portfolio_risk_content_hash(
                {
                    "runtime_config_sha256": policy.normalized_config_sha256,
                    "baseline_source_sha256": baseline_source.policy.content_sha256,
                    "native_limits_sha256": native_hash,
                }
            )
            if policy is not None and baseline_source.policy is not None
            else None
        )
        inputs: dict[str, object] = {
            "scope": "simulation_only",
            "actor_user_id": user_id,
            "account_snapshot": snapshot,
            "proposals": proposals,
            "runtime_policy": policy,
            "baseline_source": baseline_source,
            "effective_baseline": baseline,
            "native_account_limits": native,
            "asset_inputs": assets,
            "identity_bindings": identity_bindings,
            "calendar": calendar,
            "as_of": as_of,
            "business_date": business_date,
            "capacity_requested_purpose": CAPACITY_REQUESTED_PURPOSE,
        }
        report: PortfolioRiskReportPayload = {
            **assessment.report_payload,
            "outcome": combine_risk_outcomes(tuple(check["status"] for check in checks)),
            "checks": checks,
            "resource_snapshot_hash": portfolio_risk_content_hash(inputs),
            "must_not_use_for_decision": (
                assessment.report_payload["must_not_use_for_decision"]
                or any(check["status"] in {"unknown", "partial"} for check in checks)
            ),
        }
        if proposals:
            report["order_admission"] = build_portfolio_risk_order_admission(
                subjects=tuple((proposal.order_id, proposal.side) for proposal in proposals),
                checks=tuple(checks),
                must_not_use_for_decision=report["must_not_use_for_decision"],
            )
        return PreparedPortfolioRisk(
            actor_user_id=user_id,
            snapshot=snapshot,
            resources=resources,
            proposals=proposals,
            policy=policy,
            baseline_source=baseline_source,
            assets=assets,
            calendar=calendar,
            assessment=assessment,
            report=report,
            as_of=as_of,
            business_date=business_date,
            identity_bindings=identity_bindings,
            policy_binding_sha256=binding,
            native_limits_sha256=native_hash,
            input_snapshot_json=canonical_portfolio_risk_json(inputs),
        )


def combine_risk_outcomes(values: tuple[PortfolioRiskOutcome, ...]) -> PortfolioRiskOutcome:
    """Require every applicable check to pass before declaring a risk pass."""

    for status in ("blocked", "unknown", "partial"):
        if status in values:
            return status
    return "allowed"


def _requested_assets(
    snapshot: AccountSnapshot, proposals: tuple[ProposedOrder, ...]
) -> tuple[PortfolioRiskAssetIdentity, ...]:
    identities: dict[str, set[str]] = {}
    for holding in snapshot.holdings:
        if holding.quantity <= 0:
            continue
        identities.setdefault(holding.asset_code, set())
        if holding.security_id is not None:
            identities[holding.asset_code].add(holding.security_id)
    for order in snapshot.active_orders:
        identities.setdefault(order.asset_code, set()).add(order.security_id)
    for proposal in proposals:
        identities.setdefault(proposal.asset_code, set()).add(proposal.security_id)
    return tuple(
        PortfolioRiskAssetIdentity(code, security_id)
        for code, securities in sorted(identities.items())
        for security_id in (tuple(sorted(securities)) if securities else (None,))
    )


def _identity_bindings(
    snapshot: AccountSnapshot, assets: PortfolioRiskAssetsReadResult
) -> tuple[PortfolioRiskIdentityBinding, ...]:
    inputs = {asset.asset_code: asset for asset in assets.assets}
    result: list[PortfolioRiskIdentityBinding] = []
    for holding in snapshot.holdings:
        if holding.quantity <= 0:
            continue
        asset = inputs.get(holding.asset_code)
        if asset is None or asset.security_id is None:
            continue
        if holding.security_id is not None and holding.security_id != asset.security_id:
            continue
        result.append(
            PortfolioRiskIdentityBinding(
                asset_code=holding.asset_code,
                ledger_security_id=holding.security_id,
                source_security_id=asset.security_id,
                basis=(
                    "ledger" if holding.security_id is not None else "pinned_policy_source_mapping"
                ),
            )
        )
    return tuple(result)


def _resolved_calendar_assets(
    snapshot: AccountSnapshot,
    proposals: tuple[ProposedOrder, ...],
    assets: PortfolioRiskAssetsReadResult,
) -> tuple[PortfolioRiskAssetIdentity, ...]:
    resolved: dict[str, set[str]] = {}
    for asset in assets.assets:
        if asset.security_id is not None:
            resolved.setdefault(asset.asset_code, set()).add(asset.security_id)
    return tuple(
        PortfolioRiskAssetIdentity(
            item.asset_code,
            (
                item.security_id
                if item.security_id is not None
                else (
                    next(iter(resolved[item.asset_code]))
                    if len(resolved.get(item.asset_code, set())) == 1
                    else None
                )
            ),
        )
        for item in _requested_assets(snapshot, proposals)
    )


def _issue(
    dimension: str, status: Literal["blocked", "unknown"], reason: str, details: dict[str, object]
) -> PortfolioRiskCheckPayload:
    return {
        "dimension": dimension,
        "status": status,
        "reason_codes": [reason],
        "summary": "账户输入尚未满足风险核验条件",
        "details": details,
    }


def _aware(value: datetime) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioRiskUnavailable(code="PORTFOLIO_RISK_SERVER_CLOCK_INVALID")


def _text(value: object) -> str | None:
    return str(value) if value is not None else None
