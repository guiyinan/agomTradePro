"""Pre-holdout paired loss inference on the original trading-session grid."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from apps.research.domain.institutional_event_study import EventStudyError


@dataclass(frozen=True, slots=True)
class LossInference:
    """Mean paired loss reduction and its two-sided normal HAC interval."""

    count: int
    mean: float
    standard_error: float | None
    lower: float | None
    upper: float | None
    raw_p: float | None


def paired_loss_inference(
    observations: tuple[tuple[int, float], ...], *, bandwidth: int, confidence: float
) -> LossInference:
    """Use a Bartlett kernel on session-index distances, including gaps between scores.

    The intercept-only sandwich uses centered score products divided by n².
    Missing origins contribute no score. A degenerate variance or insufficient
    support for the registered bandwidth leaves inference unavailable.
    """
    if type(bandwidth) is not int or bandwidth < 0 or not 0 < confidence < 1:
        raise EventStudyError("INFERENCE_DESIGN_INVALID")
    if not observations:
        raise EventStudyError("LOSS_SERIES_EMPTY")
    previous = -1
    for origin, loss in observations:
        if type(origin) is not int or origin <= previous or not math.isfinite(loss):
            raise EventStudyError("LOSS_SERIES_INVALID")
        previous = origin
    n = len(observations)
    mean = math.fsum(value for _, value in observations) / n
    unavailable = LossInference(n, mean, None, None, None, None)
    if n <= max(1, bandwidth):
        return unavailable
    centered = {origin: value - mean for origin, value in observations}
    meat = math.fsum(x * x for x in centered.values())
    for lag in range(1, bandwidth + 1):
        cross = math.fsum(x * centered.get(i - lag, 0.0) for i, x in centered.items())
        meat += 2 * (1 - lag / (bandwidth + 1)) * cross
    if meat <= 0:
        return unavailable
    se = math.sqrt(meat) / n
    half_width = -NormalDist().inv_cdf((1 - confidence) / 2) * se
    return LossInference(
        n,
        mean,
        se,
        mean - half_width,
        mean + half_width,
        math.erfc(abs(mean) / (math.sqrt(2) * se)),
    )
