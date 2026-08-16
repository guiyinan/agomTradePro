"""Append-only ledger and exact PIT reads for benchmark trading calendars."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.portfolio.domain.policy_benchmark_trading_calendar import (
    PortfolioPolicyBenchmarkTradingCalendar,
)
from apps.portfolio.infrastructure.policy_benchmark_trading_calendar_codec import (
    PolicyBenchmarkTradingCalendarCodecError,
    decode_policy_benchmark_trading_calendar,
    encode_policy_benchmark_trading_calendar,
)
from apps.portfolio.infrastructure.policy_benchmark_trading_calendar_models import (
    _ACTIVE_CALENDAR_UOW,
    PortfolioPolicyBenchmarkTradingCalendarModel,
    _activate_calendar_uow,
    _claim_calendar_insert,
)


class PolicyBenchmarkTradingCalendarUnavailable(ValueError):
    """An exact calendar is unavailable at the requested cutoff."""


class PolicyBenchmarkTradingCalendarConflict(ValueError):
    """An immutable calendar anchor has another first winner."""


class PolicyBenchmarkTradingCalendarCorruption(ValueError):
    """Persisted calendar data failed exact validation."""


class PolicyBenchmarkTradingCalendarClock(Protocol):
    """Authoritative Portfolio calendar persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoPolicyBenchmarkTradingCalendarClock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""
        return timezone.now()


class DjangoPolicyBenchmarkTradingCalendarRepository:
    """Private first-winner writer and strict historical exact reader."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self, *, using: str = "default", clock: PolicyBenchmarkTradingCalendarClock | None = None
    ) -> None:
        self._using = using
        self._clock = clock or DjangoPolicyBenchmarkTradingCalendarClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open this capability's private append transaction."""
        token = object()
        with transaction.atomic(using=self._using), _activate_calendar_uow(token):
            yield

    def now(self) -> datetime:
        """Return the validated authoritative Portfolio clock."""
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PolicyBenchmarkTradingCalendarCorruption("calendar clock is naive")
        return value

    def append(
        self, value: PortfolioPolicyBenchmarkTradingCalendar, *, recorded_at: datetime
    ) -> PortfolioPolicyBenchmarkTradingCalendar:
        """Append or return the exact identity/content first winner."""
        token = _active_token()
        _validate(value)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise PolicyBenchmarkTradingCalendarConflict("recorded_at must be timezone-aware")
        if value.recorded_at != recorded_at:
            raise PolicyBenchmarkTradingCalendarConflict(
                "calendar recorded_at must equal the authoritative server clock"
            )
        if recorded_at >= value.valid_until:
            raise PolicyBenchmarkTradingCalendarConflict(
                "calendar must be persisted within its validity window"
            )
        existing = _exact(self._all(), value)
        if existing is not None:
            return existing[0]
        values = _model_values(value, recorded_at)
        model = PortfolioPolicyBenchmarkTradingCalendarModel(**values)
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_calendar_insert(
                    token=token,
                    model_type=PortfolioPolicyBenchmarkTradingCalendarModel,
                    expected_values=values,
                ),
            ):
                model.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = _exact(self._all(), value)
            if winner is None:
                raise PolicyBenchmarkTradingCalendarConflict(
                    "calendar append conflicted without exact first winner"
                ) from None
            return winner[0]
        return self._restore(model)

    def get_exact(
        self,
        *,
        methodology_id: str,
        methodology_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PortfolioPolicyBenchmarkTradingCalendar | None:
        """Return one exact definition by full selector at a strict PIT cutoff."""
        self._require_cutoff(as_of)
        matches = tuple(
            value
            for value, _ in self._all()
            if value.methodology_id == methodology_id
            and value.methodology_version == methodology_version
            and value.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise PolicyBenchmarkTradingCalendarCorruption("calendar selector is ambiguous")
        if not matches:
            return None
        return matches[0] if matches[0].is_knowable_at(as_of) else None

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PolicyBenchmarkTradingCalendarUnavailable("calendar as_of is naive")
        if as_of > self.now():
            raise PolicyBenchmarkTradingCalendarUnavailable("future calendar as_of is forbidden")

    def _all(
        self,
    ) -> tuple[
        tuple[
            PortfolioPolicyBenchmarkTradingCalendar, PortfolioPolicyBenchmarkTradingCalendarModel
        ],
        ...,
    ]:
        rows = tuple(
            PortfolioPolicyBenchmarkTradingCalendarModel._default_manager.using(self._using).all()
        )
        return tuple((self._restore(row), row) for row in rows)

    def _restore(
        self, model: PortfolioPolicyBenchmarkTradingCalendarModel
    ) -> PortfolioPolicyBenchmarkTradingCalendar:
        try:
            value = decode_policy_benchmark_trading_calendar(model.canonical_payload)
        except PolicyBenchmarkTradingCalendarCodecError as error:
            raise PolicyBenchmarkTradingCalendarCorruption(
                "calendar payload cannot be restored"
            ) from error
        if _headers(value) != _model_headers(model):
            raise PolicyBenchmarkTradingCalendarCorruption("calendar headers do not match payload")
        if (
            model.identity_hash != value.identity_hash
            or model.content_hash != value.content_hash
            or model.ledger_header_hash != _ledger_header_hash(value, model.recorded_at)
        ):
            raise PolicyBenchmarkTradingCalendarCorruption("calendar ledger seal is invalid")
        if (
            model.persisted_at.tzinfo is None
            or model.persisted_at.utcoffset() is None
            or model.persisted_at != model.recorded_at
            or value.recorded_at != model.recorded_at
            or model.recorded_at >= value.valid_until
        ):
            raise PolicyBenchmarkTradingCalendarCorruption("calendar persistence clock is invalid")
        return value


CalendarState = tuple[
    PortfolioPolicyBenchmarkTradingCalendar, PortfolioPolicyBenchmarkTradingCalendarModel
]


def _active_token() -> object:
    token = _ACTIVE_CALENDAR_UOW.get()
    if token is None:
        raise PolicyBenchmarkTradingCalendarConflict(
            "calendar append requires an active private unit"
        )
    return token


def _validate(value: object) -> PortfolioPolicyBenchmarkTradingCalendar:
    if type(value) is not PortfolioPolicyBenchmarkTradingCalendar:
        raise PolicyBenchmarkTradingCalendarConflict("calendar type substitution")
    try:
        PortfolioPolicyBenchmarkTradingCalendar.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PolicyBenchmarkTradingCalendarConflict("calendar is invalid") from error
    return value


def _exact(
    rows: tuple[CalendarState, ...], value: PortfolioPolicyBenchmarkTradingCalendar
) -> CalendarState | None:
    candidates = tuple(
        item
        for item in rows
        if (item[0].methodology_id, item[0].methodology_version)
        == (value.methodology_id, value.methodology_version)
        or item[0].identity_hash == value.identity_hash
        or item[0].content_hash == value.content_hash
    )
    if not candidates:
        return None
    matches = tuple(item for item in candidates if item[0] == value)
    if len(candidates) != 1 or len(matches) != 1:
        raise PolicyBenchmarkTradingCalendarConflict("calendar anchor has another first winner")
    return matches[0]


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _membership_hash(value: PortfolioPolicyBenchmarkTradingCalendar) -> str:
    return _hash({"days": [day.to_payload() for day in value.days]})


def _ledger_header_hash(
    value: PortfolioPolicyBenchmarkTradingCalendar, recorded_at: datetime
) -> str:
    return _hash(
        {
            "identity_hash": value.identity_hash,
            "content_hash": value.content_hash,
            "methodology_id": value.methodology_id,
            "methodology_version": value.methodology_version,
            "membership_hash": _membership_hash(value),
            "recorded_at": _time(recorded_at),
            "valid_until": _time(value.valid_until),
        }
    )


def _model_values(
    value: PortfolioPolicyBenchmarkTradingCalendar, recorded_at: datetime
) -> dict[str, object]:
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "methodology_id": value.methodology_id,
        "methodology_version": value.methodology_version,
        "market_calendar_code": value.market_calendar_code,
        "timezone_name": value.timezone,
        "coverage_start": value.coverage_start,
        "coverage_end": value.coverage_end,
        "day_count": len(value.days),
        "valuation_day_count": sum(day.is_valuation_day for day in value.days),
        "membership_hash": _membership_hash(value),
        "recorded_at": recorded_at,
        "valid_until": value.valid_until,
        "persisted_at": recorded_at,
        "canonical_payload": encode_policy_benchmark_trading_calendar(value),
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "ledger_header_hash": _ledger_header_hash(value, recorded_at),
    }


def _headers(value: PortfolioPolicyBenchmarkTradingCalendar) -> tuple[object, ...]:
    return (
        value.owner,
        value.artifact_type,
        value.schema,
        value.permission,
        value.methodology_id,
        value.methodology_version,
        value.market_calendar_code,
        value.timezone,
        value.coverage_start,
        value.coverage_end,
        len(value.days),
        sum(day.is_valuation_day for day in value.days),
        _membership_hash(value),
        value.recorded_at,
        value.valid_until,
        value.identity_hash,
        value.content_hash,
    )


def _model_headers(model: PortfolioPolicyBenchmarkTradingCalendarModel) -> tuple[object, ...]:
    return (
        model.owner,
        model.artifact_type,
        model.schema,
        model.permission,
        model.methodology_id,
        model.methodology_version,
        model.market_calendar_code,
        model.timezone_name,
        model.coverage_start,
        model.coverage_end,
        model.day_count,
        model.valuation_day_count,
        model.membership_hash,
        model.recorded_at,
        model.valid_until,
        model.identity_hash,
        model.content_hash,
    )


__all__ = [
    "DjangoPolicyBenchmarkTradingCalendarClock",
    "DjangoPolicyBenchmarkTradingCalendarRepository",
    "PolicyBenchmarkTradingCalendarClock",
    "PolicyBenchmarkTradingCalendarConflict",
    "PolicyBenchmarkTradingCalendarCorruption",
    "PolicyBenchmarkTradingCalendarUnavailable",
]
