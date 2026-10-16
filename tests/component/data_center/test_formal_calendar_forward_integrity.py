"""Independent checks of old-current Audit integrity during a forward publish."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from django.db import transaction

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarPublicationAuditPair,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRecord,
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
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
)
from core.exceptions import DataFetchError
from tests.component.data_center import (
    test_formal_exchange_calendar_publication_repository as fixtures,
)
from tests.component.data_center.test_formal_exchange_calendar_publication_repository import (
    _publication_schema,
)

__all__ = ["_publication_schema"]
pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


class _AuditPort(fixtures._AuditPort):
    """Observe old-pair checks and optionally return a mismatched valid receipt."""

    def __init__(self, fault: str = "none") -> None:
        super().__init__()
        self.fault = fault
        self.integrity_calls: list[str] = []

    def verify_published_integrity(
        self,
        record: CalendarFormalPublicationRecord,
        *,
        as_of: datetime,
    ) -> CalendarPublicationAuditPair:
        self.integrity_calls.append(record.publication_id)
        pair = super().verify_published_integrity(record, as_of=as_of)
        if self.fault == "wrong_publication_hash":
            return replace(pair, publication_hash="f" * 64)
        if self.fault == "wrong_alias":
            return replace(pair, database_alias="another-database")
        return pair


@pytest.mark.parametrize("fault", ["missing_pair", "wrong_publication_hash", "wrong_alias"])
def test_forward_rejects_unverified_old_pair_without_superseding_or_moving_pointer(
    fault: str,
) -> None:
    _snapshot, _unused_audit, clock, principal, request = fixtures._ready()
    audit = _AuditPort(fault)
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )
    with transaction.atomic():
        original = repository.publish(request, principal=principal)
    if fault == "missing_pair":
        audit.pairs.clear()
    successor = DjangoExchangeCalendarSnapshotRepository().save(fixtures._candidate())
    clock.value = max(original.record.published_at, successor.recorded_at) + timedelta(seconds=2)
    forward = fixtures._request(
        successor,
        DatasetContractModel.objects.get(),
        DatasetPublicationPolicyModel.objects.get(),
        expected_pointer=original.pointer,
        activation_id="old-audit-integrity-required",
    )

    with pytest.raises(DataFetchError):
        with transaction.atomic():
            repository.publish(forward, principal=principal)

    assert audit.integrity_calls == [original.record.publication_id]
    assert CanonicalPublicationModel.objects.count() == 1
    persisted = CanonicalPublicationModel.objects.get()
    assert persisted.state == "published"
    assert persisted.superseded_at is None
    pointer = CanonicalPublicationPointerModel.objects.get()
    assert str(pointer.pointer_id) == original.pointer.pointer_id
    assert str(pointer.publication_id) == original.record.publication_id
    assert pointer.updated_at == original.record.published_at


def test_forward_can_replace_an_expired_current_when_its_exact_old_pair_is_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EarlierCaptureClock:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return datetime.now(UTC) - timedelta(seconds=3550)

    with monkeypatch.context() as patch:
        patch.setattr(fixtures, "datetime", EarlierCaptureClock)
        snapshot, _unused_audit, clock, principal, request = fixtures._ready()
    audit = _AuditPort()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )
    with transaction.atomic():
        original = repository.publish(request, principal=principal)
    successor = DjangoExchangeCalendarSnapshotRepository().save(fixtures._candidate())
    clock.value = snapshot.first_seen_at + timedelta(seconds=3601)
    assert not original.record.is_effective_at(clock.value)
    forward = fixtures._request(
        successor,
        DatasetContractModel.objects.get(),
        DatasetPublicationPolicyModel.objects.get(),
        expected_pointer=original.pointer,
        activation_id="replace-expired-current-with-fresh-source",
    )

    with transaction.atomic():
        published = repository.publish(forward, principal=principal)

    assert audit.integrity_calls == [original.record.publication_id]
    assert published.record.is_effective_at(clock.value)
    assert published.pointer.pointer_id == original.pointer.pointer_id
    assert published.record.publication_id != original.record.publication_id
