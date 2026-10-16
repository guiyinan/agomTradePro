"""Normal ORM paths must not overwrite an append-only source record."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models
from django.utils import timezone

from apps.data_center.infrastructure.models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    with isolated_schema((InstrumentReferenceMappingModel, InstrumentReferenceSnapshotModel)):
        yield


def _row_values(
    kind: Literal["mapping", "snapshot"],
) -> tuple[type[models.Model], dict[str, object]]:
    """Use synthetic seals only to test ORM mutation, not Domain authenticity."""

    mapping_values: dict[str, object] = {
        "mapping_record_id": uuid4(),
        "mapping_id": "root-orm-guard",
        "mapping_version": "1",
        "source_crosswalk_id": "explicit-crosswalk",
        "source_crosswalk_version": "1",
        "source_crosswalk_hash": "d" * 64,
        "content": {},
        "content_hash": "sha256:" + "a" * 64,
        "recorded_at": timezone.now(),
        "record_digest": "sha256:" + "b" * 64,
    }
    if kind == "mapping":
        return InstrumentReferenceMappingModel, mapping_values
    mapping = InstrumentReferenceMappingModel.objects.create(**mapping_values)
    return InstrumentReferenceSnapshotModel, {
        "snapshot_id": uuid4(),
        "run_id": uuid4(),
        "mapping_record": mapping,
        "snapshot_payload": {},
        "content_hash": "sha256:" + "a" * 64,
        "recorded_at": timezone.now(),
        "record_digest": "sha256:" + "b" * 64,
        "round_count": 1,
        "occurrence_count": 1,
        "record_count": 0,
    }


@pytest.mark.parametrize("kind", ["mapping", "snapshot"])
def test_new_instance_cannot_overwrite_row_inserted_after_absence_check(
    kind: Literal["mapping", "snapshot"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, values = _row_values(kind)
    assert connection.get_autocommit()
    candidate = model(**{**values, "content_hash": "sha256:" + "c" * 64})
    real_exists = models.QuerySet.exists
    inserted: list[models.Model] = []

    def interleave_insert(queryset: models.QuerySet[models.Model]) -> bool:
        result = real_exists(queryset)
        if queryset.model is model and not result and not inserted:
            # Another writer commits the row immediately after the actual absence read.
            sealed = model(**values)
            models.Model.save(sealed, force_insert=True)
            inserted.append(sealed)
        return result

    monkeypatch.setattr(models.QuerySet, "exists", interleave_insert)
    with pytest.raises((ValidationError, IntegrityError)):
        candidate.save()
    assert len(inserted) == 1
    stored = model._default_manager.get(pk=candidate.pk)
    assert stored.content_hash == values["content_hash"]


@pytest.mark.parametrize("kind", ["mapping", "snapshot"])
def test_queryset_bulk_upsert_cannot_bypass_append_only_manager(
    kind: Literal["mapping", "snapshot"],
) -> None:
    model, values = _row_values(kind)
    original = model._default_manager.create(**values)
    replacement = model(**{**values, "content_hash": "sha256:" + "c" * 64})
    with pytest.raises(ValidationError):
        model._default_manager.all().bulk_create(
            [replacement],
            update_conflicts=True,
            update_fields=["content_hash"],
            unique_fields=[model._meta.pk.name],
        )
    original.refresh_from_db()
    assert original.content_hash == values["content_hash"]
