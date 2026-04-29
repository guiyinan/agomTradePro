"""Normalize legacy macro fact rows to canonical storage units."""

from __future__ import annotations

from decimal import Decimal

from django.core.management import BaseCommand
from django.db import transaction

from apps.data_center.infrastructure.models import MacroFactModel
from apps.data_center.infrastructure.repositories import IndicatorUnitRuleRepository


def _split_codes(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


class Command(BaseCommand):
    help = (
        "Normalize legacy data_center_macro_fact rows to canonical storage value/unit "
        "using IndicatorUnitRule."
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

    @transaction.atomic
    def handle(self, *args, **options):
        indicator_codes = _split_codes(options.get("indicator_codes"))
        dry_run = bool(options.get("dry_run"))
        rule_repo = IndicatorUnitRuleRepository()

        queryset = MacroFactModel.objects.all().order_by("indicator_code", "reporting_period", "id")
        if indicator_codes:
            queryset = queryset.filter(indicator_code__in=indicator_codes)

        updated_count = 0
        skipped_count = 0
        unchanged_count = 0

        for fact in queryset.iterator():
            action = self._normalize_fact(fact, rule_repo, dry_run=dry_run)
            if action == "updated":
                updated_count += 1
            elif action == "skipped":
                skipped_count += 1
            else:
                unchanged_count += 1

        if dry_run:
            transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                "normalize_macro_fact_units complete: "
                f"updated={updated_count}, unchanged={unchanged_count}, skipped={skipped_count}, "
                f"dry_run={dry_run}"
            )
        )

    def _normalize_fact(
        self,
        fact: MacroFactModel,
        rule_repo: IndicatorUnitRuleRepository,
        *,
        dry_run: bool,
    ) -> str:
        extra = dict(fact.extra or {})
        source_type = str(extra.get("source_type") or "")
        raw_unit = str(extra.get("original_unit") or fact.unit or "")

        rule = rule_repo.resolve_active_rule(
            fact.indicator_code,
            source_type=source_type,
            original_unit=raw_unit or None,
        )
        if rule is None:
            rule = rule_repo.resolve_active_rule(
                fact.indicator_code,
                source_type=source_type,
            )
        if rule is None:
            self.stdout.write(
                self.style.WARNING(
                    f"skip {fact.indicator_code} {fact.reporting_period}: no unit rule"
                )
            )
            return "skipped"

        original_unit = rule.original_unit or raw_unit or fact.unit or ""
        current_value = Decimal(str(fact.value))
        normalized_value = current_value
        normalized_unit = fact.unit or ""

        if fact.unit != rule.storage_unit:
            if fact.unit in {rule.original_unit, rule.display_unit, "", None}:
                normalized_value = current_value * Decimal(str(rule.multiplier_to_storage))
                normalized_unit = rule.storage_unit
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"skip {fact.indicator_code} {fact.reporting_period}: "
                        f"ambiguous unit {fact.unit!r} for rule storage={rule.storage_unit!r}"
                    )
                )
                return "skipped"

        publication_lag_days = extra.get("publication_lag_days")
        if publication_lag_days is None and fact.published_at:
            publication_lag_days = max((fact.published_at - fact.reporting_period).days, 0)

        normalized_extra = {
            **extra,
            "original_unit": original_unit,
            "display_unit": rule.display_unit,
            "dimension_key": rule.dimension_key,
            "multiplier_to_storage": float(rule.multiplier_to_storage),
            "source_type": source_type,
        }
        if publication_lag_days is not None:
            normalized_extra["publication_lag_days"] = publication_lag_days

        changed = (
            normalized_value != current_value
            or normalized_unit != fact.unit
            or normalized_extra != extra
        )
        if not changed:
            return "unchanged"

        if not dry_run:
            fact.value = normalized_value
            fact.unit = normalized_unit
            fact.extra = normalized_extra
            fact.save(update_fields=["value", "unit", "extra"])

        self.stdout.write(
            f"{'plan' if dry_run else 'fix'} {fact.indicator_code} {fact.reporting_period}: "
            f"{current_value} {fact.unit or '-'} -> {normalized_value} {normalized_unit or '-'}"
        )
        return "updated"
