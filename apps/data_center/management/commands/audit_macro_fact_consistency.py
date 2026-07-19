"""Audit canonical macro facts for revision and cross-source inconsistencies."""

from __future__ import annotations

import json
from collections import defaultdict

from django.core.management import BaseCommand, CommandError

from apps.data_center.domain.rules import (
    macro_fact_preference_key,
    macro_series_are_consistent,
)
from apps.data_center.infrastructure.macro_fact_selection import (
    configured_macro_source,
    macro_fact_source_key,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel


class Command(BaseCommand):
    help = "Audit revision conflicts and cross-source macro-fact consistency."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", default=False)
        parser.add_argument("--tolerance", type=float, default=0.01)
        parser.add_argument("--max-examples", type=int, default=20)

    def handle(self, *args, **options):
        tolerance = float(options["tolerance"])
        max_examples = max(int(options["max_examples"]), 0)
        catalogs = {
            row.code: configured_macro_source(row.extra)
            for row in IndicatorCatalogModel.objects.only("code", "extra")
        }
        facts_by_indicator: dict[str, list[MacroFactModel]] = defaultdict(list)
        for fact in MacroFactModel.objects.order_by("indicator_code", "reporting_period", "id"):
            facts_by_indicator[fact.indicator_code].append(fact)

        canonical_legacy_conflicts: list[dict[str, object]] = []
        cross_source_conflicts: list[dict[str, object]] = []
        configured_source_missing: list[dict[str, object]] = []

        for indicator_code, facts in facts_by_indicator.items():
            by_source_period: dict[tuple[str, object], list[MacroFactModel]] = defaultdict(list)
            by_source: dict[str, dict[object, float]] = defaultdict(dict)
            for fact in facts:
                source_key = macro_fact_source_key(fact)
                by_source_period[(source_key, fact.reporting_period)].append(fact)

            for (source_key, reporting_period), revisions in by_source_period.items():
                preferred = max(revisions, key=macro_fact_preference_key)
                by_source[source_key][reporting_period] = float(preferred.value)
                values = {float(item.value) for item in revisions}
                canonical_markers = {
                    bool(str((item.extra or {}).get("provider_name") or "").strip())
                    for item in revisions
                }
                if len(values) > 1 and len(canonical_markers) > 1:
                    canonical_legacy_conflicts.append(
                        {
                            "indicator_code": indicator_code,
                            "source": source_key,
                            "reporting_period": reporting_period.isoformat(),
                            "values": sorted(values),
                        }
                    )

            preferred_source = catalogs.get(indicator_code, "")
            if preferred_source and preferred_source not in by_source:
                configured_source_missing.append(
                    {
                        "indicator_code": indicator_code,
                        "configured_source": preferred_source,
                    }
                )

            sources = sorted(by_source)
            for index, primary_source in enumerate(sources):
                for backup_source in sources[index + 1 :]:
                    is_consistent, difference = macro_series_are_consistent(
                        by_source[primary_source],
                        by_source[backup_source],
                        tolerance=tolerance,
                    )
                    if not is_consistent:
                        cross_source_conflicts.append(
                            {
                                "indicator_code": indicator_code,
                                "primary_source": primary_source,
                                "backup_source": backup_source,
                                "max_difference_ratio": difference,
                                "governed_source": preferred_source,
                            }
                        )

        ungoverned_conflicts = [
            item for item in cross_source_conflicts if not item["governed_source"]
        ]
        payload = {
            "summary": {
                "indicator_count": len(facts_by_indicator),
                "fact_count": sum(len(items) for items in facts_by_indicator.values()),
                "canonical_legacy_conflict_count": len(canonical_legacy_conflicts),
                "cross_source_conflict_count": len(cross_source_conflicts),
                "ungoverned_cross_source_conflict_count": len(ungoverned_conflicts),
                "configured_source_missing_count": len(configured_source_missing),
                "tolerance": tolerance,
            },
            "canonical_legacy_conflicts": canonical_legacy_conflicts[:max_examples],
            "cross_source_conflicts": cross_source_conflicts[:max_examples],
            "configured_source_missing": configured_source_missing[:max_examples],
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        if options["strict"] and (ungoverned_conflicts or configured_source_missing):
            raise CommandError("Macro fact consistency audit found ungoverned blocking issues.")
