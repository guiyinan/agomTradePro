"""Immutable member persistence and exact normalized fact evidence reads."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from django.db import models, transaction

from apps.data_center.domain.control_plane import PublicationMember

from .publication_fact_evidence import canonical_fact_content_hash, stored_fact_evidence
from .publication_fact_identity import (
    build_publication_fact_identity,
    publication_fact_model_registry,
)
from .publication_models import PublicationMemberModel

_MAX_BIG_AUTO_FIELD_PK: int = (1 << 63) - 1


@transaction.atomic
def add_immutable_publication_member(member: PublicationMember) -> PublicationMember:
    """Append or replay exact frozen content, never overwriting an existing member."""

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
    for table in sorted(keys):
        query = registry[table]._default_manager.all().order_by("pk")
        if lock_rows:
            query = query.select_for_update()
        rows = query.in_bulk(sorted(keys[table]))
        for pk, row in rows.items():
            digest = canonical_fact_content_hash(row)
            matching = members_by_fact[(table, pk)]
            # A changed row remains visible as drift. When the normalized row is
            # unchanged, independently reject provenance invented in a member.
            if any(
                member.fact_content_hash == digest
                and not _member_provenance_matches_row(member, row)
                for member in matching
            ):
                continue
            hashes[(table, str(pk))] = digest
    return hashes


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


def _member_provenance_matches_row(member: PublicationMember, row: models.Model) -> bool:
    """Require every frozen identity and evidence claim to match the fact row."""

    try:
        identity = build_publication_fact_identity(member.dataset_key, row)
        evidence = stored_fact_evidence(row)
    except (AttributeError, TypeError, ValueError):
        return False
    if (
        member.natural_key != identity.natural_key
        or member.source != identity.source
        or member.source_record_id != identity.source_record_id
        or member.observed_at != identity.observed_at
        or member.raw_payload_hash != identity.raw_payload_hash
        or member.quality_status != identity.quality_status
        or member.revision_number != identity.revision_number
    ):
        return False
    return (
        member.available_at == evidence.available_at
        and member.fetched_at == evidence.fetched_at
        and member.source_published_at == evidence.source_published_at
        and member.raw_payload_scope == evidence.raw_payload_scope
    )
