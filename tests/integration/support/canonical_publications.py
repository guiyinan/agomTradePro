"""Canonical publication fixtures shared by integration tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import uuid4

from django.db import models

from apps.data_center.application.publication_utils import member_reference, publication_hash
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.market_time import cn_market_date_start_utc
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.publication_fact_evidence import stored_fact_evidence
from apps.data_center.infrastructure.publication_fact_identity import (
    build_publication_fact_identity,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)

_CONTRACT_VERSION = "integration-test"
_SCHEMA_VERSION = "1.0"


def publish_canonical_rows(
    *,
    dataset_key: str,
    publication_key: str,
    fact_table: str,
    observation_field: str,
    rows: Sequence[models.Model],
) -> None:
    """Publish exact canonical facts without rewriting source observation times.

    The fixture must satisfy the current-publication evidence gate: an active
    legacy publication policy bound to the fixture contract, member fact-content
    hashes recomputed from the persisted rows, a publication hash rebuilt from
    the frozen member references, and the current pointer for the scope.
    """

    if not rows:
        raise ValueError("rows must be non-empty")
    member_specs = []
    for row in rows:
        _source_observed_at(row, observation_field=observation_field)
        # 内容哈希绑定规范化后的存储行；内存对象与回读行在 Decimal/datetime
        # 精度上可能不同，直接用内存行会让证据门的重算哈希失配。
        stored_row = type(row)._default_manager.get(pk=row.pk)
        identity = build_publication_fact_identity(dataset_key, stored_row)
        evidence = stored_fact_evidence(stored_row)
        member_specs.append((stored_row, identity, evidence))
    publication_as_of = max(identity.observed_at for _, identity, _ in member_specs)
    published_at = datetime.now(UTC)

    DatasetContractModel._default_manager.filter(
        dataset_key=dataset_key,
        active=True,
    ).update(active=False)
    DatasetContractModel._default_manager.update_or_create(
        dataset_key=dataset_key,
        contract_version=_CONTRACT_VERSION,
        schema_version=_SCHEMA_VERSION,
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

    PublicationPolicyRepository().save(
        PublicationPolicy(
            dataset=DatasetKey(dataset_key, _CONTRACT_VERSION, _SCHEMA_VERSION),
            minimum_coverage_ratio=0.0,
            allow_partial=True,
            conflict_action="quarantine",
            required_evidence=("source", "observed_at"),
            retention_days=3650,
        )
    )

    publication_id = uuid4()
    CanonicalPublicationModel._default_manager.create(
        publication_id=publication_id,
        dataset_key=dataset_key,
        publication_key=publication_key,
        policy_version=f"{_CONTRACT_VERSION}:{_SCHEMA_VERSION}",
        state="published",
        selected_source="integration-test",
        publication_hash=f"integration-pending-{uuid4().hex}",
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
                natural_key=identity.natural_key,
                source=identity.source,
                source_record_id=identity.source_record_id,
                fact_table=fact_table,
                fact_pk=str(row.pk),
                observed_at=identity.observed_at,
                raw_payload_hash=identity.raw_payload_hash,
                quality_status=identity.quality_status,
                revision_number=identity.revision_number,
                available_at=evidence.available_at,
                fetched_at=evidence.fetched_at,
                source_published_at=evidence.source_published_at,
                raw_payload_scope=evidence.raw_payload_scope,
                fact_content_hash=evidence.fact_content_hash,
            )
            for row, identity, evidence in member_specs
        ]
    )

    repository = CanonicalPublicationRepository()
    frozen_members = tuple(repository.list_members(str(publication_id)))
    references = tuple(
        member_reference(member)
        for member in sorted(frozen_members, key=lambda item: item.natural_key)
    )
    digest = publication_hash(references, policy_identity=None, scope_blocks=())
    CanonicalPublicationModel._default_manager.filter(
        publication_id=publication_id,
    ).update(publication_hash=digest)
    CanonicalPublicationPointerModel._default_manager.update_or_create(
        dataset_key=dataset_key,
        publication_key=publication_key,
        defaults={
            "publication_id": publication_id,
            "publication_hash": digest,
            "activation_id": f"integration-test:{publication_id}",
        },
    )


def _source_observed_at(row: models.Model, *, observation_field: str) -> datetime:
    """Return the explicitly declared source observation boundary for one fact."""

    value = getattr(row, observation_field, None)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{observation_field} must be timezone-aware")
        return value
    if isinstance(value, date):
        return cn_market_date_start_utc(value)
    raise ValueError(
        f"{row.__class__.__name__}.{observation_field} has no supported observation value"
    )
