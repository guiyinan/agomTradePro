"""Create the zero-seed Evidence scope-source observation ledger."""

import django.db.models
from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only persistence for the dormant observation DTO boundary."""

    dependencies = [("research", "0028_evidence_scope_source_v1")]

    operations = [
        migrations.CreateModel(
            name="EvidenceScopeSourceV1ObservationModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("observation_id", models.CharField(max_length=192)),
                ("observation_version", models.CharField(max_length=192)),
                ("owner_id", models.CharField(max_length=192)),
                ("tenant_id", models.CharField(max_length=192)),
                ("account_id", models.CharField(max_length=192)),
                ("actor_id", models.CharField(max_length=192)),
                ("artifact_owner", models.CharField(max_length=192)),
                ("artifact_type", models.CharField(max_length=192)),
                ("artifact_id", models.CharField(max_length=192)),
                ("artifact_version", models.CharField(max_length=192)),
                ("artifact_content_hash", models.CharField(db_index=True, max_length=64)),
                ("status", models.CharField(max_length=16)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "research_evidence_scope_source_v1_observation",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["observation_id", "recorded_at"],
                        name="res_ev_scope_obs_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("observation_id", "observation_version"),
                        name="res_ev_scope_obs_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(status__in=("active", "revoked")),
                        name="res_ev_scope_obs_status_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(artifact_owner="research"),
                        name="res_ev_scope_obs_artifact_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(recorded_at__lt=django.db.models.F("valid_until")),
                        name="res_ev_scope_obs_clock_ck",
                    ),
                ],
            },
        ),
    ]
