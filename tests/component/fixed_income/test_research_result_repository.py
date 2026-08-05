"""Component tests for append-only fixed-income research evidence."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.fixed_income.domain.entities import (
    ImmutableResearchResult,
    PublicationInputSeal,
    ResearchPreviewStatus,
)
from apps.fixed_income.infrastructure.models import FixedIncomeResearchResultModel
from apps.fixed_income.infrastructure.repositories import FixedIncomeResearchResultRepository

pytestmark = pytest.mark.django_db


def _record() -> ImmutableResearchResult:
    return ImmutableResearchResult.build(
        result_id="r5-gold-result-v1",
        bond_id="GOLD-2Y-5PCT",
        valuation_at=datetime(2024, 1, 1, 9, tzinfo=UTC),
        settlement_date=date(2024, 1, 1),
        method_version="fixed-income-research-v1",
        status=ResearchPreviewStatus.AVAILABLE,
        payload_json='{"dirty_price":"101.886094674556213"}',
        publication_seals=(
            PublicationInputSeal(
                dataset_key="fixed_income.bond_master",
                publication_key="research",
                publication_id="bond-master-publication",
                policy_version="publication-policy.v1",
                semantic_version="fixed-income-semantics.v1",
                content_hash="a" * 64,
            ),
            PublicationInputSeal(
                dataset_key="fixed_income.government_curve",
                publication_key="research",
                publication_id="curve-publication",
                policy_version="publication-policy.v1",
                semantic_version="fixed-income-semantics.v1",
                content_hash="b" * 64,
            ),
        ),
        blocked_reasons=(),
    )


def test_repository_round_trips_append_only_research_result() -> None:
    repository = FixedIncomeResearchResultRepository()

    stored = repository.add(_record())
    loaded = repository.get(stored.result_id)

    assert loaded == stored
    assert stored.research_only is True
    assert stored.must_not_execute is True
    assert stored.must_not_use_for_decision is True


def test_duplicate_result_identity_is_rejected() -> None:
    repository = FixedIncomeResearchResultRepository()
    record = _record()
    repository.add(record)

    with pytest.raises(ValueError, match="already exists"):
        repository.add(record)


def test_model_rejects_mutation_and_deletion() -> None:
    repository = FixedIncomeResearchResultRepository()
    repository.add(_record())
    model = FixedIncomeResearchResultModel._default_manager.get(result_id="r5-gold-result-v1")
    model.output_hash = "mutated"

    with pytest.raises(ValidationError, match="immutable"):
        model.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        model.delete()


def test_domain_rejects_tampered_payload_or_declared_hash() -> None:
    record = _record()

    with pytest.raises(ValueError, match="output_hash mismatch"):
        replace(record, payload_json='{"dirty_price":"999"}')
    with pytest.raises(ValueError, match="input_hash mismatch"):
        replace(record, input_hash="f" * 64)


def test_repository_rechecks_hashes_after_persisted_payload_tampering() -> None:
    repository = FixedIncomeResearchResultRepository()
    record = repository.add(_record())
    FixedIncomeResearchResultModel._default_manager.filter(result_id=record.result_id).update(
        payload={"dirty_price": "999"}
    )

    with pytest.raises(ValueError, match="output_hash mismatch"):
        repository.get(record.result_id)

    FixedIncomeResearchResultModel._default_manager.filter(result_id=record.result_id).update(
        payload={"dirty_price": "101.886094674556213"},
        input_hash="f" * 64,
    )
    with pytest.raises(ValueError, match="input_hash mismatch"):
        repository.get(record.result_id)


def test_database_rejects_decision_eligible_result_flag() -> None:
    record = _record()
    model = FixedIncomeResearchResultModel(
        result_id="r5-invalid-decision-flag",
        bond_id=record.bond_id,
        valuation_at=record.valuation_at,
        settlement_date=record.settlement_date,
        method_version=record.method_version,
        input_hash=record.input_hash,
        output_hash=record.output_hash,
        status=record.status.value,
        payload={"dirty_price": "101.886094674556213"},
        publication_ids=list(record.publication_ids),
        publication_evidence=[
            {
                "dataset_key": seal.dataset_key,
                "publication_key": seal.publication_key,
                "publication_id": seal.publication_id,
                "policy_version": seal.policy_version,
                "semantic_version": seal.semantic_version,
                "content_hash": seal.content_hash,
            }
            for seal in record.publication_seals
        ],
        blocked_reasons=[],
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=False,
    )

    with pytest.raises(ValidationError, match="must remain research-only"):
        model.save(force_insert=True)
    with pytest.raises(IntegrityError):
        FixedIncomeResearchResultModel._default_manager.bulk_create([model])
