"""Preserve facts already frozen by a publication when ingestion runs again."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TypeVar

from django.db import connection, models, transaction
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


def latest_versioned_rows_for_assets(
    model: type[VersionedFact],
    *,
    natural_key: tuple[str, ...],
    asset_codes: Sequence[str],
    observation_field: str,
    asset_order: tuple[str, ...],
    filters: Mapping[str, object] | None = None,
) -> list[VersionedFact]:
    """Return one current row per asset without a historical correlated scan.

    PostgreSQL first reduces every asset to its maximum observation, then keeps
    the newest immutable revision for each source natural key and ranks only
    that bounded cross-section. Other databases retain the portable ORM path.
    """

    normalized_assets = tuple(
        sorted({str(code).strip().upper() for code in asset_codes if str(code).strip()})
    )
    if not normalized_assets:
        return []
    normalized_filters: dict[str, object] = dict(filters or {})
    field_names = {field.name for field in model._meta.concrete_fields}
    required_fields = {
        "asset_code",
        "id",
        "revision_number",
        observation_field,
        *natural_key,
        *(term.removeprefix("-") for term in asset_order),
        *normalized_filters,
    }
    unknown_fields = required_fields - field_names
    if unknown_fields:
        raise ValueError(f"Unknown versioned fact fields: {sorted(unknown_fields)}")

    if connection.vendor != "postgresql":
        latest_row = (
            latest_fact_revisions(model, natural_key)
            .filter(asset_code=OuterRef("asset_code"), **normalized_filters)
            .order_by(*asset_order)
            .values("id")[:1]
        )
        return list(
            model._default_manager.filter(
                asset_code__in=normalized_assets,
                pk=Subquery(latest_row),
                **normalized_filters,
            ).order_by("asset_code")
        )

    quote_name = connection.ops.quote_name
    table_name = quote_name(model._meta.db_table)
    asset_column = quote_name("asset_code")
    observation_column = quote_name(observation_field)
    filter_sql = "".join(
        f" AND base.{quote_name(field_name)} = %s" for field_name in normalized_filters
    )
    natural_columns = ", ".join(f"base.{quote_name(name)}" for name in natural_key)
    asset_order_sql = ", ".join(
        _postgres_order_term(term, table_alias="latest_revisions") for term in asset_order
    )
    sql = f"""
        WITH latest_observations AS MATERIALIZED (
            SELECT base.{asset_column} AS asset_code,
                   MAX(base.{observation_column}) AS observation_value
            FROM {table_name} AS base
            WHERE base.{asset_column} = ANY(%s){filter_sql}
            GROUP BY base.{asset_column}
        ),
        latest_revisions AS MATERIALIZED (
            SELECT DISTINCT ON ({natural_columns}) base.*
            FROM {table_name} AS base
            INNER JOIN latest_observations AS observations
                ON observations.asset_code = base.{asset_column}
               AND observations.observation_value = base.{observation_column}
            WHERE base.{asset_column} = ANY(%s){filter_sql}
            ORDER BY {natural_columns},
                     base.{quote_name('revision_number')} DESC,
                     base.{quote_name('id')} DESC
        ),
        ranked_assets AS (
            SELECT latest_revisions.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY latest_revisions.{asset_column}
                       ORDER BY {asset_order_sql}
                   ) AS publication_asset_rank
            FROM latest_revisions
        )
        SELECT *
        FROM ranked_assets
        WHERE publication_asset_rank = 1
        ORDER BY {asset_column}
    """
    filter_values: list[object] = list(normalized_filters.values())
    parameters: list[object] = [list(normalized_assets), *filter_values]
    parameters.extend([list(normalized_assets), *filter_values])
    return list(model._default_manager.raw(sql, parameters))


def _postgres_order_term(term: str, *, table_alias: str) -> str:
    """Render one validated Django-style order term for the PostgreSQL CTE."""

    descending = term.startswith("-")
    field_name = term.removeprefix("-")
    column = connection.ops.quote_name(field_name)
    direction = "DESC NULLS LAST" if descending else "ASC NULLS FIRST"
    return f"{table_alias}.{column} {direction}"


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
