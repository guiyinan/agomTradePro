"""Actual database restrictions and reversible-empty reference-state migration."""

from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import IntegrityError, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from apps.data_center.infrastructure.publication_rollback_models import CanonicalPublicationModel

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = ("data_center", "0106_price_limit_member_codec_policy")
AFTER = ("data_center", "0107_price_limit_reference_publication")


def _values() -> dict[str, object]:
    return {
        "publication_id": uuid4(),
        "dataset_key": "equity.price.limit",
        "publication_key": "price-limit:" + str(uuid4()),
        "policy_version": "fixture",
        "state": "reference_published",
        "selected_source": "tushare",
        "publication_hash": "a" * 64,
        "member_count": 1,
        "published_at": timezone.now(),
        "must_not_use_for_decision": True,
        "blocked_reason": "PRICE_LIMIT_REFERENCE_ONLY",
    }


@pytest.mark.parametrize(
    "changed",
    [
        {"dataset_key": "equity.price.bar"},
        {"must_not_use_for_decision": False},
        {"member_count": 0},
        {"published_at": None},
        {"selected_source": ""},
        {"blocked_reason": ""},
    ],
)
def test_database_refuses_reference_state_without_restrictive_evidence(
    changed: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        CanonicalPublicationModel.objects.create(**{**_values(), **changed})


def test_empty_reverse_forward_and_history_refusal_preserve_constraint_and_rows() -> None:
    initial_targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        MigrationExecutor(connection).migrate([BEFORE])
        MigrationExecutor(connection).migrate([AFTER])
        executor = MigrationExecutor(connection)
        # Only data_center was targeted; other apps retain their applied schema state.
        applied_migration_nodes = list(executor.loader.applied_migrations)
        state = executor.loader.project_state(applied_migration_nodes)
        permission = ("publish_price_limit", "Can publish reference price limits")
        assert (
            permission
            in state.apps.get_model("data_center", "PriceLimitSnapshotFactModel")._meta.permissions
        )
        historical_content_type = state.apps.get_model("contenttypes", "ContentType")
        historical_permission = state.apps.get_model("auth", "Permission")
        target_content_type = historical_content_type.objects.get(
            app_label="data_center",
            model="pricelimitsnapshotfactmodel",
        )
        historical_permission.objects.filter(
            content_type=target_content_type,
            codename="publish_price_limit",
        ).delete()
        assert not historical_permission.objects.filter(
            content_type=target_content_type,
            codename="publish_price_limit",
        ).exists()
        create_permissions(
            global_apps.get_app_config("data_center"),
            verbosity=0,
            interactive=False,
            using=connection.alias,
            apps=state.apps,
        )
        generated_content_type = historical_content_type.objects.get(
            app_label="data_center",
            model="pricelimitsnapshotfactmodel",
        )
        generated_permission = historical_permission.objects.get(
            content_type=generated_content_type,
            codename="publish_price_limit",
        )
        assert generated_permission.name == "Can publish reference price limits"
        migration = import_module(
            "apps.data_center.migrations.0107_price_limit_reference_publication"
        )
        with connection.schema_editor(atomic=False) as schema_editor:
            with pytest.raises(IrreversibleError, match="atomic"):
                migration.preserve_reference_publication_history(state.apps, schema_editor)
        record = CanonicalPublicationModel.objects.create(**_values())
        for lifecycle in ("reference_published", "reference_superseded"):
            assert (
                CanonicalPublicationModel.objects.filter(pk=record.pk).update(state=lifecycle) == 1
            )
            with pytest.raises(IrreversibleError, match="history"):
                MigrationExecutor(connection).migrate([BEFORE])
            assert AFTER in MigrationRecorder(connection).applied_migrations()
            assert CanonicalPublicationModel.objects.get(pk=record.pk).state == lifecycle
            with pytest.raises(IntegrityError), transaction.atomic():
                CanonicalPublicationModel.objects.filter(pk=record.pk).update(
                    must_not_use_for_decision=False
                )
    finally:
        MigrationExecutor(connection).migrate(initial_targets)
