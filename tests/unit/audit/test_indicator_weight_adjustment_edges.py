"""Audit indicator weight-adjustment and recommendation contracts."""

from __future__ import annotations

from datetime import date
from unittest.mock import Mock

from apps.audit.application.indicator_use_cases import (
    AdjustIndicatorWeightsRequest,
    AdjustIndicatorWeightsUseCase,
    ValidateThresholdsRequest,
    ValidateThresholdsUseCase,
)


class _Repo:
    def __init__(self) -> None:
        self.applied: list[tuple[str, float]] = []

    def get_validation_summary_by_run_id(self, validation_run_id: str) -> dict | None:
        if validation_run_id == "missing":
            return None
        return {
            "evaluation_period_start": date(2026, 1, 1),
            "evaluation_period_end": date(2026, 6, 30),
        }

    def get_indicator_performance_reports(self, **kwargs: object) -> list[dict]:
        return [
            {
                "id": 1,
                "indicator_code": "PMI",
                "validation_run_id": "validation-1",
                "evaluation_period_start": "2026-01-01",
                "evaluation_period_end": "2026-06-30",
                "recommended_weight": 1.2,
                "recommended_action": "INCREASE",
                "f1_score": 0.8,
                "stability_score": 0.75,
                "confidence_level": 0.9,
                "decay_rate": 0.01,
                "precision": 0.8,
                "recall": 0.8,
            },
        ]

    def get_threshold_config_by_indicator(self, indicator_code: str) -> dict | None:
        return {"base_weight": 1.0} if indicator_code == "PMI" else None

    def update_threshold_config_weight(self, *, indicator_code: str, new_weight: float) -> None:
        self.applied.append((indicator_code, new_weight))


def test_weight_adjustment_uses_run_scoped_reports_and_applies() -> None:
    """Weight adjustment validates its run and applies only run-scoped reports."""
    repo = _Repo()
    use_case = AdjustIndicatorWeightsUseCase(repo)
    missing = use_case.execute(AdjustIndicatorWeightsRequest("missing"))
    assert missing.success is False

    response = use_case.execute(AdjustIndicatorWeightsRequest("validation-1", auto_apply=True))
    assert response.success is True
    assert response.adjusted_weights is not None
    assert len(response.adjusted_weights) == 1
    weight = response.adjusted_weights[0]
    assert weight.adjustment_factor == 1.2
    assert "增加权重" in weight.reason
    assert repo.applied == [("PMI", 1.2)]


def test_audit_recommendation_boundaries_cover_all_outcomes() -> None:
    """Overall and per-indicator recommendations expose every risk band."""
    validate = ValidateThresholdsUseCase(_Repo())
    assert validate._generate_overall_recommendation(0, 0, 0, 0, 0) == "无指标可评估"
    assert "优秀" in validate._generate_overall_recommendation(8, 1, 1, 0.7, 0.7)
    assert "良好" in validate._generate_overall_recommendation(5, 3, 2, 0.55, 0.5)
    assert "一般" in validate._generate_overall_recommendation(3, 5, 2, 0.4, 0.4)
    assert "较差" in validate._generate_overall_recommendation(1, 8, 1, 0.2, 0.2)

    adjust = AdjustIndicatorWeightsUseCase(_Repo())
    assert "保持" in adjust._generate_adjustment_reason("KEEP", 0.7, 0.7)
    assert "降低" in adjust._generate_adjustment_reason("DECREASE", 0.4, 0.4)
    assert "移除" in adjust._generate_adjustment_reason("REMOVE", 0.2, 0.2)
    assert adjust._generate_adjustment_reason("UNKNOWN", 0, 0) == "未知原因"


def test_threshold_validation_links_each_report_to_generated_run() -> None:
    """Validation orchestration must persist the generated run ID on every report."""

    repository = Mock()
    repository.get_active_threshold_configs_by_codes.return_value = [
        {
            "indicator_code": "PMI",
            "indicator_name": "PMI",
            "category": "growth",
            "level_low": 49.0,
            "level_high": 51.0,
            "base_weight": 1.0,
            "min_weight": 0.0,
            "max_weight": 1.0,
            "decay_threshold": 0.2,
            "decay_penalty": 0.5,
            "improvement_threshold": 0.1,
            "improvement_bonus": 1.2,
            "action_thresholds": {
                "keep_min_f1": 0.6,
                "reduce_min_f1": 0.4,
                "remove_max_f1": 0.3,
            },
            "validation_periods": [],
            "description": "",
        }
    ]
    repository.get_threshold_config_by_indicator.return_value = (
        repository.get_active_threshold_configs_by_codes.return_value[0]
    )
    repository.get_macro_indicator_values.return_value = [
        (date(2026, 1, 1), 50.0),
        (date(2026, 2, 1), 51.0),
    ]
    repository.get_regime_log_values.return_value = [
        {
            "observed_at": date(2026, 1, 1),
            "dominant_regime": "Recovery",
            "confidence": 0.8,
            "growth_momentum_z": 1.0,
            "inflation_momentum_z": 0.5,
            "distribution": {"Recovery": 1.0},
        }
    ]
    repository.save_indicator_performance_record.return_value = 1

    response = ValidateThresholdsUseCase(repository).execute(
        ValidateThresholdsRequest(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 30),
        )
    )

    assert response.success is True
    assert response.validation_run_id is not None
    saved_arguments = repository.save_indicator_performance_record.call_args.kwargs
    assert saved_arguments["validation_run_id"] == response.validation_run_id
