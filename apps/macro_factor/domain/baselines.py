"""Deterministic historical-mean and fixed-universe FMP baselines."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ._runner_support import (
    decimal_text,
    hash_payload,
    require_finite,
    require_sha256,
    require_token,
)
from .runner_inputs import PITResearchRow


@dataclass(frozen=True)
class FixedFMPWeight:
    """Fixed, predeclared proxy weight for the deterministic FMP baseline."""

    asset_code: str
    weight: Decimal

    def __post_init__(self) -> None:
        require_token(self.asset_code, "FixedFMPWeight.asset_code")
        require_finite(self.weight, "FixedFMPWeight.weight")


@dataclass(frozen=True)
class FixedFMPDefinition:
    """Versioned fixed-universe FMP baseline; it performs no fitting."""

    benchmark_version: str
    intercept: Decimal
    weights: tuple[FixedFMPWeight, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        benchmark_version: str,
        intercept: Decimal,
        weights: tuple[FixedFMPWeight, ...],
    ) -> FixedFMPDefinition:
        """Build a fixed baseline and its canonical hash."""

        payload = cls._payload(benchmark_version, intercept, weights)
        return cls(benchmark_version, intercept, weights, hash_payload(payload))

    @staticmethod
    def _payload(
        benchmark_version: str,
        intercept: Decimal,
        weights: tuple[FixedFMPWeight, ...],
    ) -> dict[str, object]:
        return {
            "benchmark_version": benchmark_version,
            "intercept": decimal_text(intercept),
            "weights": [
                {"asset_code": item.asset_code, "weight": decimal_text(item.weight)}
                for item in sorted(weights, key=lambda value: value.asset_code)
            ],
        }

    def __post_init__(self) -> None:
        require_token(self.benchmark_version, "FixedFMPDefinition.benchmark_version")
        require_finite(self.intercept, "FixedFMPDefinition.intercept")
        if not self.weights:
            raise ValueError("FixedFMPDefinition.weights cannot be empty")
        codes = tuple(item.asset_code for item in self.weights)
        if len(codes) != len(set(codes)):
            raise ValueError("FixedFMPDefinition asset identities must be unique")
        require_sha256(self.content_hash, "FixedFMPDefinition.content_hash")
        expected = hash_payload(self._payload(self.benchmark_version, self.intercept, self.weights))
        if self.content_hash.lower() != expected:
            raise ValueError("FixedFMPDefinition.content_hash does not match content")

    def predict(self, row: PITResearchRow) -> Decimal:
        """Calculate a fixed weighted proxy value without fitting or defaults."""

        return self.intercept + sum(
            (item.weight * row.proxy_value(item.asset_code) for item in self.weights),
            start=Decimal("0"),
        )


@dataclass(frozen=True)
class DeterministicErrorMetrics:
    """Metrics recalculated locally from OOS actuals and predictions."""

    sample_count: int
    mean_squared_error: Decimal
    mean_absolute_error: Decimal
    r_squared: Decimal | None

    def __post_init__(self) -> None:
        if type(self.sample_count) is not int or self.sample_count <= 0:
            raise ValueError("DeterministicErrorMetrics.sample_count must be positive")
        require_finite(
            self.mean_squared_error,
            "DeterministicErrorMetrics.mean_squared_error",
        )
        require_finite(
            self.mean_absolute_error,
            "DeterministicErrorMetrics.mean_absolute_error",
        )
        if self.mean_squared_error < 0 or self.mean_absolute_error < 0:
            raise ValueError("deterministic error metrics cannot be negative")
        if self.r_squared is not None:
            require_finite(self.r_squared, "DeterministicErrorMetrics.r_squared")
            if self.r_squared > 1:
                raise ValueError("DeterministicErrorMetrics.r_squared cannot exceed one")

    def canonical_payload(self) -> dict[str, object]:
        """Return stable metric values."""

        return {
            "sample_count": self.sample_count,
            "mean_squared_error": decimal_text(self.mean_squared_error),
            "mean_absolute_error": decimal_text(self.mean_absolute_error),
            "r_squared": None if self.r_squared is None else decimal_text(self.r_squared),
        }


@dataclass(frozen=True)
class FoldBenchmarkResult:
    """Locally recalculated baseline and external OOS metrics for one fold."""

    fold_id: str
    historical_mean: DeterministicErrorMetrics
    fixed_fmp: DeterministicErrorMetrics
    external_model: DeterministicErrorMetrics

    def __post_init__(self) -> None:
        require_token(self.fold_id, "FoldBenchmarkResult.fold_id")

    def canonical_payload(self) -> dict[str, object]:
        """Return stable benchmark comparison values."""

        return {
            "fold_id": self.fold_id,
            "historical_mean": self.historical_mean.canonical_payload(),
            "fixed_fmp": self.fixed_fmp.canonical_payload(),
            "external_model": self.external_model.canonical_payload(),
        }


def calculate_error_metrics(
    actuals: tuple[Decimal, ...],
    predictions: tuple[Decimal, ...],
) -> DeterministicErrorMetrics:
    """Recalculate deterministic OOS error metrics."""

    if not actuals or len(actuals) != len(predictions):
        raise ValueError("metric inputs must be non-empty and aligned")
    count = Decimal(len(actuals))
    squared_errors = tuple(
        (actual - predicted) ** 2 for actual, predicted in zip(actuals, predictions, strict=True)
    )
    absolute_errors = tuple(
        abs(actual - predicted) for actual, predicted in zip(actuals, predictions, strict=True)
    )
    mean_actual = sum(actuals, start=Decimal("0")) / count
    total_variance = sum(((actual - mean_actual) ** 2 for actual in actuals), start=Decimal("0"))
    residual = sum(squared_errors, start=Decimal("0"))
    r_squared = None if total_variance == 0 else Decimal("1") - residual / total_variance
    return DeterministicErrorMetrics(
        sample_count=len(actuals),
        mean_squared_error=residual / count,
        mean_absolute_error=sum(absolute_errors, start=Decimal("0")) / count,
        r_squared=r_squared,
    )


__all__ = [
    "DeterministicErrorMetrics",
    "FixedFMPDefinition",
    "FixedFMPWeight",
    "FoldBenchmarkResult",
    "calculate_error_metrics",
]
