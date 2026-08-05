"""Application facade for realtime market-summary breadth reads."""

from __future__ import annotations

from typing import Any

from apps.data_center.application.public import get_market_breadth_snapshot


def get_market_breadth_payload() -> dict[str, Any]:
    """Return governed current A-share behavior facts for the realtime API."""

    return get_market_breadth_snapshot()


__all__ = ["get_market_breadth_payload"]
