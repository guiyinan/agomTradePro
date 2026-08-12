"""Create empty approved Evidence operator spec lifecycle ledgers."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed operator spec approval and activation slice."""

    dependencies = [("research", "0026_evidence_ledgers")]

    operations = [
        migrations.CreateModel(
            name="EvidenceOperatorSpecApprovalReceiptModel",
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
                ("approval_id", models.CharField(max_length=192)),
                ("approval_version", models.CharField(max_length=192)),
                ("owner_record_id", models.CharField(max_length=192)),
                ("owner_record_version", models.CharField(max_length=192)),
                ("owner_record_hash", models.CharField(max_length=64)),
                ("operator_id", models.CharField(max_length=192)),
                ("operator_version", models.CharField(max_length=192)),
                ("definition_hash", models.CharField(max_length=64)),
                (
                    "supersedes_activation_hash",
                    models.CharField(max_length=64, null=True),
                ),
                ("approved_by", models.CharField(max_length=192)),
                ("issued_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                (
                    "receipt_content_hash",
                    models.CharField(max_length=64, unique=True),
                ),
                (
                    "ledger_header_hash",
                    models.CharField(max_length=64, unique=True),
                ),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "research_evidence_operator_spec_approval",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("approval_id", "approval_version"),
                        name="res_ev_op_auth_identity_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("owner_record_id", "owner_record_version"),
                        name="res_ev_op_auth_owner_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(issued_at__lte=models.F("recorded_at"))
                            & models.Q(recorded_at__lt=models.F("valid_until"))
                        ),
                        name="res_ev_op_auth_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ActivatedEvidenceOperatorSpecModel",
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
                ("definition_hash", models.CharField(max_length=64, unique=True)),
                (
                    "supersedes_activation_hash",
                    models.CharField(db_index=True, max_length=64, null=True),
                ),
                ("activated_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                (
                    "ledger_header_hash",
                    models.CharField(max_length=64, unique=True),
                ),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "approval",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="activated_operator_spec",
                        to="research.evidenceoperatorspecapprovalreceiptmodel",
                    ),
                ),
            ],
            options={
                "db_table": "research_activated_evidence_operator_spec",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["operator_id", "recorded_at"],
                        name="res_ev_op_active_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("operator_id", "operator_version"),
                        name="res_ev_op_active_identity_uq",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(supersedes_activation_hash__isnull=True),
                        fields=("operator_id",),
                        name="res_ev_op_active_root_uq",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(supersedes_activation_hash__isnull=False),
                        fields=("supersedes_activation_hash",),
                        name="res_ev_op_active_child_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(activated_at__lte=models.F("recorded_at"))
                            & models.Q(recorded_at__lt=models.F("valid_until"))
                        ),
                        name="res_ev_op_active_clock_ck",
                    ),
                ],
            },
        ),
    ]
