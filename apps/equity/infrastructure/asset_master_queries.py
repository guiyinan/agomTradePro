"""Infrastructure queries for equity asset-master backfill data."""

from __future__ import annotations

from typing import Any

from apps.data_center.application.public import get_asset_repository_port
from apps.data_center.domain.enums import AssetType


class EquityAssetMasterQueryRepository:
    """Read equity rows used by data-center asset master backfill."""

    def list_candidate_codes(self) -> list[str]:
        """Return canonical stock codes eligible for a bounded refresh."""

        return [
            asset.code
            for asset in get_asset_repository_port().list_active()
            if asset.asset_type is AssetType.STOCK
        ]

    def list_stock_rows(self, lookup_codes: list[str]) -> list[dict[str, Any]]:
        """Return canonical stock rows used by the data-center asset refresh."""

        if not lookup_codes:
            return []
        rows: list[dict[str, Any]] = []
        repository = get_asset_repository_port()
        for code in lookup_codes:
            asset = repository.get_by_code(code)
            if asset is None or asset.asset_type is not AssetType.STOCK:
                continue
            rows.append(
                {
                    "stock_code": asset.code,
                    "name": asset.name,
                    "sector": asset.sector or asset.industry,
                    "market": asset.exchange.value,
                }
            )
        return rows
