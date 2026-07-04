"""Infrastructure read models for data-center diagnostics."""

from __future__ import annotations

from datetime import date

from django.db.models import Q

from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialFactModel,
    MacroFactModel,
    PriceBarModel,
    ProviderConfigModel,
    ValuationFactModel,
)

MIN_ACTIVE_A_SHARE_COUNT = 4000
MIN_STAR_MARKET_COUNT = 200
MIN_BSE_COUNT = 50


class DataCenterDiagnosticRepository:
    """Read data-center summary counts for operational diagnostics."""

    def get_summary(self) -> dict[str, int]:
        """Return macro fact and provider configuration counts."""

        return {
            "macro_fact_count": MacroFactModel.objects.count(),
            "provider_config_count": ProviderConfigModel.objects.count(),
            "active_provider_config_count": ProviderConfigModel.objects.filter(
                is_active=True
            ).count(),
        }

    def macro_fact_exists_on_or_before(self, reporting_period: date) -> bool:
        """Return whether a macro fact exists on or before the reporting period."""

        return bool(
            MacroFactModel.objects.filter(reporting_period__lte=reporting_period).exists()
        )

    def get_active_stock_fact_coverage_summary(self) -> dict[str, object]:
        """Return production data coverage for active stock facts."""

        active_codes = list(
            AssetMasterModel.objects.filter(
                asset_type="stock",
                exchange__in=["SSE", "SZSE", "BSE"],
            )
            .filter(Q(is_active=True) | Q(is_active__isnull=True))
            .values_list("code", flat=True)
        )
        asset_count = len(active_codes)
        universe_quality = self._active_stock_universe_quality(active_codes)
        domains = {
            "price": self._fact_domain_summary(
                active_codes,
                model=PriceBarModel,
                date_field="bar_date",
            ),
            "valuation": self._fact_domain_summary(
                active_codes,
                model=ValuationFactModel,
                date_field="val_date",
            ),
            "financial": self._fact_domain_summary(
                active_codes,
                model=FinancialFactModel,
                date_field="period_end",
            ),
        }
        facts_ready = asset_count and all(
            domain["covered_count"] == asset_count for domain in domains.values()
        )
        return {
            "status": "ok" if facts_ready and universe_quality["status"] == "ok" else "incomplete",
            "universe": "active_stock",
            "asset_count": asset_count,
            "universe_quality": universe_quality,
            "domains": domains,
        }

    def _active_stock_universe_quality(self, active_codes: list[str]) -> dict[str, object]:
        board_counts = {
            "star_market": sum(
                code.startswith(("688", "689")) and code.endswith(".SH")
                for code in active_codes
            ),
            "chinext": sum(
                code.startswith(("300", "301")) and code.endswith(".SZ")
                for code in active_codes
            ),
            "bse": sum(code.endswith(".BJ") for code in active_codes),
            "sh_main": sum(
                code.startswith(("600", "601", "603", "605")) and code.endswith(".SH")
                for code in active_codes
            ),
            "sz_main": sum(
                code.startswith(("000", "001", "002")) and code.endswith(".SZ")
                for code in active_codes
            ),
        }
        exchange_counts = {"SSE": 0, "SZSE": 0, "BSE": 0}
        for code in active_codes:
            if code.endswith(".SH"):
                exchange_counts["SSE"] += 1
            elif code.endswith(".SZ"):
                exchange_counts["SZSE"] += 1
            elif code.endswith(".BJ"):
                exchange_counts["BSE"] += 1

        issues: list[str] = []
        if len(active_codes) < MIN_ACTIVE_A_SHARE_COUNT:
            issues.append("active_a_share_universe_too_narrow")
        if board_counts["star_market"] < MIN_STAR_MARKET_COUNT:
            issues.append("star_market_undercovered")
        if board_counts["bse"] < MIN_BSE_COUNT:
            issues.append("bse_undercovered")

        return {
            "status": "ok" if not issues else "incomplete",
            "minimum_active_a_share_count": MIN_ACTIVE_A_SHARE_COUNT,
            "minimum_star_market_count": MIN_STAR_MARKET_COUNT,
            "minimum_bse_count": MIN_BSE_COUNT,
            "exchange_counts": exchange_counts,
            "board_counts": board_counts,
            "issues": issues,
        }

    def _fact_domain_summary(
        self,
        active_codes: list[str],
        *,
        model,
        date_field: str,
    ) -> dict[str, object]:
        if not active_codes:
            return {
                "covered_count": 0,
                "missing_count": 0,
                "latest_date": None,
                "status": "empty",
            }

        queryset = model.objects.filter(asset_code__in=active_codes)
        covered_count = queryset.values("asset_code").distinct().count()
        latest = queryset.order_by(f"-{date_field}").values_list(date_field, flat=True).first()
        missing_count = len(active_codes) - covered_count
        return {
            "covered_count": covered_count,
            "missing_count": missing_count,
            "latest_date": latest.isoformat() if latest else None,
            "status": "ok" if missing_count == 0 else "incomplete",
        }
