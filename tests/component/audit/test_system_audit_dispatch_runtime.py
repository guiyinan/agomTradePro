"""SQLite persistence proof for the production system-audit dispatcher root."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")
django.setup()

from apps.audit.application.system_audit_authority_provider import (
    SystemAuditActorAuthorityFacts,
    SystemAuditAuthorityBundleSelector,
    SystemAuditScopeAuthorityFacts,
)
from apps.audit.application.system_audit_outbox_dispatcher import (
    DispatchSystemAuditOutboxCommand,
    SystemAuditOutboxDispatchUnavailable,
)
from apps.audit.infrastructure import system_audit_outbox_runtime as runtime
from apps.audit.infrastructure.system_audit_delivery_receipt import (
    SystemAuditDeliveryReceiptModel,
)
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from core.integration.system_audit_authority import SystemAuditAuthorityReaders
from core.integration.system_audit_runtime_config import SystemAuditRuntimeConfigBinding
from tests.support.isolated_schema import isolated_schema
from tests.unit.audit.test_system_audit_event import make_event

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 8, 14, 12, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Isolate the exact outbox and receipt tables used by this proof."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((SystemAuditOutboxModel, SystemAuditDeliveryReceiptModel)):
            yield


def _selector() -> SystemAuditAuthorityBundleSelector:
    return SystemAuditAuthorityBundleSelector(
        actor_source_id="account-actor-source",
        actor_source_version="v1",
        actor_content_hash="a" * 64,
        scope_source_id="account-scope-source",
        scope_source_version="v1",
        scope_content_hash="b" * 64,
    )


def _binding(selector: SystemAuditAuthorityBundleSelector) -> SystemAuditRuntimeConfigBinding:
    return SystemAuditRuntimeConfigBinding(
        mode="required",
        outbox_enabled=True,
        authority_selector=selector,
        issuer_id="audit-config:" + "c" * 64,
        snapshot_id="audit-runtime-snapshot",
        snapshot_hash="d" * 64,
        profile_id="audit-runtime-profile",
        profile_key="production-audit",
        profile_version=1,
        environment="production",
    )


class _ActorReader:
    database_alias = "default"

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def get_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditActorAuthorityFacts | None:
        if not self.available:
            return None
        return SystemAuditActorAuthorityFacts(
            source_id=source_id,
            source_version=source_version,
            content_hash=expected_content_hash,
            actor_id="django-user:7",
            user_id=7,
            is_authenticated=True,
            is_staff=True,
            role="audit_reader",
            authority_state="active",
            recorded_at=as_of - timedelta(minutes=1),
            valid_until=as_of + timedelta(minutes=1),
        )


class _ScopeReader:
    database_alias = "default"

    def get_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditScopeAuthorityFacts:
        return SystemAuditScopeAuthorityFacts(
            source_id=source_id,
            source_version=source_version,
            content_hash=expected_content_hash,
            actor_id="django-user:7",
            user_id=7,
            tenant_id="tenant:primary",
            owner_id="owner:research",
            authority_state="active",
            recorded_at=as_of - timedelta(minutes=1),
            valid_until=as_of + timedelta(minutes=1),
        )


def _install_inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    actor_available: bool = True,
) -> None:
    selector = _selector()
    binding = _binding(selector)
    readers = SystemAuditAuthorityReaders(
        actor=_ActorReader(available=actor_available),
        scope=_ScopeReader(),
        database_alias="default",
    )

    def load_binding(*, environment: str) -> SystemAuditRuntimeConfigBinding:
        assert environment == "production"
        return binding

    def build_readers(*, using: str) -> SystemAuditAuthorityReaders:
        assert using == "default"
        return readers

    monkeypatch.setattr(runtime, "load_system_audit_runtime_config", load_binding)
    monkeypatch.setattr(runtime, "build_system_audit_authority_readers", build_readers)


def test_production_factory_claims_persists_receipt_and_marks_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_inputs(monkeypatch)
    dispatcher = runtime.build_system_audit_outbox_dispatcher()
    repository = dispatcher._repository
    assert isinstance(repository, DjangoSystemAuditOutboxRepository)
    event = make_event()
    with repository.atomic():
        enqueued = repository.enqueue(
            event,
            created_at=event.recorded_at,
            available_at=event.recorded_at,
        )

    result = dispatcher.execute(
        DispatchSystemAuditOutboxCommand(
            worker_id="audit-worker",
            as_of=NOW,
            limit=5,
        )
    )

    assert (result.claimed, result.delivered, result.failed, result.outcome) == (
        1,
        1,
        0,
        "success",
    )
    outbox = SystemAuditOutboxModel.objects.get(outbox_id=enqueued.outbox_id)
    assert outbox.status == SystemAuditOutboxModel.STATUS_DELIVERED
    assert outbox.claimed_by == "audit-worker"
    assert outbox.claimed_at == NOW
    assert outbox.claim_token
    assert outbox.delivered_at == NOW
    receipt = SystemAuditDeliveryReceiptModel.objects.get()
    assert receipt.event_id == event.event_id
    assert receipt.event_version == event.event_version
    assert receipt.identity_hash == event.identity_hash
    assert receipt.content_hash == event.content_hash
    assert receipt.stream_id == event.stream_id
    assert receipt.sequence_no == event.sequence_no
    assert receipt.predecessor_hash == event.predecessor_hash
    assert receipt.idempotency_key == event.idempotency_key
    assert receipt.canonical_payload == event.to_payload()

    replay_receipt = dispatcher._publisher.publish(event)
    replay_result = dispatcher.execute(
        DispatchSystemAuditOutboxCommand(
            worker_id="audit-worker-replay",
            as_of=NOW,
            limit=5,
        )
    )
    assert replay_receipt.delivery_id == receipt.delivery_id
    assert (replay_result.claimed, replay_result.delivered, replay_result.failed) == (0, 0, 0)
    assert SystemAuditDeliveryReceiptModel.objects.count() == 1


def test_missing_authority_blocks_before_claim_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_inputs(monkeypatch, actor_available=False)
    dispatcher = runtime.build_system_audit_outbox_dispatcher()
    repository = dispatcher._repository
    assert isinstance(repository, DjangoSystemAuditOutboxRepository)
    event = make_event(event_id="evt-authority-blocked", idempotency_key="audit:blocked")
    with repository.atomic():
        repository.enqueue(
            event,
            created_at=event.recorded_at,
            available_at=event.recorded_at,
        )

    with pytest.raises(SystemAuditOutboxDispatchUnavailable) as exc_info:
        dispatcher.execute(
            DispatchSystemAuditOutboxCommand(
                worker_id="audit-worker",
                as_of=NOW,
                limit=5,
            )
        )

    assert exc_info.value.reason_code == "authority_unavailable"
    outbox = SystemAuditOutboxModel.objects.get(event_id=event.event_id)
    assert outbox.status == SystemAuditOutboxModel.STATUS_PENDING
    assert outbox.attempt_count == 0
    assert outbox.claimed_at is None
    assert outbox.claimed_by is None
    assert outbox.claim_token is None
    assert SystemAuditDeliveryReceiptModel.objects.count() == 0
