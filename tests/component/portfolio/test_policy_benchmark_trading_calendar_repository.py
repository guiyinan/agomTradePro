"""Component coverage for benchmark trading-calendar persistence."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, models
from django.db.migrations import RunPython, RunSQL
from django.db.migrations.state import ProjectState

from apps.portfolio.domain.policy_benchmark_trading_calendar import (
    PolicyBenchmarkCalendarDay,
    PortfolioPolicyBenchmarkTradingCalendar,
)
from apps.portfolio.infrastructure.policy_benchmark_trading_calendar_codec import (
    PolicyBenchmarkTradingCalendarCodecError,
    decode_policy_benchmark_trading_calendar,
    encode_policy_benchmark_trading_calendar,
)
from apps.portfolio.infrastructure.policy_benchmark_trading_calendar_models import (
    PortfolioPolicyBenchmarkTradingCalendarModel,
)
from apps.portfolio.infrastructure.policy_benchmark_trading_calendar_repository import (
    DjangoPolicyBenchmarkTradingCalendarRepository,
    PolicyBenchmarkTradingCalendarConflict,
    PolicyBenchmarkTradingCalendarCorruption,
    _model_values,
)

NOW = datetime(2026, 10, 31, 0, tzinfo=UTC)
VALID_UNTIL = datetime(2026, 11, 3, 6, tzinfo=UTC)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _calendar(**changes: object) -> PortfolioPolicyBenchmarkTradingCalendar:
    values: dict[str, object] = {
        "methodology_id": "nyse-benchmark-calendar",
        "methodology_version": "v1",
        "market_calendar_code": "XNYS",
        "timezone": "America/New_York",
        "coverage_start": date(2026, 11, 1),
        "coverage_end": date(2026, 11, 2),
        "days": (
            PolicyBenchmarkCalendarDay(
                date(2026, 11, 1),
                0,
                True,
                time(1, 15, fold=1),
                time(2, 30),
                time(3),
            ),
            PolicyBenchmarkCalendarDay(date(2026, 11, 2), 1, False, None, None, None),
        ),
        "recorded_at": NOW,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkTradingCalendar(**values)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_append_codec_idempotency_and_exact_pit_roundtrip() -> None:
    repo = DjangoPolicyBenchmarkTradingCalendarRepository(clock=FixedClock(NOW))
    calendar = _calendar()
    with repo.atomic():
        assert repo.append(calendar, recorded_at=NOW) == calendar
        assert repo.append(calendar, recorded_at=NOW) == calendar
    assert PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.count() == 1
    assert (
        decode_policy_benchmark_trading_calendar(encode_policy_benchmark_trading_calendar(calendar))
        == calendar
    )
    assert (
        repo.get_exact(
            methodology_id=calendar.methodology_id,
            methodology_version="v1",
            expected_content_hash=calendar.content_hash,
            as_of=NOW,
        )
        == calendar
    )
    assert (
        repo.get_exact(
            methodology_id=calendar.methodology_id,
            methodology_version="v1",
            expected_content_hash=calendar.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    repo._clock.value = VALID_UNTIL  # type: ignore[attr-defined]
    assert (
        repo.get_exact(
            methodology_id=calendar.methodology_id,
            methodology_version="v1",
            expected_content_hash=calendar.content_hash,
            as_of=VALID_UNTIL,
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_private_uow_and_first_winner_fail_closed() -> None:
    repo = DjangoPolicyBenchmarkTradingCalendarRepository(clock=FixedClock(NOW))
    first = _calendar()
    with pytest.raises(PolicyBenchmarkTradingCalendarConflict, match="private unit"):
        repo.append(first, recorded_at=NOW)
    with repo.atomic():
        repo.append(first, recorded_at=NOW)
    conflicting_days = (
        PolicyBenchmarkCalendarDay(date(2026, 11, 1), 0, False, None, None, None),
        PolicyBenchmarkCalendarDay(date(2026, 11, 2), 1, False, None, None, None),
    )
    with repo.atomic(), pytest.raises(PolicyBenchmarkTradingCalendarConflict, match="first winner"):
        repo.append(_calendar(days=conflicting_days), recorded_at=NOW)


@pytest.mark.django_db(transaction=True)
def test_direct_mutation_paths_are_blocked() -> None:
    repo = DjangoPolicyBenchmarkTradingCalendarRepository(clock=FixedClock(NOW))
    calendar = _calendar()
    with repo.atomic():
        repo.append(calendar, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.get()
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(raw=True)
    with pytest.raises(ValidationError, match="updated"):
        PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="bulk updated"):
        PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.bulk_update(
            [row], ["content_hash"]
        )
    with pytest.raises(ValidationError, match="deleted"):
        PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.all()._raw_delete("default")
    with pytest.raises(ValidationError, match="deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="exact repository"):
        PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.bulk_create(
            [PortfolioPolicyBenchmarkTradingCalendarModel(**_model_values(calendar, NOW))]
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_restore_detects_hidden_selector_and_membership_tamper() -> None:
    repo = DjangoPolicyBenchmarkTradingCalendarRepository(clock=FixedClock(NOW))
    calendar = _calendar()
    with repo.atomic():
        repo.append(calendar, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_trading_calendar SET methodology_id=%s, methodology_version=%s, identity_hash=%s, content_hash=%s WHERE id=%s",
            ["hidden", "hidden", "0" * 64, "1" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkTradingCalendarCorruption):
        repo.get_exact(
            methodology_id=calendar.methodology_id,
            methodology_version="v1",
            expected_content_hash=calendar.content_hash,
            as_of=NOW,
        )
    with repo.atomic(), pytest.raises(PolicyBenchmarkTradingCalendarCorruption):
        repo.append(calendar, recorded_at=NOW)


@pytest.mark.django_db(transaction=True)
def test_dst_membership_and_persistence_header_seals_are_verified() -> None:
    repo = DjangoPolicyBenchmarkTradingCalendarRepository(clock=FixedClock(NOW))
    calendar = _calendar()
    with repo.atomic():
        repo.append(calendar, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.get()
    assert row.canonical_payload["days"][0]["session_open_local"] == "01:15:00[fold=1]"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_trading_calendar SET membership_hash=%s WHERE id=%s",
            ["0" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkTradingCalendarCorruption, match="headers"):
        repo.get_exact(
            methodology_id=calendar.methodology_id,
            methodology_version="v1",
            expected_content_hash=calendar.content_hash,
            as_of=NOW,
        )


def test_codec_rejects_noncanonical_dst_and_unknown_fields() -> None:
    payload = encode_policy_benchmark_trading_calendar(_calendar())
    days = list(payload["days"])  # type: ignore[arg-type]
    days[0] = {**days[0], "session_open_local": "01:15:00"}  # type: ignore[arg-type]
    with pytest.raises(PolicyBenchmarkTradingCalendarCodecError):
        decode_policy_benchmark_trading_calendar({**payload, "days": days})
    with pytest.raises(PolicyBenchmarkTradingCalendarCodecError, match="shape"):
        decode_policy_benchmark_trading_calendar({**payload, "current": True})


def test_migration_is_schema_only_zero_seed_and_matches_runtime_model() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0021_policy_benchmark_trading_calendar"
    ).Migration
    assert migration.dependencies == [("portfolio", "0020_policy_benchmark_definition")]
    assert len(migration.operations) == 1
    assert not any(isinstance(item, (RunPython, RunSQL)) for item in migration.operations)
    state = ProjectState()
    migration.operations[0].state_forwards("portfolio", state)
    rendered = state.apps.get_model("portfolio", "PortfolioPolicyBenchmarkTradingCalendarModel")

    def fields(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        result = []
        for field in model_type._meta.local_fields:
            _, path, args, kwargs = field.deconstruct()
            result.append((field.name, path, args, kwargs))
        return result

    assert fields(rendered) == fields(PortfolioPolicyBenchmarkTradingCalendarModel)
    assert [item.deconstruct() for item in rendered._meta.indexes] == [
        item.deconstruct() for item in PortfolioPolicyBenchmarkTradingCalendarModel._meta.indexes
    ]
    assert [item.deconstruct() for item in rendered._meta.constraints] == [
        item.deconstruct()
        for item in PortfolioPolicyBenchmarkTradingCalendarModel._meta.constraints
    ]
