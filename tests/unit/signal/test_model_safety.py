"""Persistence-boundary safety tests for investment signal models."""

from math import inf, nan

import pytest
from django.core.exceptions import ValidationError

from apps.signal.infrastructure.models import InvestmentSignalModel


def _valid_fields() -> dict[str, object]:
    return {
        "asset_code": "000001.SZ",
        "asset_class": "a_share_growth",
        "direction": "LONG",
        "logic_desc": "PMI recovery",
        "target_regime": "Recovery",
        "status": "pending",
    }


def _valid_rule() -> dict[str, object]:
    return {
        "logic": "AND",
        "conditions": [
            {
                "indicator_code": "PMI",
                "indicator_type": "macro",
                "operator": "lt",
                "threshold": 50.0,
            }
        ],
    }


@pytest.mark.django_db
@pytest.mark.parametrize("threshold", [True, nan, inf])
def test_direct_orm_create_rejects_invalid_invalidation_threshold(
    threshold: object,
) -> None:
    with pytest.raises(ValidationError):
        InvestmentSignalModel.objects.create(
            **_valid_fields(),
            invalidation_rule_json={
                **_valid_rule(),
                "conditions": [
                    {
                        "indicator_code": "PMI",
                        "indicator_type": "macro",
                        "operator": "lt",
                        "threshold": threshold,
                    }
                ],
            },
        )

    assert InvestmentSignalModel.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("direction", "SIDEWAYS"),
        ("status", "unknown"),
        ("backtest_performance_score", 101.0),
        ("backtest_count", -1),
        ("avg_backtest_return", nan),
    ],
)
def test_direct_orm_create_rejects_invalid_signal_fields(field: str, value: object) -> None:
    fields = _valid_fields()
    fields[field] = value

    with pytest.raises(ValidationError):
        InvestmentSignalModel.objects.create(**fields)

    assert InvestmentSignalModel.objects.count() == 0


@pytest.mark.django_db
def test_valid_rule_round_trips_to_domain() -> None:
    signal = InvestmentSignalModel.objects.create(
        **_valid_fields(),
        invalidation_rule_json=_valid_rule(),
    )

    domain_signal = signal.to_domain_entity()

    assert domain_signal.invalidation_rule is not None
    assert domain_signal.invalidation_rule.conditions[0].indicator_code == "PMI"


@pytest.mark.django_db
def test_corrupt_persisted_rule_fails_closed_on_domain_conversion() -> None:
    signal = InvestmentSignalModel.objects.create(
        **_valid_fields(),
        invalidation_rule_json=_valid_rule(),
    )
    InvestmentSignalModel.objects.filter(pk=signal.pk).update(
        invalidation_rule_json={"logic": "AND", "conditions": []}
    )
    signal.refresh_from_db()

    with pytest.raises(ValueError, match="invalid invalidation rule"):
        signal.to_domain_entity()
