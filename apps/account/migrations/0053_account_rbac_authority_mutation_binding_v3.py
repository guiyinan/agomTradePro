import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0052_account_actor_authority_raw_source_v3_ledgers"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountRbacAuthorityMutationBindingV3Model",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("mutation_id", models.CharField(max_length=192, unique=True)),
                ("mutation_kind", models.CharField(max_length=32)),
                ("source_id", models.CharField(max_length=192)),
                ("source_version", models.CharField(max_length=192)),
                ("old_authority_state", models.CharField(blank=True, max_length=16, null=True)),
                ("new_authority_state", models.CharField(max_length=16)),
                ("old_rbac_role", models.CharField(blank=True, max_length=32, null=True)),
                ("new_rbac_role", models.CharField(max_length=32)),
                ("old_profile_id", models.CharField(blank=True, max_length=192, null=True)),
                ("old_profile_version", models.CharField(blank=True, max_length=192, null=True)),
                (
                    "old_profile_content_hash",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "old_profile_identity_hash",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                ("old_profile_observed_at", models.DateTimeField(blank=True, null=True)),
                ("old_subject_actor_id", models.CharField(blank=True, max_length=192, null=True)),
                ("old_user_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("old_subject_seal", models.CharField(blank=True, max_length=64, null=True)),
                ("profile_id", models.CharField(max_length=192)),
                ("profile_version", models.CharField(max_length=192)),
                ("profile_content_hash", models.CharField(max_length=64)),
                ("profile_identity_hash", models.CharField(max_length=64)),
                ("profile_observed_at", models.DateTimeField()),
                ("subject_actor_id", models.CharField(max_length=192)),
                ("user_id", models.PositiveBigIntegerField()),
                ("subject_seal", models.CharField(max_length=64)),
                ("operator_principal_id", models.CharField(max_length=192)),
                ("operator_user_id", models.PositiveBigIntegerField()),
                ("operator_actor_id", models.CharField(max_length=192)),
                ("operator_is_authenticated", models.BooleanField()),
                ("operator_is_active", models.BooleanField()),
                ("operator_is_staff", models.BooleanField()),
                ("operator_is_superuser", models.BooleanField()),
                ("operator_rbac_role", models.CharField(max_length=32)),
                ("operator_authentication_source_id", models.CharField(max_length=192)),
                ("operator_authentication_source_version", models.CharField(max_length=192)),
                ("operator_authentication_source_content_hash", models.CharField(max_length=64)),
                ("operator_user_source_id", models.CharField(max_length=192)),
                ("operator_user_source_version", models.CharField(max_length=192)),
                ("operator_user_source_content_hash", models.CharField(max_length=64)),
                ("operator_rbac_source_id", models.CharField(max_length=192)),
                ("operator_rbac_source_version", models.CharField(max_length=192)),
                ("operator_rbac_source_content_hash", models.CharField(max_length=64)),
                ("operator_observed_at", models.DateTimeField()),
                ("operator_valid_until", models.DateTimeField()),
                ("operator_identity_hash", models.CharField(max_length=64)),
                ("operator_authority_hash", models.CharField(max_length=64)),
                ("issuer_service_id", models.CharField(max_length=192)),
                ("issuer_role", models.CharField(max_length=192)),
                ("issuer_kind", models.CharField(max_length=16)),
                ("issuer_is_automated", models.BooleanField()),
                ("issuer_identity_hash", models.CharField(max_length=64)),
                ("authority_source_identity_hash", models.CharField(max_length=64)),
                ("authority_source_content_hash", models.CharField(max_length=64)),
                ("authority_source_record_seal", models.CharField(max_length=64)),
                ("observed_at", models.DateTimeField()),
                ("issued_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                (
                    "binding_root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "binding_supersedes_content_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "source_root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "source_supersedes_content_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("transition_seal", models.CharField(max_length=64)),
                ("operator_seal", models.CharField(max_length=64)),
                ("issuer_seal", models.CharField(max_length=64)),
                ("source_binding_seal", models.CharField(max_length=64)),
                ("clock_seal", models.CharField(max_length=64)),
                ("binding_chain_seal", models.CharField(max_length=64)),
                ("authority_source_chain_seal", models.CharField(max_length=64)),
                ("fixed_authority_seal", models.CharField(max_length=64)),
                ("record_seal", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_seal", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.JSONField()),
                ("persisted_at", models.DateTimeField()),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=96)),
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=32)),
                ("status", models.CharField(max_length=16)),
                ("must_not_execute", models.BooleanField()),
                ("execution_allowed", models.BooleanField()),
            ],
            options={
                "db_table": "account_rbac_mutation_binding_v3_ledger",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="AccountRbacAuthorityMutationEpochV3AnchorModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("epoch_id", models.CharField(max_length=192, unique=True)),
                ("target_user_id", models.PositiveBigIntegerField()),
                ("subject_actor_id", models.CharField(max_length=192)),
                ("source_id", models.CharField(max_length=192, unique=True)),
                ("epoch_sequence", models.PositiveBigIntegerField()),
                ("opened_at", models.DateTimeField()),
                (
                    "previous_epoch_content_hash",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "terminal_authority_source_content_hash",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "terminal_mutation_binding_content_hash",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                ("root_claim_hash", models.CharField(max_length=64, unique=True)),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.JSONField()),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "account_rbac_mutation_epoch_v3_anchor",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="AccountRbacAuthorityProfileV3AnchorModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("profile_id", models.CharField(max_length=192, unique=True)),
                ("user_id", models.PositiveBigIntegerField()),
                ("subject_actor_id", models.CharField(max_length=192)),
                ("root_claim_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField()),
            ],
            options={
                "db_table": "account_rbac_profile_v3_anchor",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="AccountRbacAuthorityProfileV3VersionModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("profile_id", models.CharField(max_length=192)),
                ("profile_version", models.CharField(max_length=192)),
                ("profile_content_hash", models.CharField(max_length=64)),
                ("user_id", models.PositiveBigIntegerField()),
                ("subject_actor_id", models.CharField(max_length=192)),
                ("rbac_role", models.CharField(max_length=32)),
                ("observed_at", models.DateTimeField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                (
                    "root_claim_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                (
                    "supersedes_content_hash",
                    models.CharField(blank=True, max_length=64, null=True, unique=True),
                ),
                ("record_seal", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.JSONField()),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "account_rbac_profile_v3_version",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AddField(
            model_name="accountrbacauthoritymutationbindingv3model",
            name="authority_source",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="mutation_binding_v3",
                to="account.accountrbacauthoritysourcev3model",
            ),
        ),
        migrations.AddField(
            model_name="accountrbacauthoritymutationbindingv3model",
            name="predecessor",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="successor",
                to="account.accountrbacauthoritymutationbindingv3model",
            ),
        ),
        migrations.AddField(
            model_name="accountrbacauthoritymutationepochv3anchormodel",
            name="previous_epoch",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="next_epoch",
                to="account.accountrbacauthoritymutationepochv3anchormodel",
            ),
        ),
        migrations.AddField(
            model_name="accountrbacauthoritymutationbindingv3model",
            name="epoch",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bindings",
                to="account.accountrbacauthoritymutationepochv3anchormodel",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthorityprofilev3anchormodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("user_id__gt", 0)), name="acct_rbac_prof_anchor_user_ck"
            ),
        ),
        migrations.AddField(
            model_name="accountrbacauthorityprofilev3versionmodel",
            name="anchor",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="versions",
                to="account.accountrbacauthorityprofilev3anchormodel",
            ),
        ),
        migrations.AddField(
            model_name="accountrbacauthorityprofilev3versionmodel",
            name="predecessor",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="successor",
                to="account.accountrbacauthorityprofilev3versionmodel",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationepochv3anchormodel",
            constraint=models.UniqueConstraint(
                fields=("target_user_id", "epoch_sequence"), name="acct_rbac_mut_epoch_user_seq_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationepochv3anchormodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("target_user_id__gt", 0)), name="acct_rbac_mut_epoch_user_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationepochv3anchormodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("epoch_sequence", 1),
                        ("previous_epoch__isnull", True),
                        ("previous_epoch_content_hash__isnull", True),
                        ("terminal_authority_source_content_hash__isnull", True),
                        ("terminal_mutation_binding_content_hash__isnull", True),
                    ),
                    models.Q(
                        ("epoch_sequence__gt", 1),
                        ("previous_epoch__isnull", False),
                        ("previous_epoch_content_hash__isnull", False),
                        ("terminal_authority_source_content_hash__isnull", False),
                        ("terminal_mutation_binding_content_hash__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="acct_rbac_mut_epoch_root_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationepochv3anchormodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("persisted_at", models.F("opened_at"))),
                name="acct_rbac_mut_epoch_clock_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="accountrbacauthoritymutationbindingv3model",
            index=models.Index(fields=["source_id", "recorded_at"], name="acct_rbac_mut_chain_ix"),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.UniqueConstraint(
                fields=("source_id", "source_version"), name="acct_rbac_mut_source_version_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(("user_id__gt", 0)), name="acct_rbac_mut_user_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(("operator_user_id__gt", 0)),
                name="acct_rbac_mut_operator_user_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("artifact_type", "account_rbac_authority_mutation_binding_v3"),
                    ("execution_allowed", False),
                    ("must_not_execute", True),
                    ("owner", "account"),
                    ("permission", "attestation_only"),
                    ("schema", "account.rbac_authority_mutation_binding.v3"),
                    ("status", "inactive"),
                ),
                name="acct_rbac_mut_fixed_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("mutation_kind__in", ("bootstrap", "role_change", "revoke", "reactivate"))
                ),
                name="acct_rbac_mut_kind_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(("new_authority_state__in", ("current", "revoked"))),
                name="acct_rbac_mut_new_state_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "new_rbac_role__in",
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
                name="acct_rbac_mut_new_role_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("old_authority_state__isnull", True),
                    ("old_authority_state__in", ("current", "revoked")),
                    _connector="OR",
                ),
                name="acct_rbac_mut_old_state_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("issuer_is_automated", True),
                    ("issuer_kind", "service"),
                    ("issuer_role", "account_rbac_authority_mutation_issuer"),
                ),
                name="acct_rbac_mut_issuer_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("operator_is_active", True),
                    ("operator_is_authenticated", True),
                    ("operator_is_staff", True),
                    ("operator_rbac_role", "admin"),
                ),
                name="acct_rbac_mut_operator_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("binding_root_claim_hash__isnull", False),
                        ("binding_supersedes_content_hash__isnull", True),
                        ("mutation_kind", "bootstrap"),
                        ("old_authority_state__isnull", True),
                        ("old_profile_id__isnull", True),
                        ("old_rbac_role__isnull", True),
                        ("predecessor__isnull", True),
                    ),
                    models.Q(
                        ("binding_root_claim_hash__isnull", True),
                        ("binding_supersedes_content_hash__isnull", False),
                        ("mutation_kind__in", ("role_change", "revoke")),
                        ("old_authority_state", "current"),
                        ("old_profile_id__isnull", False),
                        ("old_rbac_role__isnull", False),
                        ("predecessor__isnull", False),
                    ),
                    models.Q(
                        ("binding_root_claim_hash__isnull", False),
                        ("binding_supersedes_content_hash__isnull", True),
                        ("mutation_kind", "reactivate"),
                        ("old_authority_state", "revoked"),
                        ("old_profile_id__isnull", False),
                        ("old_rbac_role__isnull", False),
                        ("predecessor__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="acct_rbac_mut_transition_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("source_root_claim_hash__isnull", False),
                        ("source_supersedes_content_hash__isnull", True),
                    ),
                    models.Q(
                        ("source_root_claim_hash__isnull", True),
                        ("source_supersedes_content_hash__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="acct_rbac_mut_source_chain_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthoritymutationbindingv3model",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("observed_at__lte", models.F("issued_at")),
                    ("issued_at__lte", models.F("recorded_at")),
                    ("recorded_at__lt", models.F("valid_until")),
                    ("persisted_at", models.F("recorded_at")),
                    ("operator_observed_at__lte", models.F("observed_at")),
                    ("profile_observed_at__lte", models.F("observed_at")),
                ),
                name="acct_rbac_mut_clock_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="accountrbacauthorityprofilev3versionmodel",
            index=models.Index(
                fields=["profile_id", "observed_at"], name="acct_rbac_prof_chain_ix"
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthorityprofilev3versionmodel",
            constraint=models.UniqueConstraint(
                fields=("profile_id", "profile_version"), name="acct_rbac_prof_version_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthorityprofilev3versionmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("user_id__gt", 0)), name="acct_rbac_prof_user_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthorityprofilev3versionmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("persisted_at", models.F("observed_at"))),
                name="acct_rbac_prof_clock_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthorityprofilev3versionmodel",
            constraint=models.CheckConstraint(
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
                name="acct_rbac_prof_root_xor_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="accountrbacauthorityprofilev3versionmodel",
            constraint=models.CheckConstraint(
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
                name="acct_rbac_prof_role_ck",
            ),
        ),
    ]
