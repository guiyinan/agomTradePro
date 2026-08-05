"""Migration evidence for the unseeded Sector-owned R1 template slice."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_sector_industry_template_migration_is_unseeded_and_research_only() -> None:
    """Create only append-only schema and enforce non-decision flags."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("sector", "0002_sectorpreferenceconfigmodel")])
        executor = MigrationExecutor(connection)
        executor.migrate([("sector", "0003_industry_operating_templates")])
        apps = executor.loader.project_state([("sector", "0003_industry_operating_templates")]).apps
        Template = apps.get_model("sector", "IndustryOperatingTemplateVersionModel")
        Evidence = apps.get_model("sector", "IndustryTemplateRunEvidenceModel")

        assert Template.objects.count() == 0
        assert Evidence.objects.count() == 0
        lifecycle_choices = {
            value for value, _label in Template._meta.get_field("lifecycle").choices
        }
        assert lifecycle_choices == {"active", "invalidated", "retired"}

        as_of_time = datetime(2025, 1, 1, tzinfo=UTC)
        Template.objects.create(
            template_code="CALLER_TEMPLATE",
            template_version=1,
            industry_code="CALLER_INDUSTRY",
            name="Caller template",
            methodology_ref="governance://caller-template/v1",
            effective_at=as_of_time,
            lifecycle="active",
            content_hash="a" * 64,
            payload={"caller": "supplied"},
        )
        Evidence.objects.create(
            run_key="CALLER_RUN",
            run_version=1,
            template_code="CALLER_TEMPLATE",
            template_version=1,
            template_content_hash="a" * 64,
            as_of_time=as_of_time,
            status="blocked",
            content_hash="b" * 64,
            payload={"status": "blocked"},
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            Evidence.objects.filter(run_key="CALLER_RUN").update(must_not_use_for_decision=False)
        with pytest.raises(IntegrityError), transaction.atomic():
            Template.objects.filter(template_code="CALLER_TEMPLATE").update(research_only=False)
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
