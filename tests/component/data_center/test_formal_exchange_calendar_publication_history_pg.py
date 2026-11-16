"""Native PostgreSQL acceptance for the exact historical calendar reader."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connection, transaction
from django.db.models.functions import Now
from django.utils import timezone

from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.data_center.application.calendar_catalog_bootstrap import CALENDAR_DATASET_KEY
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
    PublishExchangeCalendarSnapshotUseCase,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    HistoricalPublishedExchangeCalendar,
    ReadExchangeCalendarPublicationAsOfQuery,
)
from apps.data_center.calendar_publication_history_composition import (
    read_exchange_calendar_publication_as_of,
)
from apps.data_center.domain.contracts import DatasetKey
from apps.data_center.infrastructure.calendar_catalog_history_guard import (
    calendar_catalog_history_guard_applied_at,
)
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
from apps.data_center.infrastructure.formal_exchange_calendar_publication_history_reader import (
    DjangoFormalExchangeCalendarPublicationHistoryReader,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
    DjangoFormalExchangeCalendarPublicationRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import PublicationRollbackModel
from core.exceptions import DataFetchError
from core.integration.calendar_formal_publication_history_audit import (
    CoreCalendarFormalPublicationHistoricalAuditBridge,
)
from tests.component.data_center import (
    test_formal_exchange_calendar_publication_repository as publication_fixture_support,
)
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _SCHEMA_MODELS,
    _actual_publisher,
    _authorized_publish,
    _clear_auth_join_rows,
    _counts,
    _real_audit_bridge,
)
from tests.component.data_center.test_formal_exchange_calendar_publication_repository import (
    _candidate,
    _ready,
    _request,
)
from tests.support.isolated_schema import isolated_schema

_DATASET = DatasetKey(CALENDAR_DATASET_KEY, "contract-1", "schema-1")

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


@pytest.fixture(autouse=True)
def _history_schema(django_db_blocker: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use only the migrated disposable PG test DB and owned fixture rows."""

    if connection.vendor != "postgresql":
        pytest.skip("historical calendar integrity requires native PostgreSQL")
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    monkeypatch.setattr(publication_fixture_support, "_DATASET", _DATASET)
    with django_db_blocker.unblock():
        assert (
            "django_migrations" in connection.introspection.table_names()
        ), "this acceptance module requires the real migration graph"
        assert (
            calendar_catalog_history_guard_applied_at(
                connection, server_now=timezone.now().astimezone(UTC)
            )
            is not None
        ), "the actual calendar guard migration must be installed"
        with isolated_schema((*_SCHEMA_MODELS, PublicationRollbackModel)):
            try:
                yield
            finally:
                _clear_auth_join_rows()


def _publish_two() -> (
    tuple[CalendarFormalPublicationCommit, CalendarFormalPublicationCommit, datetime, datetime]
):
    """Publish two real retained snapshots through Session permission and Audit."""

    _snapshot, _audit, _clock, _principal, request = _ready()
    _user, proof = _actual_publisher(f"history-publisher-{uuid4().hex[:10]}")
    authority = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=_real_audit_bridge(), using=DEFAULT_DB_ALIAS
    )
    publish = PublishExchangeCalendarSnapshotUseCase(repository)
    first = cast(
        CalendarFormalPublicationCommit,
        _authorized_publish(authority=authority, use_case=publish, proof=proof, request=request),
    )
    first_readable_at = timezone.now().astimezone(UTC)
    successor = DjangoExchangeCalendarSnapshotRepository().save(_candidate())
    forward_request = _request(
        successor,
        DatasetContractModel._default_manager.get(dataset_key=_DATASET.value),
        DatasetPublicationPolicyModel._default_manager.get(dataset_key=_DATASET.value),
        expected_pointer=first.pointer,
        activation_id="history-forward-publication",
    )
    second = cast(
        CalendarFormalPublicationCommit,
        _authorized_publish(
            authority=authority, use_case=publish, proof=proof, request=forward_request
        ),
    )
    assert first.record.published_at < second.record.published_at
    assert first.pointer.pointer_id == second.pointer.pointer_id
    second_readable_at = timezone.now().astimezone(UTC)
    assert first_readable_at < second.record.published_at
    return first, second, first_readable_at, second_readable_at


def _query(
    commit: CalendarFormalPublicationCommit, as_of: datetime
) -> ReadExchangeCalendarPublicationAsOfQuery:
    """Name the exact historical publication without a pointer or activation."""

    return ReadExchangeCalendarPublicationAsOfQuery(
        publication_id=commit.record.publication_id,
        publication_hash=commit.record.seal.publication_hash,
        dataset_key=commit.record.seal.dataset.value,
        exchange=commit.record.seal.exchange,
        as_of=as_of,
    )


def _deactivate_exact_catalog() -> None:
    """Make only legal active/updated_at transitions under the actual DB guard."""

    assert (
        DatasetContractModel._default_manager.filter(dataset_key=_DATASET.value).update(
            active=False, updated_at=Now()
        )
        == 1
    )
    assert (
        DatasetPublicationPolicyModel._default_manager.filter(dataset_key=_DATASET.value).update(
            active=False, updated_at=Now()
        )
        == 1
    )


def _read_in_owned_uow(
    query: ReadExchangeCalendarPublicationAsOfQuery,
) -> HistoricalPublishedExchangeCalendar:
    """Use the repository in the test-owned single UOW while testing DDL rollback."""

    reader = DjangoFormalExchangeCalendarPublicationHistoryReader(
        audit_port=_real_audit_bridge(),
        historical_audit_port=CoreCalendarFormalPublicationHistoricalAuditBridge(
            using=DEFAULT_DB_ALIAS,
            coordinator=DjangoSystemAuditEventOutboxCoordinator(using=DEFAULT_DB_ALIAS),
        ),
        using=DEFAULT_DB_ALIAS,
        clock=lambda: timezone.now().astimezone(UTC),
    )
    return reader.read_publication_as_of(query)


def test_history_preserves_original_pair_after_forward_and_catalog_deactivation() -> None:
    """Old as-of keeps the original source/seal/Audit pair after legal changes."""

    first, second, first_readable_at, _second_readable_at = _publish_two()
    _deactivate_exact_catalog()
    before = _counts()
    old = read_exchange_calendar_publication_as_of(_query(first, first_readable_at))
    assert old.record.publication_id == first.record.publication_id
    assert old.record.seal == first.record.seal
    assert old.record.superseded_at == second.record.published_at
    assert old.audit_pair == first.audit_pair
    assert old.must_not_execute is True
    assert not hasattr(old, "pointer")
    assert not hasattr(old.record, "activation_id")
    assert _counts() == before


def test_history_supersession_excludes_old_and_requires_known_successor() -> None:
    """Supersession excludes the old row; the successor requires real DB knowledge."""

    first, second, _first_readable_at, second_readable_at = _publish_two()
    before = _counts()
    with pytest.raises(DataFetchError):
        read_exchange_calendar_publication_as_of(_query(first, second.record.published_at))
    current_at_boundary = read_exchange_calendar_publication_as_of(
        _query(second, second_readable_at)
    )
    assert current_at_boundary.audit_pair == second.audit_pair
    assert _counts() == before


@pytest.mark.parametrize("catalog_kind", ["contract", "policy"])
def test_published_calendar_catalog_content_and_deletion_are_db_protected(
    catalog_kind: str,
) -> None:
    """Versioned business fields and retained rows cannot mutate after publish."""

    _publish_two()
    model = DatasetContractModel if catalog_kind == "contract" else DatasetPublicationPolicyModel
    before = model._default_manager.get(dataset_key=_DATASET.value)
    values = {"owner": "changed-owner"} if catalog_kind == "contract" else {"allow_partial": True}
    with pytest.raises(DatabaseError, match="published calendar.*immutable"), transaction.atomic():
        model._default_manager.filter(pk=before.pk).update(**values)
    with pytest.raises(DatabaseError, match="published calendar.*immutable"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {connection.ops.quote_name(model._meta.db_table)} WHERE id = %s",
                [before.pk],
            )
    assert model._default_manager.get(pk=before.pk).updated_at == before.updated_at


@pytest.mark.parametrize(
    "tamper", ["disabled", "when_false", "missing_migration", "renamed_migration"]
)
def test_missing_or_tampered_guard_uses_strict_history_and_blocks_late_catalog(
    tamper: str,
) -> None:
    """A current guard claim cannot replace actual enabled, unconditional protection."""

    first, _second, first_readable_at, _second_readable_at = _publish_two()
    _deactivate_exact_catalog()
    before = _counts()
    with transaction.atomic():
        with connection.cursor() as cursor:
            if tamper == "disabled":
                cursor.execute(
                    "ALTER TABLE public.data_center_dataset_contract "
                    "DISABLE TRIGGER dc_calendar_contract_content_immutable_trg"
                )
            elif tamper == "when_false":
                cursor.execute(
                    "DROP TRIGGER dc_calendar_contract_content_immutable_trg "
                    "ON public.data_center_dataset_contract"
                )
                cursor.execute(
                    "CREATE TRIGGER dc_calendar_contract_content_immutable_trg "
                    "BEFORE UPDATE OR DELETE ON public.data_center_dataset_contract "
                    "FOR EACH ROW WHEN (false) "
                    "EXECUTE FUNCTION public.dc_guard_calendar_contract_content()"
                )
            elif tamper == "missing_migration":
                cursor.execute(
                    "DELETE FROM django_migrations WHERE app = %s AND name = %s",
                    ["data_center", "0115_calendar_history_catalog_immutability"],
                )
            else:
                cursor.execute(
                    "UPDATE django_migrations SET name = %s WHERE app = %s AND name = %s",
                    [
                        "0000_calendar_history_catalog_immutability",
                        "data_center",
                        "0115_calendar_history_catalog_immutability",
                    ],
                )
        assert (
            calendar_catalog_history_guard_applied_at(
                connection, server_now=timezone.now().astimezone(UTC)
            )
            is None
        )
        with pytest.raises(DataFetchError) as caught:
            _read_in_owned_uow(_query(first, first_readable_at))
        assert caught.value.code == "CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN"
        transaction.set_rollback(True)
    assert (
        calendar_catalog_history_guard_applied_at(
            connection, server_now=timezone.now().astimezone(UTC)
        )
        is not None
    )
    assert _counts() == before
