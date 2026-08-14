"""Create empty planning-policy activation subject and record ledgers."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema-only, zero-seed planning-policy activation persistence."""

    dependencies = [("portfolio", "0018_planning_policy_definition")]

    operations = [
        migrations.CreateModel(
            name="PortfolioPlanningPolicyActivationSubjectModel",
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
                ("subject_identity_hash", models.CharField(max_length=64, unique=True)),
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("definition_identity_hash", models.CharField(max_length=64)),
                ("definition_content_hash", models.CharField(max_length=64)),
                ("definition_recorded_at", models.DateTimeField()),
                ("requested_actor_id", models.CharField(max_length=192)),
                ("requested_actor_user_id", models.PositiveBigIntegerField()),
                ("requested_actor_role", models.CharField(max_length=192)),
                ("requested_actor_kind", models.CharField(max_length=16)),
                ("requested_actor_is_staff", models.BooleanField()),
                ("requested_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("supersedes_activation_hash", models.CharField(max_length=64, null=True)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_planning_policy_activation_subject",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["policy_id", "requested_at"],
                        name="port_pol_act_sub_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("subject_id", "subject_version"),
                        name="portfolio_plan_pol_act_sub_id_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("requested_at", models.F("recorded_at")))
                            & models.Q(("persisted_at", models.F("recorded_at")))
                            & models.Q(("definition_recorded_at__lte", models.F("requested_at")))
                            & models.Q(("requested_at__lt", models.F("valid_until")))
                            & models.Q(("requested_actor_kind", "human"))
                            & models.Q(("requested_actor_is_staff", True))
                        ),
                        name="portfolio_plan_pol_act_sub_seal_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PortfolioPlanningPolicyActivationModel",
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
                (
                    "subject_record",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="activation_record",
                        to="portfolio.portfolioplanningpolicyactivationsubjectmodel",
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("capability", models.CharField(max_length=64)),
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=64)),
                ("activation_id", models.CharField(max_length=192)),
                ("activation_version", models.CharField(max_length=192)),
                (
                    "activation_identity_hash",
                    models.CharField(max_length=64, unique=True),
                ),
                ("subject_id", models.CharField(max_length=192)),
                ("subject_version", models.CharField(max_length=192)),
                ("subject_content_hash", models.CharField(max_length=64, unique=True)),
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("definition_identity_hash", models.CharField(max_length=64)),
                ("definition_content_hash", models.CharField(max_length=64)),
                ("requested_actor_id", models.CharField(max_length=192)),
                ("requested_actor_user_id", models.PositiveBigIntegerField()),
                ("requested_actor_role", models.CharField(max_length=192)),
                ("approved_actor_id", models.CharField(max_length=192)),
                ("approved_actor_user_id", models.PositiveBigIntegerField()),
                ("approved_actor_role", models.CharField(max_length=192)),
                ("approved_actor_kind", models.CharField(max_length=16)),
                ("approved_actor_is_staff", models.BooleanField()),
                ("issued_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("predecessor_hash", models.CharField(max_length=64, null=True, unique=True)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("persisted_at", models.DateTimeField()),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_planning_policy_activation",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["policy_id", "issued_at"],
                        name="port_pol_act_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("activation_id", "activation_version"),
                        name="portfolio_plan_pol_act_id_uq",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("predecessor_hash__isnull", True)),
                        fields=("policy_id",),
                        name="portfolio_plan_pol_act_root_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("owner", "portfolio"))
                            & models.Q(("capability", "planning_policy_activation"))
                            & models.Q(("schema", "portfolio-planning-policy-activation.v1"))
                            & models.Q(("permission", "policy_configuration_only"))
                            & models.Q(("issued_at", models.F("recorded_at")))
                            & models.Q(("persisted_at", models.F("recorded_at")))
                            & models.Q(("issued_at__lt", models.F("valid_until")))
                            & models.Q(("approved_actor_kind", "human"))
                            & models.Q(("approved_actor_is_staff", True))
                        ),
                        name="portfolio_plan_pol_act_seal_ck",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(("approved_actor_id", models.F("requested_actor_id"))),
                        name="portfolio_plan_pol_act_actor_sep_ck",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(
                            (
                                "approved_actor_user_id",
                                models.F("requested_actor_user_id"),
                            )
                        ),
                        name="portfolio_plan_pol_act_user_sep_ck",
                    ),
                ],
            },
        ),
    ]
