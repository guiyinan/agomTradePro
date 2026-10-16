"""Missing current pointers must not erase evidence of earlier publications."""

from datetime import timedelta
from typing import Literal

import pytest
from django.db import transaction

from apps.data_center.application.formal_exchange_calendar_publication import (
    ReadCurrentExchangeCalendarPublicationQuery,
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


@pytest.mark.parametrize("operation", ["publish", "read"])
def test_superseded_history_without_pointer_cannot_be_treated_as_a_new_scope(
    operation: Literal["publish", "read"],
) -> None:
    _snapshot, audit, clock, principal, request = fixtures._ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit, using="default", clock=clock.now
    )
    with transaction.atomic():
        original = repository.publish(request, principal=principal)
    CanonicalPublicationModel.objects.filter(publication_id=original.record.publication_id).update(
        state="superseded", superseded_at=original.record.published_at + timedelta(seconds=1)
    )
    CanonicalPublicationPointerModel.objects.all().delete()
    successor = DjangoExchangeCalendarSnapshotRepository().save(fixtures._candidate())
    clock.value = max(original.record.published_at, successor.recorded_at) + timedelta(seconds=2)
    proposal = fixtures._request(
        successor,
        DatasetContractModel.objects.get(),
        DatasetPublicationPolicyModel.objects.get(),
        activation_id="not-a-new-scope",
    )

    with pytest.raises(DataFetchError) as caught:
        with transaction.atomic():
            if operation == "publish":
                repository.publish(proposal, principal=principal)
            else:
                repository.read_current(
                    ReadCurrentExchangeCalendarPublicationQuery(
                        dataset_key=proposal.dataset_key, exchange="SSE", as_of=clock.value
                    )
                )

    assert caught.value.code == "CALENDAR_FORMAL_POINTER_MISSING"
    assert CanonicalPublicationModel.objects.count() == 1
    assert CanonicalPublicationModel.objects.get().state == "superseded"
    assert CanonicalPublicationPointerModel.objects.count() == 0
    assert len(audit.pairs) == 1
