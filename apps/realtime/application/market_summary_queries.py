"""Application facade for realtime market-summary breadth reads."""

from __future__ import annotations

from typing import Any

from apps.data_center.application.query_services import query_published_a_share_behavior_payload


def get_market_breadth_payload() -> dict[str, Any]:
    """Return governed current A-share behavior facts for the realtime API."""

    return query_published_a_share_behavior_payload()


__all__ = ["get_market_breadth_payload"]
