"""Persistence-boundary validation for Filter configuration and state models."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.filter.domain.entities import KalmanFilterState
from apps.filter.infrastructure.models import FilterConfig, KalmanStateModel

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("hp_lambda", Decimal("-1")),
        ("kalman_level_variance", Decimal("-0.1")),
        ("kalman_slope_variance", Decimal("-0.1")),
        ("kalman_observation_variance", Decimal("0")),
        ("kalman_observation_variance", Decimal("NaN")),
    ],
)
def test_filter_config_rejects_invalid_numeric_parameters(
    field_name: str,
    invalid_value: Decimal,
) -> None:
    """Model validation matches the Domain filter parameter invariants."""

    config = FilterConfig(indicator_code=f"TEST_{field_name}")
    setattr(config, field_name, invalid_value)

    with pytest.raises(ValidationError) as exc_info:
        config.full_clean()

    assert field_name in exc_info.value.message_dict


def test_filter_config_accepts_valid_boundary_parameters() -> None:
    """Zero process variance remains valid while observation variance is positive."""

    config = FilterConfig(
        indicator_code="TEST_VALID_BOUNDARY",
        hp_lambda=Decimal("0"),
        kalman_level_variance=Decimal("0"),
        kalman_slope_variance=Decimal("0"),
        kalman_observation_variance=Decimal("0.000001"),
    )

    config.full_clean()


def test_filter_config_database_constraint_blocks_direct_invalid_create() -> None:
    """Direct ORM writes cannot bypass the positive observation variance rule."""

    with pytest.raises(IntegrityError), transaction.atomic():
        FilterConfig._default_manager.create(
            indicator_code="TEST_DIRECT_INVALID",
            kalman_observation_variance=Decimal("0"),
        )


def test_kalman_state_round_trip_uses_exact_decimal_boundary() -> None:
    """Domain state conversion preserves values without binary-float artifacts."""

    domain_state = KalmanFilterState(
        level=12.5,
        slope=-0.125,
        level_variance=0.05,
        slope_variance=0.005,
        level_slope_cov=-0.001,
        updated_at=date(2026, 7, 27),
    )

    model = KalmanStateModel.from_domain_state(
        domain_state,
        "TEST_KALMAN",
        {"source": "unit"},
    )

    assert model.level == Decimal("12.5")
    assert model.slope == Decimal("-0.125")
    assert model.params == {"source": "unit"}
    assert model.to_domain_state() == domain_state


def test_kalman_state_rejects_negative_variance_before_save() -> None:
    """Invalid Domain-shaped state cannot replace the persisted Kalman state."""

    invalid_state = KalmanFilterState(
        level=12.5,
        slope=0.1,
        level_variance=-0.05,
        slope_variance=0.005,
        level_slope_cov=0.0,
        updated_at=date(2026, 7, 27),
    )

    with pytest.raises(ValidationError) as exc_info:
        KalmanStateModel.from_domain_state(invalid_state, "TEST_INVALID", {})

    assert "level_variance" in exc_info.value.message_dict


def test_kalman_state_database_constraint_blocks_direct_negative_variance() -> None:
    """Database constraints protect state written outside the repository."""

    with pytest.raises(IntegrityError), transaction.atomic():
        KalmanStateModel._default_manager.create(
            indicator_code="TEST_DIRECT_STATE",
            level=Decimal("1"),
            slope=Decimal("0"),
            level_variance=Decimal("-0.1"),
            slope_variance=Decimal("0.1"),
            level_slope_cov=Decimal("0"),
            last_observed_date=date(2026, 7, 27),
            params={},
        )
