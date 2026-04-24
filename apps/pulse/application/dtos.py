"""Pulse application DTOs."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from apps.pulse.domain.entities import PulseSnapshot


@dataclass(frozen=True)
class PulseSnapshotDTO:
    """Serializable Pulse snapshot for application/interface boundaries."""

    observed_at: date
    regime_context: str
    composite_score: float
    regime_strength: str
    transition_warning: bool
    transition_direction: str | None
    transition_reasons: list[str]
    data_source: str
    is_reliable: bool
    dimension_scores: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_domain(cls, snapshot: PulseSnapshot) -> "PulseSnapshotDTO":
        """Build a DTO from a domain snapshot."""
        return cls(
            observed_at=snapshot.observed_at,
            regime_context=snapshot.regime_context,
            composite_score=snapshot.composite_score,
            regime_strength=snapshot.regime_strength,
            transition_warning=snapshot.transition_warning,
            transition_direction=snapshot.transition_direction,
            transition_reasons=list(snapshot.transition_reasons),
            data_source=snapshot.data_source,
            is_reliable=snapshot.is_reliable,
            dimension_scores=[
                {
                    "dimension": score.dimension,
                    "score": score.score,
                    "signal": score.signal,
                    "indicator_count": score.indicator_count,
                    "description": score.description,
                }
                for score in snapshot.dimension_scores
            ],
        )
