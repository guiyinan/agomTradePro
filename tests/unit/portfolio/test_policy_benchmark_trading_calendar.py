"""Pure tests for the Portfolio benchmark trading-calendar methodology."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from apps.portfolio.domain.policy_benchmark_trading_calendar import (
    POLICY_BENCHMARK_TRADING_CALENDAR_TYPE,
    PolicyBenchmarkCalendarDay,
    PortfolioPolicyBenchmarkTradingCalendar,
)

RECORDED_AT = datetime(2026, 3, 1, tzinfo=UTC)


def _valuation_day(day: date, ordinal: int) -> PolicyBenchmarkCalendarDay:
    return PolicyBenchmarkCalendarDay(
        calendar_date=day,
        ordinal=ordinal,
        is_valuation_day=True,
        session_open_local=time(9, 30),
        session_close_local=time(15),
        valuation_cutoff_local=time(15, 30),
    )


def _closed_day(day: date, ordinal: int) -> PolicyBenchmarkCalendarDay:
    return PolicyBenchmarkCalendarDay(
        calendar_date=day,
        ordinal=ordinal,
        is_valuation_day=False,
        session_open_local=None,
        session_close_local=None,
        valuation_cutoff_local=None,
    )


def _calendar(**changes: object) -> PortfolioPolicyBenchmarkTradingCalendar:
    start = date(2026, 3, 9)
    days = (
        _valuation_day(start, 0),
        _valuation_day(start + timedelta(days=1), 1),
        _valuation_day(start + timedelta(days=2), 2),
        _valuation_day(start + timedelta(days=3), 3),
        _valuation_day(start + timedelta(days=4), 4),
        _closed_day(start + timedelta(days=5), 5),
        _closed_day(start + timedelta(days=6), 6),
    )
    values: dict[str, object] = {
        "methodology_id": "cn-equity-benchmark-calendar",
        "methodology_version": "v1",
        "market_calendar_code": "XSHG",
        "timezone": "Asia/Shanghai",
        "coverage_start": start,
        "coverage_end": start + timedelta(days=6),
        "days": days,
        "recorded_at": RECORDED_AT,
        "valid_until": datetime(2026, 3, 16, tzinfo=UTC),
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkTradingCalendar(**values)  # type: ignore[arg-type]


def test_calendar_seals_complete_daily_membership_and_fixed_authority() -> None:
    calendar = _calendar()
    payload = calendar.to_payload()

    assert calendar.owner == "portfolio"
    assert calendar.artifact_type == "trading_calendar_definition"
    assert calendar.permission == "methodology_definition_only"
    assert calendar.activation_available is False
    assert calendar.must_not_execute is True
    assert len(calendar.identity_hash) == 64
    assert len(calendar.content_hash) == 64
    assert len(payload["days"]) == 7  # type: ignore[arg-type]
    assert payload["days"][5] == {  # type: ignore[index]
        "calendar_date": "2026-03-14",
        "ordinal": 5,
        "is_valuation_day": False,
        "session_open_local": None,
        "session_close_local": None,
        "valuation_cutoff_local": None,
    }


def test_days_must_cover_every_date_once_in_exact_ordinal_order() -> None:
    calendar = _calendar()
    with pytest.raises(ValueError, match="coverage membership"):
        replace(calendar, days=calendar.days[:2] + calendar.days[3:], content_hash="")
    with pytest.raises(ValueError, match="ordinal"):
        replace(
            calendar,
            days=(calendar.days[1], calendar.days[0], *calendar.days[2:]),
            content_hash="",
        )
    with pytest.raises(ValueError, match="coverage"):
        replace(calendar, coverage_end=calendar.coverage_end + timedelta(days=1))


def test_valuation_and_nonvaluation_day_matrix_is_exact() -> None:
    with pytest.raises(ValueError, match="valuation day"):
        PolicyBenchmarkCalendarDay(
            calendar_date=date(2026, 3, 9),
            ordinal=0,
            is_valuation_day=True,
            session_open_local=time(9, 30),
            session_close_local=None,
            valuation_cutoff_local=time(15, 30),
        )
    with pytest.raises(ValueError, match="non-valuation day"):
        PolicyBenchmarkCalendarDay(
            calendar_date=date(2026, 3, 14),
            ordinal=0,
            is_valuation_day=False,
            session_open_local=time(9, 30),
            session_close_local=None,
            valuation_cutoff_local=None,
        )
    calendar = _calendar()
    with pytest.raises(ValueError, match="session clock"):
        _calendar(
            days=(
                replace(calendar.days[0], session_close_local=time(9)),
                *calendar.days[1:],
            )
        )


def test_iana_timezone_and_dst_local_times_are_interpreted_exactly() -> None:
    spring = date(2026, 3, 8)
    with pytest.raises(ValueError, match="does not exist"):
        _calendar(
            timezone="America/New_York",
            coverage_start=spring,
            coverage_end=spring,
            days=(
                PolicyBenchmarkCalendarDay(
                    calendar_date=spring,
                    ordinal=0,
                    is_valuation_day=True,
                    session_open_local=time(2, 30),
                    session_close_local=time(3, 30),
                    valuation_cutoff_local=time(4),
                ),
            ),
            valid_until=datetime(2026, 3, 9, 5, tzinfo=UTC),
        )

    fall = date(2026, 11, 1)
    with pytest.raises(ValueError, match="ambiguous"):
        _calendar(
            timezone="America/New_York",
            coverage_start=fall,
            coverage_end=fall,
            days=(
                PolicyBenchmarkCalendarDay(
                    calendar_date=fall,
                    ordinal=0,
                    is_valuation_day=True,
                    session_open_local=time(1, 15),
                    session_close_local=time(2, 30),
                    valuation_cutoff_local=time(3),
                ),
            ),
            valid_until=datetime(2026, 11, 2, 5, tzinfo=UTC),
        )

    resolved = _calendar(
        timezone="America/New_York",
        coverage_start=fall,
        coverage_end=fall,
        days=(
            PolicyBenchmarkCalendarDay(
                calendar_date=fall,
                ordinal=0,
                is_valuation_day=True,
                session_open_local=time(1, 15, fold=1),
                session_close_local=time(2, 30),
                valuation_cutoff_local=time(3),
            ),
        ),
        valid_until=datetime(2026, 11, 2, 5, tzinfo=UTC),
    )
    assert resolved.days[0].to_payload()["session_open_local"] == "01:15:00[fold=1]"


def test_timezone_clock_and_validity_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="IANA timezone"):
        _calendar(timezone="Not/AZone")
    with pytest.raises(ValueError, match="recorded_at"):
        _calendar(recorded_at=datetime(2026, 3, 1))
    with pytest.raises(ValueError, match="valid_until"):
        _calendar(valid_until=datetime(2026, 3, 16))
    with pytest.raises(ValueError, match="published before coverage"):
        _calendar(recorded_at=datetime(2026, 3, 10, tzinfo=UTC))
    with pytest.raises(ValueError, match="cover the complete calendar"):
        _calendar(valid_until=datetime(2026, 3, 15, tzinfo=UTC))


def test_hash_binds_timezone_membership_session_and_clock() -> None:
    calendar = _calendar()
    changed = _calendar(
        days=(
            replace(calendar.days[0], valuation_cutoff_local=time(15, 45)),
            *calendar.days[1:],
        )
    )
    assert changed.identity_hash == calendar.identity_hash
    assert changed.content_hash != calendar.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(calendar, market_calendar_code="XSHE")


def test_r8_monitoring_calendar_cannot_substitute_for_benchmark_methodology() -> None:
    assert POLICY_BENCHMARK_TRADING_CALENDAR_TYPE == "trading_calendar_definition"
    assert POLICY_BENCHMARK_TRADING_CALENDAR_TYPE != "r8_monitoring_calendar_definition"
    with pytest.raises(TypeError, match="calendar days"):
        _calendar(
            coverage_start=date(2026, 3, 9),
            coverage_end=date(2026, 3, 9),
            days=(object(),),
        )

    source = Path("apps/portfolio/domain/policy_benchmark_trading_calendar.py").read_text(
        encoding="utf-8"
    )
    assert "R8MonitoringCalendar" not in source
    assert "OptimizationMonitoringPeriod" not in source


def test_domain_has_only_standard_library_dependencies() -> None:
    source = Path("apps/portfolio/domain/policy_benchmark_trading_calendar.py").read_text(
        encoding="utf-8"
    )
    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
