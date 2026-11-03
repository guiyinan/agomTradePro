"""Focused persistence contracts for the isolated calendar catalog UOW."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event, get_ident

import pytest
from django.db import close_old_connections, connection, connections, models

from apps.data_center.application.calendar_catalog_bootstrap import (
    CalendarCatalogBootstrapError,
    CalendarCatalogBootstrapResult,
    CalendarCatalogBootstrapRows,
    CreateCalendarCatalogBootstrapUseCase,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
)
from apps.data_center.infrastructure.calendar_catalog_bootstrap_repository import (
    DjangoCalendarCatalogBootstrapRepository,
    _ExistingCalendarCatalogRows,
)
from apps.data_center.infrastructure.catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DatasetContractRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
)
from tests.support.isolated_schema import isolated_schema

_DATASET_KEY = "data_center.exchange_calendar_snapshot"
_MODELS: tuple[type[models.Model], ...] = (
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
    DataOwnerRegistrationModel,
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
)

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


@pytest.fixture(autouse=True)
def _catalog_schema() -> Iterator[None]:
    """Use only Data Center catalog tables; transactional DB cleanup owns rows."""

    with isolated_schema(_MODELS, clear_existing_rows=False):
        yield


def _candidate() -> CalendarCatalogBootstrapRows:
    """Build Root's explicit isolated calendar candidate without source claims."""

    key = DatasetKey(_DATASET_KEY, "1.0", "exchange-calendar-snapshot-v1")
    contract = DatasetContract(
        key=key,
        owner="data-platform",
        frequency="calendar",
        decision_critical=True,
        fields=(
            DatasetFieldContract("exchange", "string", None, False, False),
            DatasetFieldContract("calendar_date", "date", None, False, False),
            DatasetFieldContract("is_open", "boolean", None, False, False),
            DatasetFieldContract("previous_open_date", "date", None, False, False),
        ),
        calendar_response_max_age_seconds=900,
    )
    binding = ProviderBinding(
        dataset=key,
        provider="tushare",
        capability="exchange_calendar",
        priority=10,
        freshness_seconds=None,
        validator_key="exchange_calendar.tushare.trade_cal.full_date.v1",
        enabled=True,
    )
    policy = PublicationPolicy(
        dataset=key,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fact_content_hash"),
        retention_days=3650,
        policy_version="calendar-reference-v1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    owner = DataOwnerRegistration(
        dataset_key=_DATASET_KEY,
        data_platform_owner="data-platform",
        business_owner="simulated_trading",
        acceptance_owner="data-platform",
        active=True,
    )
    return CalendarCatalogBootstrapRows(contract, binding, policy, owner)


def _use_case() -> CreateCalendarCatalogBootstrapUseCase:
    """Build the real use case against the default transactional test DB."""

    return CreateCalendarCatalogBootstrapUseCase(DjangoCalendarCatalogBootstrapRepository())


def _target_rows() -> dict[str, list[dict[str, object]]]:
    """Snapshot all target-key rows including creation and modification clocks."""

    return {
        "contracts": list(
            DatasetContractModel._default_manager.filter(dataset_key=_DATASET_KEY)
            .order_by("pk")
            .values()
        ),
        "bindings": list(
            DatasetProviderBindingModel._default_manager.filter(dataset_key=_DATASET_KEY)
            .order_by("pk")
            .values()
        ),
        "policies": list(
            DatasetPublicationPolicyModel._default_manager.filter(dataset_key=_DATASET_KEY)
            .order_by("pk")
            .values()
        ),
        "owners": list(
            DataOwnerRegistrationModel._default_manager.filter(dataset_key=_DATASET_KEY)
            .order_by("pk")
            .values()
        ),
    }


def _unrelated_rows() -> dict[str, list[dict[str, object]]]:
    """Snapshot unrelated catalog and current-publication metadata exactly."""

    key = "fixture.unrelated.calendar.catalog"
    return {
        "contracts": list(
            DatasetContractModel._default_manager.filter(dataset_key=key).order_by("pk").values()
        ),
        "bindings": list(
            DatasetProviderBindingModel._default_manager.filter(dataset_key=key)
            .order_by("pk")
            .values()
        ),
        "policies": list(
            DatasetPublicationPolicyModel._default_manager.filter(dataset_key=key)
            .order_by("pk")
            .values()
        ),
        "owners": list(
            DataOwnerRegistrationModel._default_manager.filter(dataset_key=key)
            .order_by("pk")
            .values()
        ),
        "publications": list(
            CanonicalPublicationModel._default_manager.filter(dataset_key=key)
            .order_by("pk")
            .values()
        ),
        "current_pointer": list(
            CanonicalPublicationPointerModel._default_manager.filter(dataset_key=key)
            .order_by("pk")
            .values()
        ),
    }


def _seed_unrelated_catalog() -> None:
    """Create one unrelated active dataset row in each existing catalog table."""

    key = "fixture.unrelated.calendar.catalog"
    DatasetContractModel._default_manager.create(
        dataset_key=key,
        contract_version="9",
        schema_version="1",
        owner="fixture",
        frequency="fixture",
        decision_critical=False,
        fields=[{"name": "value", "type": "string", "unit": None}],
        active=True,
    )
    DatasetProviderBindingModel._default_manager.create(
        dataset_key=key,
        contract_version="9",
        schema_version="1",
        provider="fixture-provider",
        capability="fixture",
        priority=1,
        validator_key="fixture.validator",
        enabled=True,
    )
    DatasetPublicationPolicyModel._default_manager.create(
        dataset_key=key,
        contract_version="9",
        schema_version="1",
        policy_version="fixture-policy",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source"],
        retention_days=1,
        active=True,
    )
    DataOwnerRegistrationModel._default_manager.create(
        dataset_key=key,
        data_platform_owner="fixture-platform",
        business_owner="fixture-business",
        acceptance_owner="fixture-acceptance",
        active=True,
    )
    publication = CanonicalPublicationModel._default_manager.create(
        dataset_key=key,
        publication_key="fixture-current",
        policy_version="fixture-policy",
        state="published",
        selected_source="fixture-source",
        publication_hash="fixture-hash",
        member_count=1,
        published_at=datetime.now(UTC),
    )
    CanonicalPublicationPointerModel._default_manager.create(
        dataset_key=key,
        publication_key="fixture-current",
        publication_id=publication.publication_id,
        publication_hash=publication.publication_hash,
        activation_id="fixture-activation",
    )


def test_preview_is_read_only_and_does_not_create_any_target_row() -> None:
    """The default preview identifies readiness but does not write catalog rows."""

    result = _use_case().preview(_candidate())

    assert result.outcome == "ready"
    assert result.reason_code == "CALENDAR_CATALOG_KEY_ABSENT"
    assert _target_rows() == {"contracts": [], "bindings": [], "policies": [], "owners": []}


def test_create_only_changes_target_key_and_preserves_current_publication_metadata() -> None:
    """One UOW writes four target rows without synchronizing unrelated records."""

    _seed_unrelated_catalog()
    unrelated_before = _unrelated_rows()

    result = _use_case().execute(_candidate())

    assert result.outcome == "created"
    assert result.reason_code == "CALENDAR_CATALOG_CREATED"
    assert all(len(rows) == 1 for rows in _target_rows().values())
    assert _unrelated_rows() == unrelated_before


def test_exact_replay_does_not_touch_any_record_clock_or_active_flag() -> None:
    """A complete exact replay returns without calling a save or changing clocks."""

    created = _use_case().execute(_candidate())
    before = _target_rows()

    replayed = _use_case().execute(_candidate())

    assert created.outcome == "created"
    assert replayed.outcome == "already_configured"
    assert replayed.reason_code == "CALENDAR_CATALOG_EXACT_REPLAY"
    assert _target_rows() == before


def test_partial_history_blocks_without_overwriting_existing_content() -> None:
    """Any existing partial key history blocks creation and remains unchanged."""

    contract = _candidate().contract
    DatasetContractModel._default_manager.create(
        dataset_key=contract.key.value,
        contract_version=contract.key.contract_version,
        schema_version=contract.key.schema_version,
        owner=contract.owner,
        frequency=contract.frequency,
        decision_critical=contract.decision_critical,
        fields=[
            {
                "name": field.name,
                "type": field.value_type,
                "unit": field.unit,
                "nullable": field.nullable,
                "zero_allowed": field.zero_allowed,
                "minimum": field.minimum,
                "maximum": field.maximum,
            }
            for field in contract.fields
        ],
        calendar_response_max_age_seconds=contract.calendar_response_max_age_seconds,
        active=True,
    )
    before = _target_rows()

    with pytest.raises(CalendarCatalogBootstrapError) as raised:
        _use_case().execute(_candidate())

    assert raised.value.reason_code == "CALENDAR_CATALOG_HISTORY_CONFLICT"
    assert raised.value.code == "CALENDAR_CATALOG_HISTORY_CONFLICT"
    assert raised.value.to_dict() == {
        "error": "target calendar catalog history is partial, changed, or ambiguous",
        "code": "CALENDAR_CATALOG_HISTORY_CONFLICT",
    }
    assert _target_rows() == before


def test_changed_complete_history_blocks_without_rewriting_any_clock() -> None:
    """A drifted row is not repaired or reactivated by the create-only UOW."""

    _use_case().execute(_candidate())
    DatasetProviderBindingModel._default_manager.filter(dataset_key=_DATASET_KEY).update(
        priority=11
    )
    before = _target_rows()

    with pytest.raises(CalendarCatalogBootstrapError) as raised:
        _use_case().execute(_candidate())

    assert raised.value.reason_code == "CALENDAR_CATALOG_HISTORY_CONFLICT"
    assert _target_rows() == before


def test_failure_after_all_inserts_rolls_back_the_complete_four_row_bundle() -> None:
    """An exception after repository inserts leaves no partial catalog bundle."""

    class FailingRepository(DjangoCalendarCatalogBootstrapRepository):
        """Inject failure after real insert logic, inside the UOW transaction."""

        def _create_rows(self, rows: CalendarCatalogBootstrapRows) -> bool:
            super()._create_rows(rows)
            raise RuntimeError("injected failure after candidate inserts")

    use_case = CreateCalendarCatalogBootstrapUseCase(FailingRepository())

    with pytest.raises(RuntimeError, match="injected failure"):
        use_case.execute(_candidate())

    assert _target_rows() == {"contracts": [], "bindings": [], "policies": [], "owners": []}


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires native PostgreSQL races")
def test_preview_retries_a_mixed_four_query_view_after_concurrent_full_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit between table reads resolves to its complete exact state on reread."""

    entered_binding_read = Event()
    allow_binding_read = Event()
    preview_thread_id: list[int] = []
    paused_threads: set[int] = set()
    original_read_bindings = DjangoCalendarCatalogBootstrapRepository._read_bindings

    def pause_preview_between_table_reads(
        repository: DjangoCalendarCatalogBootstrapRepository, dataset_key: str
    ) -> tuple[DatasetProviderBindingModel, ...]:
        current_id = get_ident()
        if (
            preview_thread_id
            and current_id == preview_thread_id[0]
            and current_id not in paused_threads
        ):
            paused_threads.add(current_id)
            entered_binding_read.set()
            assert allow_binding_read.wait(timeout=10)
        return original_read_bindings(repository, dataset_key)

    monkeypatch.setattr(
        DjangoCalendarCatalogBootstrapRepository,
        "_read_bindings",
        pause_preview_between_table_reads,
    )

    def preview() -> CalendarCatalogBootstrapResult:
        close_old_connections()
        preview_thread_id.append(get_ident())
        try:
            return _use_case().preview(_candidate())
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(preview)
        assert entered_binding_read.wait(timeout=10)
        created = _use_case().execute(_candidate())
        allow_binding_read.set()
        previewed = future.result(timeout=20)

    assert created.outcome == "created"
    assert previewed.outcome == "already_configured"


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires native PostgreSQL races")
def test_mixed_created_flags_conflict_and_rollback_around_non_atomic_catalog_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A competing single-row writer is not completed by this create-only UOW."""

    uow_ready = Event()
    external_row_committed = Event()

    class InterleavedRepository(DjangoCalendarCatalogBootstrapRepository):
        """Pause after the empty-state check while a separate writer adds one row."""

        def _create_rows(self, rows: CalendarCatalogBootstrapRows) -> bool:
            uow_ready.set()
            assert external_row_committed.wait(timeout=10)
            return super()._create_rows(rows)

    repository = InterleavedRepository()

    def execute() -> CalendarCatalogBootstrapResult:
        close_old_connections()
        try:
            return CreateCalendarCatalogBootstrapUseCase(repository).execute(_candidate())
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(execute)
        assert uow_ready.wait(timeout=10)
        DatasetContractRepository().save(_candidate().contract)
        external_row_committed.set()
        with pytest.raises(CalendarCatalogBootstrapError) as raised:
            future.result(timeout=20)

    assert raised.value.reason_code == "CALENDAR_CATALOG_HISTORY_CONFLICT"
    state = _target_rows()
    assert len(state["contracts"]) == 1
    assert state["bindings"] == []
    assert state["policies"] == []
    assert state["owners"] == []


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires native PostgreSQL races")
def test_concurrent_exact_first_creation_returns_one_create_and_one_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Competing identical UOWs converge on one immutable four-row bundle."""

    rendezvous = Barrier(2, timeout=10)
    original_read_state = DjangoCalendarCatalogBootstrapRepository._read_state

    def read_with_shared_empty_observation(
        repository: DjangoCalendarCatalogBootstrapRepository, dataset_key: str
    ) -> _ExistingCalendarCatalogRows:
        state = original_read_state(repository, dataset_key)
        if state.is_empty:
            rendezvous.wait(timeout=10)
        return state

    monkeypatch.setattr(
        DjangoCalendarCatalogBootstrapRepository,
        "_read_state",
        read_with_shared_empty_observation,
    )

    def execute() -> str:
        close_old_connections()
        try:
            return _use_case().execute(_candidate()).outcome
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(execute) for _ in range(2)]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sorted(outcomes) == ["already_configured", "created"]
    assert all(len(rows) == 1 for rows in _target_rows().values())
