"""Infrastructure read models for data-center diagnostics."""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from django.db import models
from django.db.models import Q

from apps.data_center.domain.entities import ProductionCoverageUniverseConfig
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialFactModel,
    MacroFactModel,
    PriceBarModel,
    ProviderConfigModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.repositories import (
    ProductionCoverageUniverseConfigRepository,
)


class _FactDomainSummary(TypedDict):
    """Typed coverage summary for one persisted fact domain."""

    covered_count: int
    missing_count: int
    latest_date: str | None
    status: str


class _UniverseQualitySummary(TypedDict):
    """Typed quality result for the configured production universe."""

    status: str
    minimum_active_a_share_count: int
    minimum_star_market_count: int
    minimum_chinext_count: int
    minimum_bse_count: int
    exchange_counts: dict[str, int]
    board_counts: dict[str, int]
    issues: list[str]


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

        return bool(MacroFactModel.objects.filter(reporting_period__lte=reporting_period).exists())

    def get_active_stock_fact_coverage_summary(self) -> dict[str, object]:
        """Return production data coverage for active stock facts."""

        config = ProductionCoverageUniverseConfigRepository().load()
        universe_queryset = AssetMasterModel.objects.filter(
            asset_type=config.asset_type,
            exchange__in=config.exchanges,
        )
        if not config.include_inactive:
            universe_queryset = universe_queryset.filter(
                Q(is_active=True) | Q(is_active__isnull=True)
            )
        active_codes = [str(code) for code in universe_queryset.values_list("code", flat=True)]
        asset_count = len(active_codes)
        universe_quality = self._active_stock_universe_quality(active_codes, config)
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
        facts_ready = asset_count > 0 and all(
            domain["covered_count"] == asset_count for domain in domains.values()
        )
        return {
            "status": "ok" if facts_ready and universe_quality["status"] == "ok" else "incomplete",
            "universe": config.universe_id,
            "asset_count": asset_count,
            "universe_config": config.to_dict(),
            "universe_quality": universe_quality,
            "domains": domains,
        }

    def list_active_stock_codes(self) -> list[str]:
        """Return the configured production A-share universe in stable code order."""

        config = ProductionCoverageUniverseConfigRepository().load()
        queryset = AssetMasterModel.objects.filter(
            asset_type=config.asset_type,
            exchange__in=config.exchanges,
        )
        if not config.include_inactive:
            queryset = queryset.filter(Q(is_active=True) | Q(is_active__isnull=True))
        return [str(code) for code in queryset.order_by("code").values_list("code", flat=True)]

    def _active_stock_universe_quality(
        self,
        active_codes: list[str],
        config: ProductionCoverageUniverseConfig,
    ) -> _UniverseQualitySummary:
        board_counts = {
            "star_market": sum(
                code.startswith(("688", "689")) and code.endswith(".SH") for code in active_codes
            ),
            "chinext": sum(
                code.startswith(("300", "301")) and code.endswith(".SZ") for code in active_codes
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
        configured_exchanges = list(config.exchanges)
        exchange_counts = dict.fromkeys(configured_exchanges, 0)
        for code in active_codes:
            if code.endswith(".SH"):
                exchange_counts["SSE"] = exchange_counts.get("SSE", 0) + 1
            elif code.endswith(".SZ"):
                exchange_counts["SZSE"] = exchange_counts.get("SZSE", 0) + 1
            elif code.endswith(".BJ"):
                exchange_counts["BSE"] = exchange_counts.get("BSE", 0) + 1

        issues: list[str] = []
        min_active = config.min_active_asset_count
        min_star = config.min_star_market_count
        min_chinext = config.min_chinext_count
        min_bse = config.min_bse_count
        if len(active_codes) < min_active:
            issues.append("active_a_share_universe_too_narrow")
        if board_counts["star_market"] < min_star:
            issues.append("star_market_undercovered")
        if board_counts["chinext"] < min_chinext:
            issues.append("chinext_undercovered")
        if board_counts["bse"] < min_bse:
            issues.append("bse_undercovered")

        return {
            "status": "ok" if not issues else "incomplete",
            "minimum_active_a_share_count": min_active,
            "minimum_star_market_count": min_star,
            "minimum_chinext_count": min_chinext,
            "minimum_bse_count": min_bse,
            "exchange_counts": exchange_counts,
            "board_counts": board_counts,
            "issues": issues,
        }

    def _fact_domain_summary(
        self,
        active_codes: list[str],
        *,
        model: type[models.Model],
        date_field: str,
    ) -> _FactDomainSummary:
        if not active_codes:
            return {
                "covered_count": 0,
                "missing_count": 0,
                "latest_date": None,
                "status": "empty",
            }

        queryset = model._default_manager.filter(asset_code__in=active_codes)
        covered_count = queryset.values("asset_code").distinct().count()
        latest_value: object = (
            queryset.order_by(f"-{date_field}").values_list(date_field, flat=True).first()
        )
        latest_date = latest_value.isoformat() if isinstance(latest_value, date) else None
        missing_count = len(active_codes) - covered_count
        return {
            "covered_count": covered_count,
            "missing_count": missing_count,
            "latest_date": latest_date,
            "status": "ok" if missing_count == 0 and latest_date is not None else "incomplete",
        }
