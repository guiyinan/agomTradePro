"""Create empty inactive transition-plan approval ledgers."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed Portfolio inactive approval slice."""

    dependencies = [("portfolio", "0016_transition_plan_contract_family")]

    operations = [
        migrations.CreateModel(
            name="TransitionPlanInactiveApprovalSubjectModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("subject_id", models.CharField(max_length=192)),
                ("subject_version", models.CharField(max_length=192)),
                ("subject_identity_hash", models.CharField(max_length=64, unique=True)),
                ("plan_id", models.CharField(max_length=64)),
                ("plan_version", models.PositiveIntegerField()),
                ("plan_content_hash", models.CharField(max_length=64)),
                ("account_id", models.CharField(max_length=64)),
                ("decision_snapshot_id", models.CharField(max_length=64)),
                ("requested_actor_id", models.CharField(max_length=192)),
                ("requested_actor_user_id", models.PositiveBigIntegerField()),
                ("requested_actor_role", models.CharField(max_length=192)),
                ("requested_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "portfolio_transition_inactive_approval_subject",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["plan_id", "plan_version", "recorded_at"],
                        name="portfolio_tr_ap_subj_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("subject_id", "subject_version"), name="portfolio_tr_ap_subj_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("plan_id", "plan_version"), name="portfolio_tr_ap_subj_plan_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("recorded_at__lt", models.F("valid_until")),
                            ("requested_at", models.F("recorded_at")),
                        ),
                        name="portfolio_tr_ap_subj_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="TransitionPlanInactiveApprovalReceiptModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("schema", models.CharField(max_length=96)),
                ("receipt_id", models.CharField(max_length=192)),
                ("receipt_version", models.CharField(max_length=192)),
                ("receipt_identity_hash", models.CharField(max_length=64, unique=True)),
                ("subject_hash", models.CharField(max_length=64, unique=True)),
                ("subject_id", models.CharField(max_length=192)),
                ("subject_version", models.CharField(max_length=192)),
                ("subject_content_hash", models.CharField(max_length=64)),
                ("plan_id", models.CharField(max_length=64)),
                ("plan_version", models.PositiveIntegerField()),
                ("plan_content_hash", models.CharField(max_length=64)),
                ("account_id", models.CharField(max_length=64)),
                ("decision_snapshot_id", models.CharField(max_length=64)),
                ("requested_actor_id", models.CharField(max_length=192)),
                ("requested_actor_user_id", models.PositiveBigIntegerField()),
                ("requested_actor_role", models.CharField(max_length=192)),
                ("approved_actor_id", models.CharField(max_length=192)),
                ("approved_actor_user_id", models.PositiveBigIntegerField()),
                ("approved_actor_role", models.CharField(max_length=192)),
                ("plan_status_at_issue", models.CharField(max_length=16)),
                ("issued_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subject_record",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval_receipt",
                        to="portfolio.transitionplaninactiveapprovalsubjectmodel",
                    ),
                ),
            ],
            options={
                "db_table": "portfolio_transition_inactive_approval_receipt",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["plan_id", "plan_version", "recorded_at"],
                        name="portfolio_tr_ap_rcpt_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("receipt_id", "receipt_version"), name="portfolio_tr_ap_rcpt_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("plan_id", "plan_version"), name="portfolio_tr_ap_rcpt_plan_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("owner", "portfolio"),
                            ("plan_status_at_issue", "APPROVED"),
                            ("schema", "portfolio-transition-plan-approval-receipt.v1"),
                        ),
                        name="portfolio_tr_ap_rcpt_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("issued_at", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="portfolio_tr_ap_rcpt_clock_ck",
                    ),
                ],
            },
        ),
    ]
