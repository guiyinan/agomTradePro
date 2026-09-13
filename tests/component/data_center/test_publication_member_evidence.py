"""Actual ORM members retain evidence and refuse rewrites independently of mutable facts."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.application.publication_utils import publication_member_from_reference
from apps.data_center.domain.entities import ValuationFact
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import ValuationFactModel
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

pytestmark = pytest.mark.django_db


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
