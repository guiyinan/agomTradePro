"""Tests for legacy-compatible and policy-bound publication evidence hashes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.domain.control_plane import PublicationFactReference


def _reference() -> PublicationFactReference:
    return PublicationFactReference(
        natural_key="asset:2026-09-13:provider",
        source="provider",
        source_record_id="record-1",
        fact_table="data_center_valuation_fact",
        fact_pk="17",
        observed_at=datetime(2026, 9, 13, 9, 0, tzinfo=UTC),
        raw_payload_hash="a" * 64,
        quality_status="accepted",
        revision_number=2,
        available_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
        source_published_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
        raw_payload_scope="batch_response_body",
        fact_content_hash="b" * 64,
    )


def test_legacy_hash_bytes_remain_exactly_unchanged() -> None:
    reference = _reference()
    payload = [
        {
            "natural_key": reference.natural_key,
            "source": reference.source,
            "fact_table": reference.fact_table,
            "fact_pk": reference.fact_pk,
            "observed_at": reference.observed_at.isoformat(),
            "raw_payload_hash": reference.raw_payload_hash,
            "quality_status": reference.quality_status,
            "revision_number": reference.revision_number,
        }
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    assert publication_hash([reference]) == hashlib.sha256(encoded).hexdigest()


def test_v2_hash_binds_policy_identity_and_all_frozen_member_metadata() -> None:
    reference = _reference()
    identity = "p2:2:" + ("c" * 64)
    digest = publication_hash([reference], policy_identity=identity)
    assert digest != publication_hash([reference])
    assert digest != publication_hash([reference], policy_identity="p2:3:" + ("c" * 64))
    changed = replace(reference, fact_content_hash="d" * 64)
    assert publication_hash([changed], policy_identity=identity) != digest


@pytest.mark.parametrize(
    "field",
    [
        "source_record_id",
        "available_at",
        "fetched_at",
        "source_published_at",
        "raw_payload_scope",
        "fact_content_hash",
    ],
)
def test_v2_hash_binds_each_new_frozen_member_field(field: str) -> None:
    reference = _reference()
    identity = "p2:2:" + ("c" * 64)
    original = publication_hash([reference], policy_identity=identity)
    if field.endswith("_at"):
        changed_value = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    elif field == "source_record_id":
        changed_value = "record-2"
    elif field == "raw_payload_scope":
        changed_value = "record_response_body"
    else:
        changed_value = "d" * 64
    assert (
        publication_hash([replace(reference, **{field: changed_value})], policy_identity=identity)
        != original
    )


@pytest.mark.parametrize(
    "identity",
    [
        "2:" + ("a" * 64),
        "p2:2:not-a-digest",
        "p2::" + ("a" * 64),
        "p2:" + ("v" * 41) + ":" + ("a" * 64),
    ],
)
def test_v2_hash_requires_self_describing_policy_identity(identity: str) -> None:
    with pytest.raises(ValueError, match="policy_identity"):
        publication_hash([_reference()], policy_identity=identity)


def test_member_reference_roundtrip_preserves_new_metadata() -> None:
    reference = _reference()
    member = publication_member_from_reference(
        reference,
        member_id="member-1",
        publication_id="publication-1",
        dataset_key="equity.valuation.fact",
    )
    assert member_reference(member) == reference
