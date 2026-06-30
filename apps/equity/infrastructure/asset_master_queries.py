"""Infrastructure queries for equity asset-master backfill data."""

from __future__ import annotations

from typing import Any

from apps.equity.infrastructure.models import StockInfoModel


class EquityAssetMasterQueryRepository:
    """Read equity rows used by data-center asset master backfill."""

    def list_candidate_codes(self) -> list[str]:
        """Return stock codes that can seed data-center asset master rows."""

        return list(
            StockInfoModel._default_manager.exclude(stock_code__isnull=True).values_list(
                "stock_code",
                flat=True,
            )
        )

    def list_stock_rows(self, lookup_codes: list[str]) -> list[dict[str, Any]]:
        """Return stock rows used by the data-center asset master backfill."""

        if not lookup_codes:
            return []
        return list(
            StockInfoModel._default_manager.filter(stock_code__in=lookup_codes).values(
                "stock_code",
                "name",
                "sector",
                "market",
            )
        )
