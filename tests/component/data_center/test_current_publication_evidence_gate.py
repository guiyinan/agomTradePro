"""Current ports enforce frozen evidence against actual ORM facts and policies."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.application.public_published_queries import (
    get_current_publication,
    get_publication_as_of,
)
from apps.data_center.application.query_services import query_published_valuation_facts
from apps.data_center.application.valuation_publication import PublishValuationBatchUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication
from apps.data_center.domain.entities import ValuationFact
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import ValuationFactModel
from apps.data_center.infrastructure.publication_models import PublicationMemberModel
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("scope", ["dataset", "publication_key"])
def test_current_gate_rejects_repository_publication_outside_requested_scope(
    monkeypatch, scope
) -> None:
    from apps.data_center.application import query_services

    policy, publication, _member = _published_snapshot()

    class WrongScopeRepository(CanonicalPublicationRepository):
        def get_current(self, dataset_key: str, publication_key: str) -> CanonicalPublication:
            """Return a valid publication belonging to a different request scope."""

            return publication

    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", WrongScopeRepository
    )
    dataset_key = "equity.quote.snapshot" if scope == "dataset" else policy.dataset.value
    publication_key = "different-scope" if scope == "publication_key" else "current"
    gate = query_services._publication_gate(dataset_key, publication_key)
    assert gate is not None
    assert gate["must_not_use_for_decision"] is True
    assert gate["blocked_reason"] == "publication_scope_mismatch"
    assert (
        CanonicalPublicationRepository().get_current(policy.dataset.value, "current") == publication
    )


def _published_snapshot():
    now = datetime.now(UTC)
    observed = now - timedelta(seconds=30)
    received = now - timedelta(seconds=5)
    policy = PublicationPolicy(
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
        minimum_coverage_ratio=0.99,
        allow_partial=True,
        conflict_action="quarantine",
        required_evidence=(
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "source_record_id",
            "raw_payload_hash",
            "raw_payload_scope",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="2",
    )
    policies = PublicationPolicyRepository()
    policies.save(policy)
    DatasetContractModel.objects.create(
        dataset_key=policy.dataset.value,
        contract_version="1.0",
        schema_version="1.0",
        owner="data-platform",
        frequency="daily",
        decision_critical=True,
        fields=[{"name": "observed_at", "value_type": "datetime"}],
        freshness_seconds=3600,
    )
    fact = ValuationFact(
        asset_code="000001.SZ",
        val_date=observed.date(),
        pe_ttm=12.5,
        source="tencent",
        observed_at=observed,
        available_at=received,
        fetched_at=received,
        raw_payload_hash="a" * 64,
        source_record_id="controlled-response-" + uuid4().hex,
        extra={
            "raw_payload_scope": "batch_response_body",
            "availability_basis": "response_completed_utc",
        },
    )
    facts = ValuationFactRepository()
    assert facts.bulk_upsert([fact]) == 1
    publications = CanonicalPublicationRepository()
    published = PublishValuationBatchUseCase(
        fact_repository=facts,
        publication_repository=publications,
        policy_repository=policies,
    ).execute([fact], provider_name="tencent", published_at=now)
    assert published is not None
    member = publications.list_members(published.publication_id)[0]
    return policy, published, member


def test_current_port_serves_exact_fact_only_with_complete_frozen_evidence() -> None:
    policy, publication, member = _published_snapshot()
    result = query_published_valuation_facts("000001.SZ")
    assert result["must_not_use_for_decision"] is False
    assert result["publication_id"] == publication.publication_id
    assert result["rows"][0]["pe_ttm"] == 12.5
    assert member.raw_payload_hash != member.fact_content_hash
    assert (
        get_current_publication(policy.dataset.value, "current")["policy_version"]
        == policy.identity
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"pe_ttm": 99},
        {"raw_payload_hash": "b" * 64},
        {"source_record_id": "rewritten"},
        {"available_at": None},
        {"fetched_at": datetime(2026, 9, 1, tzinfo=UTC)},
    ],
)
def test_current_port_blocks_fact_drift_without_rewriting_frozen_history(changes) -> None:
    policy, publication, member = _published_snapshot()
    ValuationFactModel.objects.filter(pk=member.fact_pk).update(**changes)
    result = query_published_valuation_facts("000001.SZ")
    assert result["rows"] == []
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "publication_member_fact_changed"
    metadata = get_current_publication(policy.dataset.value, "current")
    assert metadata["must_not_use_for_decision"] is True
    assert CanonicalPublicationRepository().list_members(publication.publication_id) == [member]
    historical = get_publication_as_of(policy.dataset.value, "current", publication.published_at)
    assert historical["publication_hash"] == publication.publication_hash


def test_current_port_blocks_policy_upgrade_until_publication_is_rebuilt() -> None:
    policy, publication, _member = _published_snapshot()
    PublicationPolicyRepository().save(replace(policy, policy_version="3"))
    result = query_published_valuation_facts("000001.SZ")
    assert result["rows"] == []
    assert result["blocked_reason"] == "publication_policy_changed"
    historical = get_publication_as_of(policy.dataset.value, "current", publication.published_at)
    assert historical["policy_version"] == policy.identity


def test_current_port_blocks_missing_fact_and_tampered_frozen_metadata() -> None:
    _policy, _publication, member = _published_snapshot()
    PublicationMemberModel.objects.filter(member_id=member.member_id).update(
        source_record_id="tampered"
    )
    result = query_published_valuation_facts("000001.SZ")
    assert result["rows"] == []
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "publication_member_evidence_missing"
    ValuationFactModel.objects.filter(pk=member.fact_pk).delete()
    result = query_published_valuation_facts("000001.SZ")
    assert result["rows"] == []
    assert result["blocked_reason"] == "publication_member_evidence_missing"
