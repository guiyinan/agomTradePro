"""Preserve facts already frozen by a publication when ingestion runs again."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import TypeVar

from django.db import models, transaction
from django.db.models import OuterRef, QuerySet, Subquery

from core.exceptions import DataFetchError

from .models import FinancialFactModel, PriceBarModel, QuoteSnapshotModel, ValuationFactModel
from .publication_fact_write_lock import publication_fact_write_lock
from .publication_models import PublicationMemberModel

FactModel = TypeVar("FactModel", PriceBarModel, QuoteSnapshotModel, ValuationFactModel)
VersionedFact = TypeVar(
    "VersionedFact", FinancialFactModel, PriceBarModel, QuoteSnapshotModel, ValuationFactModel
)


def latest_fact_revisions(
    model: type[VersionedFact], natural_key: tuple[str, ...]
) -> QuerySet[VersionedFact]:
    """Select one newest revision per source natural key for unpinned raw reads."""
    newest = (
        model._default_manager.filter(**{name: OuterRef(name) for name in natural_key})
        .order_by("-revision_number", "-pk")
        .values("pk")[:1]
    )
    return model._default_manager.filter(pk=Subquery(newest))


def _value(row: models.Model, name: str) -> object:
    value: object = getattr(row, name)
    field = row._meta.get_field(name)
    if value is not None and isinstance(field, models.DecimalField):
        return Decimal(str(value)).quantize(Decimal(1).scaleb(-int(field.decimal_places or 0)))
    return value


@transaction.atomic
def upsert_publication_safe_facts(
    model: type[FactModel],
    rows: Sequence[FactModel],
    *,
    natural_key: tuple[str, ...],
    update_fields: tuple[str, ...],
) -> int:
    """Update unpublished rows, but append a successor for every frozen fact.

    The PostgreSQL table lock also serializes absent-key inserts. Existing
    publication activation locks fact rows, so it cannot publish a row in the
    middle of this check-and-write transaction. Frozen hashes are never edited.
    The return count follows the existing repository contract: processed facts.
    """
    if not rows:
        return 0
    with publication_fact_write_lock(model):
        return _upsert_locked_facts(
            model, rows, natural_key=natural_key, update_fields=update_fields
        )


def _upsert_locked_facts(
    model: type[FactModel],
    rows: Sequence[FactModel],
    *,
    natural_key: tuple[str, ...],
    update_fields: tuple[str, ...],
) -> int:
    scopes: dict[str, list[object]] = {
        f"{name}__in": list({getattr(row, name) for row in rows}) for name in natural_key
    }
    existing = list(model._default_manager.select_for_update().filter(**scopes).order_by("pk"))
    newest: dict[tuple[object, ...], FactModel] = {}
    for row in existing:
        key = tuple(getattr(row, name) for name in natural_key)
        previous = newest.get(key)
        if previous is None or row.revision_number > previous.revision_number:
            newest[key] = row
    pinned = set(
        PublicationMemberModel._default_manager.filter(
            fact_table=model._meta.db_table, fact_pk__in=[str(row.pk) for row in existing]
        ).values_list("fact_pk", flat=True)
    )
    inserted: list[FactModel] = []
    updated: list[FactModel] = []
    seen: set[tuple[object, ...]] = set()
    for incoming in rows:
        key = tuple(getattr(incoming, name) for name in natural_key)
        if key in seen:
            raise DataFetchError(
                "Duplicate fact identity in ingestion batch", code="DUPLICATE_FACT_IDENTITY"
            )
        seen.add(key)
        previous = newest.get(key)
        if previous is None:
            inserted.append(incoming)
            continue
        if all(_value(previous, name) == _value(incoming, name) for name in update_fields):
            continue
        if str(previous.pk) in pinned:
            # Copy retained fields which this ingestion contract does not own.
            for field in model._meta.concrete_fields:
                if not field.primary_key and field.attname not in update_fields:
                    setattr(incoming, field.attname, getattr(previous, field.attname))
            incoming.revision_number = previous.revision_number + 1
            inserted.append(incoming)
        else:
            for name in update_fields:
                setattr(previous, name, getattr(incoming, name))
            updated.append(previous)
    if inserted:
        model._default_manager.bulk_create(inserted, batch_size=500)
    if updated:
        model._default_manager.bulk_create(
            updated,
            batch_size=500,
            update_conflicts=True,
            unique_fields=[*natural_key, "revision_number"],
            update_fields=list(update_fields),
        )
    return len(rows)
