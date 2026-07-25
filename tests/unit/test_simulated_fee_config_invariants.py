"""Persistence invariants for simulated-trading fee configurations."""

from math import inf, nan

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.simulated_trading.infrastructure.models import FeeConfigModel


def _config(
    name: str,
    *,
    asset_type: str = "equity",
    is_default: bool = False,
    minimum: float = 5.0,
) -> FeeConfigModel:
    return FeeConfigModel(
        config_name=name,
        asset_type=asset_type,
        min_commission=minimum,
        is_default=is_default,
        is_active=True,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commission_rate_buy", -0.1),
        ("commission_rate_sell", inf),
        ("stamp_duty_rate", nan),
        ("transfer_fee_rate", True),
        ("slippage_rate", 1.1),
        ("min_commission", -1.0),
        ("min_transfer_fee", inf),
    ],
)
def test_fee_config_rejects_invalid_numeric_parameters(field: str, value: object) -> None:
    config = _config("invalid")
    setattr(config, field, value)

    with pytest.raises(ValidationError):
        config.save()

    assert FeeConfigModel.objects.count() == 0


@pytest.mark.django_db
def test_invalid_replacement_does_not_clear_existing_default() -> None:
    existing = _config("existing", is_default=True)
    existing.save()
    replacement = _config("invalid-replacement", is_default=True, minimum=-1.0)

    with pytest.raises(ValidationError):
        replacement.save()

    existing.refresh_from_db()
    assert existing.is_default is True


@pytest.mark.django_db
def test_valid_replacement_atomically_switches_default() -> None:
    existing = _config("existing", is_default=True)
    existing.save()
    replacement = _config("replacement", is_default=True, minimum=8.0)

    replacement.save()

    existing.refresh_from_db()
    assert existing.is_default is False
    assert replacement.is_default is True


@pytest.mark.django_db
def test_database_constraint_blocks_default_bypass() -> None:
    first = _config("first", is_default=True)
    first.save()
    second = _config("second")
    second.save()

    with pytest.raises(IntegrityError), transaction.atomic():
        FeeConfigModel.objects.filter(pk=second.pk).update(is_default=True)
