"""Numerical implementation of the validation runner's training-only estimator."""

from __future__ import annotations

import math

import numpy as np

from apps.research.domain.institutional_event_study import EventStudyError


def ridge_predict(
    training: tuple[tuple[float, ...], ...],
    outcomes: tuple[float, ...],
    validation: tuple[tuple[float, ...], ...],
    *,
    penalty: float,
) -> tuple[float, ...]:
    """Fit standardized ridge with an unpenalized intercept; score held-out covariates."""
    if not training or not validation or not math.isfinite(penalty) or penalty <= 0:
        raise EventStudyError("RIDGE_INPUT_INVALID")
    x, y, v = (np.asarray(a, dtype=np.float64) for a in (training, outcomes, validation))
    if (
        x.ndim != 2
        or y.shape != (len(x),)
        or v.ndim != 2
        or v.shape[1] != x.shape[1]
        or not all(np.isfinite(a).all() for a in (x, y, v))
    ):
        raise EventStudyError("RIDGE_INPUT_INVALID")
    center, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (x - center) / scale
    mean = float(y.mean())
    coefficients = np.linalg.solve(x.T @ x + penalty * np.eye(x.shape[1]), x.T @ (y - mean))
    prediction = mean + ((v - center) / scale) @ coefficients
    if not np.isfinite(prediction).all():
        raise EventStudyError("RIDGE_OUTPUT_INVALID")
    return tuple(float(value) for value in prediction)
