"""Component tests for append-only fixed-income research evidence."""

from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError

from apps.fixed_income.domain.entities import ImmutableResearchResult, ResearchPreviewStatus
from apps.fixed_income.infrastructure.models import FixedIncomeResearchResultModel
from apps.fixed_income.infrastructure.repositories import FixedIncomeResearchResultRepository

pytestmark = pytest.mark.django_db


def _record() -> ImmutableResearchResult:
    return ImmutableResearchResult(
        result_id="r5-gold-result-v1",
        bond_id="GOLD-2Y-5PCT",
        valuation_at=datetime(2024, 1, 1, 9, tzinfo=UTC),
        settlement_date=date(2024, 1, 1),
        method_version="fixed-income-research-v1",
        input_hash="c" * 64,
        output_hash="d" * 64,
        status=ResearchPreviewStatus.AVAILABLE,
        payload_json='{"dirty_price":"101.886094674556213"}',
        publication_ids=("bond-master-publication", "curve-publication"),
        blocked_reasons=(),
        research_only=True,
        must_not_execute=True,
    )


def test_repository_round_trips_append_only_research_result() -> None:
    repository = FixedIncomeResearchResultRepository()

    stored = repository.add(_record())
    loaded = repository.get(stored.result_id)

    assert loaded == stored
    assert stored.research_only is True
    assert stored.must_not_execute is True


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
