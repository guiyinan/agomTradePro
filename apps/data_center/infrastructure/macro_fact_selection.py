"""Canonical macro-fact selection shared by decision-data readers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Generic, TypeVar

from apps.data_center.domain.rules import (
    MacroFactPreferenceCandidate,
    deduplicate_macro_facts,
    macro_series_are_consistent,
)

MacroFactT = TypeVar("MacroFactT", bound=MacroFactPreferenceCandidate)


@dataclass(frozen=True)
class MacroFactSeriesSelection(Generic[MacroFactT]):
    """Result of selecting one internally consistent source series."""

    facts: list[MacroFactT]
    source: str
    is_consistent: bool
    max_difference_ratio: float | None = None
    blocked_reason: str = ""


def configured_macro_source(extra: dict[str, object] | None) -> str:
    """Return the governed source explicitly configured for decision reads."""

    metadata = dict(extra or {})
    return str(
        metadata.get("governance_sync_source_type")
        or metadata.get("decision_source_type")
        or ""
    ).strip().lower()


def macro_fact_source_key(fact: MacroFactPreferenceCandidate) -> str:
    """Return the stable provider identity used for governed source selection."""

    extra = dict(fact.extra or {})
    return str(extra.get("source_type") or fact.source or "").strip().lower()


def select_macro_fact_series(
    facts: list[MacroFactT],
    *,
    preferred_source: str = "",
    tolerance: float = 0.01,
) -> MacroFactSeriesSelection[MacroFactT]:
    """Select one source without mixing inconsistent observations.

    Revision duplicates are collapsed within each source first. An explicitly
    governed source is authoritative. Without one, all overlapping sources must
    agree within tolerance before a deterministic source is selected.
    """

    by_source: dict[str, list[MacroFactT]] = defaultdict(list)
    for fact in facts:
        by_source[macro_fact_source_key(fact)].append(fact)
    by_source = {
        source: deduplicate_macro_facts(source_facts, by_source=False)
        for source, source_facts in by_source.items()
    }

    if not by_source:
        return MacroFactSeriesSelection([], "", True)

    normalized_preference = str(preferred_source or "").strip().lower()
    if normalized_preference:
        selected = by_source.get(normalized_preference, [])
        if not selected:
            return MacroFactSeriesSelection(
                [],
                normalized_preference,
                False,
                blocked_reason=(
                    f"Configured macro source {normalized_preference!r} has no observations"
                ),
            )
        return MacroFactSeriesSelection(
            sorted(selected, key=lambda fact: fact.reporting_period),
            normalized_preference,
            True,
        )

    source_names = sorted(by_source)
    max_difference: float | None = None
    for index, primary_source in enumerate(source_names):
        primary = {
            fact.reporting_period: float(fact.value)
            for fact in by_source[primary_source]
        }
        for backup_source in source_names[index + 1 :]:
            backup = {
                fact.reporting_period: float(fact.value)
                for fact in by_source[backup_source]
            }
            is_consistent, difference = macro_series_are_consistent(
                primary,
                backup,
                tolerance=tolerance,
            )
            if difference is not None:
                max_difference = max(max_difference or 0.0, difference)
            if not is_consistent:
                return MacroFactSeriesSelection(
                    [],
                    "",
                    False,
                    max_difference_ratio=max_difference,
                    blocked_reason=(
                        "Macro sources disagree beyond tolerance: "
                        f"{primary_source} vs {backup_source}"
                    ),
                )

    selected_source = min(
        source_names,
        key=lambda source: (
            -len(by_source[source]),
            source,
        ),
    )
    return MacroFactSeriesSelection(
        sorted(by_source[selected_source], key=lambda fact: fact.reporting_period),
        selected_source,
        True,
        max_difference_ratio=max_difference,
    )
