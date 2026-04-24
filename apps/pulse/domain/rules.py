"""Pulse domain rules."""

from apps.pulse.domain.entities import DimensionScore, PulseConfig
from apps.pulse.domain.services import assess_regime_strength, detect_transition_warning


def classify_pulse_strength(composite_score: float) -> str:
    """Classify a composite Pulse score into a strength bucket."""
    return assess_regime_strength(composite_score)


def should_warn_transition(
    dimension_scores: list[DimensionScore],
    regime_context: str,
    config: PulseConfig | None = None,
) -> tuple[bool, str | None, list[str]]:
    """Evaluate whether the current Pulse dimensions warn about a regime transition."""
    return detect_transition_warning(
        dim_scores=dimension_scores,
        regime_context=regime_context,
        config=config or PulseConfig.defaults(),
    )
