"""Create empty Evidence operator specification approval ledgers."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed Risk Center approval provider slice."""

    dependencies = [("risk_center", "0006_seed_initial_scenario_candidates")]

    operations = [
        migrations.CreateModel(
            name="EvidenceOperatorSpecApprovalSubjectModel",
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
                ("subject_id", models.CharField(max_length=192)),
                ("subject_version", models.CharField(max_length=192)),
                (
                    "subject_identity_hash",
                    models.CharField(max_length=64, unique=True),
                ),
                ("operator_id", models.CharField(max_length=192)),
                ("operator_version", models.CharField(max_length=192)),
                ("definition_hash", models.CharField(max_length=64, unique=True)),
                (
                    "supersedes_activation_hash",
                    models.CharField(max_length=64, null=True),
                ),
                ("requested_actor_id", models.CharField(max_length=192)),
                ("requested_actor_kind", models.CharField(max_length=16)),
                ("requested_actor_is_staff", models.BooleanField()),
                ("requested_actor_user_id", models.PositiveBigIntegerField(null=True)),
                ("requested_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                (
                    "ledger_header_hash",
                    models.CharField(max_length=64, unique=True),
                ),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "risk_center_evidence_operator_spec_subject",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["operator_id", "operator_version", "recorded_at"],
                        name="risk_ev_op_subj_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("subject_id", "subject_version"),
                        name="risk_ev_op_subj_identity_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("operator_id", "operator_version"),
                        name="risk_ev_op_subj_operator_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(requested_at__lte=models.F("recorded_at"))
                            & models.Q(recorded_at__lt=models.F("valid_until"))
                        ),
                        name="risk_ev_op_subj_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                requested_actor_kind="human",
                                requested_actor_user_id__isnull=False,
                            )
                            | models.Q(
                                requested_actor_kind__in=("ai", "service"),
                                requested_actor_is_staff=False,
                                requested_actor_user_id__isnull=True,
                            )
                        ),
                        name="risk_ev_op_subj_actor_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EvidenceOperatorSpecApprovalRecordModel",
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
                ("owner", models.CharField(max_length=32)),
                ("capability", models.CharField(max_length=64)),
                ("approval_id", models.CharField(max_length=192)),
                ("approval_version", models.CharField(max_length=192)),
                (
                    "approval_identity_hash",
                    models.CharField(max_length=64, unique=True),
                ),
                ("subject_hash", models.CharField(max_length=64, unique=True)),
                ("operator_id", models.CharField(max_length=192)),
                ("operator_version", models.CharField(max_length=192)),
                ("definition_hash", models.CharField(max_length=64, unique=True)),
                (
                    "supersedes_activation_hash",
                    models.CharField(max_length=64, null=True),
                ),
                ("approved_actor_id", models.CharField(max_length=192)),
                ("approved_actor_kind", models.CharField(max_length=16)),
                ("approved_actor_is_staff", models.BooleanField()),
                ("approved_actor_user_id", models.PositiveBigIntegerField()),
                ("issued_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                (
                    "ledger_header_hash",
                    models.CharField(max_length=64, unique=True),
                ),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subject",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval_record",
                        to="risk_center.evidenceoperatorspecapprovalsubjectmodel",
                    ),
                ),
            ],
            options={
                "db_table": "risk_center_evidence_operator_spec_approval",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["operator_id", "operator_version", "recorded_at"],
                        name="risk_ev_op_appr_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("approval_id", "approval_version"),
                        name="risk_ev_op_appr_identity_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(owner="risk_center")
                            & models.Q(capability="evidence_operator_spec_activation")
                        ),
                        name="risk_ev_op_appr_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(issued_at=models.F("recorded_at"))
                            & models.Q(recorded_at__lt=models.F("valid_until"))
                        ),
                        name="risk_ev_op_appr_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            approved_actor_kind="human",
                            approved_actor_is_staff=True,
                            approved_actor_user_id__isnull=False,
                        ),
                        name="risk_ev_op_appr_actor_ck",
                    ),
                ],
            },
        ),
    ]
