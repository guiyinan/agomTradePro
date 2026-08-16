import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("account", "0051_actor_authority_source_v3_ledgers")]
    operations = [
        migrations.CreateModel(
            name="AccountAuthenticationContextSourceV3AnchorModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("source_id", models.CharField(max_length=192, unique=True)),
                ("root_claim_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField()),
            ],
            options={
                "db_table": "account_auth_context_source_v3_anchor",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="AccountAuthenticationContextSourceV3Model",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=96)),
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=32)),
                ("status", models.CharField(max_length=16)),
                ("must_not_execute", models.BooleanField()),
                ("execution_allowed", models.BooleanField()),
                ("source_id", models.CharField(max_length=192)),
                ("source_version", models.CharField(max_length=192)),
                ("observed_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                (
                    "root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "supersedes_content_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("facts_seal", models.CharField(max_length=64)),
                ("clock_seal", models.CharField(max_length=64)),
                ("chain_seal", models.CharField(max_length=64)),
                ("fixed_authority_seal", models.CharField(max_length=64)),
                ("record_seal", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("recorded_by_service_id", models.CharField(max_length=192)),
                ("recorded_by_role", models.CharField(max_length=192)),
                ("recorded_by_kind", models.CharField(max_length=16)),
                ("recorded_by_is_automated", models.BooleanField()),
                ("recorder_binding_seal", models.CharField(max_length=64)),
                ("ledger_seal", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.JSONField()),
                ("persisted_at", models.DateTimeField()),
                ("principal_id", models.CharField(max_length=192)),
                ("user_id", models.PositiveBigIntegerField()),
                ("actor_id", models.CharField(max_length=192)),
                ("is_authenticated", models.BooleanField()),
                ("authority_state", models.CharField(max_length=16)),
                ("authenticated_at", models.DateTimeField()),
                ("principal_seal", models.CharField(max_length=64)),
                (
                    "anchor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="versions",
                        to="account.accountauthenticationcontextsourcev3anchormodel",
                    ),
                ),
                (
                    "predecessor",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="successor",
                        to="account.accountauthenticationcontextsourcev3model",
                    ),
                ),
            ],
            options={
                "db_table": "account_auth_context_source_v3_ledger",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(fields=["source_id", "recorded_at"], name="acct_auth3_chain_ix")
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_id", "source_version"), name="acct_auth3_source_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("artifact_type", "account_authentication_context_source_v3"),
                            ("execution_allowed", False),
                            ("must_not_execute", True),
                            ("owner", "account"),
                            ("permission", "attestation_only"),
                            ("recorded_by_is_automated", True),
                            ("recorded_by_kind", "service"),
                            ("recorded_by_role", "account_actor_authority_raw_recorder"),
                            ("schema", "account.authentication_context_source.v3"),
                            ("status", "inactive"),
                        ),
                        name="acct_auth3_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("authority_state", "authenticated"), ("is_authenticated", True)
                            ),
                            models.Q(("authority_state", "revoked"), ("is_authenticated", False)),
                            _connector="OR",
                        ),
                        name="acct_auth3_state_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("authenticated_at__lte", models.F("observed_at"))),
                        name="acct_auth3_auth_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("user_id__gt", 0)), name="acct_auth3_user_ck"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("predecessor__isnull", True),
                                ("root_claim_hash__isnull", False),
                                ("supersedes_content_hash__isnull", True),
                            ),
                            models.Q(
                                ("predecessor__isnull", False),
                                ("root_claim_hash__isnull", True),
                                ("supersedes_content_hash__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="acct_auth3_root_xor_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("observed_at__lte", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                            ("persisted_at", models.F("recorded_at")),
                        ),
                        name="acct_auth3_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AccountRbacAuthoritySourceV3AnchorModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("source_id", models.CharField(max_length=192, unique=True)),
                ("root_claim_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField()),
            ],
            options={
                "db_table": "account_rbac_authority_source_v3_anchor",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="AccountRbacAuthoritySourceV3Model",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=96)),
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=32)),
                ("status", models.CharField(max_length=16)),
                ("must_not_execute", models.BooleanField()),
                ("execution_allowed", models.BooleanField()),
                ("source_id", models.CharField(max_length=192)),
                ("source_version", models.CharField(max_length=192)),
                ("observed_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                (
                    "root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "supersedes_content_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("facts_seal", models.CharField(max_length=64)),
                ("clock_seal", models.CharField(max_length=64)),
                ("chain_seal", models.CharField(max_length=64)),
                ("fixed_authority_seal", models.CharField(max_length=64)),
                ("record_seal", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("recorded_by_service_id", models.CharField(max_length=192)),
                ("recorded_by_role", models.CharField(max_length=192)),
                ("recorded_by_kind", models.CharField(max_length=16)),
                ("recorded_by_is_automated", models.BooleanField()),
                ("recorder_binding_seal", models.CharField(max_length=64)),
                ("ledger_seal", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.JSONField()),
                ("persisted_at", models.DateTimeField()),
                ("user_id", models.PositiveBigIntegerField()),
                ("actor_id", models.CharField(max_length=192)),
                ("rbac_role", models.CharField(max_length=32)),
                ("authority_state", models.CharField(max_length=16)),
                ("rbac_seal", models.CharField(max_length=64)),
                (
                    "anchor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="versions",
                        to="account.accountrbacauthoritysourcev3anchormodel",
                    ),
                ),
                (
                    "predecessor",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="successor",
                        to="account.accountrbacauthoritysourcev3model",
                    ),
                ),
            ],
            options={
                "db_table": "account_rbac_authority_source_v3_ledger",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(fields=["source_id", "recorded_at"], name="acct_rbac3_chain_ix")
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_id", "source_version"), name="acct_rbac3_source_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("artifact_type", "account_rbac_authority_source_v3"),
                            ("execution_allowed", False),
                            ("must_not_execute", True),
                            ("owner", "account"),
                            ("permission", "attestation_only"),
                            ("recorded_by_is_automated", True),
                            ("recorded_by_kind", "service"),
                            ("recorded_by_role", "account_actor_authority_raw_recorder"),
                            ("schema", "account.rbac_authority_source.v3"),
                            ("status", "inactive"),
                        ),
                        name="acct_rbac3_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("authority_state__in", ("current", "revoked"))),
                        name="acct_rbac3_state_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "rbac_role__in",
                                (
                                    "admin",
                                    "owner",
                                    "analyst",
                                    "investment_manager",
                                    "trader",
                                    "risk",
                                    "read_only",
                                ),
                            )
                        ),
                        name="acct_rbac3_role_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("user_id__gt", 0)), name="acct_rbac3_user_ck"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("predecessor__isnull", True),
                                ("root_claim_hash__isnull", False),
                                ("supersedes_content_hash__isnull", True),
                            ),
                            models.Q(
                                ("predecessor__isnull", False),
                                ("root_claim_hash__isnull", True),
                                ("supersedes_content_hash__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="acct_rbac3_root_xor_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("observed_at__lte", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                            ("persisted_at", models.F("recorded_at")),
                        ),
                        name="acct_rbac3_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AccountUserAuthoritySourceV3AnchorModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("source_id", models.CharField(max_length=192, unique=True)),
                ("root_claim_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField()),
            ],
            options={
                "db_table": "account_user_authority_source_v3_anchor",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="AccountUserAuthoritySourceV3Model",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=96)),
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=32)),
                ("status", models.CharField(max_length=16)),
                ("must_not_execute", models.BooleanField()),
                ("execution_allowed", models.BooleanField()),
                ("source_id", models.CharField(max_length=192)),
                ("source_version", models.CharField(max_length=192)),
                ("observed_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                (
                    "root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "supersedes_content_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("facts_seal", models.CharField(max_length=64)),
                ("clock_seal", models.CharField(max_length=64)),
                ("chain_seal", models.CharField(max_length=64)),
                ("fixed_authority_seal", models.CharField(max_length=64)),
                ("record_seal", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("recorded_by_service_id", models.CharField(max_length=192)),
                ("recorded_by_role", models.CharField(max_length=192)),
                ("recorded_by_kind", models.CharField(max_length=16)),
                ("recorded_by_is_automated", models.BooleanField()),
                ("recorder_binding_seal", models.CharField(max_length=64)),
                ("ledger_seal", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.JSONField()),
                ("persisted_at", models.DateTimeField()),
                ("user_id", models.PositiveBigIntegerField()),
                ("actor_id", models.CharField(max_length=192)),
                ("is_active", models.BooleanField()),
                ("is_staff", models.BooleanField()),
                ("is_superuser", models.BooleanField()),
                ("authority_state", models.CharField(max_length=16)),
                ("user_seal", models.CharField(max_length=64)),
                (
                    "anchor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="versions",
                        to="account.accountuserauthoritysourcev3anchormodel",
                    ),
                ),
                (
                    "predecessor",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="successor",
                        to="account.accountuserauthoritysourcev3model",
                    ),
                ),
            ],
            options={
                "db_table": "account_user_authority_source_v3_ledger",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(fields=["source_id", "recorded_at"], name="acct_user3_chain_ix")
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_id", "source_version"), name="acct_user3_source_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("artifact_type", "account_user_authority_source_v3"),
                            ("execution_allowed", False),
                            ("must_not_execute", True),
                            ("owner", "account"),
                            ("permission", "attestation_only"),
                            ("recorded_by_is_automated", True),
                            ("recorded_by_kind", "service"),
                            ("recorded_by_role", "account_actor_authority_raw_recorder"),
                            ("schema", "account.user_authority_source.v3"),
                            ("status", "inactive"),
                        ),
                        name="acct_user3_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("authority_state", "current"), ("is_active", True)),
                            models.Q(("authority_state", "deactivated"), ("is_active", False)),
                            _connector="OR",
                        ),
                        name="acct_user3_state_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("user_id__gt", 0)), name="acct_user3_user_ck"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("predecessor__isnull", True),
                                ("root_claim_hash__isnull", False),
                                ("supersedes_content_hash__isnull", True),
                            ),
                            models.Q(
                                ("predecessor__isnull", False),
                                ("root_claim_hash__isnull", True),
                                ("supersedes_content_hash__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="acct_user3_root_xor_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("observed_at__lte", models.F("recorded_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                            ("persisted_at", models.F("recorded_at")),
                        ),
                        name="acct_user3_clock_ck",
                    ),
                ],
            },
        ),
    ]
