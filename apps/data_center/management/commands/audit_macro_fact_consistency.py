"""Audit canonical macro facts without false-clean or unbounded-memory results."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Generator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from apps.data_center.domain.rules import (
    MacroFactPreferenceCandidate,
    macro_fact_preference_key,
    macro_series_are_consistent,
)
from apps.data_center.infrastructure.macro_fact_selection import (
    configured_macro_source,
    macro_fact_source_key,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel
from shared.numeric import safe_float

DEFAULT_TOLERANCE = 0.01
DEFAULT_MAX_EXAMPLES = 20
QUERY_CHUNK_SIZE = 2_000


@dataclass
class AuditAccumulator:
    """Bounded examples and complete counters for one audit run."""

    indicator_count: int = 0
    fact_count: int = 0
    canonical_legacy_conflict_count: int = 0
    cross_source_conflict_count: int = 0
    ungoverned_cross_source_conflict_count: int = 0
    configured_source_missing_count: int = 0
    canonical_legacy_conflicts: list[dict[str, object]] = field(default_factory=list)
    cross_source_conflicts: list[dict[str, object]] = field(default_factory=list)
    configured_source_missing: list[dict[str, object]] = field(default_factory=list)

    @property
    def has_blocking_issues(self) -> bool:
        """Return whether strict mode must fail the deployment guard."""

        return bool(
            self.ungoverned_cross_source_conflict_count or self.configured_source_missing_count
        )

    def as_payload(self, *, tolerance: float) -> dict[str, object]:
        """Return the stable JSON-compatible command payload."""

        return {
            "summary": {
                "indicator_count": self.indicator_count,
                "fact_count": self.fact_count,
                "canonical_legacy_conflict_count": self.canonical_legacy_conflict_count,
                "cross_source_conflict_count": self.cross_source_conflict_count,
                "ungoverned_cross_source_conflict_count": (
                    self.ungoverned_cross_source_conflict_count
                ),
                "configured_source_missing_count": self.configured_source_missing_count,
                "tolerance": tolerance,
            },
            "canonical_legacy_conflicts": self.canonical_legacy_conflicts,
            "cross_source_conflicts": self.cross_source_conflicts,
            "configured_source_missing": self.configured_source_missing,
        }


class Command(BaseCommand):
    """Report revision and cross-source conflicts for canonical macro facts."""

    help = "Audit revision conflicts and cross-source macro-fact consistency."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register strict-mode and bounded report controls."""

        parser.add_argument("--strict", action="store_true", default=False)
        parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
        parser.add_argument("--max-examples", type=int, default=DEFAULT_MAX_EXAMPLES)

    def handle(self, *args: object, **options: object) -> None:
        """Validate options, stream facts, and emit one deterministic audit report."""

        del args
        strict = self._parse_strict(options.get("strict", False))
        tolerance = self._parse_tolerance(options.get("tolerance", DEFAULT_TOLERANCE))
        max_examples = self._parse_max_examples(options.get("max_examples", DEFAULT_MAX_EXAMPLES))

        try:
            audit = self._run_audit(
                tolerance=tolerance,
                max_examples=max_examples,
            )
            rendered = json.dumps(
                audit.as_payload(tolerance=tolerance),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        except (DatabaseError, TypeError, ValueError, OverflowError) as exc:
            raise CommandError(
                f"Macro fact consistency audit failed: {type(exc).__name__}"
            ) from exc

        self.stdout.write(rendered)
        if strict and audit.has_blocking_issues:
            raise CommandError("Macro fact consistency audit found ungoverned blocking issues.")

    @staticmethod
    def _parse_strict(raw_value: object) -> bool:
        """Require a real boolean from CLI and dynamic callers."""

        if not isinstance(raw_value, bool):
            raise CommandError("--strict must be a boolean")
        return raw_value

    @staticmethod
    def _parse_tolerance(raw_value: object) -> float:
        """Require the same finite [0, 1] ratio used by failover settings."""

        if isinstance(raw_value, bool):
            raise CommandError("--tolerance must be a finite number in [0, 1]")
        tolerance = safe_float(raw_value)
        if tolerance is None or not 0.0 <= tolerance <= 1.0:
            raise CommandError("--tolerance must be a finite number in [0, 1]")
        return float(tolerance)

    @staticmethod
    def _parse_max_examples(raw_value: object) -> int:
        """Require an explicit non-negative integer example limit."""

        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
            raise CommandError("--max-examples must be a non-negative integer")
        return raw_value

    def _run_audit(self, *, tolerance: float, max_examples: int) -> AuditAccumulator:
        """Stream ordered facts and retain only bounded report examples."""

        catalogs = self._load_catalog_sources()
        audit = AuditAccumulator()
        current_indicator = ""
        current_facts: list[MacroFactModel] = []
        facts = MacroFactModel._default_manager.only(
            "id",
            "indicator_code",
            "reporting_period",
            "value",
            "source",
            "revision_number",
            "published_at",
            "fetched_at",
            "extra",
        ).order_by("indicator_code", "reporting_period", "id")
        fact_iterator = cast(
            Generator[MacroFactModel, None, None],
            facts.iterator(chunk_size=QUERY_CHUNK_SIZE),
        )
        with closing(fact_iterator) as fact_rows:
            for fact in fact_rows:
                indicator_code = fact.indicator_code.strip()
                if not indicator_code:
                    raise ValueError("macro fact indicator_code must be non-empty")
                if current_indicator and indicator_code != current_indicator:
                    self._audit_indicator(
                        current_indicator,
                        current_facts,
                        preferred_source=catalogs.get(current_indicator, ""),
                        tolerance=tolerance,
                        max_examples=max_examples,
                        audit=audit,
                    )
                    current_facts = []
                current_indicator = indicator_code
                current_facts.append(fact)

        if current_indicator:
            self._audit_indicator(
                current_indicator,
                current_facts,
                preferred_source=catalogs.get(current_indicator, ""),
                tolerance=tolerance,
                max_examples=max_examples,
                audit=audit,
            )
        return audit

    @staticmethod
    def _load_catalog_sources() -> dict[str, str]:
        """Load governed source choices with validated JSON-object metadata."""

        sources: dict[str, str] = {}
        queryset = IndicatorCatalogModel._default_manager.only("code", "extra")
        row_iterator = cast(
            Generator[IndicatorCatalogModel, None, None],
            queryset.iterator(chunk_size=QUERY_CHUNK_SIZE),
        )
        with closing(row_iterator) as rows:
            for row in rows:
                code = row.code.strip()
                if not code:
                    raise ValueError("indicator catalog code must be non-empty")
                sources[code] = configured_macro_source(
                    Command._json_object(row.extra, field_name="indicator catalog extra")
                )
        return sources

    @staticmethod
    def _audit_indicator(
        indicator_code: str,
        facts: list[MacroFactModel],
        *,
        preferred_source: str,
        tolerance: float,
        max_examples: int,
        audit: AuditAccumulator,
    ) -> None:
        """Audit one indicator while its rows are the only facts held in memory."""

        audit.indicator_count += 1
        audit.fact_count += len(facts)
        by_source_period: dict[tuple[str, date], list[MacroFactModel]] = defaultdict(list)
        by_source: dict[str, dict[date, float]] = defaultdict(dict)
        for fact in facts:
            Command._json_object(fact.extra, field_name="macro fact extra")
            candidate = cast(MacroFactPreferenceCandidate, fact)
            source_key = macro_fact_source_key(candidate)
            if not source_key:
                raise ValueError("macro fact source must be non-empty")
            by_source_period[(source_key, fact.reporting_period)].append(fact)

        for (source_key, reporting_period), revisions in by_source_period.items():
            preferred = max(
                revisions,
                key=lambda item: macro_fact_preference_key(
                    cast(MacroFactPreferenceCandidate, item)
                ),
            )
            preferred_value = Command._finite_fact_value(preferred.value)
            by_source[source_key][reporting_period] = preferred_value
            values = {Command._finite_fact_value(item.value) for item in revisions}
            canonical_markers = {
                bool(
                    str(
                        Command._json_object(
                            item.extra,
                            field_name="macro fact extra",
                        ).get("provider_name")
                        or ""
                    ).strip()
                )
                for item in revisions
            }
            if len(values) > 1 and len(canonical_markers) > 1:
                audit.canonical_legacy_conflict_count += 1
                Command._append_example(
                    audit.canonical_legacy_conflicts,
                    {
                        "indicator_code": indicator_code,
                        "source": source_key,
                        "reporting_period": reporting_period.isoformat(),
                        "values": sorted(values),
                    },
                    max_examples=max_examples,
                )

        if preferred_source and preferred_source not in by_source:
            audit.configured_source_missing_count += 1
            Command._append_example(
                audit.configured_source_missing,
                {
                    "indicator_code": indicator_code,
                    "configured_source": preferred_source,
                },
                max_examples=max_examples,
            )

        sources = sorted(by_source)
        for index, primary_source in enumerate(sources):
            for backup_source in sources[index + 1 :]:
                is_consistent, difference = macro_series_are_consistent(
                    by_source[primary_source],
                    by_source[backup_source],
                    tolerance=tolerance,
                )
                if is_consistent:
                    continue
                if difference is None:
                    raise ValueError("inconsistent macro series must include a difference")
                audit.cross_source_conflict_count += 1
                if not preferred_source:
                    audit.ungoverned_cross_source_conflict_count += 1
                Command._append_example(
                    audit.cross_source_conflicts,
                    {
                        "indicator_code": indicator_code,
                        "primary_source": primary_source,
                        "backup_source": backup_source,
                        "max_difference_ratio": difference,
                        "governed_source": preferred_source,
                    },
                    max_examples=max_examples,
                )

    @staticmethod
    def _json_object(value: object, *, field_name: str) -> dict[str, object]:
        """Require JSON object metadata before it enters audit logic."""

        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise TypeError(f"{field_name} must be an object")
        return cast(dict[str, object], value)

    @staticmethod
    def _finite_fact_value(value: object) -> float:
        """Return one finite persisted fact value or fail the audit."""

        parsed = safe_float(value)
        if parsed is None:
            raise ValueError("macro fact value must be finite")
        return float(parsed)

    @staticmethod
    def _append_example(
        examples: list[dict[str, object]],
        example: dict[str, object],
        *,
        max_examples: int,
    ) -> None:
        """Retain at most the requested number of examples per category."""

        if len(examples) < max_examples:
            examples.append(example)
