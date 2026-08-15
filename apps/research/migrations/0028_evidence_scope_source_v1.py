"""Create the zero-seed Evidence scope-source v1 ledger."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only dormant persistence for the strict scope-source contract."""

    dependencies = [("research", "0027_evidence_operator_spec_lifecycle")]

    operations = [
        migrations.CreateModel(
            name="EvidenceScopeSourceV1Model",
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
                ("source_id", models.CharField(max_length=192)),
                ("source_version", models.CharField(max_length=192)),
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
                ("root_claim_hash", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "supersedes_content_hash",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "predecessor",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="successor",
                        to="research.evidencescopesourcev1model",
                    ),
                ),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("source_owner", models.CharField(max_length=192)),
                ("source_artifact_type", models.CharField(max_length=192)),
                ("source_schema", models.CharField(max_length=192)),
                ("permission", models.CharField(max_length=32)),
                ("must_not_execute", models.BooleanField()),
                ("execution_allowed", models.BooleanField()),
                ("canonical_payload", models.JSONField()),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "research_evidence_scope_source_v1",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["source_id", "recorded_at"],
                        name="res_ev_scope_src_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_id", "source_version"),
                        name="res_ev_scope_src_identity_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("root_claim_hash",),
                        name="res_ev_scope_src_root_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("supersedes_content_hash",),
                        name="res_ev_scope_src_pred_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(recorded_at__lt=models.F("valid_until"))
                            & models.Q(persisted_at=models.F("recorded_at"))
                        ),
                        name="res_ev_scope_src_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(status__in=("active", "revoked")),
                        name="res_ev_scope_src_status_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(source_owner="research")
                            & models.Q(source_artifact_type="evidence_scope_source")
                            & models.Q(source_schema="research.evidence_scope_source.v1")
                            & models.Q(permission="read_only")
                            & models.Q(must_not_execute=True)
                            & models.Q(execution_allowed=False)
                        ),
                        name="res_ev_scope_src_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            (
                                models.Q(root_claim_hash__isnull=False)
                                & models.Q(supersedes_content_hash__isnull=True)
                                & models.Q(predecessor__isnull=True)
                            )
                            | (
                                models.Q(root_claim_hash__isnull=True)
                                & models.Q(supersedes_content_hash__isnull=False)
                                & models.Q(predecessor__isnull=False)
                            )
                        ),
                        name="res_ev_scope_src_chain_ck",
                    ),
                ],
            },
        ),
    ]
