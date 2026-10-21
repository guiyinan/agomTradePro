"""Typed TUI read adapter for Regime analytical views."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.regime.application.interface_services import (
    get_regime_current_payload,
    get_regime_dashboard_payload,
)
from apps.regime.application.navigator_use_cases import (
    GetRegimeNavigatorHistoryUseCase,
)
from apps.regime.domain.services_v2 import RegimeType
from shared.numeric import safe_float


def _parse_date(value: str) -> date:
    """Parse an optional ISO date, defaulting to the current date."""

    return date.fromisoformat(value) if value else date.today()


def _parse_months(value: str) -> int:
    """Parse and bound the Regime history window."""

    months = int(value or "12")
    if months < 1 or months > 60:
        raise ValueError("months 必须在 1 到 60 之间")
    return months


def _date_value(value: Any) -> date | None:
    """Return a validated date without converting timestamps into source dates."""

    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _distribution_rows(distribution: Any, *, available: bool) -> list[dict[str, Any]]:
    """Project a complete, owner-provided probability map into percentage rows."""

    if not available or not isinstance(distribution, dict):
        return []
    if set(distribution) != {regime.value for regime in RegimeType}:
        return []
    rows: list[dict[str, Any]] = []
    probabilities: list[float] = []
    for regime in RegimeType:
        raw_probability = distribution.get(regime.value)
        if isinstance(raw_probability, bool):
            return []
        probability = safe_float(raw_probability)
        if probability is None or not 0.0 <= probability <= 1.0:
            return []
        probabilities.append(probability)
        rows.append(
            {
                "regime": regime.value,
                "probability_percent": round(probability * 100, 6),
            }
        )
    if not math.isclose(math.fsum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-9):
        return []
    return rows


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

        owner_payload = get_regime_current_payload(
            as_of_date=as_of_date,
            data_source=source or None,
        )
        owner_data_value = owner_payload.get("data")
        owner_data = owner_data_value if isinstance(owner_data_value, dict) else {}
        owner_contract_value = owner_data.get("contract")
        owner_contract = owner_contract_value if isinstance(owner_contract_value, dict) else {}
        observed_at_value = owner_data.get("observed_at")
        observed_at = _date_value(observed_at_value)
        observed_at_label = observed_at.isoformat() if observed_at is not None else None
        contract_observed_at = _date_value(owner_contract.get("observed_at"))
        market_data_as_of = _date_value(owner_contract.get("market_data_as_of"))
        is_stale = bool(owner_data.get("is_stale") or owner_contract.get("is_stale"))
        must_not_use_for_decision = bool(
            owner_data.get("must_not_use_for_decision")
            or owner_contract.get("must_not_use_for_decision")
        )
        freshness_status = str(owner_contract.get("freshness_status") or "unknown")
        if is_stale:
            freshness_status = "stale"
        observation_is_valid = (
            observed_at is not None
            and contract_observed_at == observed_at
            and market_data_as_of == observed_at
            and observed_at <= as_of_date
        )
        regime_name = str(owner_data.get("dominant_regime") or "Unknown")
        available = (
            owner_payload.get("success") is True
            and observation_is_valid
            and freshness_status == "fresh"
            and not is_stale
            and not must_not_use_for_decision
            and regime_name != "Unknown"
        )
        blocked_reason = str(
            owner_data.get("blocked_reason") or owner_contract.get("blocked_reason") or ""
        )
        if not available and not blocked_reason:
            blocked_reason = "regime_data_unavailable"

        current_source = str(owner_data.get("source") or source)
        is_fallback = bool(owner_data.get("is_fallback"))
        raw_warnings = owner_data.get("warnings")
        warnings = (
            [str(item) for item in raw_warnings if str(item)]
            if isinstance(raw_warnings, list)
            else []
        )
        result: dict[str, Any] = {}
        dashboard_payload: dict[str, Any] = {}
        if available:
            dashboard_payload = get_regime_dashboard_payload(
                requested_source=current_source or source or None,
                as_of_date=as_of_date,
                skip_cache=False,
            )
            result_value = dashboard_payload.get("regime_result")
            result = result_value if isinstance(result_value, dict) else {}
            dashboard_warnings = dashboard_payload.get("warnings")
            if isinstance(dashboard_warnings, list):
                warnings.extend(str(item) for item in dashboard_warnings if str(item))

        distribution = _distribution_rows(owner_data.get("distribution"), available=available)
        if available and not distribution:
            warnings.append("象限概率分布不完整，已隐藏概率图。")

        history = GetRegimeNavigatorHistoryUseCase().execute(
            as_of_date - timedelta(days=30 * months),
            as_of_date,
        )
        confidence = safe_float(owner_data.get("confidence"))
        displayed_confidence = (
            round(confidence * 100, 6) if confidence is not None and available else None
        )
        contract_payload = {
            "observed_at": observed_at_label,
            "market_data_as_of": (
                market_data_as_of.isoformat() if market_data_as_of is not None else None
            ),
            "as_of_date": as_of_date.isoformat(),
            "freshness_status": freshness_status,
            "is_stale": is_stale,
            "must_not_use_for_decision": must_not_use_for_decision or not available,
            "blocked_reason": blocked_reason,
            "is_fallback": is_fallback,
        }
        summary = {
            "as_of_date": as_of_date.isoformat(),
            "observed_at": observed_at_label,
            "freshness_status": freshness_status,
            "must_not_use_for_decision": must_not_use_for_decision or not available,
            "blocked_reason": blocked_reason,
            "source": current_source,
            "is_fallback": is_fallback,
            "quadrant": regime_name if available else "Unknown",
            "confidence_percent": displayed_confidence,
            "growth_level": (safe_float(owner_data.get("growth_value")) if available else None),
            "growth_trend": str(
                result.get("pmi_trend") or owner_data.get("growth_level") or "flat"
            ),
            "inflation_level": (
                safe_float(owner_data.get("inflation_value")) if available else None
            ),
            "inflation_trend": str(
                result.get("cpi_trend") or owner_data.get("inflation_level") or "flat"
            ),
            "warning_count": len(warnings),
            "warnings": warnings,
            "error": blocked_reason if not available else "",
        }
        return Response(
            {
                "success": True,
                "available": available,
                "summary": summary,
                "contract": contract_payload,
                "distribution": distribution,
                "momentum": _build_momentum_rows(result) if available else [],
                "history": _build_history_rows(dict(history or {})),
            }
        )
