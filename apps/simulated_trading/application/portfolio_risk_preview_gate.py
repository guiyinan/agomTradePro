"""Attach full portfolio risk to a candidate preview without creating orders."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskOrderAdmissionPayload,
    PortfolioRiskReportPayload,
)
from apps.risk_center.application.portfolio_risk_order_admission import (
    portfolio_risk_order_admission_is_effective,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskUnavailable,
    assess_owner_portfolio_preview,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
)


class PortfolioRiskPreviewGate(Protocol):
    """Revalidate a complete preview before it is presented as risk-qualified."""

    def qualify_preview(
        self, *, preview: RebalancePlanPreview, user_id: int, account_id: int
    ) -> RebalancePlanPreview:
        """Preserve the preview amounts and attach the current explained risk result."""
        ...


class ConfiguredPortfolioRiskPreviewGate:
    """Keep M1 checks and add sector, overlap and capacity constraints."""

    def qualify_preview(
        self, *, preview: RebalancePlanPreview, user_id: int, account_id: int
    ) -> RebalancePlanPreview:
        """Block unresolved risk while retaining all original M1 and source reasons."""

        try:
            report = assess_owner_portfolio_preview(
                user_id=user_id, account_id=account_id, preview=preview
            )
        except PortfolioRiskUnavailable:
            return _blocked(preview, "PORTFOLIO_RISK_UNAVAILABLE")
        result = replace(preview, portfolio_risk=report)
        if not _has_actionable_trade(preview):
            if _qualified_read_report(report):
                return result
            return _blocked(result, "PORTFOLIO_RISK_NOT_QUALIFIED")
        if portfolio_risk_order_admission_is_effective(report):
            return result
        return _blocked(
            result,
            "PORTFOLIO_RISK_NOT_QUALIFIED",
            admission=report.get("order_admission"),
        )


def _has_actionable_trade(preview: RebalancePlanPreview) -> bool:
    """Require an exact order decision only when the preview contains a trade."""

    return any(
        row.action in {"buy", "sell"} and row.actionable_quantity != 0
        for row in preview.asset_items
    )


def _qualified_read_report(report: PortfolioRiskReportPayload) -> bool:
    """Allow an empty preview only when its ordinary risk read fully qualifies."""

    return (
        report.get("scope") == "simulation_only"
        and report.get("must_not_execute") is True
        and report.get("outcome") == "allowed"
        and report.get("must_not_use_for_decision") is False
    )


def _blocked(
    preview: RebalancePlanPreview,
    reason: str,
    admission: PortfolioRiskOrderAdmissionPayload | None = None,
) -> RebalancePlanPreview:
    decisions = admission["decisions"] if admission is not None else []

    def block_trade_row(row: RebalancePlanPreviewItem) -> RebalancePlanPreviewItem:
        if row.action not in {"buy", "sell"}:
            return row
        order_id = f"preview:{row.asset_code}:{row.action}"
        decision = next((item for item in decisions if item["order_id"] == order_id), None)
        if decision is not None and decision["outcome"] == "allowed":
            return row
        extra_reasons = decision["reason_codes"] if decision is not None else []
        row_reason_codes = tuple(dict.fromkeys((*row.reason_codes, reason, *extra_reasons)))
        return replace(row, status="blocked", reason_codes=row_reason_codes)

    return replace(
        preview,
        status="blocked",
        reason_codes=tuple(dict.fromkeys((*preview.reason_codes, reason))),
        asset_items=tuple(block_trade_row(row) for row in preview.asset_items),
    )
