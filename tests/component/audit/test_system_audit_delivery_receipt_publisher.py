import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")
django.setup()
from django.core.exceptions import ValidationError
from django.db import connection

from apps.audit.application.system_audit_composition import (
    CanonicalSystemAuditPublisherPreflight,
    SystemAuditPublisherContractViolation,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.audit.infrastructure.system_audit_delivery_receipt import (
    DjangoSystemAuditDeliveryReceiptPublisher,
    SystemAuditDeliveryReceiptModel,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.audit.test_system_audit_event import make_event

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Create the receipt table for this isolated component suite."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((SystemAuditDeliveryReceiptModel,)):
            yield


def _event() -> SystemAuditEvent:
    return make_event()


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def test_preflight_and_publish_preserve_exact_event_and_replay() -> None:
    event = _event()
    first_published_at = event.recorded_at + timedelta(seconds=1)
    clock = FixedClock(first_published_at)
    publisher = DjangoSystemAuditDeliveryReceiptPublisher(clock=clock)

    assert publisher.database_alias == "default"
    assert publisher.preflight() == CanonicalSystemAuditPublisherPreflight(
        sink_id="audit-system-delivery-receipt-v1", sink_kind="durable"
    )
    first = publisher.publish(event)
    clock.value += timedelta(minutes=5)
    replay = publisher.publish(event)

    assert replay == first
    assert first.canonical_payload == event.to_payload()
    assert first.published_at == first_published_at
    assert SystemAuditDeliveryReceiptModel.objects.count() == 1


@pytest.mark.parametrize("using", ["", " default", "default ", "bad alias"])
def test_publisher_rejects_noncanonical_database_alias(using: str) -> None:
    with pytest.raises(ValueError, match="database alias"):
        DjangoSystemAuditDeliveryReceiptPublisher(using=using)


def test_direct_orm_insert_update_delete_is_rejected() -> None:
    event = _event()
    publisher = DjangoSystemAuditDeliveryReceiptPublisher(
        clock=FixedClock(event.recorded_at + timedelta(seconds=1))
    )
    publisher.publish(event)
    row = SystemAuditDeliveryReceiptModel.objects.get()

    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        SystemAuditDeliveryReceiptModel.objects.filter(pk=row.pk).update(content_hash="0" * 64)
    with pytest.raises(ValidationError):
        SystemAuditDeliveryReceiptModel.objects.bulk_update([row], ["content_hash"])
    with pytest.raises(ValidationError):
        SystemAuditDeliveryReceiptModel._base_manager.bulk_create(
            [
                SystemAuditDeliveryReceiptModel(
                    event_id="direct-event",
                    event_version="1",
                    identity_hash="1" * 64,
                    content_hash="2" * 64,
                    stream_id="direct-stream",
                    sequence_no=1,
                    predecessor_hash=None,
                    idempotency_key="direct-idempotency",
                    canonical_payload={},
                    sink_id="direct-sink",
                    delivery_id="direct-delivery",
                    published_at=event.recorded_at,
                )
            ]
        )


def test_invalid_event_and_identity_conflict_fail_closed() -> None:
    event = _event()
    publisher = DjangoSystemAuditDeliveryReceiptPublisher(
        clock=FixedClock(event.recorded_at + timedelta(seconds=1))
    )
    publisher.publish(event)
    forged = replace(event, content_hash="0" * 64)
    with pytest.raises(SystemAuditPublisherContractViolation):
        publisher.publish(forged)

    idempotency_collision = make_event(
        event_id="evt-idempotency-collision",
        idempotency_key=event.idempotency_key,
    )
    with pytest.raises(SystemAuditPublisherContractViolation):
        publisher.publish(idempotency_collision)


def test_publisher_rejects_persisted_receipt_tamper() -> None:
    event = _event()
    publisher = DjangoSystemAuditDeliveryReceiptPublisher(
        clock=FixedClock(event.recorded_at + timedelta(seconds=1))
    )
    publisher.publish(event)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_system_delivery_receipt SET content_hash = %s WHERE event_id = %s",
            ["0" * 64, event.event_id],
        )

    with pytest.raises(SystemAuditPublisherContractViolation):
        publisher.publish(event)
