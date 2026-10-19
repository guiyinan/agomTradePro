"""Persist one real formal calendar publication for the Auto caller fixture.

The calendar body is a local, fixed Tushare response fixture. It is retained,
parsed, stored, formally published, and read back through the production paths;
this helper does not call a provider or qualify external market data.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from hashlib import sha256
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import DEFAULT_DB_ALIAS, connection
from django.utils import timezone as django_timezone

from apps.config_center.application import runtime_config as runtime_config_application
from apps.config_center.application import runtime_public as runtime_public_application
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.config_center.domain import runtime_config as runtime_config_domain
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRequest,
    PublishExchangeCalendarSnapshotUseCase,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_at,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_capture_configuration_at,
)
from apps.data_center.domain.contracts import DatasetKey
from apps.data_center.domain.exchange_calendar import ExchangeCalendarSnapshot
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.exchange_calendar_repository import (
    DjangoExchangeCalendarSnapshotRepository,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
    DjangoFormalExchangeCalendarPublicationRepository,
)
from apps.simulated_trading import execution_current_reference_composition
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_current_published_execution_calendar_reader,
)
from tests.component.data_center import test_calendar_workbench_scope as calendar_scope_fixture
from tests.component.data_center import (
    test_formal_calendar_publication_postgres as calendar_publication_fixture,
)
from tests.component.data_center import (
    test_formal_exchange_calendar_publication_repository as calendar_source_fixture,
)
from tests.support.runtime_config import configure_critical_runtime

_DATASET_KEY = "data_center.exchange_calendar_snapshot"
_CONTRACT_VERSION = "2.0"
_SCHEMA_VERSION = "1.0"
_AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
_KNOWLEDGE_AT = _AS_OF - timedelta(seconds=10)
_PUBLICATION_AT = _AS_OF - timedelta(seconds=4)
_COVERAGE_START = date(2026, 10, 15)
_COVERAGE_END = date(2026, 10, 19)
_EXCHANGE_TIMEZONE_KEY = "config_center.market.exchange_timezone_map"


@dataclass(frozen=True, slots=True)
class FormalCalendarFixture:
    """Expose exact persisted publication, source bytes, and session evidence."""

    as_of: datetime
    dataset_key: str
    exchange: str
    timezone_name: str
    calendar_response_max_age_seconds: int
    snapshot: ExchangeCalendarSnapshot
    publication_id: str
    publication_hash: str
    raw_body: bytes
    raw_body_sha256: str
    raw_payload_hash: str
    calendar_evidence: ExecutionCalendarEvidence
    market_session: date
    next_open_session: date

    def __post_init__(self) -> None:
        """Require the result to retain exact source and publication identities."""

        if type(self.as_of) is not datetime or self.as_of.utcoffset() is None:
            raise TypeError("calendar fixture cutoff must be an aware datetime")
        if self.dataset_key != _DATASET_KEY or self.calendar_response_max_age_seconds != 900:
            raise ValueError("calendar fixture must retain the selected dataset TTL")
        if sha256(self.raw_body).hexdigest() != self.raw_body_sha256:
            raise ValueError("calendar fixture raw body digest does not match")
        if self.raw_body_sha256 != self.snapshot.raw_reference.body_sha256:
            raise ValueError("calendar fixture raw body is not bound to the snapshot")
        if self.raw_payload_hash != self.snapshot.raw_reference.payload_hash:
            raise ValueError("calendar fixture RawPayload identity does not match")
        if self.calendar_evidence.snapshot != self.snapshot:
            raise ValueError("calendar fixture reader did not return the persisted snapshot")


def persist_auto_uow_formal_calendar(
    *,
    as_of: datetime,
    exchange: str,
    timezone_name: str,
    advance_clock: Callable[[], None],
) -> FormalCalendarFixture:
    """Persist and reread a complete current formal calendar at the fixed cutoff.

    The active capture catalog, exact retained response, snapshot, runtime
    timezone profile, formal publication, and current-calendar reader all use
    their real repositories and application composition. Call
    :func:`freeze_auto_uow_fixture_clocks` before creating caller fixtures.
    Source and catalog clocks precede ``as_of`` by ten seconds; runtime snapshot
    clocks advance within the following second. Publication is four seconds early,
    and ``advance_clock`` moves audit reads to the explicit execution cutoff.
    """

    if connection.vendor != "postgresql":
        raise RuntimeError("the formal calendar publication fixture requires PostgreSQL")
    if type(as_of) is not datetime or as_of != _AS_OF or as_of.utcoffset() is None:
        raise ValueError("calendar fixture requires the exact aware 2026-10-16 02:00 UTC cutoff")
    if type(exchange) is not str or not exchange or exchange.strip() != exchange:
        raise ValueError("exchange must be an exact nonempty token")
    if (
        type(timezone_name) is not str
        or not timezone_name
        or timezone_name.strip() != timezone_name
    ):
        raise ValueError("timezone_name must be an exact nonempty token")
    try:
        exchange_timezone = ZoneInfo(timezone_name)
    except (TypeError, ValueError) as error:
        raise ValueError("timezone_name must identify an installed IANA timezone") from error
    if as_of.astimezone(exchange_timezone).date() != date(2026, 10, 16):
        raise ValueError("the requested exchange timezone must map the cutoff to 2026-10-16")

    _require_fixture_clocks_frozen()
    runtime_environment = _runtime_environment()
    source_rows = _calendar_rows(exchange)
    raw_body = _raw_calendar_body(source_rows)

    with _runtime_public_write_clock():
        configure_critical_runtime()
        activate_runtime_profile_patch(
            environment=runtime_environment,
            patch={_EXCHANGE_TIMEZONE_KEY: {exchange: timezone_name}},
            actor="ash03-auto-calendar-fixture",
            reason="bind the formal execution-calendar fixture timezone",
        )
    calendar_scope_fixture._write_configuration()

    capture_dataset = DatasetKey(_DATASET_KEY, _CONTRACT_VERSION, _SCHEMA_VERSION)
    with ExitStack() as fixture_patches:
        fixture_patches.enter_context(
            patch.object(calendar_source_fixture, "_DATASET", capture_dataset)
        )
        fixture_patches.enter_context(patch.object(calendar_source_fixture, "_EXCHANGE", exchange))
        fixture_patches.enter_context(
            patch.object(calendar_source_fixture, "_START", _COVERAGE_START)
        )
        fixture_patches.enter_context(patch.object(calendar_source_fixture, "_END", _COVERAGE_END))
        fixture_patches.enter_context(
            patch.object(calendar_source_fixture, "_PROVIDER_ROWS", list(source_rows))
        )
        candidate = calendar_source_fixture._candidate()
        if candidate.raw_reference.body_sha256 != sha256(raw_body).hexdigest():
            raise AssertionError("retained response body differs from the exact test fixture")
        snapshot = DjangoExchangeCalendarSnapshotRepository().save(candidate)
        contract = DatasetContractModel._default_manager.get(
            dataset_key=_DATASET_KEY,
            contract_version=_CONTRACT_VERSION,
            schema_version=_SCHEMA_VERSION,
        )
        policy = DatasetPublicationPolicyModel._default_manager.get(
            dataset_key=_DATASET_KEY,
            contract_version=_CONTRACT_VERSION,
            schema_version=_SCHEMA_VERSION,
        )
        request: CalendarFormalPublicationRequest = calendar_source_fixture._request(
            snapshot,
            contract,
            policy,
            activation_id="ash03-auto-current-calendar",
        )

    capture_configuration = read_calendar_capture_configuration_at(as_of=as_of)
    if capture_configuration.dataset.value != _DATASET_KEY:
        raise AssertionError("active calendar capture dataset differs from the fixture dataset")
    if capture_configuration.calendar_response_max_age_seconds != 900:
        raise AssertionError("active calendar capture TTL differs from its contract")

    # The authorization context must own the outer transaction and commit.
    with patch.object(django_timezone, "now", lambda: _PUBLICATION_AT):
        user, proof = calendar_publication_fixture._actual_publisher(
            f"ash03-auto-calendar-{uuid4().hex}"
        )
        del user
        authority = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
        publication_repository = DjangoFormalExchangeCalendarPublicationRepository(
            audit_port=calendar_publication_fixture._real_audit_bridge(),
            using=DEFAULT_DB_ALIAS,
            clock=lambda: _PUBLICATION_AT,
        )
        publish = PublishExchangeCalendarSnapshotUseCase(publication_repository)
        published = calendar_publication_fixture._authorized_publish(
            authority=authority,
            use_case=publish,
            proof=proof,
            request=request,
        )

    advance_clock()
    current = read_current_exchange_calendar_at(
        ReadCurrentExchangeCalendarPublicationQuery(
            dataset_key=_DATASET_KEY,
            exchange=exchange,
            as_of=as_of,
        )
    )
    if current.record != published.record or current.pointer != published.pointer:
        raise AssertionError(
            "current formal calendar read differs from the publication just written"
        )

    reader = build_current_published_execution_calendar_reader(
        dataset_key=capture_configuration.dataset.value,
        runtime_environment=runtime_environment,
    )
    evidence = reader.get_effective_execution_calendar(
        exchange=exchange,
        as_of=as_of,
        coverage_start=_COVERAGE_START,
    )
    if evidence is None:
        raise AssertionError("current formal calendar reader returned no execution evidence")
    evidence.validate_for(as_of)
    expected_dates = tuple(
        _COVERAGE_START + timedelta(days=offset)
        for offset in range((_COVERAGE_END - _COVERAGE_START).days + 1)
    )
    if tuple(day.calendar_date for day in evidence.snapshot.days) != expected_dates:
        raise AssertionError("formal calendar fixture must retain every date from 15 through 19")
    if tuple(day.is_open for day in evidence.snapshot.days) != (True, True, False, False, True):
        raise AssertionError("formal calendar fixture open/closed sessions are incomplete")
    expected_previous_open = (
        date(2026, 10, 14),
        date(2026, 10, 15),
        date(2026, 10, 16),
        date(2026, 10, 16),
        date(2026, 10, 16),
    )
    if tuple(day.previous_open_date for day in evidence.snapshot.days) != expected_previous_open:
        raise AssertionError("formal calendar fixture previous-open dates are inconsistent")
    if evidence.publication is None or evidence.publication.timezone_name != timezone_name:
        raise AssertionError("formal publication does not retain the active exchange timezone")

    market_session = evidence.current_open_session(as_of)
    next_open_session = evidence.release_session(market_session, 1)
    if market_session != date(2026, 10, 16) or next_open_session != date(2026, 10, 19):
        raise AssertionError("calendar fixture did not resolve the expected session and T+1 date")
    return FormalCalendarFixture(
        as_of=as_of,
        dataset_key=_DATASET_KEY,
        exchange=exchange,
        timezone_name=timezone_name,
        calendar_response_max_age_seconds=capture_configuration.calendar_response_max_age_seconds,
        snapshot=evidence.snapshot,
        publication_id=evidence.publication.publication_id,
        publication_hash=evidence.publication.publication_hash,
        raw_body=raw_body,
        raw_body_sha256=sha256(raw_body).hexdigest(),
        raw_payload_hash=evidence.snapshot.raw_reference.payload_hash,
        calendar_evidence=evidence,
        market_session=market_session,
        next_open_session=next_open_session,
    )


def freeze_auto_uow_fixture_clocks(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze fixture knowledge writes ten seconds before the fixed UoW cutoff.

    Runtime-profile, capture-configuration, raw-source, Django model, and
    settlement-clock seams share this timestamp. The runtime-public module
    keeps the native datetime class for strict cutoff reads; profile writes
    temporarily use the fixed subclass. The V2 source's own observed,
    available, and source flags are not rewritten by this clock fixture.
    """

    fixed_datetime = _datetime_class_at(_KNOWLEDGE_AT)
    monkeypatch.setattr(django_timezone, "now", _fixed_django_now)
    monkeypatch.setattr(runtime_public_application, "datetime", datetime)
    monkeypatch.setattr(runtime_config_application, "datetime", fixed_datetime)
    monkeypatch.setattr(runtime_config_domain, "datetime", fixed_datetime)
    monkeypatch.setattr(tushare_client, "datetime", fixed_datetime)
    monkeypatch.setattr(calendar_source_fixture, "datetime", fixed_datetime)
    monkeypatch.setattr(
        execution_current_reference_composition._ServerUTCClock,
        "now",
        _fixed_server_clock_now,
    )
    return _KNOWLEDGE_AT


def _fixed_django_now() -> datetime:
    """Return the fixture's single aware knowledge-write instant."""

    return _KNOWLEDGE_AT


def _fixed_server_clock_now(_clock: object) -> datetime:
    """Return the same instant through the current-reference UoW clock seam."""

    return _KNOWLEDGE_AT


def _require_fixture_clocks_frozen() -> None:
    """Reject setup unless every direct timestamp seam is on the exact clock."""

    datetime_modules = (
        runtime_config_application,
        tushare_client,
        calendar_source_fixture,
    )
    if runtime_public_application.datetime is not datetime:
        raise RuntimeError("runtime-public cutoff reader must retain the native datetime class")
    if django_timezone.now().astimezone(UTC) != _KNOWLEDGE_AT:
        raise RuntimeError("Django fixture clock is not frozen at the expected instant")
    if execution_current_reference_composition._ServerUTCClock().now() != _KNOWLEDGE_AT:
        raise RuntimeError("settlement fixture clock is not frozen at the expected instant")
    if any(module.datetime.now(UTC) != _KNOWLEDGE_AT for module in datetime_modules):
        raise RuntimeError("a direct fixture datetime seam is not frozen at the expected instant")
    runtime_known_at = runtime_config_domain.datetime.now(UTC)
    if not _KNOWLEDGE_AT <= runtime_known_at < _KNOWLEDGE_AT + timedelta(seconds=1):
        raise RuntimeError("runtime snapshot clock is outside its bounded knowledge window")


@contextmanager
def _runtime_public_write_clock() -> Iterator[None]:
    """Freeze profile-write timestamps without changing strict cutoff checks."""

    fixed_datetime = _datetime_class_at(_KNOWLEDGE_AT)
    with patch.object(runtime_public_application, "datetime", fixed_datetime):
        yield


def _runtime_environment() -> str:
    """Return the settings-matched Config Center runtime environment."""

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    return "production" if settings_module.endswith(".production") else "development"


def _datetime_class_at(value: datetime) -> type[datetime]:
    """Build a temporary datetime subclass whose ``now`` is one exact instant."""

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            """Return the requested UTC instant in the caller's timezone."""

            selected = value.replace(tzinfo=None) if tz is None else value.astimezone(tz)
            return cls(
                selected.year,
                selected.month,
                selected.day,
                selected.hour,
                selected.minute,
                selected.second,
                selected.microsecond,
                tzinfo=selected.tzinfo,
                fold=selected.fold,
            )

    return _FixedDateTime


def _calendar_rows(exchange: str) -> tuple[tuple[str, str, int, str], ...]:
    """Return the complete, explicit weekday and weekend response fixture."""

    return (
        (exchange, "20261015", 1, "20261014"),
        (exchange, "20261016", 1, "20261015"),
        (exchange, "20261017", 0, "20261016"),
        (exchange, "20261018", 0, "20261016"),
        (exchange, "20261019", 1, "20261016"),
    )


def _raw_calendar_body(rows: tuple[tuple[str, str, int, str], ...]) -> bytes:
    """Serialize the exact body shape consumed by the real Tushare parser."""

    fields = "exchange,cal_date,is_open,pretrade_date"
    body = {
        "code": 0,
        "msg": None,
        "data": {"fields": fields.split(","), "items": [list(row) for row in rows]},
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


__all__ = [
    "FormalCalendarFixture",
    "freeze_auto_uow_fixture_clocks",
    "persist_auto_uow_formal_calendar",
]
