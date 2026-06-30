"""Infrastructure read models for policy diagnostics."""

from __future__ import annotations

from collections import Counter
from typing import Any

from apps.policy.infrastructure.models import PolicyLog, RSSSourceConfigModel


class PolicyDiagnosticRepository:
    """Read policy summary rows for operational diagnostics."""

    def get_policy_event_count(self) -> int:
        """Return the number of policy events."""

        return int(PolicyLog.objects.count())

    def get_recent_event_summary(self, *, limit: int = 10) -> dict[str, Any]:
        """Return recent policy event level counts and latest event details."""

        if limit <= 0:
            return {"level_summary": {}, "latest": None}
        recent_events = list(PolicyLog.objects.order_by("-event_date")[:limit])
        if not recent_events:
            return {"level_summary": {}, "latest": None}
        level_summary = dict(Counter(event.level for event in recent_events))
        latest = recent_events[0]
        return {
            "level_summary": level_summary,
            "latest": {
                "event_date": latest.event_date,
                "level": latest.level,
                "title": latest.title,
            },
        }

    def get_rss_source_summary(self) -> dict[str, int]:
        """Return RSS source counts."""

        return {
            "rss_count": RSSSourceConfigModel.objects.count(),
            "active_rss_count": RSSSourceConfigModel.objects.filter(is_active=True).count(),
        }
