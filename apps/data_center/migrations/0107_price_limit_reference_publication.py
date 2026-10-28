"""Keep reference publication separate from decision-qualified publication."""

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps


def preserve_reference_publication_history(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Refuse reversal before changing any state or constraint with history present."""
    connection = schema_editor.connection
    if not connection.in_atomic_block:
        raise IrreversibleError("Reference publication reversal requires an atomic transaction.")
    model = apps.get_model("data_center", "CanonicalPublicationModel")
    if connection.vendor == "postgresql":
        table = schema_editor.quote_name(model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
    if (
        model._base_manager.using(connection.alias)
        .filter(state__in=["reference_published", "reference_superseded"])
        .exists()
    ):
        raise IrreversibleError("Cannot remove reference publication states with history present.")


class Migration(migrations.Migration):
    """Add the explicit restricted state and publisher permission, without grants."""

    atomic = True
    dependencies = [("data_center", "0106_price_limit_member_codec_policy")]
    operations = [
        migrations.AlterModelOptions(
            name="pricelimitsnapshotfactmodel",
            options={
                "base_manager_name": "objects",
                "ordering": ["-recorded_at", "snapshot_id"],
                "permissions": [("publish_price_limit", "Can publish reference price limits")],
            },
        ),
        migrations.AlterField(
            model_name="canonicalpublicationmodel",
            name="state",
            field=models.CharField(
                choices=[
                    ("candidate", "candidate"),
                    ("published", "published"),
                    ("superseded", "superseded"),
                    ("blocked", "blocked"),
                    ("reference_published", "reference_published"),
                    ("reference_superseded", "reference_superseded"),
                ],
                default="candidate",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="canonicalpublicationmodel",
            constraint=models.CheckConstraint(
                condition=~models.Q(state__in=["reference_published", "reference_superseded"])
                | (
                    models.Q(
                        dataset_key="equity.price.limit",
                        must_not_use_for_decision=True,
                        member_count=1,
                        published_at__isnull=False,
                    )
                    & ~models.Q(selected_source="")
                    & ~models.Q(blocked_reason="")
                ),
                name="dc_publication_reference_restricted",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop, reverse_code=preserve_reference_publication_history
        ),
    ]
