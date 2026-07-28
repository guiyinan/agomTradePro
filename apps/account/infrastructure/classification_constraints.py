"""Database constraints for Account classification reference models."""

from django.db import models
from django.db.models import F, Q
from django.db.models.constraints import BaseConstraint

ASSET_CATEGORY_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(level__gte=1),
        name="account_asset_category_level_positive",
    ),
    models.CheckConstraint(
        condition=~Q(parent=F("id")),
        name="account_asset_category_not_self_parent",
    ),
]

CURRENCY_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(precision__gte=0, precision__lte=8),
        name="account_currency_precision_0_8",
    ),
    models.CheckConstraint(
        condition=Q(is_base=False) | Q(is_active=True),
        name="account_currency_base_must_be_active",
    ),
    models.UniqueConstraint(
        fields=["is_base"],
        condition=Q(is_base=True),
        name="account_currency_single_base",
    ),
]

EXCHANGE_RATE_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(rate__gt=0),
        name="account_exchange_rate_positive",
    ),
    models.CheckConstraint(
        condition=~Q(from_currency=F("to_currency")),
        name="account_exchange_rate_distinct_pair",
    ),
]

__all__ = [
    "ASSET_CATEGORY_CONSTRAINTS",
    "CURRENCY_CONSTRAINTS",
    "EXCHANGE_RATE_CONSTRAINTS",
]
