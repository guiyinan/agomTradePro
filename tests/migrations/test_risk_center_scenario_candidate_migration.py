"""Migration evidence for initial maintainable Risk Center candidates."""

from __future__ import annotations

import importlib
from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.risk_center.domain.scenarios import (
    ProbabilitySource,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSetMember,
    ScenarioSetRevision,
    ScenarioSourceType,
    ScenarioType,
    scenario_parameters_from_mapping,
)

MIGRATION_NAME = "0006_seed_initial_scenario_candidates"
MIGRATION_MODULE = "apps.risk_center.migrations.0006_seed_initial_scenario_candidates"


def _assert_revision_hash_is_domain_parseable(revision: object) -> None:
    """Rebuild a persisted revision through strict domain parsing and hash validation."""

    scenario_type = ScenarioType(revision.scenario_type)  # type: ignore[attr-defined]
    parameters = scenario_parameters_from_mapping(
        scenario_type,
        revision.parameters,  # type: ignore[attr-defined]
    )
    ScenarioRevision(
        revision_id=str(revision.revision_id),  # type: ignore[attr-defined]
        scenario_key=str(revision.definition.scenario_key),  # type: ignore[attr-defined]
        version=int(revision.version),  # type: ignore[attr-defined]
        based_on_version=revision.based_on_version,  # type: ignore[attr-defined]
        status=ScenarioRevisionStatus(revision.status),  # type: ignore[attr-defined]
        scenario_type=scenario_type,
        parameters=parameters,
        assumptions=tuple(revision.assumptions),  # type: ignore[attr-defined]
        source_evidence=tuple(revision.source_evidence),  # type: ignore[attr-defined]
        source_type=ScenarioSourceType(revision.source_type),  # type: ignore[attr-defined]
        created_by=str(revision.created_by),  # type: ignore[attr-defined]
        change_reason=str(revision.change_reason),  # type: ignore[attr-defined]
        effective_at=revision.effective_at,  # type: ignore[attr-defined]
        created_at=revision.created_at,  # type: ignore[attr-defined]
        content_hash=str(revision.content_hash),  # type: ignore[attr-defined]
    )


def _assert_set_hash_is_domain_parseable(set_revision: object) -> None:
    """Rebuild a persisted set revision through domain probability/hash validation."""

    members = tuple(
        ScenarioSetMember(
            scenario_revision_id=str(member.scenario_revision_id),
            probability=Decimal(str(member.probability)),
            probability_source=ProbabilitySource(member.probability_source),
            sort_order=int(member.sort_order),
        )
        for member in set_revision.members.order_by("sort_order", "id")  # type: ignore[attr-defined]
    )
    ScenarioSetRevision(
        revision_id=str(set_revision.revision_id),  # type: ignore[attr-defined]
        set_key=str(set_revision.scenario_set.set_key),  # type: ignore[attr-defined]
        version=int(set_revision.version),  # type: ignore[attr-defined]
        status=ScenarioRevisionStatus(set_revision.status),  # type: ignore[attr-defined]
        members=members,
        driver_axes=tuple(set_revision.driver_axes),  # type: ignore[attr-defined]
        created_by=str(set_revision.created_by),  # type: ignore[attr-defined]
        change_reason=str(set_revision.change_reason),  # type: ignore[attr-defined]
        created_at=set_revision.created_at,  # type: ignore[attr-defined]
        effective_from=set_revision.effective_from,  # type: ignore[attr-defined]
        effective_to=set_revision.effective_to,  # type: ignore[attr-defined]
        content_hash=str(set_revision.content_hash),  # type: ignore[attr-defined]
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_initial_scenario_candidates_are_typed_inactive_and_idempotent() -> None:
    """M4 seeds stay candidate-only, parseable, reversible, and duplicate-free."""

    seed_module = importlib.import_module(MIGRATION_MODULE)
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("risk_center", "0005_scenario_write_governance")])
        executor = MigrationExecutor(connection)
        executor.migrate([("risk_center", MIGRATION_NAME)])
        apps = executor.loader.project_state([("risk_center", MIGRATION_NAME)]).apps

        Definition = apps.get_model("risk_center", "StressScenarioDefinitionModel")
        Revision = apps.get_model("risk_center", "StressScenarioRevisionModel")
        ScenarioSet = apps.get_model("risk_center", "ScenarioSetModel")
        SetRevision = apps.get_model("risk_center", "ScenarioSetRevisionModel")
        Activation = apps.get_model("risk_center", "ScenarioActivationModel")

        scenario_keys = tuple(seed_module.ALL_SCENARIO_KEYS)
        set_keys = tuple(seed_module.ALL_SET_KEYS)
        revisions = list(
            Revision.objects.filter(
                definition__scenario_key__in=scenario_keys,
                source_type="seed",
                created_by=seed_module.CREATED_BY,
            ).select_related("definition")
        )
        assert len(revisions) == 10
        assert {item.scenario_type for item in revisions} == {
            "rolling_extreme",
            "parametric_shock",
            "macro_path",
        }
        assert sum(item.scenario_type == "rolling_extreme" for item in revisions) == 1
        assert sum(item.scenario_type == "parametric_shock" for item in revisions) == 1
        assert sum(item.scenario_type == "macro_path" for item in revisions) == 8
        assert all(item.status == "candidate" for item in revisions)
        assert all(item.effective_at is None for item in revisions)

        for revision in revisions:
            assert revision.source_evidence
            assert all(item["observed_at"] is None for item in revision.source_evidence)
            assert all(item["freshness"] == "missing" for item in revision.source_evidence)
            assert all(item["reliability"] == "blocked" for item in revision.source_evidence)
            assert all(
                item["must_not_use_for_decision"] is True for item in revision.source_evidence
            )
            _assert_revision_hash_is_domain_parseable(revision)

        set_revisions = list(
            SetRevision.objects.filter(
                scenario_set__set_key__in=set_keys,
                created_by=seed_module.CREATED_BY,
            )
            .select_related("scenario_set")
            .prefetch_related("members__scenario_revision")
        )
        assert len(set_revisions) == 2
        assert ScenarioSet.objects.filter(set_key__in=set_keys).count() == 2
        assert all(item.status == "candidate" for item in set_revisions)
        assert all(item.effective_from is None for item in set_revisions)
        assert (
            Activation.objects.filter(
                scenario_set_revision_id__in=[item.pk for item in set_revisions]
            ).count()
            == 0
        )
        for set_revision in set_revisions:
            members = list(set_revision.members.all())
            assert len(members) == 4
            assert sum(
                (member.probability for member in members),
                Decimal("0"),
            ) == Decimal("1")
            assert {member.probability_source for member in members} == {"subjective"}
            assert {member.scenario_revision.parameters["probability"] for member in members} == {
                "0.25"
            }
            _assert_set_hash_is_domain_parseable(set_revision)

        counts_before = (
            Definition.objects.filter(scenario_key__in=scenario_keys).count(),
            Revision.objects.filter(
                definition__scenario_key__in=scenario_keys,
                created_by=seed_module.CREATED_BY,
            ).count(),
            ScenarioSet.objects.filter(set_key__in=set_keys).count(),
            SetRevision.objects.filter(
                scenario_set__set_key__in=set_keys,
                created_by=seed_module.CREATED_BY,
            ).count(),
        )
        seed_module.seed_initial_scenario_candidates(apps, object())
        counts_after = (
            Definition.objects.filter(scenario_key__in=scenario_keys).count(),
            Revision.objects.filter(
                definition__scenario_key__in=scenario_keys,
                created_by=seed_module.CREATED_BY,
            ).count(),
            ScenarioSet.objects.filter(set_key__in=set_keys).count(),
            SetRevision.objects.filter(
                scenario_set__set_key__in=set_keys,
                created_by=seed_module.CREATED_BY,
            ).count(),
        )
        assert counts_after == counts_before == (10, 10, 2, 2)

        Definition.objects.create(
            scenario_key="test.unrelated.seed.sentinel",
            name="Unrelated sentinel",
            category="test",
            owner="test",
            status="active",
            description="Must survive reversing the candidate seed migration.",
            legacy_aliases=[],
            created_at=seed_module.CREATED_AT,
        )
        executor = MigrationExecutor(connection)
        executor.migrate([("risk_center", "0005_scenario_write_governance")])
        apps = executor.loader.project_state(
            [("risk_center", "0005_scenario_write_governance")]
        ).apps
        Definition = apps.get_model("risk_center", "StressScenarioDefinitionModel")
        assert Definition.objects.filter(scenario_key="test.unrelated.seed.sentinel").exists()
        assert not Definition.objects.filter(scenario_key__in=scenario_keys).exists()

        executor = MigrationExecutor(connection)
        executor.migrate([("risk_center", MIGRATION_NAME)])
        apps = executor.loader.project_state([("risk_center", MIGRATION_NAME)]).apps
        Revision = apps.get_model("risk_center", "StressScenarioRevisionModel")
        assert (
            Revision.objects.filter(
                definition__scenario_key__in=scenario_keys,
                created_by=seed_module.CREATED_BY,
            ).count()
            == 10
        )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
