"""Focused branch coverage for signal domain value contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from apps.signal.domain.entities import InvestmentSignal
from apps.signal.domain.forecast_scenario_evidence import (
    ScenarioForecastBinding,
    ScenarioForecastOutcomeEvidence,
    ScenarioProbabilitySource,
    scenario_revision_uuid,
)
from apps.signal.domain.invalidation import (
    ComparisonOperator,
    IndicatorType,
    InvalidationCondition,
    InvalidationRule,
    LogicOperator,
)


def _binding() -> ScenarioForecastBinding:
    return ScenarioForecastBinding.from_values(
        scenario_revision_id=uuid4(),
        scenario_set_revision_id=None,
        subjective_probability="0.4",
        subjective_probability_source_version="subjective-v1",
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    (
        ({"subjective_probability": True}, "finite probability"),
        ({"subjective_probability": object()}, "finite probability"),
        ({"subjective_probability": "2"}, "within"),
        ({"subjective_probability_source_version": 1}, "must be a string"),
        ({"subjective_probability_source_version": " "}, "required"),
        ({"subjective_probability_source_version": "x" * 65}, "exceeds"),
        ({"subjective_probability_source_version": "bad\nvalue"}, "control"),
    ),
)
def test_scenario_binding_rejects_invalid_probability_metadata(
    kwargs: dict[str, object],
    match: str,
) -> None:
    values: dict[str, object] = {
        "scenario_revision_id": uuid4(),
        "scenario_set_revision_id": None,
        "subjective_probability": Decimal("0.5"),
        "subjective_probability_source_version": "subjective-v1",
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=match):
        ScenarioForecastBinding.from_values(**values)


def test_scenario_uuid_and_model_fields_fail_closed() -> None:
    invalid_revision_id: Any = "bad"
    with pytest.raises(ValueError, match="UUID"):
        scenario_revision_uuid(1, "revision")
    with pytest.raises(ValueError, match="UUID"):
        scenario_revision_uuid("bad", "revision")
    with pytest.raises(ValueError, match="scenario_revision_id"):
        ScenarioForecastBinding(
            scenario_revision_id=invalid_revision_id,
            scenario_set_revision_id=None,
            subjective_probability=Decimal("0.5"),
            subjective_probability_source_version="subjective-v1",
        )
    with pytest.raises(ValueError, match="requires source"):
        ScenarioForecastBinding(
            scenario_revision_id=uuid4(),
            scenario_set_revision_id=None,
            subjective_probability=Decimal("0.5"),
            subjective_probability_source_version="subjective-v1",
            model_probability=Decimal("0.6"),
        )


def test_outcome_evidence_validates_scores_and_selects_source() -> None:
    binding = _binding()
    with pytest.raises(ValueError, match="timezone-aware"):
        ScenarioForecastOutcomeEvidence(
            "entry",
            binding,
            datetime(2026, 1, 1),
            True,
            0.1,
            None,
        )
    with pytest.raises(ValueError, match="within"):
        ScenarioForecastOutcomeEvidence(
            "entry",
            binding,
            datetime.now(UTC),
            True,
            float("nan"),
            None,
        )
    outcome = ScenarioForecastOutcomeEvidence(
        "entry",
        binding,
        datetime.now(UTC),
        True,
        0.1,
        None,
    )
    assert outcome.score_for(ScenarioProbabilitySource.SUBJECTIVE) == 0.1
    assert outcome.score_for(ScenarioProbabilitySource.MODEL_INFERRED) is None


def test_investment_signal_exposes_structured_and_fallback_descriptions() -> None:
    condition = InvalidationCondition(
        indicator_code="PMI",
        indicator_type=IndicatorType.MACRO,
        operator=ComparisonOperator.LT,
        threshold=50,
    )
    rule = InvalidationRule([condition], LogicOperator.AND)
    structured = InvestmentSignal(None, "000001.SZ", "equity", "LONG", "logic", rule)
    fallback = InvestmentSignal(None, "000001.SZ", "equity", "LONG", "logic")

    assert structured.has_invalidation_rule is True
    assert structured.human_readable_invalidation == rule.human_readable
    assert fallback.has_invalidation_rule is False
    assert fallback.human_readable_invalidation == "未设置证伪条件"
