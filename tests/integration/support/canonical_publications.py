"""Canonical publication fixtures shared by integration tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from uuid import uuid4

from django.db import models

from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    PublicationMemberModel,
)


def publish_canonical_rows(
    *,
    dataset_key: str,
    publication_key: str,
    fact_table: str,
    rows: Sequence[models.Model],
) -> None:
    """Publish exact canonical facts without rewriting source observation times."""

    if not rows:
        raise ValueError("rows must be non-empty")
    observed_rows = [(row, _source_observed_at(row)) for row in rows]
    publication_as_of = max(observed_at for _, observed_at in observed_rows)
    published_at = datetime.now(UTC)

    DatasetContractModel._default_manager.filter(
        dataset_key=dataset_key,
        active=True,
    ).update(active=False)
    DatasetContractModel._default_manager.update_or_create(
        dataset_key=dataset_key,
        contract_version="integration-test",
        schema_version="1.0",
        defaults={
            "owner": "integration-tests",
            "frequency": "daily",
            "decision_critical": True,
            "fields": [
                {
                    "name": "observed_at",
                    "value_type": "datetime",
                    "nullable": False,
                    "zero_allowed": False,
                }
            ],
            "freshness_seconds": 7 * 24 * 60 * 60,
            "active": True,
        },
    )

    publication_id = uuid4()
    CanonicalPublicationModel._default_manager.create(
        publication_id=publication_id,
        dataset_key=dataset_key,
        publication_key=publication_key,
        policy_version="integration-test:1.0",
        state="published",
        selected_source="integration-test",
        publication_hash=f"integration-{uuid4().hex}",
        member_count=len(rows),
        coverage_requested_count=len(rows),
        coverage_eligible_count=len(rows),
        coverage_selected_count=len(rows),
        coverage_missing_count=0,
        coverage_conflict_count=0,
        as_of=publication_as_of,
        published_at=published_at,
        must_not_use_for_decision=False,
    )
    PublicationMemberModel._default_manager.bulk_create(
        [
            PublicationMemberModel(
                member_id=uuid4(),
                publication_id=publication_id,
                dataset_key=dataset_key,
                natural_key=f"{fact_table}:{row.pk}",
                source=str(getattr(row, "source", "integration-test")),
                source_record_id=f"{fact_table}:{row.pk}",
                fact_table=fact_table,
                fact_pk=str(row.pk),
                observed_at=observed_at,
                raw_payload_hash=f"integration-{row.pk}",
                quality_status="accepted",
                revision_number=1,
            )
            for row, observed_at in observed_rows
        ]
    )


def _source_observed_at(row: models.Model) -> datetime:
    """Return a fact's own observation boundary as an aware datetime."""

    for field_name in (
        "observed_at",
        "snapshot_at",
        "available_at",
        "published_at",
        "bar_date",
        "val_date",
        "reporting_period",
        "as_of",
        "period_end",
    ):
        value = getattr(row, field_name, None)
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min, tzinfo=UTC)
    raise ValueError(f"{row.__class__.__name__} has no supported source observation field")
