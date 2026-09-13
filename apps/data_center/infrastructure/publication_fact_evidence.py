"""Exact normalized fact identity, kept separate from vendor response-body evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from django.db import models

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.market_time import cn_market_date_start_utc

from .publication_fact_identity import build_publication_fact_identity


class _FactJSONEncoder(json.JSONEncoder):
    """Preserve full timestamp precision and finite decimal values at the ORM boundary."""

    def default(self, value: object) -> object:
        """Serialize the supported ORM scalar types without lossy millisecond trimming."""

        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Canonical fact timestamp must be timezone-aware")
            return value.astimezone(UTC).isoformat(timespec="microseconds")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("Canonical fact decimal must be finite")
            return str(value)
        if isinstance(value, UUID):
            return str(value)
        return super().default(value)


def canonical_fact_content_hash(row: models.Model) -> str:
    """Bind every persisted concrete field, including values and evidence, to SHA-256.

    This digest describes a normalized database row. It never attests to an
    original HTTP response, even when a vendor body hash is unavailable.
    """

    payload: dict[str, object] = {
        field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields
    }
    encoded = json.dumps(
        {"encoding": "canonical-fact-row-v1", "table": row._meta.db_table, "fields": payload},
        cls=_FactJSONEncoder,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class StoredFactEvidence:
    """Typed evidence added to a reference after reading its exact persisted row."""

    available_at: datetime | None
    fetched_at: datetime | None
    raw_payload_scope: str
    fact_content_hash: str
    source_published_at: datetime | None = None


def stored_fact_evidence(row: models.Model) -> StoredFactEvidence:
    """Narrow dynamic ORM timestamps and JSON scope before returning immutable evidence."""

    available: object = getattr(row, "available_at", None)
    fetched: object = getattr(row, "fetched_at", None)
    source_published: object = getattr(row, "published_at", None)
    extra: object = getattr(row, "extra", None)
    scope: object = extra.get("raw_payload_scope", "") if isinstance(extra, dict) else ""
    for name, value in (("available_at", available), ("fetched_at", fetched)):
        if value is not None and not isinstance(value, datetime):
            raise ValueError(f"Canonical fact {name} must be datetime or None")
    if source_published is not None and not isinstance(source_published, datetime):
        if isinstance(source_published, date):
            source_published = cn_market_date_start_utc(source_published)
        else:
            raise ValueError("Canonical source published_at must be date/datetime or None")
    if not isinstance(scope, str):
        raise ValueError("Canonical raw_payload_scope must be text")
    return StoredFactEvidence(
        available_at=available if isinstance(available, datetime) else None,
        fetched_at=fetched if isinstance(fetched, datetime) else None,
        source_published_at=source_published if isinstance(source_published, datetime) else None,
        raw_payload_scope=scope,
        fact_content_hash=canonical_fact_content_hash(row),
    )


def publication_fact_reference(
    row: models.Model,
    *,
    natural_key: str,
    observed_at: datetime,
    legacy_payload_hash: str,
    source_record_id: str | None = None,
    revision_number: int | None = None,
    quality_status: str | None = None,
) -> PublicationFactReference:
    """Attach exact row evidence while preserving a source or normalized fallback hash.

    A fallback digest is evidence of the normalized row encoding only; it is
    never presented as an original HTTP response-body digest.
    """

    source: object = getattr(row, "source", None)
    stored_record: object = getattr(row, "source_record_id", "")
    record: object = source_record_id if source_record_id is not None else stored_record
    raw_hash: object = getattr(row, "raw_payload_hash", "")
    quality: object = (
        quality_status if quality_status is not None else getattr(row, "quality_status", "accepted")
    )
    revision: object = (
        revision_number if revision_number is not None else getattr(row, "revision_number", 1)
    )
    if not all(isinstance(value, str) for value in (source, record, raw_hash, quality)):
        raise ValueError("Canonical fact source evidence must be text")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ValueError("Canonical fact revision must be an integer")
    evidence = stored_fact_evidence(row)
    return PublicationFactReference(
        natural_key=natural_key,
        source=source if isinstance(source, str) else "",
        source_record_id=record if isinstance(record, str) and record else natural_key,
        fact_table=row._meta.db_table,
        fact_pk=str(row.pk),
        observed_at=observed_at,
        raw_payload_hash=(
            raw_hash if isinstance(raw_hash, str) and raw_hash else legacy_payload_hash
        ),
        quality_status=quality if isinstance(quality, str) else "",
        revision_number=revision,
        available_at=evidence.available_at,
        fetched_at=evidence.fetched_at,
        source_published_at=evidence.source_published_at,
        raw_payload_scope=evidence.raw_payload_scope if raw_hash and stored_record else "",
        fact_content_hash=evidence.fact_content_hash,
    )


def publication_fact_reference_for_dataset(
    row: models.Model,
    *,
    dataset_key: str,
) -> PublicationFactReference:
    """Build a reference from the canonical rule for a normalized dataset."""

    identity = build_publication_fact_identity(dataset_key, row)
    return publication_fact_reference(
        row,
        natural_key=identity.natural_key,
        source_record_id=identity.source_record_id,
        observed_at=identity.observed_at,
        legacy_payload_hash=identity.raw_payload_hash,
        quality_status=identity.quality_status,
        revision_number=identity.revision_number,
    )
