"""Focused branch coverage for pure macro-factor domain guards."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from apps.macro_factor.domain._runner_support import (
    require_aware,
    require_finite,
    require_positive,
    require_sha256,
    require_text,
    require_token,
)
from apps.macro_factor.domain.baselines import (
    DeterministicErrorMetrics,
    FixedFMPDefinition,
    FixedFMPWeight,
    calculate_error_metrics,
)


@pytest.mark.parametrize(
    ("call", "match"),
    (
        (lambda: require_text("  ", "field"), "blank"),
        (lambda: require_text("abc", "field", maximum=2), "exceeds"),
        (lambda: require_token("has space", "field"), "whitespace"),
        (lambda: require_sha256("bad", "field"), "sha256"),
        (lambda: require_aware(datetime(2026, 1, 1), "field"), "timezone-aware"),
        (lambda: require_finite(Decimal("NaN"), "field"), "finite Decimal"),
        (lambda: require_finite(1, "field"), "finite Decimal"),
        (lambda: require_positive(False, "field"), "positive integer"),
        (lambda: require_positive(0, "field"), "positive integer"),
    ),
)
def test_runner_support_guards_reject_invalid_boundaries(call, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        call()


def test_fixed_fmp_definition_rejects_incomplete_or_tampered_content() -> None:
    weight = FixedFMPWeight("ETF", Decimal("1"))
    with pytest.raises(ValueError, match="cannot be empty"):
        FixedFMPDefinition.create(
            benchmark_version="v1",
            intercept=Decimal("0"),
            weights=(),
        )
    with pytest.raises(ValueError, match="unique"):
        FixedFMPDefinition.create(
            benchmark_version="v1",
            intercept=Decimal("0"),
            weights=(weight, weight),
        )
    valid = FixedFMPDefinition.create(
        benchmark_version="v1",
        intercept=Decimal("0"),
        weights=(weight,),
    )
    with pytest.raises(ValueError, match="does not match"):
        FixedFMPDefinition(
            benchmark_version=valid.benchmark_version,
            intercept=valid.intercept,
            weights=valid.weights,
            content_hash="0" * 64,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        {"sample_count": False},
        {"sample_count": 0},
        {"mean_squared_error": Decimal("-1")},
        {"mean_absolute_error": Decimal("-1")},
        {"r_squared": Decimal("1.1")},
    ),
)
def test_error_metrics_reject_invalid_values(mutation: dict[str, object]) -> None:
    values: dict[str, object] = {
        "sample_count": 2,
        "mean_squared_error": Decimal("1"),
        "mean_absolute_error": Decimal("1"),
        "r_squared": Decimal("0.5"),
    }
    values.update(mutation)
    with pytest.raises(ValueError):
        DeterministicErrorMetrics(
            sample_count=cast(Any, values["sample_count"]),
            mean_squared_error=cast(Any, values["mean_squared_error"]),
            mean_absolute_error=cast(Any, values["mean_absolute_error"]),
            r_squared=cast(Any, values["r_squared"]),
        )


def test_calculate_error_metrics_covers_alignment_and_constant_actuals() -> None:
    with pytest.raises(ValueError, match="non-empty and aligned"):
        calculate_error_metrics((), ())
    with pytest.raises(ValueError, match="non-empty and aligned"):
        calculate_error_metrics((Decimal("1"),), ())

    metrics = calculate_error_metrics(
        (Decimal("2"), Decimal("2")),
        (Decimal("1"), Decimal("3")),
    )
    assert metrics.r_squared is None
