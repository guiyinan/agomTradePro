"""Owner fixture calendar routes retain the production weekend freshness fence."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from apps.data_center.application import market_calendar
from apps.data_center.application.interface_services import load_provider_settings_payload
from apps.data_center.calendar_evidence_composition import build_calendar_evidence_port
from tests.support.ash03_auto_calendar_fixture import FormalCalendarFixture
from tests.support.ash05_owner_market_calendar import (
    OwnerModelCalendarInstaller,
    SyntheticOwnerCalendarTransport,
)
from tests.support.ash05_owner_market_calendar import (  # noqa: F401
    owner_model_calendar as owner_model_calendar,
)
from tests.support.runtime_config import configure_critical_runtime


def _scope(*, wrong_open_day: bool = False) -> FormalCalendarFixture:
    """Supply only the published scope read by the synthetic transport unit test."""
    return cast(
        FormalCalendarFixture,
        SimpleNamespace(
            as_of=datetime(2026, 11, 15, 8, tzinfo=UTC),
            exchange="SZSE",
            timezone_name="Asia/Shanghai",
            snapshot=SimpleNamespace(
                days=(
                    SimpleNamespace(calendar_date=date(2026, 11, 13), is_open=True),
                    SimpleNamespace(calendar_date=date(2026, 11, 14), is_open=wrong_open_day),
                    SimpleNamespace(calendar_date=date(2026, 11, 15), is_open=False),
                )
            ),
        ),
    )


@pytest.mark.django_db
def test_explicit_owner_route_resolves_the_closed_weekend_through_actual_composition(
    owner_model_calendar: OwnerModelCalendarInstaller,
) -> None:
    """Missing configuration blocks; configured SDK rows reach the real session reader."""
    cutoff = datetime(2026, 11, 15, 8, tzinfo=UTC)
    configure_critical_runtime()
    market_calendar.load_cn_market_calendar_evidence.cache_clear()
    assert load_provider_settings_payload()["status"] == "blocked"
    assert market_calendar.latest_completed_cn_market_session(cutoff) is None

    owner_model_calendar(_scope())
    settings = load_provider_settings_payload()
    assert settings["status"] == "active"
    assert settings["default_source"] == "akshare"
    assert market_calendar.latest_completed_cn_market_session(cutoff) == date(2026, 11, 13)
    before = datetime.now(UTC)
    evidence = build_calendar_evidence_port().trading_calendar_evidence(
        date(2026, 11, 15) - timedelta(days=45), date(2026, 11, 15)
    )
    after = datetime.now(UTC)
    assert evidence.coverage_start == date(2026, 10, 1)
    assert evidence.coverage_end == date(2026, 11, 15)
    assert evidence.source == "akshare"
    assert evidence.open_sessions[-1] == date(2026, 11, 13)
    assert before <= evidence.observed_at <= after


def test_owner_calendar_transport_rejects_conflicting_published_states() -> None:
    """The support route cannot silently disagree with the formal fixture calendar."""
    with pytest.raises(AssertionError, match="differs from its publication"):
        SyntheticOwnerCalendarTransport(_scope(wrong_open_day=True))
