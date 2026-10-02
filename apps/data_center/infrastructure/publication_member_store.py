"""Immutable member persistence and exact normalized fact evidence reads."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from django.db import models, transaction

from apps.data_center.domain.control_plane import PublicationMember, PublicationState

from .publication_fact_evidence import stored_fact_evidence
from .publication_fact_identity import (
    build_publication_fact_identity,
    publication_fact_model_registry,
)
from .publication_models import CanonicalPublicationModel, PublicationMemberModel

_MAX_BIG_AUTO_FIELD_PK: int = (1 << 63) - 1


@transaction.atomic
def add_immutable_publication_member(member: PublicationMember) -> PublicationMember:
    """Append or replay exact frozen content, never overwriting an existing member."""

    publication = (
        CanonicalPublicationModel._default_manager.select_for_update()
        .filter(publication_id=UUID(member.publication_id))
        .first()
    )
    if publication is None:
        raise ValueError("Publication member parent does not exist")
    if (
        publication.state != PublicationState.CANDIDATE.value
        or publication.members_sealed_at is not None
    ):
        raise ValueError("Publication member set is sealed")
    row, _created = PublicationMemberModel._default_manager.get_or_create(
        publication_id=UUID(member.publication_id),
        natural_key=member.natural_key,
        defaults={
            "member_id": UUID(member.member_id),
            "dataset_key": member.dataset_key,
            "source": member.source,
            "source_record_id": member.source_record_id,
            "fact_table": member.fact_table,
            "fact_pk": member.fact_pk,
            "observed_at": member.observed_at,
            "raw_payload_hash": member.raw_payload_hash,
            "quality_status": member.quality_status,
            "revision_number": member.revision_number,
            "available_at": member.available_at,
            "fetched_at": member.fetched_at,
            "source_published_at": member.source_published_at,
            "raw_payload_scope": member.raw_payload_scope,
            "fact_content_hash": member.fact_content_hash,
        },
    )
    restored = row.to_domain()
    if restored != member:
        raise ValueError("Publication member content is immutable")
    return restored


def publication_fact_content_hashes(
    members: Sequence[PublicationMember],
    *,
    lock_rows: bool = False,
) -> dict[tuple[str, str], str]:
    """Bind each frozen member to its exact stored fact, never to claimed provenance."""

    hashes, _ingested_run_ids = publication_fact_content_hashes_and_ingested_runs(
        members,
        lock_rows=lock_rows,
    )
    return hashes


def publication_fact_content_hashes_and_ingested_runs(
    members: Sequence[PublicationMember],
    *,
    lock_rows: bool = False,
) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str | None]]:
    """Read exact fact hashes and ingestion identities with the same bounded queries."""

    dataset_models = publication_fact_model_registry()
    registry: dict[str, type[models.Model]] = {
        model._meta.db_table: model for model in dataset_models.values()
    }
    keys: dict[str, set[int]] = defaultdict(set)
    members_by_fact: dict[tuple[str, int], list[PublicationMember]] = defaultdict(list)
    for member in members:
        expected_model = dataset_models.get(member.dataset_key)
        if expected_model is None or member.fact_table != expected_model._meta.db_table:
            raise ValueError("Publication fact table is not registered")
        fact_pk = _normalize_fact_pk(member.fact_pk)
        keys[member.fact_table].add(fact_pk)
        members_by_fact[(member.fact_table, fact_pk)].append(member)
    hashes: dict[tuple[str, str], str] = {}
    ingested_run_ids: dict[tuple[str, str], str | None] = {}
    for table in sorted(keys):
        query = registry[table]._default_manager.all().order_by("pk")
        if lock_rows:
            query = query.select_for_update()
        rows = query.in_bulk(sorted(keys[table]))
        for pk, row in rows.items():
            ingested_run_id: object = getattr(row, "ingested_run_id", None)
            if ingested_run_id is not None and not isinstance(ingested_run_id, UUID):
                raise ValueError("Publication fact ingested_run_id is not a UUID")
            ingested_run_ids[(table, str(pk))] = (
                str(ingested_run_id) if isinstance(ingested_run_id, UUID) else None
            )
            matching = members_by_fact[(table, pk)]
            digest = _fact_hash_when_provenance_matches(matching, row)
            if digest is not None:
                hashes[(table, str(pk))] = digest
    return hashes, ingested_run_ids


def _normalize_fact_pk(fact_pk: str) -> int:
    """Convert one persisted integer primary key, rejecting ambiguous text."""

    if not isinstance(fact_pk, str) or not fact_pk or not fact_pk.isascii():
        raise ValueError("Publication fact primary key must be canonical decimal text")
    if not fact_pk.isdecimal() or (len(fact_pk) > 1 and fact_pk.startswith("0")):
        raise ValueError("Publication fact primary key must be canonical decimal text")
    normalized = int(fact_pk)
    if normalized < 1 or normalized > _MAX_BIG_AUTO_FIELD_PK or str(normalized) != fact_pk:
        raise ValueError("Publication fact primary key must be a positive integer")
    return normalized


def _fact_hash_when_provenance_matches(
    members: Sequence[PublicationMember],
    row: models.Model,
) -> str | None:
    """Hash once, rejecting matching-hash members with invented provenance."""

    try:
        identity = build_publication_fact_identity(members[0].dataset_key, row)
        evidence = stored_fact_evidence(
            row,
            require_verified_source_evidence=(
                members[0].dataset_key == "equity.financial.fact"
                and any(member.source_published_at is not None for member in members)
            ),
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    for member in members:
        if member.fact_content_hash != evidence.fact_content_hash:
            continue
        if (
            member.natural_key != identity.natural_key
            or member.source != identity.source
            or member.source_record_id != identity.source_record_id
            or member.observed_at != identity.observed_at
            or member.raw_payload_hash != identity.raw_payload_hash
            or member.quality_status != identity.quality_status
            or member.revision_number != identity.revision_number
            or member.available_at != evidence.available_at
            or member.fetched_at != evidence.fetched_at
            or member.source_published_at != evidence.source_published_at
            or member.raw_payload_scope != evidence.raw_payload_scope
        ):
            return None
    return evidence.fact_content_hash
