"""Audit on-demand Data Center coverage without hydrating by default."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
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


class Command(BaseCommand):
    help = "Dry-run audit for single-asset Data Center price/valuation/financial/quote coverage."

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        """Register bounded coverage-audit options."""

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

    def handle(self, *args: Any, **options: Any) -> None:
        """Audit the requested universe without hydrating unless explicitly enabled."""

        lookback_days = self._positive_int_option(
            options.get("lookback_days"), name="lookback-days", maximum=3650
        )
        sample_size = self._positive_int_option(
            options.get("sample_size"), name="sample-size", maximum=1000
        )
        universe = options.get("universe")
        if universe not in {"visible", "active", "all"}:
            raise CommandError("universe must be one of: visible, active, all")
        raw_asset_codes = options.get("asset_codes")
        if not isinstance(raw_asset_codes, list) or not all(
            isinstance(code, str) for code in raw_asset_codes
        ):
            raise CommandError("asset-code must be supplied as text")
        if len(raw_asset_codes) > 1000:
            raise CommandError("asset-code accepts at most 1000 values")
        for option_name in ("hydrate", "as_json"):
            if not isinstance(options.get(option_name), bool):
                raise CommandError(f"{option_name.replace('_', '-')} must be a boolean flag")

        end_date = timezone.localdate()
        start_date = end_date - timedelta(days=lookback_days)
        service = make_on_demand_data_center_service()
        asset_codes = self._resolve_universe(universe, raw_asset_codes)

        results: dict[str, Any] = {
            "mode": "hydrate" if options["hydrate"] else "dry_run",
            "universe": universe,
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

        payload = self._summarize(results, sample_size=sample_size)
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
            for item in summary["issues"][:sample_size]:
                self.stdout.write(
                    f"  {item['asset_code']} {item['status']} "
                    f"{item.get('coverage_start')}..{item.get('coverage_end')} "
                    f"n={item.get('points_count')}"
                )

    def _resolve_universe(self, universe: str, explicit_codes: list[str]) -> list[str]:
        if explicit_codes:
            return sorted({str(code).strip().upper() for code in explicit_codes if code})

        active_stock_codes = set(
            AssetMasterModel._default_manager.filter(
                asset_type="stock",
                exchange__in=["SSE", "SZSE", "BSE"],
            )
            .filter(Q(is_active=True) | Q(is_active__isnull=True))
            .values_list("code", flat=True)
        )

        if universe == "visible":
            codes = set(active_stock_codes)
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

    def _summarize(self, results: dict[str, Any], *, sample_size: int) -> dict[str, Any]:
        summarized_domains: dict[str, dict[str, Any]] = {}
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

    @staticmethod
    def _positive_int_option(value: object, *, name: str, maximum: int) -> int:
        """Return one validated positive integer CLI option."""

        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise CommandError(f"{name} must be an integer between 1 and {maximum}")
        return value
