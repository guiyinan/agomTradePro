"""Component coverage for versioned publication metadata integrity."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest

from apps.data_center.application.current_publication_evidence import (
    current_publication_evidence_blocked_reason,
)
from apps.data_center.application.publication_utils import member_reference, publication_hash
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.publication_snapshot_policy import (
    validate_publication_snapshot_policy,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import PriceBarModel
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)

pytestmark = pytest.mark.django_db


DATASET_KEY = "equity.price.bar"


def _policy(*, conflict_action: str = "quarantine") -> PublicationPolicy:
    """Return the active p2 price policy used by the component fixtures."""

    return PublicationPolicy(
        dataset=DatasetKey(DATASET_KEY, "1.0", "1.0"),
        minimum_coverage_ratio=0.99,
        allow_partial=True,
        conflict_action=conflict_action,
        required_evidence=(
            "source",
            "observed_at",
            "fetched_at",
            "payload_hash",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="2",
    )


def _snapshot(
    *,
    conflict_action: str = "quarantine",
) -> tuple[PublicationPolicy, CanonicalPublication, PublicationMember]:
    """Persist one canonical fact and build its valid versioned snapshot."""

    policy = _policy(conflict_action=conflict_action)
    PublicationPolicyRepository().save(policy)
    fact = PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 9, 12),
        freq="1d",
        adjustment="none",
        open=12,
        high=13,
        low=11,
        close=12.5,
        volume=1000,
        amount=12500,
        source="tencent",
        source_record_id="tencent:000001.SZ:2026-09-12",
        raw_payload_hash="a" * 64,
    )
    price = PriceBar(
        asset_code=fact.asset_code,
        bar_date=fact.bar_date,
        freq=fact.freq,
        adjustment=PriceAdjustment(fact.adjustment),
        open=float(fact.open),
        high=float(fact.high),
        low=float(fact.low),
        close=float(fact.close),
        volume=float(fact.volume) if fact.volume is not None else None,
        amount=float(fact.amount) if fact.amount is not None else None,
        source=fact.source,
        fetched_at=fact.fetched_at,
    )
    reference = PriceBarRepository().list_publication_candidates([price])[0]
    observed_at = reference.observed_at
    published_at = reference.fetched_at
    if published_at is None:
        raise AssertionError("price publication fixture requires fetched_at")
    published_at += timedelta(seconds=1)
    publication_id = str(uuid4())
    member = PublicationMember(
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key=DATASET_KEY,
        natural_key=reference.natural_key,
        source=reference.source,
        source_record_id=reference.source_record_id,
        fact_table=reference.fact_table,
        fact_pk=reference.fact_pk,
        observed_at=observed_at,
        raw_payload_hash=reference.raw_payload_hash,
        quality_status=reference.quality_status,
        revision_number=reference.revision_number,
        available_at=reference.available_at,
        fetched_at=reference.fetched_at,
        source_published_at=reference.source_published_at,
        raw_payload_scope=reference.raw_payload_scope,
        fact_content_hash=reference.fact_content_hash,
    )
    digest = publication_hash((member_reference(member),), policy_identity=policy.identity)
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key=DATASET_KEY,
        publication_key="current",
        policy_version=policy.identity,
        state=PublicationState.PUBLISHED,
        selected_source="tencent",
        publication_hash=digest,
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            missing_count=0,
            conflict_count=0,
            generated_at=published_at,
        ),
        member_count=1,
        conflict_count=0,
        as_of=observed_at,
        published_at=published_at,
        created_by="test.versioned-publication-integrity",
        run_id=str(uuid4()),
    )
    return policy, publication, member


def _fact_hashes(member: PublicationMember) -> dict[tuple[str, str], str]:
    """Build the exact fact hash map expected by the current gate."""

    return {(member.fact_table, member.fact_pk): member.fact_content_hash}


def test_p2_same_id_exact_replay_is_idempotent() -> None:
    """An exact retry may replay the same immutable publication identity."""

    _policy_value, publication, member = _snapshot()
    repository = CanonicalPublicationRepository()

    first = repository.publish_with_members(publication, (member,))
    stored_coverage = CoverageSnapshotModel.objects.get(publication_id=publication.publication_id)
    stored_coverage_id = stored_coverage.coverage_id
    stored_coverage_generated_at = stored_coverage.generated_at
    replay = repository.publish_with_members(publication, (member,))

    assert replay == first
    persisted = CanonicalPublicationModel.objects.get(publication_id=publication.publication_id)
    assert persisted.state == PublicationState.PUBLISHED.value
    assert persisted.selected_source == "tencent"
    assert persisted.published_at == publication.published_at
    replayed_coverage = CoverageSnapshotModel.objects.get(publication_id=publication.publication_id)
    assert replayed_coverage.coverage_id == stored_coverage_id
    assert replayed_coverage.generated_at == stored_coverage_generated_at
    assert (
        PublicationMemberModel.objects.filter(publication_id=publication.publication_id).count()
        == 1
    )


@pytest.mark.parametrize("change", ["selected_source", "published_at", "coverage"])
def test_p2_same_id_metadata_rewrite_is_rejected_and_history_unchanged(change: str) -> None:
    """A reused p2 ID cannot rewrite source, time, or coverage metadata."""

    _policy_value, publication, member = _snapshot()
    repository = CanonicalPublicationRepository()
    repository.publish_with_members(publication, (member,))

    if change == "selected_source":
        forged = replace(publication, selected_source="forged-provider")
    elif change == "published_at":
        forged = replace(
            publication,
            published_at=publication.published_at + timedelta(seconds=1),
        )
    else:
        forged = replace(
            publication,
            coverage=replace(
                publication.coverage,
                requested_count=2,
                eligible_count=2,
            ),
        )

    with pytest.raises(ValueError):
        repository.publish_with_members(forged, (member,))

    persisted = CanonicalPublicationModel.objects.get(publication_id=publication.publication_id)
    assert persisted.state == PublicationState.PUBLISHED.value
    assert persisted.selected_source == publication.selected_source
    assert persisted.published_at == publication.published_at
    assert persisted.coverage_requested_count == publication.coverage.requested_count
    assert persisted.coverage_eligible_count == publication.coverage.eligible_count
    assert persisted.coverage_selected_count == publication.coverage.selected_count
    assert repository.list_members(publication.publication_id) == [member]


def test_p2_selected_source_uses_mixed_source_summary() -> None:
    """Mixed-source current rebuilds use their deterministic source summary."""

    policy, publication, member = _snapshot()
    first = replace(member, member_id=str(uuid4()), natural_key="a", source="provider-b")
    second = replace(member, member_id=str(uuid4()), natural_key="b", source="provider-a")
    mixed = replace(
        publication,
        member_count=2,
        selected_source="provider-a,provider-b",
        coverage=replace(
            publication.coverage,
            requested_count=2,
            eligible_count=2,
            selected_count=2,
        ),
    )

    validate_publication_snapshot_policy(policy, mixed, members=(first, second))
    with pytest.raises(ValueError, match="selected_source"):
        validate_publication_snapshot_policy(
            policy,
            replace(mixed, selected_source="provider-a"),
            members=(first, second),
        )


@pytest.mark.parametrize("entry_point", ["save", "publish"])
def test_direct_p2_entry_points_apply_coverage_policy(entry_point: str) -> None:
    """Repository entry points cannot bypass p2 coverage/conflict policy."""

    policy, publication, member = _snapshot(conflict_action="block")
    repository = CanonicalPublicationRepository()
    candidate = replace(publication, state=PublicationState.CANDIDATE)
    invalid = replace(
        publication,
        coverage=replace(
            publication.coverage,
            requested_count=2,
            eligible_count=2,
        ),
        conflict_count=1,
    )
    if entry_point == "publish":
        repository.save(candidate)
        repository.add_member(member)
        target = invalid
    else:
        repository.add_member(member)
        target = invalid

    with pytest.raises(ValueError, match="coverage|conflict|policy"):
        if entry_point == "publish":
            repository.publish(target)
        else:
            repository.save(target)


def test_current_gate_rejects_policy_dataset_mismatch_without_changing_v1_hash() -> None:
    """Legacy identity bytes remain unchanged while dataset binding is explicit."""

    _policy_value, versioned, member = _snapshot()
    legacy_policy = PublicationPolicy(
        dataset=DatasetKey("equity.quote.snapshot", "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "observed_at", "fact_content_hash"),
        retention_days=90,
    )
    legacy_member = replace(member, dataset_key=DATASET_KEY)
    legacy_publication = replace(
        versioned,
        policy_version=legacy_policy.identity,
        publication_hash=publication_hash((member_reference(legacy_member),)),
    )

    reason = current_publication_evidence_blocked_reason(
        legacy_publication,
        policy=legacy_policy,
        members=(legacy_member,),
        fact_content_hashes=_fact_hashes(legacy_member),
        knowledge_cutoff=versioned.published_at + timedelta(seconds=1),
    )

    assert reason == "publication_policy_dataset_mismatch"
