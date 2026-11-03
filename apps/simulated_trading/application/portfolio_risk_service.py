"""Owner-scoped portfolio risk shared by previews, normal execution and pressure."""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Literal

from apps.risk_center.application.portfolio_baseline_risk import portfolio_risk_subject_is_excluded
from apps.risk_center.application.portfolio_pressure_catalogue import (
    list_approved_portfolio_pressure_options,
)
from apps.risk_center.application.portfolio_risk_assets import (
    CloseSnapshotSessionEvidenceProvider,
)
from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioPressureOptionsPayload,
    PortfolioRiskCheckPayload,
    PortfolioRiskReportPayload,
)
from apps.risk_center.application.portfolio_risk_deadlines import (
    portfolio_risk_execution_deadline_for_evidence,
)
from apps.risk_center.application.portfolio_risk_execution_evidence import (
    PortfolioRiskExecutionEvidence,
)
from apps.risk_center.application.portfolio_risk_order_admission import (
    build_portfolio_risk_order_admission,
    portfolio_risk_order_admission_is_effective,
)
from apps.risk_center.application.portfolio_risk_runtime import PortfolioRiskRuntime
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.risk_center.application.portfolio_risk_snapshot import ProposedOrder
from apps.risk_center.domain.portfolio_risk_sources import PortfolioRiskSourceEvidence
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventV1,
    validate_local_simulated_fill_event,
)
from apps.simulated_trading.application.order_submission_market import (
    CLOSE_ORDER_MARKET_PURPOSE,
    SUPPORTED_ORDER_MARKET_PURPOSES,
)
from apps.simulated_trading.application.portfolio_risk_calendar import PortfolioRiskCalendarReader
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PortfolioRiskPressureRunner,
    PreparedPortfolioRisk,
)
from apps.simulated_trading.application.portfolio_risk_preparation import (
    CLOSE_SNAPSHOT_REQUESTED_PURPOSE,
    PortfolioRiskContextBuilder,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskAccountAccessDenied,
)
from apps.simulated_trading.application.portfolio_risk_qualification import (
    PortfolioRiskExecutionQualification,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    PortfolioRiskResourceSnapshotReaderProtocol,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import RebalancePlanPreview
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent


class OwnerScopedPortfolioRiskService:
    """Use one risk policy/source path without granting execution from a GET report."""

    def __init__(
        self,
        *,
        resources: PortfolioRiskResourceSnapshotReaderProtocol,
        runtime: PortfolioRiskRuntime,
        clock: PortfolioRiskClock,
        business_timezone: tzinfo,
        code_version: str,
        using: str,
        pressure_runner: PortfolioRiskPressureRunner,
        calendar_reader: PortfolioRiskCalendarReader,
        close_snapshot_session_provider: CloseSnapshotSessionEvidenceProvider | None = None,
    ) -> None:
        """Inject public owner ports and actual server/code identities."""

        self._contexts = PortfolioRiskContextBuilder(
            resources=resources,
            runtime=runtime,
            clock=clock,
            business_timezone=business_timezone,
            calendar_reader=calendar_reader,
            close_snapshot_session_provider=close_snapshot_session_provider,
        )
        self._resources = resources
        self._runtime = runtime
        self._clock = clock
        self._business_timezone = business_timezone
        self._code_version = code_version
        self._using = using
        self._pressure_runner = pressure_runner

    def get_report(self, *, user_id: int, account_id: int) -> PortfolioRiskReportPayload:
        """Read the current account constraints without creating orders or evidence."""

        return self._contexts.prepare(user_id=user_id, account_id=account_id).report

    def get_pressure_options(
        self, *, user_id: int, account_id: int
    ) -> PortfolioPressureOptionsPayload:
        """Read the named approved catalogue without fetching financial data or running it."""

        scope = self._resources.read_account_scope(user_id=user_id, account_id=account_id)
        if scope is None or not scope.can_read:
            raise PortfolioRiskAccountAccessDenied()
        return {
            "account_id": account_id,
            "options": list_approved_portfolio_pressure_options(as_of=self._clock.now()),
            "scope": "simulation_only",
            "read_only": True,
        }

    def assess_preview(
        self, *, user_id: int, account_id: int, preview: RebalancePlanPreview
    ) -> PortfolioRiskReportPayload:
        """Recheck every candidate order and keep unknown or changed input blocked."""

        proposals: list[ProposedOrder] = []
        reasons: list[str] = []
        for row in preview.asset_items:
            if row.action not in {"buy", "sell"}:
                continue
            security_id = row.identity.get("security_id") if row.identity is not None else None
            quantity = row.actionable_quantity
            price = row.reference_price
            if (
                type(security_id) is not str
                or not security_id.strip()
                or quantity is None
                or price is None
            ):
                reasons.append("PORTFOLIO_RISK_PREVIEW_ORDER_INPUT_UNKNOWN")
                continue
            if quantity == 0:
                continue
            fee = _fee_cap(row.fee)
            if fee is None:
                reasons.append("PORTFOLIO_RISK_PREVIEW_FEE_BUDGET_UNKNOWN")
            proposals.append(
                ProposedOrder(
                    order_id=f"preview:{row.asset_code}:{row.action}",
                    asset_code=row.asset_code,
                    security_id=security_id,
                    side="buy" if row.action == "buy" else "sell",
                    quantity=quantity,
                    price=price,
                    fee_cap=fee,
                )
            )
        session: date | None = None
        if preview.risk_context.reference_price_basis == "published_close":
            dates = {
                row.price_as_of for row in preview.asset_items if row.action in {"buy", "sell"}
            }
            if len(dates) == 1 and None not in dates:
                session = next(iter(dates))
            else:
                reasons.append("PORTFOLIO_RISK_PREVIEW_CLOSE_SESSION_UNKNOWN")
        prepared = self._contexts.prepare(
            user_id=user_id,
            account_id=account_id,
            proposals=tuple(proposals),
            execution_session=session,
        )
        if preview.cash_before is None or preview.cash_before != prepared.snapshot.cash:
            reasons.append("PORTFOLIO_RISK_PREVIEW_CASH_CHANGED")
        holdings = {row.asset_code: row.quantity for row in prepared.snapshot.holdings}
        for row in preview.asset_items:
            if row.current_quantity is not None and row.current_quantity != holdings.get(
                row.asset_code, Decimal("0")
            ):
                reasons.append("PORTFOLIO_RISK_PREVIEW_POSITION_CHANGED")
        if reasons:
            return _with_failed_check(
                prepared.report,
                dimension="preview_binding",
                reasons=tuple(dict.fromkeys(reasons)),
                summary="清单输入已变化或仍不完整，请重新生成后查看风险",
            )
        return prepared.report

    def validate_order(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_cap: Decimal,
        market_purpose: str | None = None,
        as_of: datetime,
        execution_session: date,
    ) -> PortfolioRiskExecutionQualification:
        """Validate exact resources under the existing account lock before execution."""

        intent.__post_init__()
        if type(fee_cap) is not Decimal or not fee_cap.is_finite() or fee_cap < 0:
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_FEE_BUDGET_INVALID")
        proposal = ProposedOrder(
            order_id=f"new:{intent.idempotency_key}",
            asset_code=intent.asset_code,
            security_id=intent.security_id,
            side=intent.side.value,
            quantity=intent.quantity,
            price=intent.price,
            fee_cap=fee_cap,
        )
        prepared = self._contexts.prepare(
            user_id=intent.user_id,
            account_id=intent.account_id,
            proposals=(proposal,),
            execution_session=execution_session,
            require_write=True,
            lower_bound=as_of,
        )
        _require_market_purpose_binding(
            capacity_requested_purpose=prepared.capacity_requested_purpose,
            market_purpose=market_purpose,
            all_source_evidence=prepared.assessment.all_source_evidence,
        )
        return self._qualify_prepared(
            prepared,
            intent=intent,
            execution_session=execution_session,
            audit_key=intent.idempotency_key,
            request_hash=intent.request_payload_hash,
            admission_order_id=proposal.order_id,
            subject={
                "kind": "new_order",
                "intent": intent,
                "fee_cap": fee_cap,
                "market_purpose": market_purpose,
            },
        )

    def validate_reserved_fill(
        self,
        *,
        intent: SimulatedTradeIntent,
        event: LocalSimulatedFillEventV1,
        market_purpose: str | None = None,
        execution_session: date,
        as_of: datetime,
    ) -> PortfolioRiskExecutionQualification:
        """Qualify an existing accepted hold once, without inventing another proposal."""

        intent.__post_init__()
        event = validate_local_simulated_fill_event(event)
        if (
            event.account_id,
            event.user_id,
            event.asset_code,
            event.security_id,
            event.side,
            event.order_idempotency_key,
            event.intent_payload_hash,
        ) != (
            intent.account_id,
            intent.user_id,
            intent.asset_code,
            intent.security_id,
            intent.side,
            intent.idempotency_key,
            intent.request_payload_hash,
        ):
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_FILL_IDENTITY_MISMATCH")
        prepared = self._contexts.prepare(
            user_id=intent.user_id,
            account_id=intent.account_id,
            execution_session=execution_session,
            require_write=True,
            lower_bound=as_of,
        )
        _require_market_purpose_binding(
            capacity_requested_purpose=prepared.capacity_requested_purpose,
            market_purpose=market_purpose,
            all_source_evidence=prepared.assessment.all_source_evidence,
        )
        matched = tuple(
            order
            for order in prepared.snapshot.active_orders
            if order.order_id == str(event.reservation_id)
        )
        if len(matched) != 1:
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_FILL_HOLD_UNKNOWN")
        order = matched[0]
        if (
            (order.asset_code, order.security_id, order.side)
            != (
                intent.asset_code,
                intent.security_id,
                intent.side.value,
            )
            or order.remaining_quantity is None
            or event.quantity > order.remaining_quantity
        ):
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_FILL_HOLD_MISMATCH")
        baseline = prepared.baseline_source.policy
        if baseline is not None and portfolio_risk_subject_is_excluded(
            asset_code=intent.asset_code,
            hard_exclusions=baseline.hard_exclusions,
        ):
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_BASELINE_HARD_EXCLUSION")
        return self._qualify_prepared(
            prepared,
            intent=intent,
            execution_session=execution_session,
            audit_key=event.source_event_id,
            request_hash=event.event_payload_hash,
            admission_order_id=f"reservation:{event.reservation_id}",
            subject={
                "kind": "reserved_fill",
                "accepted_intent": intent,
                "event": event,
                "execution_session": execution_session,
                "market_purpose": market_purpose,
            },
        )

    def _qualify_prepared(
        self,
        prepared: PreparedPortfolioRisk,
        *,
        intent: SimulatedTradeIntent,
        execution_session: date,
        audit_key: str,
        request_hash: str,
        admission_order_id: str,
        subject: dict[str, object],
    ) -> PortfolioRiskExecutionQualification:
        bound_json = canonical_portfolio_risk_json(
            {
                "risk_input_snapshot_json": prepared.input_snapshot_json,
                "executing_subject": subject,
            }
        )
        order_admission = build_portfolio_risk_order_admission(
            subjects=((admission_order_id, _intent_risk_side(intent)),),
            subject_id=audit_key,
            checks=tuple(prepared.report["checks"]),
            must_not_use_for_decision=prepared.report["must_not_use_for_decision"],
        )
        bound_report: PortfolioRiskReportPayload = {
            **prepared.report,
            "order_admission": order_admission,
            "resource_snapshot_hash": portfolio_risk_content_hash(
                {"input_snapshot_json": bound_json}
            ),
        }
        if not portfolio_risk_order_admission_is_effective(
            bound_report,
            subject_id=audit_key,
            side=_intent_risk_side(intent),
            order_ids=(admission_order_id,),
        ):
            raise SimulatedTradeExecutionBlocked(
                "portfolio risk has not qualified this exact simulated order",
                code="PORTFOLIO_RISK_NOT_QUALIFIED",
                details={
                    "reason_codes": list(
                        dict.fromkeys(
                            (
                                *_report_reasons(prepared.report),
                                *order_admission["reason_codes"],
                            )
                        )
                    )
                },
            )
        policy = prepared.policy
        baseline = prepared.baseline_source.policy
        if policy is None or baseline is None or prepared.policy_binding_sha256 is None:
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_POLICY_BINDING_UNKNOWN")
        policy_deadlines = tuple(
            value
            for value in (baseline.effective_until, prepared.calendar.valid_until)
            if value is not None
        )
        deadlines = tuple(
            portfolio_risk_execution_deadline_for_evidence(
                source,
                policy,
                account_id=intent.account_id,
                business_timezone=self._business_timezone,
                additional_policy_deadlines=policy_deadlines,
                requested_purpose=(
                    prepared.capacity_requested_purpose
                    if source.policy_clock_proof is not None
                    and source.policy_clock_proof.source_kind
                    in ("capacity_window", "execution_session_state")
                    else policy.industry_policy.requested_purpose
                ),
            )
            for source in prepared.assessment.all_source_evidence
        )
        if not deadlines or any(value is None for value in deadlines):
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_SOURCE_DEADLINE_UNKNOWN")
        known_deadlines = tuple(value for value in deadlines if value is not None)
        until = min(known_deadlines)
        qualification = PortfolioRiskExecutionQualification(
            account_id=intent.account_id,
            owner_user_id=intent.user_id,
            execution_session=execution_session,
            checked_at=prepared.as_of,
            valid_until=until,
            policy_version=policy.industry_policy.policy_version,
            policy_content_sha256=prepared.policy_binding_sha256,
            runtime_config_sha256=policy.normalized_config_sha256,
            baseline_source_sha256=baseline.content_sha256,
            native_limits_sha256=prepared.native_limits_sha256,
            resource_snapshot_hash=bound_report["resource_snapshot_hash"],
        )
        writer = self._runtime.execution_evidence_writer
        if writer.unit_of_work_key != f"django:{self._using}":
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_EVIDENCE_UOW_MISMATCH")
        writer.record_passed_check(
            PortfolioRiskExecutionEvidence(
                account_id=intent.account_id,
                owner_user_id=intent.user_id,
                account_policy_id=baseline.account_policy_id,
                idempotency_key=audit_key,
                request_payload_hash=request_hash,
                code_version=self._code_version,
                policy_binding_sha256=prepared.policy_binding_sha256,
                report=bound_report,
                input_snapshot_json=bound_json,
            )
        )
        return qualification

    def verify_qualification(
        self, *, qualification: PortfolioRiskExecutionQualification, as_of: datetime
    ) -> None:
        """Recheck expiry and mutable policy sources while the account lock remains held."""

        qualification.__post_init__()
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_EXECUTION_CLOCK_INVALID")
        if as_of < qualification.checked_at or as_of >= qualification.valid_until:
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_EXECUTION_PROOF_EXPIRED")
        business_date = as_of.astimezone(self._business_timezone).date()
        current = self._runtime.policy_reader.read_policy(
            account_id=qualification.account_id, as_of=as_of, business_date=business_date
        ).policy
        baseline = self._runtime.baseline_reader.read_baseline_policy(
            account_id=qualification.account_id, as_of=as_of
        ).policy
        if (
            current is None
            or baseline is None
            or current.industry_policy.policy_version != qualification.policy_version
            or current.normalized_config_sha256 != qualification.runtime_config_sha256
            or baseline.content_sha256 != qualification.baseline_source_sha256
        ):
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_POLICY_CHANGED")
        actual_binding = portfolio_risk_content_hash(
            {
                "runtime_config_sha256": current.normalized_config_sha256,
                "baseline_source_sha256": baseline.content_sha256,
                "native_limits_sha256": qualification.native_limits_sha256,
            }
        )
        if actual_binding != qualification.policy_content_sha256:
            raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_POLICY_CHANGED")

    def run_pressure(
        self,
        *,
        user_id: int,
        account_id: int,
        scenario_version_id: str,
        idempotency_key: str,
    ) -> PortfolioRiskReportPayload:
        """Explicitly run pressure only after rechecking the actual account owner."""

        prepared = self._contexts.prepare(
            user_id=user_id, account_id=account_id, require_write=True
        )
        return self._pressure_runner.run(
            prepared=prepared,
            scenario_identifier=scenario_version_id,
            idempotency_key=idempotency_key,
        )


def _require_market_purpose_binding(
    *,
    capacity_requested_purpose: str,
    market_purpose: str | None,
    all_source_evidence: tuple[PortfolioRiskSourceEvidence, ...],
) -> None:
    """Require a close-market order whenever used risk evidence is close-only."""

    if market_purpose is not None and (
        type(market_purpose) is not str or market_purpose not in SUPPORTED_ORDER_MARKET_PURPOSES
    ):
        raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_MARKET_PURPOSE_UNKNOWN")
    close_risk = capacity_requested_purpose == CLOSE_SNAPSHOT_REQUESTED_PURPOSE or any(
        source.source_purpose == CLOSE_ORDER_MARKET_PURPOSE
        or "close_snapshot_only" in source.restrictions
        for source in all_source_evidence
    )
    close_market = market_purpose == CLOSE_ORDER_MARKET_PURPOSE
    if close_risk and not close_market:
        raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_MARKET_PURPOSE_MISMATCH")


def _fee_cap(payload: dict[str, object] | None) -> Decimal | None:
    if payload is None:
        return None
    value = payload.get("total")
    if type(value) is Decimal:
        amount = value
    elif type(value) is str:
        try:
            amount = Decimal(value)
        except (InvalidOperation, TypeError, ValueError):
            return None
    else:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _report_reasons(report: PortfolioRiskReportPayload) -> list[str]:
    return list(
        dict.fromkeys(reason for check in report["checks"] for reason in check["reason_codes"])
    )


def _with_failed_check(
    report: PortfolioRiskReportPayload, *, dimension: str, reasons: tuple[str, ...], summary: str
) -> PortfolioRiskReportPayload:
    check: PortfolioRiskCheckPayload = {
        "dimension": dimension,
        "status": "unknown",
        "reason_codes": list(reasons),
        "summary": summary,
        "details": {},
    }
    failed_report: PortfolioRiskReportPayload = {
        **report,
        "outcome": "blocked" if report["outcome"] == "blocked" else "unknown",
        "must_not_use_for_decision": True,
        "checks": [*report["checks"], check],
    }
    existing = report.get("order_admission")
    if existing is not None:
        existing_decisions = existing["decisions"]
        failed_report["order_admission"] = build_portfolio_risk_order_admission(
            subjects=tuple((item["order_id"], item["side"]) for item in existing_decisions),
            subject_id=existing["subject_id"],
            checks=tuple(failed_report["checks"]),
            must_not_use_for_decision=True,
        )
    return failed_report


def _intent_risk_side(intent: SimulatedTradeIntent) -> Literal["buy", "sell"]:
    """Narrow the validated execution side to the public risk contract."""

    if intent.side.value == "buy":
        return "buy"
    if intent.side.value == "sell":
        return "sell"
    raise SimulatedTradeExecutionBlocked(code="PORTFOLIO_RISK_ORDER_SIDE_UNKNOWN")
