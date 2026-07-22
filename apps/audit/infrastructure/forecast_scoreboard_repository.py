"""Aggregate finalized forecast outcomes without manufacturing legacy evidence."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from core.integration.research_integrity_registry import get_finalized_forecast_entries


class ForecastScoreboardRepository:
    def summarize(self, group_by: str | None = None) -> dict[str, Any]:
        rows = get_finalized_forecast_entries()
        buckets: dict[str, list[Any]] = defaultdict(list)
        for row in rows:
            key = str(getattr(row, group_by)) if group_by else "all"
            buckets[key].append(row)
        results = []
        for key, entries in sorted(buckets.items()):
            scoreable = [item for item in entries if item.outcome.hit is not None]
            briers = [item.outcome.brier_score for item in scoreable if item.outcome.brier_score is not None]
            excess = [item.outcome.excess_return for item in scoreable if item.outcome.excess_return is not None]
            invalidated_entries = sum(
                any(evaluation.triggered for evaluation in item.evaluations.all())
                for item in entries
            )
            invalidation_hours = [
                (triggered_at - item.published_at).total_seconds() / 3600
                for item in entries
                for triggered_at in [
                    min(
                        (
                            evaluation.first_triggered_at or evaluation.checked_at
                            for evaluation in item.evaluations.all()
                            if evaluation.triggered
                        ),
                        default=None,
                    )
                ]
                if triggered_at is not None
            ]
            results.append(
                {
                    "group": key,
                    "sample_count": len(scoreable),
                    "total_finalized": len(entries),
                    "coverage": len(scoreable) / len(entries) if entries else 0.0,
                    "hit_rate": (
                        sum(bool(item.outcome.hit) for item in scoreable) / len(scoreable)
                        if scoreable
                        else None
                    ),
                    "average_excess_return": mean(excess) if excess else None,
                    "brier_score": mean(briers) if briers else None,
                    "invalidation_rate": (
                        invalidated_entries / len(entries) if entries else 0.0
                    ),
                    "average_invalidation_hours": (
                        mean(invalidation_hours) if invalidation_hours else None
                    ),
                    "ranking_eligible": len(scoreable) >= 30,
                }
            )
        return {"group_by": group_by, "results": results}
