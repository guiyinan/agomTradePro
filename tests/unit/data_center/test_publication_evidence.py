"""Bounded tests for typed publication evidence and policy-key validation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import PublicationFactReference, PublicationMember
from apps.data_center.domain.publication_evidence import validate_publication_evidence

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
OBSERVED = NOW - timedelta(hours=3)
AVAILABLE = NOW - timedelta(hours=2)
FETCHED = NOW - timedelta(hours=1)


def _policy(
    *,
    version: str = "2",
    evidence: tuple[str, ...] = (
        "source",
        "observed_at",
        "available_at",
        "fetched_at",
        "raw_payload_hash",
        "raw_payload_scope",
    ),
) -> PublicationPolicy:
    return PublicationPolicy(
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=evidence,
        retention_days=3650,
        policy_version=version,
    )


def _reference(**changes: object) -> PublicationFactReference:
    reference = PublicationFactReference(
        natural_key="asset:2026-09-13:provider",
        source="provider",
        source_record_id="provider-record",
        fact_table="data_center_valuation_fact",
        fact_pk="17",
        observed_at=OBSERVED,
        raw_payload_hash="a" * 64,
        quality_status="accepted",
        revision_number=1,
        available_at=AVAILABLE,
        fetched_at=FETCHED,
        source_published_at=OBSERVED,
        raw_payload_scope="batch_response_body",
        fact_content_hash="b" * 64,
    )
    return replace(reference, **changes)


def test_versioned_policy_requires_typed_evidence_and_normalized_hash() -> None:
    validate_publication_evidence(_policy(), [_reference()], published_at=NOW)

    with pytest.raises(ValueError, match="fact_content_hash"):
        validate_publication_evidence(
            _policy(), [_reference(fact_content_hash="")], published_at=NOW
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("available_at", FETCHED + timedelta(seconds=1), "available_at is after fetched_at"),
        ("fetched_at", NOW + timedelta(seconds=1), "fetched_at is after publication"),
        ("observed_at", FETCHED + timedelta(seconds=1), "observed_at is after fetched_at"),
        ("raw_payload_hash", "A" * 64, "raw_payload_hash"),
        ("raw_payload_scope", "normalized_fact", "raw_payload_scope"),
        ("quality_status", "degraded", "quality"),
        ("quality_status", "unknown", "quality"),
    ],
)
def test_versioned_policy_rejects_invalid_timing_hash_scope_or_quality(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_publication_evidence(_policy(), [_reference(**{field: value})], published_at=NOW)


def test_source_published_at_is_distinct_from_canonical_publication_time() -> None:
    policy = _policy(evidence=("source", "published_at"))
    validate_publication_evidence(
        policy,
        [_reference(source_published_at=OBSERVED)],
        published_at=NOW,
    )
    with pytest.raises(ValueError, match="published_at"):
        validate_publication_evidence(
            policy,
            [_reference(source_published_at=None)],
            published_at=NOW,
        )


def test_legacy_payload_hash_accepts_existing_non_raw_encoding() -> None:
    policy = _policy(version="legacy", evidence=("source", "observed_at", "payload_hash"))
    reference = _reference(raw_payload_hash="sha256:normalized-fact")
    validate_publication_evidence(policy, [reference], published_at=NOW)


def test_member_metadata_uses_the_same_typed_gate() -> None:
    member = PublicationMember(
        member_id="member-1",
        publication_id="publication-1",
        dataset_key="equity.valuation.fact",
        natural_key="asset:2026-09-13:provider",
        source="provider",
        source_record_id="provider-record",
        fact_table="data_center_valuation_fact",
        fact_pk="17",
        observed_at=OBSERVED,
        raw_payload_hash="a" * 64,
        quality_status="valid",
        revision_number=1,
        available_at=AVAILABLE,
        fetched_at=FETCHED,
        source_published_at=OBSERVED,
        raw_payload_scope="record_response_body",
        fact_content_hash="b" * 64,
    )
    validate_publication_evidence(_policy(), [member], published_at=NOW)


@pytest.mark.parametrize("field", ["available_at", "fetched_at", "source_published_at"])
def test_reference_rejects_naive_optional_timestamps(field: str) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _reference(**{field: datetime(2026, 9, 13, 10, 0)})


def test_member_rejects_naive_optional_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        PublicationMember(
            member_id="member-1",
            publication_id="publication-1",
            dataset_key="equity.valuation.fact",
            natural_key="asset:2026-09-13:provider",
            source="provider",
            source_record_id="provider-record",
            fact_table="data_center_valuation_fact",
            fact_pk="17",
            observed_at=OBSERVED,
            fetched_at=datetime(2026, 9, 13, 11, 0),
        )


@pytest.mark.parametrize(
    "evidence",
    [
        ("source", "not_registered"),
        ("source", "source"),
    ],
)
def test_policy_rejects_unknown_or_repeated_evidence_keys(
    evidence: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="unknown|duplicate"):
        _policy(version="legacy", evidence=evidence)
