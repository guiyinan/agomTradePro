from datetime import date

import pytest
from django.db import IntegrityError, transaction

from apps.regime.infrastructure.models import RegimeLog
from apps.regime.management.commands.recalculate_regime import Command


def test_recalculate_regime_help_warns_about_daily_backfill_runtime() -> None:
    assert "小时" in Command.help
    assert "daily" in Command.help


def test_recalculate_regime_daily_dates_fill_calendar_gaps() -> None:
    dates = Command._build_calculation_dates(
        available_dates=[date(2026, 1, 31), date(2026, 2, 28)],
        start_date=date(2026, 1, 30),
        end_date=date(2026, 2, 2),
        frequency="daily",
    )

    assert dates == [date(2026, 1, 31), date(2026, 2, 1), date(2026, 2, 2)]


def test_recalculate_regime_monthly_dates_keep_last_available_day() -> None:
    dates = Command._build_calculation_dates(
        available_dates=[date(2026, 1, 15), date(2026, 1, 31), date(2026, 2, 20)],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 28),
        frequency="monthly",
    )

    assert dates == [date(2026, 1, 31), date(2026, 2, 20)]


@pytest.mark.django_db
def test_regime_log_rejects_legacy_strategy_code_after_normalization() -> None:
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RegimeLog.objects.create(
                observed_at=date(2026, 1, 1),
                growth_momentum_z=0.1,
                inflation_momentum_z=0.2,
                distribution={"Overheat": 1.0},
                dominant_regime="HG",
                confidence=1.0,
            )
