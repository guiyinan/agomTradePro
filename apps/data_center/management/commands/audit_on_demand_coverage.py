"""Audit on-demand Data Center coverage without hydrating by default."""

from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.data_center.application.interface_services import make_on_demand_data_center_service
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialFactModel,
    PriceBarModel,
    QuoteSnapshotModel,
    ValuationFactModel,
)
from apps.equity.infrastructure.models import StockInfoModel


class Command(BaseCommand):
    help = "Dry-run audit for single-asset Data Center price/valuation/financial/quote coverage."

    def add_arguments(self, parser):
        parser.add_argument("--asset-code", action="append", dest="asset_codes", default=[])
        parser.add_argument(
            "--universe",
            choices=["visible", "active", "all"],
            default="visible",
        )
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--hydrate", action="store_true")
        parser.add_argument("--lookback-days", type=int, default=365)
        parser.add_argument("--sample-size", type=int, default=20)

    def handle(self, *args, **options):
        end_date = timezone.localdate()
        start_date = end_date - timedelta(days=options["lookback_days"])
        service = make_on_demand_data_center_service()
        asset_codes = self._resolve_universe(options["universe"], options["asset_codes"])

        results = {
            "mode": "hydrate" if options["hydrate"] else "dry_run",
            "universe": options["universe"],
            "asset_count": len(asset_codes),
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "domains": {
                "price": {},
                "valuation": {},
                "financial": {},
                "quote": {},
            },
        }

        for code in asset_codes:
            if options["hydrate"]:
                price = service.ensure_price_bars(code, start_date, end_date)
                valuation = service.ensure_valuations(code, start_date, end_date)
                financial = service.ensure_financials(code, periods=8)
                quote = service.ensure_intraday(code)
            else:
                price = service.assess_price_bars(code, start_date, end_date)
                valuation = service.assess_valuations(code, start_date, end_date)
                financial = service.assess_financials(code, periods=8)
                quote = service.assess_intraday(code)

            self._append_domain_result(results["domains"]["price"], code, price.quality.to_dict())
            self._append_domain_result(
                results["domains"]["valuation"], code, valuation.quality.to_dict()
            )
            self._append_domain_result(
                results["domains"]["financial"], code, financial.quality.to_dict()
            )
            self._append_domain_result(results["domains"]["quote"], code, quote.quality.to_dict())

        payload = self._summarize(results, sample_size=options["sample_size"])
        if options["as_json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write(
            f"Data Center coverage audit ({payload['mode']}): "
            f"{payload['asset_count']} assets, {payload['start']} -> {payload['end']}"
        )
        for domain, summary in payload["domains"].items():
            counts = summary["counts"]
            self.stdout.write(
                f"- {domain}: "
                f"fresh={counts.get('fresh', 0)} stale={counts.get('stale', 0)} "
                f"sparse={counts.get('sparse', 0)} missing={counts.get('missing', 0)} "
                f"provider_failed={counts.get('provider_failed', 0)}"
            )
            for item in summary["issues"][: options["sample_size"]]:
                self.stdout.write(
                    f"  {item['asset_code']} {item['status']} "
                    f"{item.get('coverage_start')}..{item.get('coverage_end')} "
                    f"n={item.get('points_count')}"
                )

    def _resolve_universe(self, universe: str, explicit_codes: list[str]) -> list[str]:
        if explicit_codes:
            return sorted({str(code).strip().upper() for code in explicit_codes if code})

        if universe == "visible":
            codes = set(
                StockInfoModel._default_manager.filter(is_active=True).values_list(
                    "stock_code", flat=True
                )
            )
            codes.update(
                PriceBarModel._default_manager.values_list("asset_code", flat=True).distinct()
            )
            codes.update(
                ValuationFactModel._default_manager.values_list("asset_code", flat=True).distinct()
            )
            codes.update(
                FinancialFactModel._default_manager.values_list("asset_code", flat=True).distinct()
            )
            codes.update(
                QuoteSnapshotModel._default_manager.values_list("asset_code", flat=True).distinct()
            )
            return sorted({str(code).strip().upper() for code in codes if code})

        asset_qs = AssetMasterModel._default_manager.filter(
            asset_type="stock",
            exchange__in=["SSE", "SZSE", "BSE"],
        )
        if universe in {"active", "all"}:
            asset_qs = asset_qs.filter(Q(is_active=True) | Q(is_active__isnull=True))
        codes = set(asset_qs.values_list("code", flat=True))
        codes.update(
            StockInfoModel._default_manager.filter(is_active=True).values_list(
                "stock_code", flat=True
            )
        )
        return sorted({str(code).strip().upper() for code in codes if code})

    def _append_domain_result(
        self,
        domain_results: dict[str, list[dict[str, object]]],
        asset_code: str,
        quality: dict[str, object],
    ) -> None:
        status = str(quality["status"])
        item = {"asset_code": asset_code, **quality}
        domain_results.setdefault(status, []).append(item)

    def _summarize(self, results: dict[str, object], *, sample_size: int) -> dict[str, object]:
        summarized_domains = {}
        for domain, by_status in results["domains"].items():
            counts = {status: len(items) for status, items in by_status.items()}
            issues = []
            for status in ("provider_failed", "missing", "sparse", "stale"):
                issues.extend(by_status.get(status, []))
            summarized_domains[domain] = {
                "counts": counts,
                "issues": issues[:sample_size],
            }
        return {
            **results,
            "domains": summarized_domains,
        }
