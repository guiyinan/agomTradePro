"""Typed TUI read adapter for the investment command overview."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.application.interface_services import (
    build_beta_market_summary_payload,
    build_dashboard_data,
)


class DashboardBetaMarketTuiView(APIView):
    """Return the decision-safe Beta conclusion shown before Alpha selection."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return one portable row for the Beta-to-Alpha research workflow."""

        del request
        row = build_beta_market_summary_payload()
        return Response(
            {
                "success": True,
                "rows": [row],
                "total": 1,
                "must_not_use_for_decision": bool(row.get("must_not_use_for_decision", True)),
                "blocked_reason": str(row.get("blocked_reason") or ""),
            }
        )


class DashboardTuiOverviewView(APIView):
    """Return P0 summary plus portable allocation and performance chart rows."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return one owner-scoped dashboard snapshot without template JSON."""

        user_id = getattr(request.user, "id", None)
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            return Response(
                {"success": False, "error": "认证用户缺少持久化身份"},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = build_dashboard_data(user_id)
        allocation_total = sum(float(value or 0) for value in data.allocation_data.values())
        allocation_rows = [
            {
                "asset_class": str(asset_class),
                "market_value": float(market_value or 0),
                "weight_percent": (
                    round(float(market_value or 0) / allocation_total * 100, 6)
                    if allocation_total > 0
                    else 0.0
                ),
            }
            for asset_class, market_value in data.allocation_data.items()
        ]
        performance_rows: list[dict[str, Any]] = []
        for raw_row in data.performance_data:
            row = dict(raw_row)
            if "return_pct" in row and row["return_pct"] is not None:
                row["return_pct"] = round(float(row["return_pct"]), 6)
            performance_rows.append(row)
        return Response(
            {
                "success": True,
                "summary": {
                    "display_name": data.display_name,
                    "current_regime": data.current_regime,
                    "regime_confidence_percent": round(data.regime_confidence * 100, 6),
                    "total_assets": data.total_assets,
                    "total_return": data.total_return,
                    "total_return_percent": data.total_return_pct,
                    "cash_balance": data.cash_balance,
                    "invested_value": data.invested_value,
                    "invested_ratio_percent": round(data.invested_ratio * 100, 6),
                    "position_count": data.position_count,
                    "active_signal_count": len(data.active_signals),
                    "pending_review_count": data.pending_review_count,
                    "regime_data_health": data.regime_data_health,
                },
                "allocation": allocation_rows,
                "performance": performance_rows,
            }
        )
