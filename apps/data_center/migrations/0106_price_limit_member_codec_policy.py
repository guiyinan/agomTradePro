"""Bind the price-limit nullable member codec to its exact versioned policy."""

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps

_PRICE_LIMIT_CODEC = "price-limit-nullable-member-v1"


def preserve_price_limit_codec_history(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Refuse to restore the old constraint while any price-limit policy remains."""

    connection = schema_editor.connection
    if not connection.in_atomic_block:
        raise IrreversibleError(
            "Price-limit policy reversal requires an atomic schema transaction."
        )
    model = apps.get_model("data_center", "DatasetPublicationPolicyModel")
    if connection.vendor == "postgresql":
        table = schema_editor.quote_name(model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
    if (
        model._base_manager.using(connection.alias)
        .filter(member_codec_version=_PRICE_LIMIT_CODEC)
        .exists()
    ):
        raise IrreversibleError(
            "Cannot restore the old publication policy constraint while price-limit codec history exists."
        )


class Migration(migrations.Migration):
    """Allow the one exact price-limit codec without changing Calendar policy rules."""

    atomic = True

    dependencies = [("data_center", "0105_price_limit_snapshot")]

    operations = [
        migrations.RemoveConstraint(
            model_name="datasetpublicationpolicymodel",
            name="dc_dataset_policy_member_codec_valid",
        ),
        migrations.AddConstraint(
            model_name="datasetpublicationpolicymodel",
            constraint=models.CheckConstraint(
                condition=models.Q(member_codec_version__isnull=True)
                | (
                    models.Q(member_codec_version="calendar-nullable-member-v1")
                    & ~models.Q(policy_version="legacy")
                )
                | (
                    models.Q(member_codec_version=_PRICE_LIMIT_CODEC)
                    & models.Q(dataset_key="equity.price.limit")
                    & ~models.Q(policy_version="legacy")
                ),
                name="dc_dataset_policy_member_codec_valid",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=preserve_price_limit_codec_history,
        ),
    ]
