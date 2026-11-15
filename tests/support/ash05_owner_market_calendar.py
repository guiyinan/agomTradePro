"""Explicit synthetic provider calendar for the owner price-publication journeys."""

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from apps.data_center import provider_runtime
from apps.data_center.application.interface_services import save_provider_settings_payload
from apps.data_center.application.market_calendar import load_cn_market_calendar_evidence
from apps.data_center.infrastructure import _provider_adapter_akshare
from apps.data_center.infrastructure.models import ProviderConfigModel
from tests.support.ash03_auto_calendar_fixture import FormalCalendarFixture, _calendar_rows

OwnerModelCalendarInstaller = Callable[[FormalCalendarFixture], None]


class SyntheticOwnerCalendarTransport:
    """Serve local weekday rows through the real AKShare calendar normalizer."""

    def __init__(self, calendar: FormalCalendarFixture) -> None:
        """Retain a bounded schedule consistent with the published fixture."""
        today = calendar.as_of.astimezone(ZoneInfo(calendar.timezone_name)).date()
        self._schedule = _calendar_rows(
            calendar.exchange,
            start=today - timedelta(days=52),
            end=today + timedelta(days=7),
        )
        published = {day.calendar_date: day.is_open for day in calendar.snapshot.days}
        for _exchange, encoded, opened, _previous in self._schedule:
            day = datetime.strptime(encoded, "%Y%m%d").date()
            if day in published and bool(opened) != published[day]:
                raise AssertionError("synthetic provider calendar differs from its publication")

    def tool_trade_date_hist_sina(self) -> object:
        """Return only synthetic open dates; the adapter sets its actual observed time."""
        import pandas as pd

        return pd.DataFrame(
            {
                "trade_date": [
                    datetime.strptime(encoded, "%Y%m%d").date().isoformat()
                    for _exchange, encoded, opened, _previous in self._schedule
                    if opened == 1
                ]
            }
        )


@pytest.fixture
def owner_model_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[OwnerModelCalendarInstaller]:
    """Install an explicit provider route after world setup and isolate its caches."""

    def install(calendar: FormalCalendarFixture) -> None:
        """Configure this test's route without changing price policies or clock gates."""
        transport = SyntheticOwnerCalendarTransport(calendar)
        settings = save_provider_settings_payload(
            default_source="akshare",
            enable_failover=False,
            failover_tolerance=0.01,
            actor="pytest.ash05-synthetic-owner-calendar",
        )
        if settings.get("status") != "active":
            raise AssertionError("synthetic owner calendar provider settings are blocked")
        ProviderConfigModel._default_manager.create(
            name=f"ash05-synthetic-owner-calendar-{uuid4().hex}",
            source_type="akshare",
            is_active=True,
            priority=1,
            extra_config={"synthetic_fixture": True},
            description="Synthetic calendar transport for owner raw-price acceptance only.",
        )
        monkeypatch.setattr(_provider_adapter_akshare, "get_akshare_module", lambda: transport)
        provider_runtime.reset_registry()
        load_cn_market_calendar_evidence.cache_clear()

    try:
        yield install
    finally:
        load_cn_market_calendar_evidence.cache_clear()
        provider_runtime.reset_registry()


__all__ = ["OwnerModelCalendarInstaller", "owner_model_calendar"]
