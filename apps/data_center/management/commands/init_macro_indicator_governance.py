"""Initialize macro indicator semantics and chart governance metadata."""

from __future__ import annotations

from django.core.management import BaseCommand, CommandError

from apps.data_center.infrastructure.models import IndicatorCatalogModel
from apps.data_center.infrastructure.seed_data.macro_indicator_governance import (
    INDICATOR_METADATA_UPDATES,
    merge_governance_extra,
)


def _split_codes(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


class Command(BaseCommand):
    help = (
        "Seed macro indicator series semantics, compatibility alias metadata, and "
        "chart_policy into IndicatorCatalog.extra."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--indicator-codes",
            dest="indicator_codes",
            default=None,
            help="Comma-separated indicator codes to limit the repair scope.",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=False,
            help="Preview changes without saving them.",
        )
        parser.add_argument(
            "--strict",
            dest="strict",
            action="store_true",
            default=False,
            help="Fail if any active indicator in scope still lacks explicit series_semantics.",
        )

    def handle(self, *args, **options):
        indicator_codes = set(_split_codes(options.get("indicator_codes")))
        dry_run = bool(options.get("dry_run"))
        strict = bool(options.get("strict"))

        target_updates = {
            code: payload
            for code, payload in INDICATOR_METADATA_UPDATES.items()
            if not indicator_codes or code in indicator_codes
        }
        scoped_qs = IndicatorCatalogModel.objects.filter(is_active=True)
        if indicator_codes:
            scoped_qs = scoped_qs.filter(code__in=sorted(indicator_codes))

        updated_count = 0
        unchanged_count = 0
        missing_catalog_codes: list[str] = []

        for code, payload in target_updates.items():
            indicator = IndicatorCatalogModel.objects.filter(code=code).first()
            if indicator is None:
                missing_catalog_codes.append(code)
                continue

            merged_extra = merge_governance_extra(indicator.extra, payload["extra"])
            update_fields: list[str] = []

            if indicator.name_cn != payload["name_cn"]:
                indicator.name_cn = payload["name_cn"]
                update_fields.append("name_cn")
            if indicator.description != payload["description"]:
                indicator.description = payload["description"]
                update_fields.append("description")
            if indicator.extra != merged_extra:
                indicator.extra = merged_extra
                update_fields.append("extra")

            if not update_fields:
                unchanged_count += 1
                continue

            updated_count += 1
            if not dry_run:
                indicator.save(update_fields=update_fields)

        for indicator in scoped_qs.order_by("code"):
            if indicator.code in target_updates:
                continue
            if not (indicator.extra or {}).get("series_semantics"):
                continue

            merged_extra = merge_governance_extra(indicator.extra, {})
            if indicator.extra == merged_extra:
                continue

            updated_count += 1
            if not dry_run:
                indicator.extra = merged_extra
                indicator.save(update_fields=["extra"])

        uncovered_codes = [
            indicator.code
            for indicator in scoped_qs.order_by("code")
            if not (indicator.extra or {}).get("series_semantics")
        ]

        if missing_catalog_codes:
            self.stdout.write(
                self.style.WARNING(
                    "catalog rows missing for seeded codes: "
                    + ", ".join(sorted(missing_catalog_codes))
                )
            )

        if uncovered_codes:
            self.stdout.write(
                self.style.WARNING(
                    "active indicators still missing explicit series_semantics: "
                    + ", ".join(uncovered_codes)
                )
            )

        summary = (
            "init_macro_indicator_governance complete: "
            f"updated={updated_count}, unchanged={unchanged_count}, "
            f"missing_catalog={len(missing_catalog_codes)}, uncovered={len(uncovered_codes)}, "
            f"dry_run={dry_run}"
        )
        if strict and uncovered_codes:
            raise CommandError(summary)

        self.stdout.write(self.style.SUCCESS(summary))
