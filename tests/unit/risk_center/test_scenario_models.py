"""Database contracts for immutable scenario persistence and activation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.risk_center.application.scenario_dtos import (
    ActivateScenarioSetCommandDTO,
    CreateScenarioRevisionCommandDTO,
)
from apps.risk_center.domain.scenarios import (
    HistoricalWindowParameters,
    ProbabilitySource,
    ScenarioDefinition,
    ScenarioRevisionStatus,
    ScenarioSet,
    ScenarioSetMember,
    ScenarioSetRevision,
    ScenarioSourceType,
    ScenarioType,
)
from apps.risk_center.infrastructure.models import StressScenarioRevisionModel
from apps.risk_center.infrastructure.scenario_repositories import DjangoScenarioRepository

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)


@pytest.mark.django_db
def test_seeded_legacy_alias_resolves_to_a_valid_immutable_revision() -> None:
    repository = DjangoScenarioRepository()

    revision = repository.get_revision("2015_crash")

    assert revision is not None
    assert revision.scenario_key == "historical.cn_equity.2015_crash"
    assert revision.version == 1
    assert revision.source_type is ScenarioSourceType.LEGACY_CODE_MIGRATION
    assert len(revision.content_hash) == 64

    model = StressScenarioRevisionModel._default_manager.get(revision_id=revision.revision_id)
    model.status = "superseded"
    with pytest.raises(ValidationError, match="immutable"):
        model.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        model.delete()


@pytest.mark.django_db
def test_repository_allocates_next_version_and_rejects_stale_base() -> None:
    repository = DjangoScenarioRepository()
    definition = repository.save_definition(
        ScenarioDefinition(
            scenario_key="test.server-versioned",
            name="Server versioned",
            category="test",
            owner="risk_center",
            created_at=NOW,
        )
    )
    parameters = HistoricalWindowParameters(
        start_date=NOW.date(),
        end_date=NOW.date(),
        source="published-test",
        event_description="test window",
    )
    first = repository.append_next_revision(
        CreateScenarioRevisionCommandDTO(
            scenario_key=definition.scenario_key,
            scenario_type=ScenarioType.HISTORICAL_WINDOW,
            parameters=parameters,
            assumptions=("first",),
            source_type=ScenarioSourceType.HUMAN,
            created_by="operator",
            change_reason="first draft",
        )
    )
    second = repository.append_next_revision(
        CreateScenarioRevisionCommandDTO(
            scenario_key=definition.scenario_key,
            scenario_type=ScenarioType.HISTORICAL_WINDOW,
            parameters=parameters,
            assumptions=("second",),
            source_type=ScenarioSourceType.HUMAN,
            created_by="operator",
            change_reason="second draft",
            based_on_version=1,
        )
    )

    assert (first.version, second.version, second.based_on_version) == (1, 2, 1)
    with pytest.raises(ValueError, match="version conflict"):
        repository.append_next_revision(
            CreateScenarioRevisionCommandDTO(
                scenario_key=definition.scenario_key,
                scenario_type=ScenarioType.HISTORICAL_WINDOW,
                parameters=parameters,
                assumptions=("stale",),
                source_type=ScenarioSourceType.HUMAN,
                created_by="operator",
                change_reason="stale draft",
                based_on_version=1,
            )
        )


@pytest.mark.django_db
def test_activation_is_single_scope_and_optimistically_locked() -> None:
    repository = DjangoScenarioRepository()
    scenario_revision = repository.get_revision("2020_covid")
    assert scenario_revision is not None
    repository.save_scenario_set(
        ScenarioSet(
            set_key="test.activation-set",
            name="Activation set",
            purpose="portfolio_stress",
            owner="risk_center",
        )
    )
    set_revision = repository.save_set_revision(
        ScenarioSetRevision(
            revision_id="0cc10ac4-f391-4c34-b49d-6292d52b1197",
            set_key="test.activation-set",
            version=1,
            status=ScenarioRevisionStatus.APPROVED,
            members=(
                ScenarioSetMember(
                    scenario_revision_id=scenario_revision.revision_id,
                    probability=Decimal("1"),
                    probability_source=ProbabilitySource.SUBJECTIVE,
                    sort_order=0,
                ),
            ),
            driver_axes=("historical",),
            created_by="operator",
            change_reason="activation test",
            created_at=NOW,
        )
    )
    first = repository.activate_set_revision(
        ActivateScenarioSetCommandDTO(
            environment="test",
            purpose="portfolio_stress",
            scenario_set_revision_id=set_revision.revision_id,
            activated_by="operator",
            reason="activate",
            expected_active_activation_id=None,
        )
    )

    assert (
        repository.get_active_set_revision(environment="test", purpose="portfolio_stress")
        == set_revision
    )
    with pytest.raises(ValueError, match="activation conflict"):
        repository.activate_set_revision(
            ActivateScenarioSetCommandDTO(
                environment="test",
                purpose="portfolio_stress",
                scenario_set_revision_id=set_revision.revision_id,
                activated_by="operator",
                reason="stale activation",
                expected_active_activation_id=None,
            )
        )
    assert first.previous_activation_id is None


@pytest.mark.django_db
def test_database_rejects_duplicate_definition_version() -> None:
    seeded = StressScenarioRevisionModel._default_manager.select_related("definition").first()
    assert seeded is not None
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StressScenarioRevisionModel._default_manager.bulk_create(
                [
                    StressScenarioRevisionModel(
                        definition=seeded.definition,
                        version=seeded.version,
                        status="approved",
                        scenario_type=seeded.scenario_type,
                        parameters=seeded.parameters,
                        assumptions=seeded.assumptions,
                        source_evidence=seeded.source_evidence,
                        source_type="seed",
                        content_hash=seeded.content_hash,
                        created_by="test",
                        change_reason="duplicate",
                    )
                ]
            )
