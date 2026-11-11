"""Create explicit Account service-write grant and revocation ledgers."""

import django.db.models.deletion
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_GRANT_TABLE = "account_sim_corp_action_write_grant_ledger"
_REVOCATION_TABLE = "account_sim_corp_action_write_grant_revocation_ledger"
_GUARD_NAMES = (
    (_GRANT_TABLE, "acct_scawg_grant_guard", "acct_scawg_grant_immutable_trg"),
    (_REVOCATION_TABLE, "acct_scawg_revoke_guard", "acct_scawg_revoke_immut_trg"),
)


def install_append_only_guards(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Reject raw PostgreSQL updates and deletes from both immutable ledgers."""

    del apps
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    for table_name, function_name, trigger_name in _GUARD_NAMES:
        table = quote(table_name)
        function = quote(function_name)
        trigger = quote(trigger_name)
        schema_editor.execute(f"""
            CREATE FUNCTION {function}() RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog
            AS $grant_guard$
            BEGIN
                RAISE EXCEPTION 'simulated corporate-action write grant is append-only'
                    USING ERRCODE = '23514';
            END;
            $grant_guard$
            """)
        schema_editor.execute(f"""
            CREATE TRIGGER {trigger}
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}()
            """)
        schema_editor.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}")


def remove_append_only_guards(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Remove only the PostgreSQL guards when reversing this schema migration."""

    del apps
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    for table_name, function_name, trigger_name in _GUARD_NAMES:
        schema_editor.execute(f"DROP TRIGGER {quote(trigger_name)} ON {quote(table_name)}")
        schema_editor.execute(f"DROP FUNCTION {quote(function_name)}()")


class Migration(migrations.Migration):
    dependencies = [("account", "0069_protect_v1_provenance_receipts")]

    operations = [
        migrations.CreateModel(
            name="SimulatedCorporateActionWriteGrantModel",
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
                ("artifact_type", models.CharField(max_length=96)),
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=64)),
                ("service_actor_id", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=16)),
                ("identity_hash", models.CharField(max_length=64)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.JSONField()),
                ("grant_id", models.CharField(max_length=192)),
                ("grant_version", models.CharField(max_length=192)),
                ("account_namespace", models.CharField(max_length=32)),
                ("account_id", models.CharField(max_length=192)),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("tenant_id", models.CharField(max_length=192)),
                ("owner_id", models.CharField(max_length=192)),
                ("account_source_id", models.CharField(max_length=192)),
                ("account_source_version", models.CharField(max_length=192)),
                ("account_source_content_hash", models.CharField(max_length=64)),
                ("policy_id", models.CharField(max_length=192)),
                ("policy_version", models.CharField(max_length=192)),
                ("policy_content_hash", models.CharField(max_length=64)),
                ("consent_evidence_id", models.CharField(max_length=192)),
                ("consent_evidence_version", models.CharField(max_length=192)),
                ("consent_evidence_hash", models.CharField(max_length=64)),
                ("issuer_evidence_id", models.CharField(max_length=192)),
                ("issuer_evidence_version", models.CharField(max_length=192)),
                ("issuer_evidence_hash", models.CharField(max_length=64)),
                ("consented_at", models.DateTimeField()),
                ("issued_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
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
                        to="account.simulatedcorporateactionwritegrantmodel",
                    ),
                ),
            ],
            options={
                "db_table": _GRANT_TABLE,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="SimulatedCorporateActionWriteGrantRevocationModel",
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
                ("artifact_type", models.CharField(max_length=96)),
                ("schema", models.CharField(max_length=96)),
                ("permission", models.CharField(max_length=64)),
                ("service_actor_id", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=16)),
                ("identity_hash", models.CharField(max_length=64)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("canonical_payload", models.JSONField()),
                ("revocation_id", models.CharField(max_length=192)),
                ("revocation_version", models.CharField(max_length=192)),
                ("grant_id", models.CharField(max_length=192)),
                ("grant_version", models.CharField(max_length=192)),
                ("grant_identity_hash", models.CharField(max_length=64)),
                ("grant_content_hash", models.CharField(max_length=64, unique=True)),
                ("revocation_evidence_id", models.CharField(max_length=192)),
                ("revocation_evidence_version", models.CharField(max_length=192)),
                ("revocation_evidence_hash", models.CharField(max_length=64)),
                ("issuer_evidence_id", models.CharField(max_length=192)),
                ("issuer_evidence_version", models.CharField(max_length=192)),
                ("issuer_evidence_hash", models.CharField(max_length=64)),
                ("revoked_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                (
                    "target_grant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="simulated_corporate_action_write_grant_revocation",
                        to="account.simulatedcorporateactionwritegrantmodel",
                    ),
                ),
            ],
            options={
                "db_table": _REVOCATION_TABLE,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AddIndex(
            model_name="simulatedcorporateactionwritegrantmodel",
            index=models.Index(fields=["grant_id", "recorded_at"], name="acct_scawg_grant_time_ix"),
        ),
        migrations.AddIndex(
            model_name="simulatedcorporateactionwritegrantmodel",
            index=models.Index(
                fields=["account_id", "recorded_at"], name="acct_scawg_account_time_ix"
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantmodel",
            constraint=models.UniqueConstraint(
                fields=("grant_id", "grant_version"), name="acct_scawg_version_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantmodel",
            constraint=models.UniqueConstraint(
                condition=models.Q(("predecessor__isnull", True)),
                fields=("grant_id",),
                name="acct_scawg_root_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantmodel",
            constraint=models.UniqueConstraint(
                fields=("supersedes_content_hash",), name="acct_scawg_predecessor_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("account_namespace", "simulated"),
                    ("artifact_type", "simulated_corporate_action_write_grant"),
                    ("owner", "account"),
                    ("permission", "simulated_corporate_action_stage_write"),
                    ("schema", "account.simulated_corporate_action_write_grant.v1"),
                    ("service_actor_id", "simulated-trading"),
                    ("status", "active"),
                ),
                name="acct_scawg_fixed_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("consented_at__lte", models.F("issued_at")),
                    ("issued_at__lte", models.F("recorded_at")),
                    ("recorded_at__lt", models.F("valid_until")),
                ),
                name="acct_scawg_clock_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("supersedes_content_hash__isnull", True), ("predecessor__isnull", True)
                    ),
                    models.Q(
                        ("supersedes_content_hash__isnull", False), ("predecessor__isnull", False)
                    ),
                    _connector="OR",
                ),
                name="acct_scawg_chain_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="simulatedcorporateactionwritegrantrevocationmodel",
            index=models.Index(
                fields=["grant_content_hash", "recorded_at"], name="acct_scawgr_grant_time_ix"
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantrevocationmodel",
            constraint=models.UniqueConstraint(
                fields=("revocation_id", "revocation_version"),
                name="acct_scawgr_version_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantrevocationmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("artifact_type", "simulated_corporate_action_write_grant_revocation"),
                    ("owner", "account"),
                    ("permission", "simulated_corporate_action_stage_write"),
                    (
                        "schema",
                        "account.simulated_corporate_action_write_grant.revocation.v1",
                    ),
                    ("service_actor_id", "simulated-trading"),
                    ("status", "revoked"),
                ),
                name="acct_scawgr_fixed_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedcorporateactionwritegrantrevocationmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("revoked_at__lte", models.F("recorded_at"))),
                name="acct_scawgr_clock_ck",
            ),
        ),
        migrations.RunPython(
            install_append_only_guards,
            remove_append_only_guards,
            hints={
                "model_name": "simulatedcorporateactionwritegrantmodel",
            },
        ),
    ]
