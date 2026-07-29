"""Typed TUI read adapter for Regime analytical views."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.regime.application.interface_services import get_regime_dashboard_payload
from apps.regime.application.navigator_use_cases import (
    GetRegimeNavigatorHistoryUseCase,
)


def _parse_date(value: str) -> date:
    """Parse an optional ISO date, defaulting to the current date."""

    return date.fromisoformat(value) if value else date.today()


def _parse_months(value: str) -> int:
    """Parse and bound the Regime history window."""

    months = int(value or "12")
    if months < 1 or months > 60:
        raise ValueError("months 必须在 1 到 60 之间")
    return months


def _json_list(value: Any) -> list[Any]:
    """Return a JSON list from the dashboard's serialized chart field."""

    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def _build_momentum_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge growth and inflation tails into aligned portable chart rows."""

    growth_dates = _json_list(result.get("growth_dates"))
    growth_values = _json_list(result.get("growth_values"))
    inflation_dates = _json_list(result.get("inflation_dates"))
    inflation_values = _json_list(result.get("inflation_values"))
    rows_by_date: dict[str, dict[str, Any]] = {}
    for index, raw_date in enumerate(growth_dates):
        date_label = str(raw_date or "")
        if not date_label:
            continue
        rows_by_date.setdefault(date_label, {"date": date_label})["growth"] = (
            growth_values[index] if index < len(growth_values) else None
        )
    for index, raw_date in enumerate(inflation_dates):
        date_label = str(raw_date or "")
        if not date_label:
            continue
        rows_by_date.setdefault(date_label, {"date": date_label})["inflation"] = (
            inflation_values[index] if index < len(inflation_values) else None
        )
    return [rows_by_date[key] for key in sorted(rows_by_date)]


def _rows_by_date(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index history rows by their non-empty date value."""

    return {str(row["date"]): row for row in rows if isinstance(row, dict) and row.get("date")}


def _build_history_rows(history: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Regime, Pulse, and action histories into one chart table."""

    pulse = _rows_by_date(list(history.get("pulse_history") or []))
    actions = _rows_by_date(list(history.get("action_history") or []))
    transitions = _rows_by_date(list(history.get("regime_transitions") or []))
    dates = sorted(set(pulse) | set(actions) | set(transitions))
    rows: list[dict[str, Any]] = []
    for date_label in dates:
        pulse_row = pulse.get(date_label, {})
        action_row = actions.get(date_label, {})
        transition_row = transitions.get(date_label, {})
        rows.append(
            {
                "date": date_label,
                "regime": transition_row.get("to_regime"),
                "regime_confidence_percent": (
                    round(float(transition_row.get("confidence") or 0) * 100, 6)
                    if transition_row
                    else None
                ),
                "pulse": pulse_row.get("composite_score"),
                "growth": pulse_row.get("growth_score"),
                "inflation": pulse_row.get("inflation_score"),
                "liquidity": pulse_row.get("liquidity_score"),
                "sentiment": pulse_row.get("sentiment_score"),
                "risk_budget_percent": action_row.get("risk_budget_pct"),
                "equity_weight_percent": action_row.get("equity_weight"),
                "bond_weight_percent": action_row.get("bond_weight"),
                "commodity_weight_percent": action_row.get("commodity_weight"),
                "cash_weight_percent": action_row.get("cash_weight"),
            }
        )
    return rows


class RegimeTuiOverviewView(APIView):
    """Return current Regime evidence and its chart-ready history."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return current classification, distribution, momentum, and history."""

        try:
            as_of_date = _parse_date(str(request.query_params.get("as_of_date") or ""))
            months = _parse_months(str(request.query_params.get("months") or "12"))
        except (TypeError, ValueError) as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        source = str(request.query_params.get("source") or "").strip()
        if len(source) > 64:
            return Response(
                {"success": False, "error": "数据源标识长度不能超过 64 个字符"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = get_regime_dashboard_payload(
            requested_source=source or None,
            as_of_date=as_of_date,
            skip_cache=False,
        )
        result = dict(payload.get("regime_result") or {})
        history = GetRegimeNavigatorHistoryUseCase().execute(
            as_of_date - timedelta(days=30 * months),
            as_of_date,
        )
        distribution = [
            {
                "regime": str(regime),
                "probability_percent": round(float(probability or 0) * 100, 6),
            }
            for regime, probability in dict(result.get("distribution") or {}).items()
        ]
        warnings = [str(item) for item in payload.get("warnings") or []]
        return Response(
            {
                "success": True,
                "available": bool(result),
                "summary": {
                    "as_of_date": as_of_date.isoformat(),
                    "source": str(payload.get("current_source") or source),
                    "quadrant": str(result.get("quadrant") or "Unknown"),
                    "confidence_percent": round(
                        float(result.get("confidence") or 0) * 100,
                        6,
                    ),
                    "growth_level": result.get("pmi_value"),
                    "growth_trend": str(result.get("pmi_trend") or "flat"),
                    "inflation_level": result.get("cpi_value"),
                    "inflation_trend": str(result.get("cpi_trend") or "flat"),
                    "warning_count": len(warnings),
                    "warnings": warnings,
                    "error": str(payload.get("error") or ""),
                },
                "distribution": distribution,
                "momentum": _build_momentum_rows(result),
                "history": _build_history_rows(dict(history or {})),
            }
        )
