"""Native preparation locks and the actual calendar operation-use-case journey."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from typing import cast
from uuid import uuid4

import pytest
from django.db import DEFAULT_DB_ALIAS, close_old_connections, connections, transaction
from django.utils import timezone

from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CalendarPublicationPreparationContext,
    ConfirmCalendarPublicationIntent,
    ConfirmCalendarPublicationUseCase,
    PreviewCalendarPublicationIntent,
    PreviewCalendarPublicationUseCase,
    ReadCurrentCalendarIntent,
    ReadCurrentCalendarUseCase,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
    CalendarPublicationTransition,
    PublishExchangeCalendarSnapshotUseCase,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotReference,
)
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
)
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
    DjangoFormalExchangeCalendarPublicationRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from core.exceptions import AuthorizationError, DataFetchError
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _actual_publisher,
    _backend_pid,
    _postgres_publication_schema,
    _real_audit_bridge,
    _set_worker_timeouts,
    _wait_for_exact_blocker,
)
from tests.component.data_center.test_formal_exchange_calendar_publication_repository import (
    _DATASET,
    _ready,
)

__all__ = ["_postgres_publication_schema"]
pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "apps.data_center",
        "apps.audit",
    ],
)


class _ServerClock:
    """Use actual server UTC time for the application operations under test."""

    def now(self) -> datetime:
        """Return one aware UTC instant."""

        return timezone.now().astimezone(UTC)


class _ActivationIds:
    """Mint technical activation IDs without a database or business defaults."""

    def new_id(self) -> str:
        """Return a fresh bounded identity for a proposed new publication."""

        return uuid4().hex


def _repository() -> DjangoFormalExchangeCalendarPublicationRepository:
    """Use the actual same-alias Core/Audit adapter rather than receipt fakes."""

    return DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=_real_audit_bridge(), using=DEFAULT_DB_ALIAS
    )


def _operations(
    repository: DjangoFormalExchangeCalendarPublicationRepository,
) -> tuple[
    PreviewCalendarPublicationUseCase,
    ConfirmCalendarPublicationUseCase,
    ReadCurrentCalendarUseCase,
]:
    """Compose the new App ports with real preparation, publication and read paths."""

    clock = _ServerClock()
    return (
        PreviewCalendarPublicationUseCase(
            preparation=repository, clock=clock, activation_ids=_ActivationIds()
        ),
        ConfirmCalendarPublicationUseCase(
            preparation=repository,
            publisher=PublishExchangeCalendarSnapshotUseCase(repository),
            clock=clock,
        ),
        ReadCurrentCalendarUseCase(reader=repository, clock=clock),
    )


def _guarded_confirm(
    use_case: ConfirmCalendarPublicationUseCase,
    intent: ConfirmCalendarPublicationIntent,
    proof: CalendarPublisherSessionRequestProof,
) -> CalendarFormalPublicationCommit:
    """Return only after the actual Session/grant-owning transaction exits."""

    authority = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    with authority.locked_calendar_publisher(proof) as principal:
        result = use_case.execute(intent, principal=principal)
    return result


def _formal_row_counts() -> dict[str, int]:
    """Name every formal table count so ordering cannot hide an invalid assertion."""

    return {
        "publications": CanonicalPublicationModel._default_manager.count(),
        "pointers": CanonicalPublicationPointerModel._default_manager.count(),
        "members": PublicationMemberModel._default_manager.count(),
        "coverage": CoverageSnapshotModel._default_manager.count(),
        "events": SystemAuditEventModel._default_manager.count(),
        "outbox": SystemAuditOutboxModel._default_manager.count(),
    }


def test_native_preview_confirm_original_retry_and_reference_after_revocation() -> None:
    """An unchanged original confirmation retries the exact current committed winner."""

    snapshot_value, _audit, _clock, _principal, _request = _ready()
    snapshot = cast(ExchangeCalendarSnapshot, snapshot_value)
    user, proof = _actual_publisher("native-calendar-operations-publisher")
    repository = _repository()
    preview, confirm, read = _operations(repository)
    before = _formal_row_counts()
    authority = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    with authority.locked_calendar_publisher(proof) as principal:
        proposed = preview.execute(
            PreviewCalendarPublicationIntent(snapshot.reference()), principal=principal
        )
    assert _formal_row_counts() == before

    original_intent = proposed.confirmation_intent()
    first = _guarded_confirm(confirm, original_intent, proof)
    assert first.transition is CalendarPublicationTransition.FIRST_PUBLISH
    assert all(value == 1 for value in _formal_row_counts().values())
    retry = _guarded_confirm(confirm, original_intent, proof)
    assert retry.transition is CalendarPublicationTransition.EXACT_CURRENT_REPLAY
    assert retry.record == first.record
    assert retry.pointer == first.pointer
    assert retry.audit_pair == first.audit_pair
    assert all(value == 1 for value in _formal_row_counts().values())

    user.user_permissions.clear()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        current = read.execute(ReadCurrentCalendarIntent(_DATASET.value, "SSE"))
    assert current is not None
    assert current.record == first.record
    assert current.must_not_execute is True
    with pytest.raises(AuthorizationError):
        _guarded_confirm(confirm, original_intent, proof)
    assert all(value == 1 for value in _formal_row_counts().values())


def test_native_catalog_ttl_change_invalidates_an_existing_preview_before_writes() -> None:
    """Matching catalog version strings cannot hide a changed TTL from confirmation."""

    snapshot_value, _audit, _clock, _principal, _request = _ready()
    snapshot = cast(ExchangeCalendarSnapshot, snapshot_value)
    _user, proof = _actual_publisher("native-calendar-stale-preview")
    preview, confirm, _read = _operations(_repository())
    authority = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    with authority.locked_calendar_publisher(proof) as principal:
        proposed = preview.execute(
            PreviewCalendarPublicationIntent(snapshot.reference()), principal=principal
        )
    updated = DatasetContractModel._default_manager.filter(dataset_key=_DATASET.value).update(
        calendar_response_max_age_seconds=7200,
        updated_at=timezone.now(),
    )
    assert updated == 1
    before = _formal_row_counts()
    with pytest.raises(CalendarPublicationOperationsError) as failure:
        _guarded_confirm(confirm, proposed.confirmation_intent(), proof)
    assert failure.value.code == "CALENDAR_PUBLICATION_PREVIEW_STALE"
    assert _formal_row_counts() == before


def _prepare_in_worker(
    reference: ExchangeCalendarSnapshotReference,
    *,
    start: Barrier,
    pids: dict[str, int],
) -> CalendarPublicationPreparationContext | tuple[str, str] | None:
    """Run actual trusted preparation through one independent PostgreSQL backend."""

    close_old_connections()
    try:
        _set_worker_timeouts()
        pids["preparation"] = _backend_pid()
        start.wait(timeout=10)
        try:
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                return _repository().load_exact(reference, known_at=timezone.now().astimezone(UTC))
        except DataFetchError as error:
            return "blocked", error.code
    finally:
        connections[DEFAULT_DB_ALIAS].close()


def test_native_preparation_does_not_wait_on_an_earlier_catalog_row_lock() -> None:
    """An ordinary catalog SELECT after SHARE avoids a row-lock upgrade cycle."""

    snapshot_value, _audit, _clock, _principal, _request = _ready()
    snapshot = cast(ExchangeCalendarSnapshot, snapshot_value)
    start = Barrier(2, timeout=10)
    completed = Event()
    pids: dict[str, int] = {}

    def prepare() -> CalendarPublicationPreparationContext | tuple[str, str] | None:
        try:
            return _prepare_in_worker(snapshot.reference(), start=start, pids=pids)
        finally:
            completed.set()

    before = _formal_row_counts()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            contract = DatasetContractModel._default_manager.select_for_update().get(
                dataset_key=_DATASET.value
            )
            future = pool.submit(prepare)
            start.wait(timeout=10)
            completed_while_row_held = completed.wait(timeout=5)
            contract.owner = "writer-after-calendar-preparation"
            contract.save(using=DEFAULT_DB_ALIAS, update_fields=("owner",))
        result = future.result(timeout=15)
    assert completed_while_row_held, "preparation waited for an unnecessary catalog row lock"
    assert type(result) is CalendarPublicationPreparationContext
    assert result.snapshot.reference() == snapshot.reference()
    assert _formal_row_counts() == before


def test_native_preparation_waits_for_catalog_dml_and_reads_committed_inactivation() -> None:
    """Observe the exact native blocker, then reject its committed active change."""

    snapshot_value, _audit, _clock, _principal, _request = _ready()
    snapshot = cast(ExchangeCalendarSnapshot, snapshot_value)
    start = Barrier(2, timeout=10)
    pids: dict[str, int] = {}
    before = _formal_row_counts()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            contract = DatasetContractModel._default_manager.get(dataset_key=_DATASET.value)
            contract.active = False
            contract.save(using=DEFAULT_DB_ALIAS, update_fields=("active",))
            blocker_pid = _backend_pid()
            future = pool.submit(_prepare_in_worker, snapshot.reference(), start=start, pids=pids)
            start.wait(timeout=10)
            assert (
                _wait_for_exact_blocker((pids["preparation"],), blocker_pid) == pids["preparation"]
            )
        result = future.result(timeout=15)
    assert result == ("blocked", "CALENDAR_FORMAL_CONTRACT_MISSING")
    assert _formal_row_counts() == before
