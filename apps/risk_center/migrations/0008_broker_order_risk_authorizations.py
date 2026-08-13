"""Create empty Broker order risk authorization ledgers."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed Broker order risk authorization slice."""

    dependencies = [("risk_center", "0007_evidence_operator_spec_approvals")]

    operations = [
        migrations.CreateModel(
            name="BrokerOrderRiskAuthorizationSubjectModel",
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
                ("account_id", models.PositiveBigIntegerField()),
                ("order_id", models.CharField(max_length=36)),
                ("scope_content_hash", models.CharField(max_length=64)),
                ("supersedes_authorization_hash", models.CharField(max_length=64, null=True)),
                ("requested_actor_id", models.CharField(max_length=192)),
                ("requested_actor_kind", models.CharField(max_length=16)),
                ("requested_actor_is_staff", models.BooleanField()),
                ("requested_actor_user_id", models.PositiveBigIntegerField(null=True)),
                ("requested_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "risk_center_broker_order_risk_subject",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["account_id", "order_id", "recorded_at"],
                        name="risk_br_ord_subj_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("subject_id", "subject_version"), name="risk_br_ord_subj_id_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("requested_at", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="risk_br_ord_subj_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("requested_actor_is_staff", True),
                            ("requested_actor_kind", "human"),
                            ("requested_actor_user_id__isnull", False),
                        ),
                        name="risk_br_ord_subj_actor_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BrokerOrderRiskAuthorizationRecordModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("capability", models.CharField(max_length=64)),
                ("permission_cap", models.CharField(max_length=32)),
                ("authorization_id", models.CharField(max_length=192)),
                ("authorization_version", models.CharField(max_length=192)),
                ("authorization_identity_hash", models.CharField(max_length=64, unique=True)),
                ("subject_hash", models.CharField(max_length=64, unique=True)),
                ("account_id", models.PositiveBigIntegerField()),
                ("order_id", models.CharField(max_length=36)),
                ("supersedes_authorization_hash", models.CharField(max_length=64, null=True)),
                ("approved_actor_id", models.CharField(max_length=192)),
                ("approved_actor_kind", models.CharField(max_length=16)),
                ("approved_actor_is_staff", models.BooleanField()),
                ("approved_actor_user_id", models.PositiveBigIntegerField()),
                ("issued_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subject",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authorization_record",
                        to="risk_center.brokerorderriskauthorizationsubjectmodel",
                    ),
                ),
            ],
            options={
                "db_table": "risk_center_broker_order_risk_authorization",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["account_id", "order_id", "recorded_at"],
                        name="risk_br_ord_auth_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("authorization_id", "authorization_version"),
                        name="risk_br_ord_auth_id_uq",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("supersedes_authorization_hash__isnull", False)),
                        fields=("supersedes_authorization_hash",),
                        name="risk_br_ord_auth_next_uq",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("supersedes_authorization_hash__isnull", True)),
                        fields=("account_id", "order_id"),
                        name="risk_br_ord_auth_root_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("capability", "broker_order_risk_authorization"),
                            ("owner", "risk_center"),
                            ("permission_cap", "execution_eligible"),
                        ),
                        name="risk_br_ord_auth_owner_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("issued_at", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="risk_br_ord_auth_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("approved_actor_is_staff", True),
                            ("approved_actor_kind", "human"),
                            ("approved_actor_user_id__isnull", False),
                        ),
                        name="risk_br_ord_auth_actor_ck",
                    ),
                ],
            },
        ),
    ]
