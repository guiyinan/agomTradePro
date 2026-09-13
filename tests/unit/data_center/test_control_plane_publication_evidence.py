"""The generic publication port must invoke the centralized evidence gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.control_plane import PublishCanonicalDatasetUseCase
from apps.data_center.application.publication_utils import member_reference, publication_hash
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
OBSERVED = NOW - timedelta(hours=3)


class _Repository:
    def __init__(self) -> None:
        self.published: tuple[CanonicalPublication, tuple[PublicationMember, ...]] | None = None

    def publish_with_members(
        self,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> CanonicalPublication:
        self.published = (publication, members)
        return publication


def _policy() -> PublicationPolicy:
    return PublicationPolicy(
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "observed_at", "raw_payload_hash", "raw_payload_scope"),
        retention_days=3650,
        policy_version="2",
    )


def _member(policy: PublicationPolicy) -> PublicationMember:
    return PublicationMember(
        member_id="member-1",
        publication_id="publication-1",
        dataset_key=policy.dataset.value,
        natural_key="asset:2026-09-13:provider",
        source="provider",
        source_record_id="record-1",
        fact_table="data_center_valuation_fact",
        fact_pk="17",
        observed_at=OBSERVED,
        raw_payload_hash="a" * 64,
        quality_status="accepted",
        revision_number=1,
        available_at=NOW - timedelta(hours=2),
        fetched_at=NOW - timedelta(hours=1),
        raw_payload_scope="batch_response_body",
        fact_content_hash="b" * 64,
    )


def _publication(policy: PublicationPolicy, member: PublicationMember) -> CanonicalPublication:
    reference = member_reference(member)
    return CanonicalPublication(
        publication_id=member.publication_id,
        dataset_key=policy.dataset.value,
        publication_key="current",
        policy_version=policy.identity,
        state=PublicationState.PUBLISHED,
        selected_source=member.source,
        publication_hash=publication_hash([reference], policy_identity=policy.identity),
        coverage=CoverageSnapshot(
            coverage_id="coverage-1",
            publication_id=member.publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=NOW,
        ),
        member_count=1,
        as_of=OBSERVED,
        published_at=NOW,
    )


def test_generic_publish_port_runs_evidence_gate_before_repository() -> None:
    policy = _policy()
    member = _member(policy)
    repository = _Repository()
    result = PublishCanonicalDatasetUseCase(repository).execute(
        _publication(policy, member),
        policy=policy,
        members=(member,),
    )
    assert result.publication_id == member.publication_id
    assert repository.published is not None


def test_generic_publish_port_rejects_missing_raw_scope_before_repository() -> None:
    policy = _policy()
    member = _member(policy)
    repository = _Repository()
    with pytest.raises(ValueError, match="raw_payload_scope"):
        PublishCanonicalDatasetUseCase(repository).execute(
            _publication(policy, member),
            policy=policy,
            members=(replace(member, raw_payload_scope=""),),
        )
    assert repository.published is None


def test_generic_p2_publish_rejects_forged_selected_source_before_repository() -> None:
    policy = _policy()
    member = _member(policy)
    repository = _Repository()
    with pytest.raises(ValueError, match="selected_source"):
        PublishCanonicalDatasetUseCase(repository).execute(
            replace(_publication(policy, member), selected_source="invented-vendor"),
            policy=policy,
            members=(member,),
        )
    assert repository.published is None
