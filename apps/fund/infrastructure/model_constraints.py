"""Database constraints for governed Fund reference and fact models."""

from django.db import models
from django.db.models import F, Q
from django.db.models.constraints import BaseConstraint

FUND_INFO_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(fund_scale__isnull=True) | Q(fund_scale__gte=0),
        name="fund_info_scale_nonnegative",
    ),
]

FUND_MANAGER_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(tenure_end__isnull=True) | Q(tenure_end__gte=F("tenure_start")),
        name="fund_manager_tenure_dates_ordered",
    ),
    models.CheckConstraint(
        condition=Q(total_tenure_days__isnull=True) | Q(total_tenure_days__gte=0),
        name="fund_manager_tenure_days_nonnegative",
    ),
]

FUND_NAV_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(condition=Q(unit_nav__gt=0), name="fund_nav_unit_positive"),
    models.CheckConstraint(condition=Q(accum_nav__gt=0), name="fund_nav_accum_positive"),
]

FUND_HOLDING_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(holding_amount__isnull=True) | Q(holding_amount__gte=0),
        name="fund_holding_amount_nonnegative",
    ),
    models.CheckConstraint(
        condition=Q(holding_value__isnull=True) | Q(holding_value__gte=0),
        name="fund_holding_value_nonnegative",
    ),
    models.CheckConstraint(
        condition=Q(holding_ratio__isnull=True) | Q(holding_ratio__gte=0, holding_ratio__lte=100),
        name="fund_holding_ratio_0_100",
    ),
]

FUND_SECTOR_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(allocation_ratio__gte=0, allocation_ratio__lte=100),
        name="fund_sector_ratio_0_100",
    ),
]

FUND_PERFORMANCE_CONSTRAINTS: list[BaseConstraint] = [
    models.CheckConstraint(
        condition=Q(end_date__gte=F("start_date")),
        name="fund_performance_dates_ordered",
    ),
    models.CheckConstraint(
        condition=Q(volatility__isnull=True) | Q(volatility__gte=0),
        name="fund_performance_volatility_nonnegative",
    ),
]

__all__ = [
    "FUND_HOLDING_CONSTRAINTS",
    "FUND_INFO_CONSTRAINTS",
    "FUND_MANAGER_CONSTRAINTS",
    "FUND_NAV_CONSTRAINTS",
    "FUND_PERFORMANCE_CONSTRAINTS",
    "FUND_SECTOR_CONSTRAINTS",
]
