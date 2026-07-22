from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("events", "0004_event_replay_run")]

    operations = [
        migrations.AddField(model_name="storedeventmodel", name="aggregate_id", field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.AddField(model_name="storedeventmodel", name="aggregate_type", field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.AddField(model_name="storedeventmodel", name="aggregate_version", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="storedeventmodel", name="effective_at", field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="storedeventmodel", name="schema_version", field=models.CharField(default="v1", max_length=16)),
        migrations.AddConstraint(
            model_name="storedeventmodel",
            constraint=models.UniqueConstraint(
                condition=models.Q(("aggregate_version__isnull", False)),
                fields=("aggregate_type", "aggregate_id", "aggregate_version"),
                name="stored_event_aggregate_version_uniq",
            ),
        ),
    ]

