"""Create empty append-only Research Evidence ledgers."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed Evidence M1 persistence slice."""

    dependencies = [("research", "0025_r7_analogy_path_owner")]

    operations = [
        migrations.CreateModel(
            name="EvidenceOperatorSpecModel",
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
                ("operator_id", models.CharField(max_length=192)),
                ("operator_version", models.CharField(max_length=192)),
                ("research_family", models.CharField(db_index=True, max_length=192)),
                ("output_artifact_type", models.CharField(max_length=192)),
                ("claim_kind", models.CharField(max_length=32)),
                ("method_kind", models.CharField(max_length=32)),
                ("activated_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "research_evidence_operator_spec",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["research_family", "recorded_at"],
                        name="res_ev_op_family_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("operator_id", "operator_version"),
                        name="res_ev_op_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(activated_at__lte=models.F("recorded_at"))
                            & models.Q(recorded_at__lt=models.F("valid_until"))
                        ),
                        name="res_ev_op_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EvidenceTrackRecordModel",
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
                ("snapshot_id", models.CharField(max_length=192)),
                ("snapshot_version", models.CharField(max_length=192)),
                ("artifact_owner", models.CharField(max_length=192)),
                ("artifact_type", models.CharField(max_length=192)),
                ("artifact_id", models.CharField(max_length=192)),
                ("artifact_version", models.CharField(max_length=192)),
                ("artifact_hash", models.CharField(db_index=True, max_length=64)),
                ("target", models.CharField(max_length=192)),
                ("horizon", models.CharField(max_length=192)),
                ("sample_policy_id", models.CharField(max_length=192)),
                ("sample_policy_version", models.CharField(max_length=192)),
                ("evaluated_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "research_evidence_track_record",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["artifact_id", "artifact_version", "recorded_at"],
                        name="res_ev_track_art_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("snapshot_id", "snapshot_version"),
                        name="res_ev_track_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(evaluated_at__lte=models.F("recorded_at"))
                            & models.Q(recorded_at__lt=models.F("valid_until"))
                        ),
                        name="res_ev_track_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EvidenceEnvelopeModel",
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
                ("output_owner", models.CharField(max_length=192)),
                ("output_artifact_type", models.CharField(max_length=192)),
                ("output_artifact_id", models.CharField(max_length=192)),
                ("output_artifact_version", models.CharField(max_length=192)),
                ("output_artifact_hash", models.CharField(db_index=True, max_length=64)),
                ("operator_spec_id", models.CharField(max_length=192)),
                ("operator_spec_version", models.CharField(max_length=192)),
                ("operator_spec_hash", models.CharField(max_length=64)),
                ("claim_kind", models.CharField(max_length=32)),
                ("method_kind", models.CharField(max_length=32)),
                ("research_family", models.CharField(db_index=True, max_length=192)),
                ("governance_state", models.CharField(max_length=32)),
                ("permission", models.CharField(max_length=32)),
                ("evaluated_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("must_not_use_for_decision", models.BooleanField()),
                ("must_not_execute", models.BooleanField()),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "research_evidence_envelope",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=[
                            "output_artifact_id",
                            "output_artifact_version",
                            "recorded_at",
                        ],
                        name="res_ev_env_output_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "output_owner",
                            "output_artifact_type",
                            "output_artifact_id",
                            "output_artifact_version",
                        ),
                        name="res_ev_env_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(evaluated_at__lte=models.F("recorded_at"))
                            & models.Q(recorded_at__lt=models.F("valid_until"))
                        ),
                        name="res_ev_env_clock_ck",
                    ),
                ],
            },
        ),
    ]
