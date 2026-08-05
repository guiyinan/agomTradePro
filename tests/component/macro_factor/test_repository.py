"""Component coverage for append-only R3 research records."""

import pytest
from django.core.exceptions import ValidationError

from apps.macro_factor.infrastructure.models import MacroFactorResearchResultModel
from apps.macro_factor.infrastructure.repositories import MacroFactorResearchResultRepository
from tests.unit.macro_factor.factories import complete_result

pytestmark = pytest.mark.django_db


def _record():  # type: ignore[no-untyped-def]
    return complete_result().to_record()


def test_repository_round_trips_reproducible_research_result() -> None:
    repository = MacroFactorResearchResultRepository()

    stored = repository.add(_record())
    loaded = repository.get(stored.result_id)

    assert loaded == stored
    assert stored.factor_version == "macro-growth-v1"
    assert stored.research_only is True
    assert stored.must_not_use_for_decision is True


def test_duplicate_result_identity_is_rejected() -> None:
    repository = MacroFactorResearchResultRepository()
    record = _record()
    repository.add(record)

    with pytest.raises(ValueError, match="already exists"):
        repository.add(record)


def test_model_rejects_mutation_and_deletion() -> None:
    repository = MacroFactorResearchResultRepository()
    repository.add(_record())
    model = MacroFactorResearchResultModel._default_manager.get(
        result_id="macro-factor-result-growth-v1"
    )
    model.content_hash = "7" * 64

    with pytest.raises(ValidationError, match="immutable"):
        model.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        model.delete()
