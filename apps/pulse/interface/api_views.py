"""Pulse API Views"""

import json
import logging
from datetime import date
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import DatabaseError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.pulse.domain.entities import PulseSnapshot

from .serializers import PulseHistoryQuerySerializer

logger = logging.getLogger(__name__)

_MAX_PULSE_PAYLOAD_BYTES = 1_048_576
_PULSE_API_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImproperlyConfigured,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValidationError,
    ValueError,
)


class PulseApiPayloadError(RuntimeError):
    """Raised when a Pulse response is not bounded finite JSON data."""


def _validated_json_payload(value: object) -> object:
    """Return detached finite JSON data within the Pulse response limit."""

    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PulseApiPayloadError("pulse_payload_invalid") from exc
    if len(encoded.encode("utf-8")) > _MAX_PULSE_PAYLOAD_BYTES:
        raise PulseApiPayloadError("pulse_payload_too_large")
    return json.loads(encoded)


class PulseCurrentView(APIView):
    """获取最新 Pulse 快照

    GET /api/pulse/current/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return the latest reliable or diagnostic Pulse snapshot."""

        try:
            from apps.pulse.application.use_cases import GetLatestPulseUseCase

            use_case = GetLatestPulseUseCase()
            snapshot = use_case.execute(
                as_of_date=date.today(),
                refresh_if_stale=True,
            )

            if not snapshot:
                return Response(
                    {
                        "success": True,
                        "available": False,
                        "count": 0,
                        "data": [],
                        "message": "No pulse data available",
                    },
                    status=status.HTTP_200_OK,
                )

            return Response(
                {
                    "success": True,
                    "available": True,
                    "count": 1,
                    "data": _serialize_snapshot(snapshot),
                }
            )

        except _PULSE_API_EXCEPTIONS as exc:
            logger.warning(
                "Pulse current API failed; exception_type=%s",
                type(exc).__name__,
            )
            return Response(
                {"success": False, "error": "pulse_current_unavailable"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PulseHistoryView(APIView):
    """获取历史 Pulse 记录

    GET /api/pulse/history/?months=6
    GET /api/pulse/history/?limit=30
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return bounded Pulse history after validating query controls."""

        serializer = PulseHistoryQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        query = cast(dict[str, Any], serializer.validated_data)
        try:
            months = int(query["months"])
            limit_value = query.get("limit")
            limit = int(limit_value) if limit_value is not None else None
            from apps.pulse.application.query_services import list_pulse_history_payloads

            raw_data = list_pulse_history_payloads(months=months, limit=limit)
            data = _validated_json_payload(raw_data)
            if not isinstance(data, list):
                raise PulseApiPayloadError("pulse_history_payload_invalid")

            return Response({"success": True, "count": len(data), "data": data})

        except _PULSE_API_EXCEPTIONS as exc:
            logger.warning(
                "Pulse history API failed; exception_type=%s",
                type(exc).__name__,
            )
            return Response(
                {"success": False, "error": "pulse_history_unavailable"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PulseCalculateView(APIView):
    """手动触发 Pulse 计算

    POST /api/pulse/calculate/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """Calculate a fresh Pulse snapshot for an authenticated staff user."""

        if not (
            getattr(request.user, "is_staff", False) is True
            or getattr(request.user, "is_superuser", False) is True
        ):
            return Response(
                {"success": False, "error": "Staff only"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            from apps.pulse.application.use_cases import CalculatePulseUseCase

            use_case = CalculatePulseUseCase()
            snapshot = use_case.execute()

            if not snapshot:
                return Response(
                    {"success": False, "error": "pulse_calculation_failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            data = _validated_json_payload(
                {
                    "composite_score": snapshot.composite_score,
                    "regime_strength": snapshot.regime_strength,
                    "transition_warning": snapshot.transition_warning,
                }
            )
            return Response({"success": True, "data": data})

        except _PULSE_API_EXCEPTIONS as exc:
            logger.warning(
                "Pulse calculation API failed; exception_type=%s",
                type(exc).__name__,
            )
            return Response(
                {"success": False, "error": "pulse_calculation_failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def _serialize_snapshot(snapshot: PulseSnapshot) -> dict[str, Any]:
    """Serialize a pulse snapshot into the public API contract."""
    from apps.pulse.application.query_services import build_pulse_indicator_display_payloads

    indicator_display = build_pulse_indicator_display_payloads(snapshot.indicator_readings)

    indicator_observed_at = {
        str(reading.code): (reading.observed_at.isoformat() if reading.observed_at else None)
        for reading in snapshot.indicator_readings
    }
    market_observed_dates = [
        reading.observed_at
        for reading in snapshot.indicator_readings
        if reading.dimension == "sentiment" and reading.observed_at is not None
    ]
    market_data_as_of = max(market_observed_dates).isoformat() if market_observed_dates else None
    stale_indicator_codes = [
        str(reading.code)
        for reading in snapshot.indicator_readings
        if getattr(reading, "is_stale", False)
    ]
    is_stale = bool(stale_indicator_codes) or snapshot.data_source == "stale"
    must_not_use_for_decision = not snapshot.is_reliable
    blocked_reason = (
        "Pulse 数据未通过 freshness/reliability 校验，当前快照仅可用于诊断，不得直接用于决策。"
        if must_not_use_for_decision
        else ""
    )
    contract = {
        "observed_at": snapshot.observed_at.isoformat(),
        "data_source": snapshot.data_source,
        "is_reliable": snapshot.is_reliable,
        "is_stale": is_stale,
        "stale_indicator_codes": stale_indicator_codes,
        "must_not_use_for_decision": must_not_use_for_decision,
        "blocked_reason": blocked_reason,
        "market_data_as_of": market_data_as_of,
        "indicator_observed_at": indicator_observed_at,
    }
    payload = {
        "observed_at": snapshot.observed_at.isoformat(),
        "regime_context": snapshot.regime_context,
        "composite_score": snapshot.composite_score,
        "regime_strength": snapshot.regime_strength,
        "transition_warning": snapshot.transition_warning,
        "transition_direction": snapshot.transition_direction,
        "transition_reasons": snapshot.transition_reasons,
        "data_source": snapshot.data_source,
        "is_reliable": snapshot.is_reliable,
        "is_stale": is_stale,
        "stale_indicator_codes": stale_indicator_codes,
        "must_not_use_for_decision": must_not_use_for_decision,
        "blocked_reason": blocked_reason,
        "market_data_as_of": market_data_as_of,
        "indicator_observed_at": indicator_observed_at,
        "contract": contract,
        "dimensions": {
            ds.dimension: {
                "score": ds.score,
                "signal": ds.signal,
                "indicator_count": ds.indicator_count,
                "description": ds.description,
            }
            for ds in snapshot.dimension_scores
        },
        "indicators": [
            {
                "code": r.code,
                "name": r.name,
                "dimension": r.dimension,
                "value": r.value,
                "signal": r.signal,
                "signal_score": r.signal_score,
                "direction": r.direction,
                "is_stale": r.is_stale,
                "data_age_days": r.data_age_days,
                "observed_at": r.observed_at.isoformat() if r.observed_at else None,
                "source_kind": r.source_kind,
                **indicator_display.get(r.code, {}),
            }
            for r in snapshot.indicator_readings
        ],
    }
    normalized = _validated_json_payload(payload)
    if not isinstance(normalized, dict):
        raise PulseApiPayloadError("pulse_snapshot_payload_invalid")
    return cast(dict[str, Any], normalized)
