"""Explicit composition checks for settlement-bound simulated trading."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import cast

import pytest

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    PublishedExecutionCalendarReader,
    ReleaseDueSimulatedSettlementsUseCase,
)
from apps.simulated_trading.application.fee_policy_v2 import (
    CreateFeePolicyVersionUseCase,
    FeePolicyVersionStorageUnavailable,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import ExecutionCalendarEvidence
from apps.simulated_trading.execution_settlement_composition import (
    build_create_fee_policy_version_use_case,
    build_execute_settlement_bound_simulated_trade_use_case,
    build_release_due_simulated_settlements_use_case,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)


class _RuleReader:
    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        raise AssertionError("composition must not read a rule")


class _CalendarReader:
    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        raise AssertionError("composition must not read a calendar")


class _IdentityReader:
    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1 | None:
        raise AssertionError("composition must not read instrument identity")


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 16, tzinfo=UTC)


def test_trade_composition_requires_ports_and_shares_alias_bound_repository() -> None:
    rule_reader = _RuleReader()
    calendar_reader = _CalendarReader()
    identity_reader = _IdentityReader()
    clock = _Clock()

    use_case = build_execute_settlement_bound_simulated_trade_use_case(
        using="execution_test",
        rule_reader=rule_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        clock=clock,
    )

    assert type(use_case) is ExecuteSettlementBoundSimulatedTradeUseCase
    repository = use_case._repository
    assert type(repository) is DjangoSimulatedTradeExecutionRepository
    assert repository._using == "execution_test"
    assert use_case._fee_policy_reader is repository
    assert use_case._rule_reader is rule_reader
    assert use_case._identity_reader is identity_reader
    assert use_case._calendar_reader is calendar_reader
    assert use_case._clock is clock


def test_release_composition_requires_calendar_and_explicit_database_alias() -> None:
    calendar_reader = _CalendarReader()
    clock = _Clock()

    use_case = build_release_due_simulated_settlements_use_case(
        using="release_test",
        calendar_reader=calendar_reader,
        clock=clock,
    )

    assert type(use_case) is ReleaseDueSimulatedSettlementsUseCase
    assert type(use_case._repository) is DjangoSimulatedTradeExecutionRepository
    assert use_case._repository._using == "release_test"
    assert use_case._calendar_reader is calendar_reader
    assert use_case._clock is clock


def test_composition_rejects_an_invalid_alias_without_provider_defaults() -> None:
    with pytest.raises(ValueError, match="using"):
        build_release_due_simulated_settlements_use_case(
            using=" ",
            calendar_reader=_CalendarReader(),
            clock=_Clock(),
        )


def test_fee_policy_composition_retains_explicit_alias_without_database_access() -> None:
    """An operator-selected alias reaches the policy repository unchanged."""

    use_case = build_create_fee_policy_version_use_case(using="fee_operator_test")

    assert type(use_case) is CreateFeePolicyVersionUseCase
    assert type(use_case._repository) is DjangoFeePolicyV2Repository
    assert use_case._repository._using == "fee_operator_test"


@pytest.mark.parametrize("alias", ["", " ", "default "])
def test_fee_policy_composition_rejects_invalid_alias_without_a_default(alias: str) -> None:
    """A missing or noncanonical alias cannot fall back to the default database."""

    with pytest.raises(FeePolicyVersionStorageUnavailable, match="database alias"):
        build_create_fee_policy_version_use_case(using=alias)


def _published_calendar_fixture() -> object:
    """Build a fully sealed one-day current-publication value from existing pure fixtures."""

    from apps.data_center.application.formal_exchange_calendar_publication import (
        CurrentPublishedExchangeCalendar,
    )
    from tests.unit.data_center.test_formal_exchange_calendar_publication import (
        NOW,
        _pointer,
        _record,
    )

    record = _record()
    return CurrentPublishedExchangeCalendar(record=record, pointer=_pointer(record), as_of=NOW)


def _install_calendar_adapter_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: object | None,
    runtime_value: object | None,
    owner_error: Exception | None = None,
) -> tuple[list[object], list[tuple[str, str, datetime | None]]]:
    """Replace only the two public owner reads and record their exact requests."""

    import apps.config_center.application.runtime_public as runtime_public
    import apps.data_center.calendar_publication_operations_composition as calendar_composition
    import apps.simulated_trading.execution_settlement_composition as composition

    current_queries: list[object] = []
    runtime_queries: list[tuple[str, str, datetime | None]] = []

    def read_current(query: object) -> object:
        current_queries.append(query)
        if owner_error is not None:
            raise owner_error
        if current is None:
            raise AssertionError("test source must be explicit")
        return current

    def get_runtime_value(
        *,
        environment: str,
        definition_key: str,
        as_of: datetime | None = None,
    ) -> object | None:
        runtime_queries.append((environment, definition_key, as_of))
        return runtime_value

    monkeypatch.setattr(
        calendar_composition,
        "read_current_exchange_calendar_at",
        read_current,
        raising=False,
    )
    monkeypatch.setattr(
        composition,
        "read_current_exchange_calendar_at",
        read_current,
        raising=False,
    )
    monkeypatch.setattr(runtime_public, "get_active_runtime_value", get_runtime_value)
    monkeypatch.setattr(
        composition,
        "get_active_runtime_value",
        get_runtime_value,
        raising=False,
    )
    monkeypatch.setattr(composition, "runtime_public", runtime_public, raising=False)
    return current_queries, runtime_queries


def _calendar_adapter_factory() -> Callable[..., object]:
    """Resolve the new factory dynamically so the pre-feature tree still collects."""

    import apps.simulated_trading.execution_settlement_composition as composition

    factory = getattr(composition, "build_current_published_execution_calendar_reader", None)
    assert callable(factory), "published-calendar adapter factory is not implemented"
    return cast(Callable[..., object], factory)


def test_published_calendar_adapter_maps_exact_current_source_and_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit factory preserves every source seal and both read scopes."""

    from inspect import Parameter, signature

    from apps.data_center.application.formal_exchange_calendar_publication import (
        CurrentPublishedExchangeCalendar,
        ReadCurrentExchangeCalendarPublicationQuery,
    )
    from apps.simulated_trading.domain.execution_settlement_calendar import (
        CalendarPublicationReference,
        ExecutionCalendarEvidence,
    )
    from tests.unit.data_center.test_formal_exchange_calendar_publication import (
        DATASET,
        NOW,
    )

    current = cast(CurrentPublishedExchangeCalendar, _published_calendar_fixture())
    source_queries, runtime_queries = _install_calendar_adapter_fakes(
        monkeypatch,
        current=current,
        runtime_value={"SSE": "Etc/UTC"},
    )
    factory = cast(Callable[..., object], _calendar_adapter_factory())
    parameters = signature(factory).parameters
    assert tuple(parameters) == ("dataset_key", "runtime_environment")
    assert all(parameter.kind is Parameter.KEYWORD_ONLY for parameter in parameters.values())
    assert all(parameter.default is Parameter.empty for parameter in parameters.values())

    reader = cast(
        PublishedExecutionCalendarReader,
        factory(dataset_key=DATASET.value, runtime_environment="calendar-test"),
    )
    assert source_queries == []
    assert runtime_queries == []

    evidence = reader.get_effective_execution_calendar(
        exchange="SSE",
        as_of=NOW,
        coverage_start=None,
    )
    assert type(evidence) is ExecutionCalendarEvidence
    assert len(source_queries) == 1
    query = cast(ReadCurrentExchangeCalendarPublicationQuery, source_queries[0])
    assert type(query) is ReadCurrentExchangeCalendarPublicationQuery
    assert query.dataset_key == DATASET.value
    assert query.exchange == "SSE"
    assert query.as_of is NOW
    assert runtime_queries == [("calendar-test", "config_center.market.exchange_timezone_map", NOW)]

    source = current.record.seal.snapshot
    source_raw = source.candidate.raw_reference
    snapshot = evidence.snapshot
    assert snapshot.snapshot_id == source.snapshot_id
    assert snapshot.exchange == source.exchange
    assert snapshot.coverage_start == source.coverage_start
    assert snapshot.coverage_end == source.coverage_end
    assert snapshot.provider_name == source.provider_name
    assert snapshot.raw_reference.to_payload() == source_raw.to_payload()
    assert snapshot.content_hash == source.content_hash
    assert snapshot.record_digest == source.record_digest
    assert snapshot.first_seen_at == source.first_seen_at
    assert snapshot.recorded_at == source.recorded_at
    assert snapshot.source_published_at is None
    assert tuple(day.to_payload() for day in snapshot.days) == tuple(
        day.to_payload() for day in source.candidate.days
    )

    publication = evidence.publication
    assert type(publication) is CalendarPublicationReference
    source_member = current.record.seal.member_reference.member
    assert publication.publication_id == current.record.publication_id
    assert publication.member_id == source.snapshot_id
    assert publication.member_id != source_member.member_id
    assert publication.publication_hash == current.record.seal.publication_hash
    assert publication.fact_content_hash == source_member.fact_content_hash
    assert publication.policy_hash == current.record.seal.policy.content_hash
    assert publication.published_at == current.record.published_at
    assert publication.recorded_at == current.pointer.updated_at
    assert publication.recorded_at == publication.published_at
    assert publication.reference_valid_from == current.record.window.valid_from
    assert publication.reference_valid_until == current.record.window.valid_until
    assert publication.timezone_name == "Etc/UTC"


def test_published_calendar_adapter_returns_none_only_for_exact_missing_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed exact-current absence remains absence; other owner errors do not."""

    from apps.data_center.application.formal_exchange_calendar_publication import (
        CalendarFormalPublicationApplicationError,
    )
    from tests.unit.data_center.test_formal_exchange_calendar_publication import (
        DATASET,
        NOW,
    )

    missing = CalendarFormalPublicationApplicationError(
        "no exact current publication", code="CALENDAR_CURRENT_PUBLICATION_MISSING"
    )
    source_queries, _runtime_queries = _install_calendar_adapter_fakes(
        monkeypatch,
        current=_published_calendar_fixture(),
        runtime_value={"SSE": "Etc/UTC"},
        owner_error=missing,
    )
    factory = cast(Callable[..., object], _calendar_adapter_factory())
    reader = cast(
        PublishedExecutionCalendarReader,
        factory(dataset_key=DATASET.value, runtime_environment="calendar-test"),
    )

    result = reader.get_effective_execution_calendar(
        exchange="SSE",
        as_of=NOW,
        coverage_start=None,
    )
    assert result is None
    assert len(source_queries) == 1


def test_published_calendar_adapter_wraps_nonabsence_owner_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scope, seal, and result corruption remain typed blocks with their owner cause."""

    from apps.data_center.application.formal_exchange_calendar_publication import (
        CalendarFormalPublicationApplicationError,
    )
    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionBlocked,
    )
    from tests.unit.data_center.test_formal_exchange_calendar_publication import (
        DATASET,
        NOW,
    )

    owner_error = CalendarFormalPublicationApplicationError(
        "sealed current calendar is corrupt",
        code="CALENDAR_FORMAL_PUBLICATION_HASH_MISMATCH",
    )
    _install_calendar_adapter_fakes(
        monkeypatch,
        current=_published_calendar_fixture(),
        runtime_value={"SSE": "Etc/UTC"},
        owner_error=owner_error,
    )
    factory = cast(Callable[..., object], _calendar_adapter_factory())
    reader = cast(
        PublishedExecutionCalendarReader,
        factory(dataset_key=DATASET.value, runtime_environment="calendar-test"),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as captured:
        reader.get_effective_execution_calendar(
            exchange="SSE",
            as_of=NOW,
            coverage_start=None,
        )
    assert captured.value.__cause__ is owner_error


@pytest.mark.parametrize(
    ("runtime_value", "expected_error"),
    [
        (None, "ExecutionCalendarUnavailable"),
        ({"SH": "Etc/UTC"}, "ExecutionCalendarUnavailable"),
        ({"SSE": 7}, "SimulatedTradeExecutionBlocked"),
        ({"SSE": "No/Such_Zone"}, "SimulatedTradeExecutionBlocked"),
        ({"SSE": "Etc/UTC", 1: "Etc/UTC"}, "SimulatedTradeExecutionBlocked"),
        (["malformed"], "SimulatedTradeExecutionBlocked"),
    ],
)
def test_published_calendar_adapter_fails_closed_on_timezone_configuration(
    monkeypatch: pytest.MonkeyPatch,
    runtime_value: object | None,
    expected_error: str,
) -> None:
    """Missing scope and malformed timezone values never create a permissive fallback."""

    from apps.simulated_trading.application.execution_settlement_uow import (
        ExecutionCalendarUnavailable,
        SimulatedTradeExecutionBlocked,
    )
    from tests.unit.data_center.test_formal_exchange_calendar_publication import (
        DATASET,
        NOW,
    )

    error_types = {
        "ExecutionCalendarUnavailable": ExecutionCalendarUnavailable,
        "SimulatedTradeExecutionBlocked": SimulatedTradeExecutionBlocked,
    }
    _install_calendar_adapter_fakes(
        monkeypatch,
        current=_published_calendar_fixture(),
        runtime_value=runtime_value,
    )
    factory = cast(Callable[..., object], _calendar_adapter_factory())
    reader = cast(
        PublishedExecutionCalendarReader,
        factory(dataset_key=DATASET.value, runtime_environment="calendar-test"),
    )

    with pytest.raises(error_types[expected_error]):
        reader.get_effective_execution_calendar(
            exchange="SSE",
            as_of=NOW,
            coverage_start=None,
        )


def test_published_calendar_adapter_rejects_source_scope_cutoff_and_range_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter validates the owner's exact scope and complete date coverage."""
    from datetime import timedelta

    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionBlocked,
    )
    from tests.unit.data_center.test_formal_exchange_calendar_publication import (
        DATASET,
        NOW,
    )

    source = _published_calendar_fixture()
    _install_calendar_adapter_fakes(
        monkeypatch,
        current=source,
        runtime_value={"SSE": "Etc/UTC", "SH": "Etc/UTC"},
    )
    factory = cast(Callable[..., object], _calendar_adapter_factory())
    reader = cast(
        PublishedExecutionCalendarReader,
        factory(dataset_key=DATASET.value, runtime_environment="calendar-test"),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        reader.get_effective_execution_calendar(
            exchange="SH",
            as_of=NOW,
            coverage_start=None,
        )
    with pytest.raises(SimulatedTradeExecutionBlocked):
        reader.get_effective_execution_calendar(
            exchange="SSE",
            as_of=NOW + timedelta(seconds=1),
            coverage_start=None,
        )
    with pytest.raises(SimulatedTradeExecutionBlocked):
        reader.get_effective_execution_calendar(
            exchange="SSE",
            as_of=NOW,
            coverage_start=date(2026, 10, 17),
        )
