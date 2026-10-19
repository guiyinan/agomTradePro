"""Real-row reads across generic p2 financial partial publications."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.data_center.application import query_services
from apps.data_center.application.publication_utils import (
    current_publication_id_for_hash,
    member_reference,
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.application.query_services import query_published_financial_facts
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationScopeBlock,
    PublicationState,
)
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import (
    CanonicalPublicationPointerModel,
    FinancialFactModel,
)
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)

pytestmark = pytest.mark.django_db

DATASET_KEY = "equity.financial.fact"
_SELECTED_ASSET = "600000.SH"
_BLOCKED_ASSET = "000001.SZ"
_BLOCK_REASON = "financial_source_data_unavailable"


def _publish_generic_p2_partial(
    *,
    blocked_asset_code: str,
) -> tuple[CanonicalPublication, PublicationMember, FinancialFactModel]:
    """Persist a p2 partial through the direct generic repository entry points."""

    announced_at = datetime.now(UTC) - timedelta(minutes=20)
    available_at = announced_at + timedelta(minutes=5)
    policy = PublicationPolicy(
        dataset=DatasetKey(DATASET_KEY, "1.0", "1.0"),
        minimum_coverage_ratio=0.5,
        allow_partial=True,
        conflict_action="quarantine",
        required_evidence=(
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "source_record_id",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version=f"ash04-partial-{uuid4().hex[:12]}",
    )
    PublicationPolicyRepository().save(policy)
    DatasetContractModel.objects.filter(dataset_key=DATASET_KEY).delete()
    DatasetContractModel.objects.create(
        dataset_key=DATASET_KEY,
        contract_version="1.0",
        schema_version="1.0",
        owner="test.data-center",
        frequency="quarterly",
        decision_critical=True,
        fields=[
            {
                "name": "available_at",
                "value_type": "datetime",
                "unit": None,
                "nullable": False,
                "zero_allowed": False,
            }
        ],
        freshness_seconds=3650 * 24 * 60 * 60,
    )

    fact = FinancialFactModel.objects.create(
        asset_code=_SELECTED_ASSET,
        period_end=date(2026, 6, 30),
        period_type="quarterly",
        metric_code="revenue",
        value=Decimal("123.4500"),
        unit="CNY",
        source="fixture-financial-provider",
        report_date=available_at.date(),
        announced_at=announced_at,
        available_at=available_at,
        source_record_id=f"fixture-row-{uuid4()}",
        quality_status="accepted",
    )
    reference = publication_fact_reference_for_dataset(
        fact,
        dataset_key=DATASET_KEY,
    )
    run_id = str(uuid4())
    block = PublicationScopeBlock(
        asset_code=blocked_asset_code,
        reason_code=_BLOCK_REASON,
        source=reference.source,
        publication_run_id=run_id,
        policy_version=policy.identity,
    )
    provisional_id = str(uuid4())
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=provisional_id,
        dataset_key=DATASET_KEY,
    )
    digest = publication_hash(
        (member_reference(member),),
        policy_identity=policy.identity,
        scope_blocks=(block,),
    )
    publication_id = current_publication_id_for_hash(DATASET_KEY, "current", digest)
    member = replace(member, publication_id=publication_id)
    block = PublicationScopeBlock(
        asset_code=block.asset_code,
        reason_code=block.reason_code,
        target_trade_date=block.target_trade_date,
        source=block.source,
        publication_run_id=block.publication_run_id,
        policy_version=block.policy_version,
        publication_id=publication_id,
        evidence_source=block.evidence_source,
    )
    assert (
        publication_hash(
            (member_reference(member),),
            policy_identity=policy.identity,
            scope_blocks=(block,),
        )
        == digest
    )

    published_at = max(datetime.now(UTC), fact.fetched_at) + timedelta(seconds=1)
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key=DATASET_KEY,
        publication_key="current",
        policy_version=policy.identity,
        state=PublicationState.PUBLISHED,
        selected_source=reference.source,
        publication_hash=digest,
        coverage=CoverageSnapshot(
            coverage_id=publication_id,
            publication_id=publication_id,
            requested_count=2,
            eligible_count=1,
            selected_count=1,
            missing_count=1,
            conflict_count=0,
            generated_at=published_at,
        ),
        member_count=1,
        conflict_count=0,
        as_of=reference.observed_at,
        published_at=published_at,
        created_by="test.ash04-financial-partial-read",
        run_id=run_id,
        scope_blocks=(block,),
    )
    repository = CanonicalPublicationRepository()
    repository.save(replace(publication, state=PublicationState.CANDIDATE))
    repository.add_member(member)
    stored = repository.publish(publication)
    assert stored.scope_blocks == (block,)
    assert repository.list_members(publication_id) == [member]
    CanonicalPublicationPointerModel.objects.update_or_create(
        dataset_key=DATASET_KEY,
        publication_key="current",
        defaults={
            "publication_id": publication_id,
            "publication_hash": digest,
            "activation_id": f"fixture:{publication_id}",
        },
    )
    return stored, member, fact


def test_financial_partial_reads_selected_asset_without_cross_blocking_other_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A separate blocked security does not suppress the persisted selected fact."""

    publication, member, fact = _publish_generic_p2_partial(blocked_asset_code=_BLOCKED_ASSET)
    original_query = query_services.query_financial_facts
    queried_assets: list[str] = []

    def _track_query(
        asset_code: str,
        *,
        limit: int = 20,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
        knowledge_cutoff: datetime | None = None,
    ) -> list[dict[str, object]]:
        queried_assets.append(asset_code)
        return original_query(
            asset_code,
            limit=limit,
            end=end,
            fact_pks=fact_pks,
            knowledge_cutoff=knowledge_cutoff,
        )

    monkeypatch.setattr(query_services, "query_financial_facts", _track_query)
    assert publication.published_at is not None
    cutoff = publication.published_at + timedelta(seconds=1)
    selected = query_published_financial_facts(_SELECTED_ASSET, knowledge_cutoff=cutoff)
    blocked = query_published_financial_facts(_BLOCKED_ASSET, knowledge_cutoff=cutoff)

    assert selected["must_not_use_for_decision"] is False
    assert selected["publication_id"] == publication.publication_id
    assert selected["rows"][0]["asset_code"] == _SELECTED_ASSET
    assert selected["rows"][0]["metric_code"] == "revenue"
    assert selected["rows"][0]["value"] == float(fact.value)
    assert member.fact_pk == str(fact.pk)
    assert blocked["rows"] == []
    assert blocked["must_not_use_for_decision"] is True
    assert blocked["blocked_reason"] == _BLOCK_REASON
    assert blocked["scope_block"]["asset_code"] == _BLOCKED_ASSET
    assert queried_assets == [_SELECTED_ASSET]


def test_direct_repository_publish_overlap_should_block_before_fact_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-asset scope block must win over a selected row in direct repo.publish."""

    publication, member, _fact = _publish_generic_p2_partial(blocked_asset_code=_SELECTED_ASSET)
    queried_assets: list[str] = []
    original_query = query_services.query_financial_facts

    def _track_query(
        asset_code: str,
        *,
        limit: int = 20,
        end: date | None = None,
        fact_pks: Sequence[str] | None = None,
        knowledge_cutoff: datetime | None = None,
    ) -> list[dict[str, object]]:
        queried_assets.append(asset_code)
        return original_query(
            asset_code,
            limit=limit,
            end=end,
            fact_pks=fact_pks,
            knowledge_cutoff=knowledge_cutoff,
        )

    monkeypatch.setattr(query_services, "query_financial_facts", _track_query)
    assert publication.published_at is not None
    cutoff = publication.published_at + timedelta(seconds=1)
    result = query_published_financial_facts(_SELECTED_ASSET, knowledge_cutoff=cutoff)

    assert member.natural_key.startswith(f"{_SELECTED_ASSET}:")
    assert result["rows"] == []
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == _BLOCK_REASON
    assert result["scope_block"]["asset_code"] == _SELECTED_ASSET
    assert queried_assets == []
