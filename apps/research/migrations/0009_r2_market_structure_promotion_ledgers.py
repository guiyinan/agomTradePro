# Generated manually for schema-only R2 promotion ledgers.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0008_r6_qualification_ledgers"),
    ]

    operations = [
        migrations.CreateModel(
            name="R2MarketStructurePromotionPolicyModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("policy_id", models.CharField(max_length=200)),
                ("policy_version", models.CharField(max_length=100)),
                ("scope_id", models.CharField(db_index=True, max_length=200)),
                ("scope_content_hash", models.CharField(max_length=64)),
                ("registered_at", models.DateTimeField(db_index=True)),
                ("active_from", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("ledger_receipt_hash", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.TextField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("research_only", models.BooleanField(default=True)),
                ("structure_description_only", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "research_r2_ms_promotion_policy",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("policy_id", "policy_version"),
                        name="research_r2_ms_policy_identity_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("research_only", True),
                            ("structure_description_only", True),
                            ("must_not_use_for_decision", True),
                            ("must_not_execute", True),
                        ),
                        name="research_r2_ms_policy_safety",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("registered_at__lte", models.F("active_from")),
                            ("active_from__lt", models.F("valid_until")),
                        ),
                        name="research_r2_ms_policy_clocks",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="R2MarketStructurePromotionDecisionModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("decision_id", models.CharField(max_length=200)),
                ("decision_version", models.CharField(max_length=100)),
                ("scope_id", models.CharField(db_index=True, max_length=200)),
                ("scope_content_hash", models.CharField(max_length=64)),
                ("policy_id", models.CharField(max_length=200)),
                ("policy_version", models.CharField(max_length=100)),
                ("policy_content_hash", models.CharField(max_length=64)),
                ("evidence_key", models.CharField(max_length=128)),
                ("evidence_version", models.PositiveIntegerField()),
                ("evidence_content_hash", models.CharField(max_length=64)),
                ("authorization_id", models.CharField(max_length=200)),
                ("authorization_version", models.CharField(max_length=100)),
                ("authorization_content_hash", models.CharField(max_length=64, unique=True)),
                ("outcome", models.CharField(max_length=16)),
                ("decided_at", models.DateTimeField(db_index=True)),
                ("semantic_recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("ledger_receipt_hash", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.TextField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("research_only", models.BooleanField(default=True)),
                ("structure_description_only", models.BooleanField(default=True)),
                ("must_not_use_for_decision", models.BooleanField(default=True)),
                ("must_not_execute", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "research_r2_ms_promotion_decision",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("decision_id", "decision_version"),
                        name="research_r2_ms_decision_identity_unique",
                    ),
                    models.UniqueConstraint(
                        fields=("authorization_id", "authorization_version"),
                        name="research_r2_ms_decision_auth_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("research_only", True),
                            ("structure_description_only", True),
                            ("must_not_use_for_decision", True),
                            ("must_not_execute", True),
                        ),
                        name="research_r2_ms_decision_safety",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("decided_at__lte", models.F("semantic_recorded_at")),
                            ("semantic_recorded_at__lt", models.F("valid_until")),
                        ),
                        name="research_r2_ms_decision_clocks",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="R2MarketStructurePromotionLifecycleEventModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("event_id", models.CharField(max_length=200)),
                ("event_version", models.CharField(max_length=100)),
                ("scope_id", models.CharField(db_index=True, max_length=200)),
                ("scope_content_hash", models.CharField(max_length=64)),
                ("stream_id", models.CharField(db_index=True, max_length=300)),
                ("sequence", models.PositiveIntegerField()),
                ("event_type", models.CharField(max_length=16)),
                ("decision_id", models.CharField(max_length=200)),
                ("decision_version", models.CharField(max_length=100)),
                ("decision_content_hash", models.CharField(max_length=64)),
                ("rollback_target_id", models.CharField(blank=True, max_length=200)),
                ("rollback_target_version", models.CharField(blank=True, max_length=100)),
                ("rollback_target_content_hash", models.CharField(blank=True, max_length=64)),
                ("authorization_id", models.CharField(max_length=200)),
                ("authorization_version", models.CharField(max_length=100)),
                ("authorization_content_hash", models.CharField(max_length=64, unique=True)),
                ("previous_event_hash", models.CharField(blank=True, max_length=64)),
                ("occurred_at", models.DateTimeField(db_index=True)),
                ("semantic_recorded_at", models.DateTimeField(db_index=True)),
                ("ledger_recorded_at", models.DateTimeField(db_index=True)),
                ("ledger_receipt_hash", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.TextField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "research_r2_ms_promotion_lifecycle",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event_id", "event_version"),
                        name="research_r2_ms_event_identity_unique",
                    ),
                    models.UniqueConstraint(
                        fields=("stream_id", "sequence"),
                        name="research_r2_ms_event_sequence_unique",
                    ),
                    models.UniqueConstraint(
                        fields=("authorization_id", "authorization_version"),
                        name="research_r2_ms_event_auth_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("occurred_at__lte", models.F("semantic_recorded_at"))),
                        name="research_r2_ms_event_clocks",
                    ),
                ],
            },
        ),
    ]
