"""Audit indicator weight-adjustment and recommendation contracts."""

from __future__ import annotations

from datetime import date

from apps.audit.application.indicator_use_cases import (
    AdjustIndicatorWeightsRequest,
    AdjustIndicatorWeightsUseCase,
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

    def get_indicator_performance_by_date_range(self, **kwargs: object) -> list[dict]:
        return [
            {
                "indicator_code": "PMI",
                "recommended_weight": 1.2,
                "recommended_action": "INCREASE",
                "f1_score": 0.8,
                "stability_score": 0.75,
                "confidence_level": 0.9,
                "decay_rate": 0.01,
            },
            {
                "indicator_code": "MISSING",
                "recommended_weight": 0.5,
                "recommended_action": "REMOVE",
                "f1_score": 0.2,
                "stability_score": 0.3,
                "confidence_level": 0.6,
            },
        ]

    def get_threshold_config_by_indicator(self, indicator_code: str) -> dict | None:
        return {"base_weight": 1.0} if indicator_code == "PMI" else None

    def update_threshold_config_weight(self, *, indicator_code: str, new_weight: float) -> None:
        self.applied.append((indicator_code, new_weight))


def test_weight_adjustment_handles_missing_run_skips_unknown_and_applies() -> None:
    """Weight adjustment validates its run, skips missing configs, and applies explicitly."""
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
