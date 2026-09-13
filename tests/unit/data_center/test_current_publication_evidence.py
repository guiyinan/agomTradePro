"""Bounded tests for the pure current-publication evidence helper."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.current_publication_evidence import (
    current_publication_evidence_blocked_reason,
)
from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
OBSERVED = NOW - timedelta(hours=4)
AVAILABLE = NOW - timedelta(hours=3)
FETCHED = NOW - timedelta(hours=2)


def _policy(
    *,
    version: str = "legacy",
    evidence: tuple[str, ...] = ("source", "observed_at", "payload_hash"),
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


def _member(
    *,
    publication_id: str = "publication-1",
    natural_key: str = "asset:2026-09-13:provider",
    fact_pk: str = "17",
    fact_content_hash: str = "b" * 64,
    raw_payload_hash: str = "a" * 64,
    raw_payload_scope: str = "batch_response_body",
    quality_status: str = "accepted",
) -> PublicationMember:
    return PublicationMember(
        member_id=f"member-{fact_pk}",
        publication_id=publication_id,
        dataset_key="equity.valuation.fact",
        natural_key=natural_key,
        source="provider",
        source_record_id=f"record-{fact_pk}",
        fact_table="data_center_valuation_fact",
        fact_pk=fact_pk,
        observed_at=OBSERVED,
        raw_payload_hash=raw_payload_hash,
        quality_status=quality_status,
        revision_number=1,
        available_at=AVAILABLE,
        fetched_at=FETCHED,
        source_published_at=OBSERVED,
        raw_payload_scope=raw_payload_scope,
        fact_content_hash=fact_content_hash,
    )


def _publication(
    policy: PublicationPolicy,
    members: tuple[PublicationMember, ...],
    *,
    published_at: datetime = NOW,
    state: PublicationState = PublicationState.PUBLISHED,
    must_not_use_for_decision: bool = False,
) -> CanonicalPublication:
    references = tuple(
        member_reference(member) for member in sorted(members, key=lambda x: x.natural_key)
    )
    identity = policy.identity if policy.uses_versioned_evidence else None
    return CanonicalPublication(
        publication_id="publication-1",
        dataset_key=policy.dataset.value,
        publication_key="current",
        policy_version=policy.identity,
        state=state,
        selected_source="provider",
        publication_hash=publication_hash(references, policy_identity=identity),
        coverage=CoverageSnapshot(
            coverage_id="coverage-1",
            publication_id="publication-1",
            requested_count=len(members),
            eligible_count=len(members),
            selected_count=len(members),
            generated_at=published_at,
        ),
        member_count=len(members),
        as_of=OBSERVED,
        published_at=published_at,
        must_not_use_for_decision=must_not_use_for_decision,
    )


def _fact_hashes(members: tuple[PublicationMember, ...]) -> dict[tuple[str, str], str]:
    return {(member.fact_table, member.fact_pk): member.fact_content_hash for member in members}


def _reason(
    publication: CanonicalPublication,
    policy: PublicationPolicy | None,
    members: tuple[PublicationMember, ...],
    fact_content_hashes: dict[tuple[str, str], str],
    *,
    knowledge_cutoff: datetime = NOW,
) -> str | None:
    return current_publication_evidence_blocked_reason(
        publication,
        policy=policy,
        members=members,
        fact_content_hashes=fact_content_hashes,
        knowledge_cutoff=knowledge_cutoff,
    )


def test_complete_legacy_current_still_requires_normalized_fact_proof() -> None:
    policy = _policy()
    members = (_member(),)
    publication = _publication(policy, members)
    assert _reason(publication, policy, members, _fact_hashes(members)) is None
    assert _reason(publication, policy, members, {}) == "publication_member_evidence_missing"
    assert (
        _reason(
            publication,
            policy,
            (replace(members[0], fact_content_hash=""),),
            _fact_hashes(members),
        )
        == "publication_member_evidence_missing"
    )


def test_policy_is_required_and_identity_must_match_current_publication() -> None:
    legacy = _policy()
    members = (_member(),)
    publication = _publication(legacy, members)
    assert (
        _reason(publication, None, members, _fact_hashes(members)) == "publication_policy_missing"
    )

    changed_policy = _policy(version="2")
    assert (
        _reason(publication, changed_policy, members, _fact_hashes(members))
        == "publication_policy_changed"
    )


@pytest.mark.parametrize(
    "publication_kwargs",
    [
        {"published_at": NOW + timedelta(seconds=1)},
    ],
)
def test_current_knowledge_boundary_and_decision_block_fail_closed(
    publication_kwargs: dict[str, object],
) -> None:
    policy = _policy()
    members = (_member(),)
    publication = _publication(policy, members, **publication_kwargs)
    assert _reason(publication, policy, members, _fact_hashes(members)) == (
        "publication_knowledge_unavailable"
    )


def test_current_marked_must_not_use_is_unavailable() -> None:
    policy = _policy()
    members = (_member(),)
    publication = _publication(policy, members)
    object.__setattr__(publication, "must_not_use_for_decision", True)
    assert _reason(publication, policy, members, _fact_hashes(members)) == (
        "publication_knowledge_unavailable"
    )


def test_naive_knowledge_cutoff_is_unavailable() -> None:
    policy = _policy()
    members = (_member(),)
    publication = _publication(policy, members)
    assert (
        _reason(
            publication,
            policy,
            members,
            _fact_hashes(members),
            knowledge_cutoff=datetime(2026, 9, 13, 12, 0),
        )
        == "publication_knowledge_unavailable"
    )


def test_member_count_identity_and_uniqueness_are_snapshot_errors() -> None:
    policy = _policy()
    first = _member()
    second = replace(first, member_id="member-18", fact_pk="18")
    publication = _publication(policy, (first,))
    assert _reason(publication, policy, (first, second), _fact_hashes((first, second))) == (
        "publication_member_snapshot_invalid"
    )

    duplicate = replace(first, member_id="member-duplicate")
    publication_with_two = _publication(policy, (first, duplicate))
    assert (
        _reason(
            publication_with_two,
            policy,
            (first, duplicate),
            _fact_hashes((first, duplicate)),
        )
        == "publication_member_snapshot_invalid"
    )


def test_fact_map_missing_or_drifted_hash_is_distinct_from_member_snapshot_tamper() -> None:
    policy = _policy()
    members = (_member(),)
    publication = _publication(policy, members)
    assert _reason(publication, policy, members, {}) == "publication_member_evidence_missing"
    assert (
        _reason(
            publication,
            policy,
            members,
            {(members[0].fact_table, members[0].fact_pk): "c" * 64},
        )
        == "publication_member_fact_changed"
    )
    tampered = replace(members[0], fact_content_hash="c" * 64)
    assert (
        _reason(publication, policy, (tampered,), _fact_hashes(members))
        == "publication_member_fact_changed"
    )


def test_v2_current_uses_policy_bound_hash_and_raw_evidence_gate() -> None:
    policy = _policy(
        version="2",
        evidence=(
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "raw_payload_hash",
            "raw_payload_scope",
        ),
    )
    members = (_member(),)
    publication = _publication(policy, members)
    assert _reason(publication, policy, members, _fact_hashes(members)) is None
    invalid_scope = replace(members[0], raw_payload_scope="normalized_fact")
    assert (
        _reason(publication, policy, (invalid_scope,), _fact_hashes((invalid_scope,)))
        == "publication_member_evidence_missing"
    )


def test_current_rejects_hash_tampering_and_extra_fact_map_entries() -> None:
    policy = _policy()
    members = (_member(),)
    publication = _publication(policy, members)
    extra = {
        **_fact_hashes(members),
        ("data_center_valuation_fact", "18"): "c" * 64,
    }
    assert _reason(publication, policy, members, extra) == "publication_member_snapshot_invalid"

    tampered_publication = replace(publication, publication_hash="c" * 64)
    assert (
        _reason(tampered_publication, policy, members, _fact_hashes(members))
        == "publication_member_snapshot_invalid"
    )
