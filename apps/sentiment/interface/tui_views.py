"""Typed TUI read adapter for the sentiment dashboard."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sentiment.application.interface_services import (
    get_recent_sentiment_indices_payload,
    get_sentiment_health_payload,
)


def _parse_days(value: str) -> int:
    """Parse a bounded recent-index window."""

    days = int(value or "30")
    if days < 1 or days > 365:
        raise ValueError("days 必须在 1 到 365 之间")
    return days


def _number(mapping: dict[str, Any], *keys: str) -> float:
    """Return the first present numeric value from a boundary mapping."""

    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return round(float(value), 6)
    return 0.0


class SentimentTuiOverviewView(APIView):
    """Return dashboard summary and portable recent sentiment rows."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return a read-only sentiment snapshot for TUI table and chart views."""

        try:
            days = _parse_days(str(request.query_params.get("days") or "30"))
        except (TypeError, ValueError) as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recent_payload = get_recent_sentiment_indices_payload(days=days)
        health = get_sentiment_health_payload()
        rows: list[dict[str, Any]] = []
        for raw_row in recent_payload.get("indices") or []:
            if not isinstance(raw_row, dict):
                continue
            index = dict(raw_row.get("index") or {})
            sources = dict(raw_row.get("sources") or {})
            rows.append(
                {
                    "date": str(raw_row.get("date") or ""),
                    "composite": _number(index, "composite", "overall"),
                    "news": _number(index, "news"),
                    "policy": _number(index, "policy"),
                    "level": str(raw_row.get("level") or ""),
                    "confidence_percent": round(
                        float(raw_row.get("confidence") or 0) * 100,
                        6,
                    ),
                    "data_sufficient": bool(raw_row.get("data_sufficient", False)),
                    "news_count": int(sources.get("news_count", sources.get("news", 0)) or 0),
                    "policy_events_count": int(
                        sources.get(
                            "policy_events_count",
                            sources.get("policy", 0),
                        )
                        or 0
                    ),
                }
            )
        latest = rows[0] if rows else {}
        return Response(
            {
                "success": True,
                "summary": {
                    "service_status": str(health.get("status") or "unknown"),
                    "ai_provider_available": bool(health.get("ai_provider_available", False)),
                    "cache_count": int(health.get("cache_count") or 0),
                    "latest_index_date": str(
                        health.get("latest_index_date") or latest.get("date") or ""
                    ),
                    "latest_composite": latest.get("composite"),
                    "latest_news": latest.get("news"),
                    "latest_policy": latest.get("policy"),
                    "latest_level": str(latest.get("level") or ""),
                    "latest_confidence_percent": latest.get("confidence_percent"),
                    "latest_data_sufficient": bool(latest.get("data_sufficient", False)),
                    "freshness_status": str(health.get("freshness_status") or "unknown"),
                    "must_not_use_for_decision": bool(
                        health.get("must_not_use_for_decision", True)
                    ),
                    "blocked_reason": str(health.get("blocked_reason") or ""),
                },
                "indices": rows,
                "total": len(rows),
                "days": days,
            }
        )
