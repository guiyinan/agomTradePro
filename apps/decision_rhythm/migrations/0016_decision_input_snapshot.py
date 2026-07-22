from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("decision_rhythm", "0015_transfer_transition_plan_owner")]

    operations = [
        migrations.CreateModel(
            name="DecisionInputSnapshotModel",
            fields=[
                ("snapshot_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("schema_version", models.CharField(default="v1", max_length=16)),
                ("as_of_time", models.DateTimeField(db_index=True)),
                ("state_hash", models.CharField(max_length=64, unique=True)),
                ("pit_manifest_id", models.CharField(db_index=True, max_length=64)),
                ("components", models.JSONField(default=dict)),
                ("portfolio_snapshot_id", models.CharField(max_length=64)),
                ("config_version", models.CharField(max_length=64)),
                ("strategy_version", models.CharField(max_length=64)),
                ("prompt_version", models.CharField(blank=True, max_length=64)),
                ("freshness", models.JSONField(default=dict)),
                ("quality", models.JSONField(default=dict)),
                ("must_not_use", models.BooleanField(db_index=True, default=False)),
                ("missing_components", models.JSONField(default=list)),
                ("creation_reason", models.CharField(blank=True, max_length=255)),
                ("correlation_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("caller", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "decision_input_snapshot",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["as_of_time", "must_not_use"],
                        name="decision_in_as_of_t_0f30f6_idx",
                    )
                ],
            },
        )
    ]
