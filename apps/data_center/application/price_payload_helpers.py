"""Pure payload mappings for Data Center price queries."""

from __future__ import annotations

from typing import Any

from apps.data_center.domain.entities import PriceBar


def _price_bar_payload(bar: PriceBar) -> dict[str, Any]:
    """Serialize one canonical price bar using the stable cross-app payload shape."""

    return {
        "asset_code": bar.asset_code,
        "timestamp": bar.bar_date.isoformat(),
        "period": bar.freq,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume) if bar.volume is not None else None,
        "amount": float(bar.amount) if bar.amount is not None else None,
        "source": bar.source,
        "fetched_at": bar.fetched_at.isoformat(),
    }
