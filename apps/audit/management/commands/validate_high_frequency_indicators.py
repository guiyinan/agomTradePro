"""Validate governed high-frequency macro indicators against Regime history."""

from __future__ import annotations

import importlib
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.audit.infrastructure.models import ValidationSummaryModel
from apps.data_center.application.public import get_macro_fact_series, get_macro_runtime_metadata
from apps.regime.infrastructure.models import RegimeLog

ValidationResult = dict[str, object]
ValidationResults = dict[str, ValidationResult]
ValidationReport = dict[str, object]

# Fixture-only compatibility seams.  Production reads go through the Data
# Center public port; tests and downstream dry-run harnesses may inject a
# model-shaped manager without importing the Data Center ORM here.
MacroFactModel: object | None = None
IndicatorCatalogModel: object | None = None


class _PearsonResultProtocol(Protocol):
    """SciPy correlation result compatibility surface."""

    statistic: float
    pvalue: float


@dataclass(frozen=True)
class ValidationThresholds:
    """Validated thresholds controlling availability and association decisions."""

    min_data_points: int = 100
    min_correlation: float = 0.3
    max_p_value: float = 0.05
    min_years: float = 3.0

    def __post_init__(self) -> None:
        """Reject invalid thresholds before any database access."""

        if isinstance(self.min_data_points, bool) or self.min_data_points <= 0:
            raise ValueError("min_data_points must be a positive integer")
        for name, value in (
            ("min_correlation", self.min_correlation),
            ("max_p_value", self.max_p_value),
            ("min_years", self.min_years),
        ):
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= self.min_correlation <= 1.0:
            raise ValueError("min_correlation must be between 0 and 1")
        if not 0.0 < self.max_p_value <= 1.0:
            raise ValueError("max_p_value must be in (0, 1]")
        if self.min_years < 0.0:
            raise ValueError("min_years must be non-negative")


def _pearsonr(left: list[float], right: list[float]) -> tuple[float, float]:
    """Call SciPy through a typed optional-library boundary."""

    stats_module = importlib.import_module("scipy.stats")
    pearson: object = getattr(stats_module, "pearsonr", None)
    if not callable(pearson):
        raise ImportError("scipy.stats.pearsonr is unavailable")
    raw_result: object = cast(Callable[[list[float], list[float]], object], pearson)(left, right)
    if isinstance(raw_result, tuple) and len(raw_result) >= 2:
        return float(raw_result[0]), float(raw_result[1])
    result = cast(_PearsonResultProtocol, raw_result)
    return float(result.statistic), float(result.pvalue)


def _number(result: ValidationResult, key: str) -> float | None:
    """Read a finite numeric result value without treating booleans as numbers."""

    value = result.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _report_integer(report: ValidationReport, key: str) -> int:
    """Read an integer report invariant before crossing into the ORM boundary."""

    value = report.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"report {key} must be an integer")
    return value


def _load_macro_rows(
    indicator_code: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, object]]:
    """Load canonical macro rows, preserving a model-shaped test seam."""

    if MacroFactModel is not None:
        manager = cast(Any, MacroFactModel)._default_manager
        raw_rows = manager.filter(
            indicator_code=indicator_code,
            reporting_period__gte=start_date,
            reporting_period__lte=end_date,
        ).order_by("reporting_period")
        return [
            {
                "reporting_period": row.reporting_period,
                "value": row.value,
            }
            for row in raw_rows
        ]
    return get_macro_fact_series(
        indicator_code,
        start=start_date,
        end=end_date,
        limit=2000,
        use_pit=True,
    )


class IndicatorValidator:
    """Validate governed indicator availability and contemporaneous association."""

    ADVERSE_REGIMES = frozenset({"Deflation", "Stagflation"})

    def __init__(
        self,
        start_date: date,
        end_date: date,
        indicator_codes: tuple[str, ...],
        thresholds: ValidationThresholds | None = None,
        term_spread_indicator: str | None = None,
    ) -> None:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        normalized_codes = tuple(
            dict.fromkeys(code.strip() for code in indicator_codes if code.strip())
        )
        if not normalized_codes:
            raise ValueError("at least one indicator code is required")
        if term_spread_indicator is not None and term_spread_indicator not in normalized_codes:
            raise ValueError("term_spread_indicator must be included in indicator_codes")
        self.start_date = start_date
        self.end_date = end_date
        self.indicator_codes = normalized_codes
        self.thresholds = thresholds or ValidationThresholds()
        self.term_spread_indicator = term_spread_indicator
        self.validation_results: ValidationResults = {}

    def check_data_availability(self) -> ValidationResults:
        """Classify data volume and time-span coverage for every governed indicator."""

        requested_days = max((self.end_date - self.start_date).days, 1)
        for indicator_code in self.indicator_codes:
            try:
                rows = _load_macro_rows(indicator_code, self.start_date, self.end_date)
            except Exception as exc:
                self.validation_results[indicator_code] = {
                    "status": "ERROR",
                    "message": f"availability query failed: {type(exc).__name__}",
                }
                continue
            if not rows:
                self.validation_results[indicator_code] = {
                    "status": "NO_DATA",
                    "message": f"指标 {indicator_code} 无数据",
                    "count": 0,
                    "date_range": None,
                }
                continue

            first_date = date.fromisoformat(str(rows[0]["reporting_period"]))
            last_date = date.fromisoformat(str(rows[-1]["reporting_period"]))
            observed_days = max((last_date - first_date).days, 0)
            observed_years = observed_days / 365.2425
            count = len(rows)
            enough_points = count >= self.thresholds.min_data_points
            enough_years = observed_years >= self.thresholds.min_years
            self.validation_results[indicator_code] = {
                "status": "OK" if enough_points and enough_years else "INSUFFICIENT",
                "count": count,
                "first_date": first_date,
                "last_date": last_date,
                "coverage": min(observed_days / requested_days, 1.0),
                "observed_years": observed_years,
            }
        return self.validation_results

    def calculate_correlation_with_regime(self) -> ValidationResults:
        """Measure contemporaneous association with a binary adverse-Regime target."""

        try:
            regime_rows = list(
                RegimeLog._default_manager.filter(
                    observed_at__gte=self.start_date,
                    observed_at__lte=self.end_date,
                ).order_by("observed_at")
            )
        except Exception as exc:
            for result in self.validation_results.values():
                if result.get("status") == "OK":
                    result["status"] = "ERROR"
                    result["message"] = f"regime query failed: {type(exc).__name__}"
            return self.validation_results

        regime_by_date = {
            row.observed_at: 1.0 if row.dominant_regime in self.ADVERSE_REGIMES else 0.0
            for row in regime_rows
        }
        if len(regime_by_date) < 10:
            for result in self.validation_results.values():
                if result.get("status") == "OK":
                    result["correlation_status"] = "NO_REGIME_DATA"
            return self.validation_results

        for indicator_code, result in self.validation_results.items():
            if result.get("status") != "OK":
                continue
            try:
                indicator_rows = _load_macro_rows(indicator_code, self.start_date, self.end_date)
                pairs = [
                    (
                        regime_by_date[date.fromisoformat(str(row["reporting_period"]))],
                        float(cast(float, row["value"])),
                    )
                    for row in indicator_rows
                    if date.fromisoformat(str(row["reporting_period"])) in regime_by_date
                    and math.isfinite(float(cast(float, row["value"])))
                ]
                if len(pairs) < 10:
                    result["correlation_status"] = "INSUFFICIENT_OVERLAP"
                    result["overlap_count"] = len(pairs)
                    continue
                correlation, p_value = _pearsonr(
                    [pair[0] for pair in pairs],
                    [pair[1] for pair in pairs],
                )
                if not math.isfinite(correlation) or not math.isfinite(p_value):
                    result["correlation_status"] = "NON_FINITE"
                    continue
                result.update(
                    {
                        "correlation_status": "OK",
                        "correlation": correlation,
                        "p_value": p_value,
                        "overlap_count": len(pairs),
                        "correlation_significant": p_value <= self.thresholds.max_p_value,
                        "correlation_meets_threshold": (
                            abs(correlation) >= self.thresholds.min_correlation
                        ),
                    }
                )
            except Exception as exc:
                result["status"] = "ERROR"
                result["correlation_status"] = "ERROR"
                result["message"] = f"correlation failed: {type(exc).__name__}"
        return self.validation_results

    def event_study_term_spread(self) -> ValidationResult:
        """Study inversions only when a governed term-spread indicator is explicit."""

        indicator_code = self.term_spread_indicator
        if indicator_code is None:
            return {"status": "SKIPPED", "message": "term spread indicator not configured"}
        if self.validation_results.get(indicator_code, {}).get("status") != "OK":
            return {"status": "INSUFFICIENT_DATA"}
        try:
            rows = _load_macro_rows(indicator_code, self.start_date, self.end_date)
            if len(rows) < self.thresholds.min_data_points:
                return {"status": "INSUFFICIENT_DATA"}

            inversion_events: list[ValidationResult] = []
            current_rows: list[dict[str, object]] = []
            for row in rows:
                if float(cast(float, row["value"])) < 0:
                    current_rows.append(row)
                elif current_rows:
                    inversion_events.append(self._build_inversion_event(current_rows))
                    current_rows = []
            if current_rows:
                inversion_events.append(self._build_inversion_event(current_rows))

            event_results: list[ValidationResult] = []
            for event in inversion_events:
                event_date = event.get("start_date")
                if not isinstance(event_date, date):
                    continue
                future_regimes = RegimeLog._default_manager.filter(
                    observed_at__gt=event_date,
                    observed_at__lte=event_date + timedelta(days=365),
                ).order_by("observed_at")
                regime_values = [row.dominant_regime for row in future_regimes]
                if regime_values:
                    event_results.append(
                        {
                            **event,
                            "recession_occurred": any(
                                regime in self.ADVERSE_REGIMES for regime in regime_values
                            ),
                        }
                    )
            accuracy = (
                sum(1 for event in event_results if event.get("recession_occurred") is True)
                / len(event_results)
                if event_results
                else 0.0
            )
            summary: ValidationResult = {
                "status": "OK",
                "total_inversions": len(inversion_events),
                "events": event_results,
                "prediction_accuracy": accuracy,
            }
            self.validation_results[indicator_code]["event_study"] = summary
            return summary
        except Exception as exc:
            return {"status": "ERROR", "message": f"event study failed: {type(exc).__name__}"}

    @staticmethod
    def _build_inversion_event(rows: list[dict[str, object]]) -> ValidationResult:
        """Build one inversion event from consecutive inverted observations."""

        dates = [date.fromisoformat(str(row["reporting_period"])) for row in rows]
        start_date = min(dates)
        end_date = max(dates)
        return {
            "start_date": start_date,
            "end_date": end_date,
            "duration_days": (end_date - start_date).days,
            "min_spread": min(float(cast(float, row["value"])) for row in rows),
        }

    def generate_validation_report(self) -> ValidationReport:
        """Generate an honest availability/association report without fabricated F1 metrics."""

        approved: list[str] = []
        rejected: list[str] = []
        pending: list[str] = []
        for indicator_code, result in self.validation_results.items():
            status = result.get("status")
            if status == "OK":
                correlation = _number(result, "correlation")
                p_value = _number(result, "p_value")
                if (
                    result.get("correlation_status") == "OK"
                    and correlation is not None
                    and p_value is not None
                    and abs(correlation) >= self.thresholds.min_correlation
                    and p_value <= self.thresholds.max_p_value
                ):
                    approved.append(indicator_code)
                else:
                    pending.append(indicator_code)
            else:
                rejected.append(indicator_code)

        total = len(self.indicator_codes)
        approval_ratio = len(approved) / total
        if approval_ratio >= 0.6:
            recommendation = "建议进入 Phase 1 开发阶段"
        elif approval_ratio >= 0.3:
            recommendation = "建议有条件进入 Phase 1，仅部署通过验证的指标"
        else:
            recommendation = "建议重新评估指标选择或数据源"
        return {
            "validation_run_id": (
                f"phase0_{self.start_date}_{self.end_date}_{uuid.uuid4().hex[:8]}"
            ),
            "total_indicators": total,
            "approved_indicators": len(approved),
            "rejected_indicators": len(rejected),
            "pending_indicators": len(pending),
            "avg_f1_score": None,
            "avg_stability_score": None,
            "overall_recommendation": recommendation,
            "detailed_results": self.validation_results,
        }


class Command(BaseCommand):
    """Run governed high-frequency availability and association validation."""

    help = "验证高频指标的数据可用性和与逆风 Regime 的同期关联"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register validation command options."""

        parser.add_argument("--start-date", type=str, default="2018-01-01")
        parser.add_argument("--end-date", type=str, default=str(date.today()))
        parser.add_argument("--min-data-points", type=int, default=100)
        parser.add_argument("--min-correlation", type=float, default=0.3)
        parser.add_argument("--max-p-value", type=float, default=0.05)
        parser.add_argument("--min-years", type=float, default=3.0)
        parser.add_argument(
            "--indicators",
            type=str,
            default=None,
            help="Comma-separated governed indicator codes; defaults to active D/W catalog rows",
        )
        parser.add_argument("--term-spread-indicator", type=str, default=None)
        parser.add_argument("--save-report", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        """Validate inputs, run checks, and optionally persist the summary."""

        del args
        try:
            start_date = date.fromisoformat(self._required_string(options, "start_date"))
            end_date = date.fromisoformat(self._required_string(options, "end_date"))
            thresholds = ValidationThresholds(
                min_data_points=self._required_int(options, "min_data_points"),
                min_correlation=self._required_float(options, "min_correlation"),
                max_p_value=self._required_float(options, "max_p_value"),
                min_years=self._required_float(options, "min_years"),
            )
            indicator_codes = self._resolve_indicator_codes(options.get("indicators"))
            term_spread = self._optional_string(options.get("term_spread_indicator"))
            save_report = options.get("save_report", False)
            if not isinstance(save_report, bool):
                raise ValueError("save_report must be a boolean")
            validator = IndicatorValidator(
                start_date,
                end_date,
                indicator_codes,
                thresholds,
                term_spread,
            )
        except (ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("Phase 0 高频指标验证")
        self.stdout.write(f"验证期间: {start_date} 至 {end_date}")
        self.stdout.write(f"指标数量: {len(indicator_codes)}")
        validator.check_data_availability()
        validator.calculate_correlation_with_regime()
        event_study = validator.event_study_term_spread()
        report = validator.generate_validation_report()
        self._write_report(report, event_study)
        if save_report:
            self._save_report(report, start_date, end_date)
        self.stdout.write(self.style.SUCCESS("Phase 0 验证完成"))

    @staticmethod
    def _required_string(options: dict[str, object], key: str) -> str:
        value = options.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("optional string must be non-empty")
        return value.strip()

    @staticmethod
    def _required_int(options: dict[str, object], key: str) -> int:
        value = options.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
        return value

    @staticmethod
    def _required_float(options: dict[str, object], key: str) -> float:
        value = options.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{key} must be numeric")
        return float(value)

    @staticmethod
    def _resolve_indicator_codes(raw_value: object) -> tuple[str, ...]:
        """Resolve explicit codes or active governed daily/weekly catalog rows."""

        if raw_value is not None:
            if not isinstance(raw_value, str):
                raise ValueError("indicators must be a comma-separated string")
            codes = tuple(
                dict.fromkeys(part.strip() for part in raw_value.split(",") if part.strip())
            )
            if not codes:
                raise ValueError("indicators must contain at least one code")
            return codes

        if IndicatorCatalogModel is not None:
            rows = cast(Any, IndicatorCatalogModel)._default_manager.filter(
                is_active=True,
                default_period_type__in=("D", "W"),
            ).values_list("code", "extra")
            codes = tuple(
                str(code)
                for code, extra in rows
                if not (isinstance(extra, dict) and extra.get("governance_sync_supported") is False)
            )
        else:
            metadata = get_macro_runtime_metadata()
            codes = tuple(
                str(code)
                for code, item in metadata.items()
                if item.get("default_period_type") in {"D", "W"}
                and item.get("governance_sync_supported") is not False
            )
        if not codes:
            raise ValueError("no active governed daily/weekly indicators are configured")
        return codes

    def _write_report(self, report: ValidationReport, event_study: ValidationResult) -> None:
        """Write a compact command summary without pretending association is F1."""

        self.stdout.write(f'  总指标数: {report["total_indicators"]}')
        self.stdout.write(f'  通过指标: {report["approved_indicators"]}')
        self.stdout.write(f'  拒绝指标: {report["rejected_indicators"]}')
        self.stdout.write(f'  待定指标: {report["pending_indicators"]}')
        self.stdout.write(f'  事件研究: {event_study.get("status", "UNKNOWN")}')
        self.stdout.write(f'总体建议: {report["overall_recommendation"]}')

    def _save_report(self, report: ValidationReport, start_date: date, end_date: date) -> None:
        """Persist the completed summary or fail the command visibly."""

        try:
            summary = ValidationSummaryModel._default_manager.create(
                validation_run_id=str(report["validation_run_id"]),
                evaluation_period_start=start_date,
                evaluation_period_end=end_date,
                total_indicators=_report_integer(report, "total_indicators"),
                approved_indicators=_report_integer(report, "approved_indicators"),
                rejected_indicators=_report_integer(report, "rejected_indicators"),
                pending_indicators=_report_integer(report, "pending_indicators"),
                avg_f1_score=None,
                avg_stability_score=None,
                overall_recommendation=str(report["overall_recommendation"]),
                status="completed",
                is_shadow_mode=True,
            )
        except Exception as exc:
            raise CommandError(f"保存验证报告失败: {type(exc).__name__}") from exc
        self.stdout.write(self.style.SUCCESS(f"报告已保存: {summary.validation_run_id}"))
