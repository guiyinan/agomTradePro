"""Actual ORM members retain evidence and refuse rewrites independently of mutable facts."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.application.publication_utils import publication_member_from_reference
from apps.data_center.domain.control_plane import PublicationMember
from apps.data_center.domain.entities import ValuationFact
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import ValuationFactModel
from apps.data_center.infrastructure.publication_models import CanonicalPublicationModel
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

pytestmark = pytest.mark.django_db


def _persist_candidate_parent(member: PublicationMember, *, member_count: int = 1) -> None:
    """Create the candidate row whose lock seals this member set."""

    CanonicalPublicationModel.objects.create(
        publication_id=member.publication_id,
        dataset_key=member.dataset_key,
        publication_key=f"member-evidence:{member.publication_id}",
        policy_version="fixture",
        selected_source=member.source,
        publication_hash=hashlib.sha256(member.publication_id.encode()).hexdigest(),
        member_count=member_count,
        coverage_requested_count=member_count,
        coverage_eligible_count=member_count,
        coverage_selected_count=member_count,
        as_of=member.observed_at,
    )


def _persist_reference():
    observed = datetime(2026, 9, 11, 7, tzinfo=UTC)
    received = observed + timedelta(minutes=5)
    raw_hash = hashlib.sha256(b"controlled original batch response bytes").hexdigest()
    fact = ValuationFact(
        asset_code="000001.SZ",
        val_date=observed.date(),
        pe_ttm=12.5,
        source="tencent",
        observed_at=observed,
        available_at=received,
        fetched_at=received,
        source_record_id="tencent:quote_batch:000001.SZ:" + raw_hash,
        raw_payload_hash=raw_hash,
        extra={
            "raw_payload_scope": "batch_response_body",
            "availability_basis": "response_completed_utc",
        },
    )
    facts = ValuationFactRepository()
    assert facts.bulk_upsert([fact]) == 1
    return facts.list_publication_candidates([fact])[0]


def test_stored_member_roundtrips_full_source_evidence() -> None:
    reference = _persist_reference()
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key="equity.valuation.fact",
    )
    publications = CanonicalPublicationRepository()
    _persist_candidate_parent(member)
    assert publications.add_member(member) == member
    assert publications.list_members(member.publication_id) == [member]
    assert member.available_at == reference.available_at != reference.observed_at
    assert member.fetched_at == reference.fetched_at
    assert member.raw_payload_scope == "batch_response_body"
    assert len(member.fact_content_hash) == 64
    assert member.fact_content_hash != member.raw_payload_hash


@pytest.mark.parametrize(
    "changed",
    [
        {"raw_payload_hash": "b" * 64},
        {"fact_content_hash": "c" * 64},
        {"available_at": datetime(2026, 9, 11, 7, 4, tzinfo=UTC)},
        {"fact_pk": "999"},
    ],
)
def test_stored_member_replay_cannot_overwrite_any_frozen_evidence(changed) -> None:
    reference = _persist_reference()
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key="equity.valuation.fact",
    )
    publications = CanonicalPublicationRepository()
    _persist_candidate_parent(member)
    assert publications.add_member(member) == member
    assert publications.add_member(member) == member
    with pytest.raises(ValueError, match="immutable"):
        publications.add_member(replace(member, **changed))
    assert publications.list_members(member.publication_id) == [member]


def test_mutable_fact_value_change_preserves_raw_body_and_invalidates_frozen_fact_hash() -> None:
    reference = _persist_reference()
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key="equity.valuation.fact",
    )
    publications = CanonicalPublicationRepository()
    _persist_candidate_parent(member)
    publications.add_member(member)
    before = publications.get_fact_content_hashes((member,))
    assert before[(member.fact_table, member.fact_pk)] == member.fact_content_hash
    ValuationFactModel.objects.filter(pk=reference.fact_pk).update(pe_ttm=99)
    after = publications.get_fact_content_hashes((member,))
    assert after[(member.fact_table, member.fact_pk)] != member.fact_content_hash
    assert (
        ValuationFactModel.objects.get(pk=reference.fact_pk).raw_payload_hash
        == member.raw_payload_hash
    )
    assert publications.list_members(member.publication_id) == [member]


def test_quote_publication_add_member_uses_one_lookup_and_insert_per_member() -> None:
    """Characterize the current O(N) member persistence contract."""

    member_count = 32
    publication_id = str(uuid4())
    members = tuple(
        PublicationMember(
            member_id=str(uuid4()),
            publication_id=publication_id,
            dataset_key="equity.quote.snapshot",
            natural_key=f"{index:06d}.SZ:2026-09-24T07:00:00+00:00:provider",
            source="provider",
            source_record_id=f"quote-{index}",
            fact_table="data_center_quote_snapshot",
            fact_pk=str(index + 1),
            observed_at=datetime(2026, 9, 24, 7, tzinfo=UTC),
        )
        for index in range(member_count)
    )
    publications = CanonicalPublicationRepository()
    _persist_candidate_parent(members[0], member_count=member_count)

    with CaptureQueriesContext(connection) as captured:
        for member in members:
            publications.add_member(member)

    member_selects = [
        query
        for query in captured
        if query["sql"].lstrip().upper().startswith("SELECT")
        and "data_center_publication_member" in query["sql"]
    ]
    parent_selects = [
        query
        for query in captured
        if query["sql"].lstrip().upper().startswith("SELECT")
        and "data_center_canonical_publication" in query["sql"]
    ]
    member_inserts = [
        query
        for query in captured
        if query["sql"].lstrip().upper().startswith("INSERT")
        and "data_center_publication_member" in query["sql"]
    ]
    assert len(parent_selects) == member_count
    assert len(member_selects) == member_count
    assert len(member_inserts) == member_count
