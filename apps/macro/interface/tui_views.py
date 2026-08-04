"""Typed TUI read adapter for the macro data overview."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.macro.application.interface_services import get_macro_data_page_snapshot
from apps.macro.application.trend_filter_service import (
    INDICATOR_CODE_PATTERN,
    MAX_TREND_FILTER_LIMIT,
    MIN_TREND_FILTER_LIMIT,
    SUPPORTED_TREND_FILTER_TYPES,
)
from apps.macro.composition import build_macro_trend_filter_service


def _authenticated_user_id(request: Request) -> int:
    """Return the persisted ID for the authenticated request user."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("认证用户缺少持久化身份")
    return user_id


def _timeline_row_map(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index timeline rows by their non-empty date value."""

    return {str(row["date"]): row for row in rows if isinstance(row, dict) and row.get("date")}


def _build_risk_timeline_rows(
    timeline: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flatten the combined risk timeline into portable chart rows."""

    temperature = _timeline_row_map(list(timeline.get("temperature") or []))
    pulse = _timeline_row_map(list(timeline.get("pulse") or []))
    regime = _timeline_row_map(list(timeline.get("regime") or []))
    rows: list[dict[str, Any]] = []
    for raw_date in timeline.get("dates") or []:
        date_label = str(raw_date)
        temperature_row = temperature.get(date_label, {})
        pulse_row = pulse.get(date_label, {})
        regime_row = regime.get(date_label, {})
        rows.append(
            {
                "date": date_label,
                "market_temperature": temperature_row.get("score"),
                "pulse_normalized": pulse_row.get("normalized_score"),
                "regime": regime_row.get("regime"),
                "regime_confidence_percent": (
                    round(float(regime_row.get("confidence") or 0) * 100, 6) if regime_row else None
                ),
            }
        )
    return rows


class MacroTuiOverviewView(APIView):
    """Return the user-facing macro catalog, selected series, and risk timeline."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return one read-only macro snapshot projected for portable TUI views."""

        indicator_code = str(request.query_params.get("indicator_code") or "").strip()
        if len(indicator_code) > 80:
            return Response(
                {"success": False, "error": "指标代码长度不能超过 80 个字符"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user_id = _authenticated_user_id(request)
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        snapshot = get_macro_data_page_snapshot(
            selected_indicator=indicator_code,
            user_id=user_id,
            can_sync_macro_data=False,
            published_only=True,
        )
        indicator_map = dict(snapshot.get("indicator_map") or {})
        selected_code = str(snapshot.get("selected_indicator") or "")
        selected = dict(indicator_map.get(selected_code) or {})
        indicators = [
            {
                "code": str(item.get("code") or code),
                "name": str(item.get("name") or code),
                "latest_value": item.get("latest_value"),
                "unit": str(item.get("unit") or ""),
                "latest_period": str(item.get("latest_period") or ""),
                "has_data": bool(item.get("has_data", False)),
                "sync_supported": bool(item.get("sync_supported", False)),
            }
            for code, item in indicator_map.items()
            if isinstance(item, dict)
        ]
        series = [
            {
                "period": str(
                    row.get("reporting_period_label") or row.get("reporting_period") or ""
                ),
                "value": row.get("value"),
                "unit": str(row.get("unit") or selected.get("unit") or ""),
                "source": str(row.get("source") or ""),
                "freshness_status": str(row.get("freshness_status") or ""),
                "decision_grade": str(row.get("decision_grade") or ""),
            }
            for row in snapshot.get("history") or []
            if isinstance(row, dict)
        ]
        thermometer = dict(snapshot.get("market_thermometer") or {})
        regime = dict(snapshot.get("regime_summary") or {})
        pulse = dict(snapshot.get("pulse_card") or {})
        stats = dict(snapshot.get("stats") or {})
        return Response(
            {
                "success": True,
                "summary": {
                    "selected_indicator_code": selected_code,
                    "selected_indicator_name": str(selected.get("name") or selected_code),
                    "selected_indicator_unit": str(selected.get("unit") or ""),
                    "selected_latest_period": str(selected.get("latest_period") or ""),
                    "selected_freshness_status": str(selected.get("freshness_status") or ""),
                    "selected_decision_grade": str(selected.get("decision_grade") or ""),
                    "selected_must_not_use_for_decision": bool(
                        selected.get("must_not_use_for_decision", True)
                    ),
                    "selected_blocked_reason": str(selected.get("blocked_reason") or ""),
                    "total_indicators": int(stats.get("total_indicators") or 0),
                    "synced_indicators": int(stats.get("synced_indicators") or 0),
                    "total_records": int(stats.get("total_records") or 0),
                    "regime": str(regime.get("regime_label") or "未知"),
                    "regime_confidence_percent": round(
                        float(regime.get("confidence") or 0) * 100,
                        6,
                    ),
                    "pulse_score": round(float(pulse.get("pulse_composite") or 0), 6),
                    "market_temperature_score": round(
                        float(thermometer.get("market_temperature_score") or 0),
                        6,
                    ),
                    "market_temperature_band": str(
                        thermometer.get("market_temperature_band_label") or "未知"
                    ),
                    "must_not_use_for_decision": bool(
                        thermometer.get("market_temperature_degraded", False)
                    ),
                    "blocked_reason": str(
                        thermometer.get("market_temperature_blocked_reason") or ""
                    ),
                },
                "indicators": indicators,
                "series": series,
                "risk_timeline": _build_risk_timeline_rows(
                    dict(snapshot.get("macro_risk_timeline") or {})
                ),
            }
        )


class MacroTrendFilterTuiView(APIView):
    """Return a read-only PIT-safe trend projection for one macro series."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Validate bounded query inputs and return portable chart rows."""

        indicator_code = str(request.query_params.get("indicator_code") or "").strip()
        filter_type = str(request.query_params.get("filter_type") or "HP").strip().upper()
        raw_limit = str(request.query_params.get("limit") or "120").strip()
        if INDICATOR_CODE_PATTERN.fullmatch(indicator_code) is None:
            return Response(
                {
                    "success": False,
                    "error": "指标代码只能包含字母、数字、点、冒号、下划线或连字符",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if filter_type not in SUPPORTED_TREND_FILTER_TYPES:
            return Response(
                {"success": False, "error": "滤波器只支持 HP 或 KALMAN"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            limit = int(raw_limit)
        except ValueError:
            return Response(
                {"success": False, "error": "历史点数必须是整数"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not MIN_TREND_FILTER_LIMIT <= limit <= MAX_TREND_FILTER_LIMIT:
            return Response(
                {
                    "success": False,
                    "error": (
                        f"历史点数必须在 {MIN_TREND_FILTER_LIMIT}-" f"{MAX_TREND_FILTER_LIMIT} 之间"
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = build_macro_trend_filter_service().execute(
                indicator_code=indicator_code,
                filter_type=filter_type,
                limit=limit,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "success": True,
                "summary": {
                    "indicator_code": result.indicator_code,
                    "indicator_name": result.indicator_name,
                    "filter_type": result.filter_type,
                    "unit": result.unit,
                    "point_count": len(result.rows),
                    "start_period": result.start_period,
                    "end_period": result.end_period,
                    "data_source": result.data_source,
                    "freshness_status": result.freshness_status,
                    "decision_grade": result.decision_grade,
                    "must_not_use_for_decision": result.must_not_use_for_decision,
                    "blocked_reason": result.blocked_reason,
                    "latest_quality": result.latest_quality,
                },
                "rows": [
                    {
                        "period": row.period,
                        "original": row.original,
                        "trend": row.trend,
                        "cycle": row.cycle,
                        "slope": row.slope,
                    }
                    for row in result.rows
                ],
            }
        )
