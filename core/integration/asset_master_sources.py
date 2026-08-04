"""Composition-time legacy sources for the Data Center asset-master backfill."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

AssetMasterRows = dict[str, list[dict[str, object]]]


class AssetMasterSourceProvider(Protocol):
    """Business-owned source contract injected into the Data Center backfill."""

    def collect_candidate_codes(self) -> list[str]:
        """Return legacy asset codes eligible for a full backfill."""

    def load_local_rows(
        self,
        *,
        lookup_codes: list[str],
        base_codes: list[str],
    ) -> AssetMasterRows:
        """Return source rows for the requested legacy codes."""


@dataclass(frozen=True)
class LegacyAssetMasterSourceProvider:
    """Adapter assembled at the composition boundary from owner query ports."""

    def collect_candidate_codes(self) -> list[str]:
        """Collect candidates without making Data Center import business apps."""

        from apps.asset_analysis.application.query_services import (
            list_asset_master_pool_candidate_codes,
        )
        from apps.equity.application.query_services import (
            list_asset_master_stock_candidate_codes,
        )
        from apps.fund.application.query_services import (
            list_asset_master_fund_candidate_codes,
        )
        from apps.rotation.application.query_services import (
            list_asset_master_rotation_candidate_codes,
        )

        codes: list[str] = []
        codes.extend(list_asset_master_stock_candidate_codes())
        codes.extend(list_asset_master_fund_candidate_codes())
        codes.extend(list_asset_master_rotation_candidate_codes())
        codes.extend(list_asset_master_pool_candidate_codes())
        return codes

    def load_local_rows(
        self,
        *,
        lookup_codes: list[str],
        base_codes: list[str],
    ) -> AssetMasterRows:
        """Load legacy rows through each business owner query port."""

        from apps.asset_analysis.application.query_services import list_asset_master_pool_rows
        from apps.equity.application.query_services import list_asset_master_stock_rows
        from apps.fund.application.query_services import (
            list_asset_master_fund_rows,
            list_asset_master_holding_rows,
        )
        from apps.rotation.application.query_services import list_asset_master_rotation_rows

        return {
            "stock_rows": list_asset_master_stock_rows(lookup_codes),
            "fund_rows": list_asset_master_fund_rows(base_codes),
            "holding_rows": list_asset_master_holding_rows(lookup_codes),
            "rotation_rows": list_asset_master_rotation_rows(base_codes),
            "pool_rows": list_asset_master_pool_rows(lookup_codes),
        }


def build_legacy_asset_master_source() -> AssetMasterSourceProvider:
    """Build the legacy source adapter at an explicit composition boundary."""

    return LegacyAssetMasterSourceProvider()


__all__ = [
    "AssetMasterRows",
    "AssetMasterSourceProvider",
    "LegacyAssetMasterSourceProvider",
    "build_legacy_asset_master_source",
]
