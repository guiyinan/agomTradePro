from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import django
import pytest
from django.db import transaction

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")
django.setup()

from apps.audit.application.data_publication_audit import DataPublicationAuditObservation
from apps.audit.application.system_audit_event_outbox import (
    AppendSystemAuditEventOutboxCommand,
    AppendSystemAuditEventOutboxUseCase,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef
from apps.audit.infrastructure import system_audit_outbox_runtime
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from apps.data_center.application.publication_activation import PublicationActivationRequest
from apps.data_center.domain.control_plane import CanonicalPublication
from tests.support.isolated_schema import isolated_schema
from tests.unit.audit.test_system_audit_event import make_event

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 8, 14, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object):
    """Create the two schema-only tables for this isolated component."""

    blocker = django_db_blocker
    with blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((SystemAuditEventModel, SystemAuditOutboxModel)):
            yield


def test_event_and_outbox_commit_as_one_exact_pair() -> None:
    event = make_event()
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    result = AppendSystemAuditEventOutboxUseCase(coordinator).execute(
        AppendSystemAuditEventOutboxCommand(
            event=event,
            expected_predecessor_hash=None,
            recorded_at=event.recorded_at,
        )
    )

    assert result.event == event
    assert result.outbox_id is not None
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1
    outbox = SystemAuditOutboxModel._default_manager.get()
    assert outbox.event_id == event.event_id
    assert outbox.payload_hash == event.content_hash
    assert outbox.created_at == event.recorded_at


def test_exact_retry_replays_without_duplicate_rows() -> None:
    event = make_event()
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    command = AppendSystemAuditEventOutboxCommand(
        event=event,
        expected_predecessor_hash=None,
        recorded_at=event.recorded_at,
    )

    first = AppendSystemAuditEventOutboxUseCase(coordinator).execute(command)
    second = AppendSystemAuditEventOutboxUseCase(coordinator).execute(command)

    assert second == first
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1


def test_outbox_failure_rolls_back_event_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()

    def fail_enqueue(
        _repository: DjangoSystemAuditOutboxRepository,
        _event: object,
        *,
        available_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> object:
        del available_at, created_at
        raise RuntimeError("simulated outbox failure")

    monkeypatch.setattr(DjangoSystemAuditOutboxRepository, "enqueue", fail_enqueue)
    with pytest.raises(SystemAuditEventOutboxUnavailable):
        AppendSystemAuditEventOutboxUseCase(DjangoSystemAuditEventOutboxCoordinator()).execute(
            AppendSystemAuditEventOutboxCommand(
                event=event,
                expected_predecessor_hash=None,
                recorded_at=event.recorded_at,
            )
        )

    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0


def _activation_observation() -> DataPublicationAuditObservation:
    """Build one complete, caller-scoped publication audit observation."""

    return DataPublicationAuditObservation(
        dataset_key="equity.quote.snapshot",
        publication_key="current",
        publication_id="publication-activation-test",
        publication_version="1",
        publication_hash="a" * 64,
        provider_key="quote-provider",
        run_id="run-activation-test",
        ingested_run_id="ingested-run-activation-test",
        member_count=1,
        coverage_requested_count=1,
        coverage_eligible_count=1,
        coverage_selected_count=1,
        outcome=AuditOutcome.PUBLISHED,
        raw_audit_id="1",
        raw_audit_version="1",
        raw_audit_content_hash="b" * 64,
        occurred_at=NOW,
        recorded_at=NOW,
        scope=AuditScopeRef(tenant_id="tenant:test", owner_id="owner:test"),
    )


def _build_activation_writer(monkeypatch: pytest.MonkeyPatch):
    """Use the real writer factory with a real, alias-bound coordinator."""

    coordinator = DjangoSystemAuditEventOutboxCoordinator(using="default")
    monkeypatch.setattr(
        system_audit_outbox_runtime,
        "_build_system_audit_runtime_composition",
        lambda *, environment, using: SimpleNamespace(
            database_alias=using,
            event_outbox_coordinator=coordinator,
        ),
    )
    return system_audit_outbox_runtime.build_publication_activation_audit_writer(
        environment="production",
        using="default",
    )


def test_publication_activation_factory_writer_commits_event_and_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _build_activation_writer(monkeypatch)
    observation = _activation_observation()
    request = cast(PublicationActivationRequest, object())
    publication = cast(CanonicalPublication, object())

    with transaction.atomic(using="default"):
        result = writer.append_required(
            request=request,
            publication=publication,
            members=(),
            observation=observation,
        )

    assert result.outbox_id is not None
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1


def test_publication_activation_factory_writer_outbox_failure_rolls_back_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _build_activation_writer(monkeypatch)
    observation = _activation_observation()
    request = cast(PublicationActivationRequest, object())
    publication = cast(CanonicalPublication, object())

    def fail_enqueue_targeted(
        _repository: DjangoSystemAuditOutboxRepository,
        _event: object,
        *,
        available_at: datetime,
        created_at: datetime,
    ) -> object:
        del available_at, created_at
        raise RuntimeError("simulated publication outbox failure")

    monkeypatch.setattr(
        DjangoSystemAuditOutboxRepository,
        "enqueue_targeted",
        fail_enqueue_targeted,
    )

    with pytest.raises(RuntimeError, match="simulated publication outbox failure"):
        with transaction.atomic(using="default"):
            writer.append_required(
                request=request,
                publication=publication,
                members=(),
                observation=observation,
            )

    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
