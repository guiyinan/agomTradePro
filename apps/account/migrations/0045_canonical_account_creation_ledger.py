import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("account", "0044_account_owner_assignment_evidence_v2_ledger")]

    operations = [
        migrations.CreateModel(
            name="CanonicalAccountCreationAllocationModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=64)),
                ("schema", models.CharField(max_length=64)),
                ("allocation_id", models.CharField(max_length=192)),
                ("allocation_version", models.CharField(max_length=192)),
                ("canonical_account_namespace", models.CharField(max_length=192)),
                ("canonical_account_id", models.CharField(max_length=192)),
                ("requested_row_user_id", models.PositiveBigIntegerField()),
                ("requested_raw_account_type", models.CharField(max_length=192)),
                ("intended_underlying_unified_account_namespace", models.CharField(max_length=192)),
                ("request_fingerprint_hash", models.CharField(max_length=64)),
                ("requester_actor_id", models.CharField(max_length=192)),
                ("requester_user_id", models.PositiveBigIntegerField()),
                ("requester_role", models.CharField(max_length=192)),
                ("requester_kind", models.CharField(max_length=16)),
                ("requester_is_authenticated", models.BooleanField()),
                ("allocated_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("recorded_service_id", models.CharField(max_length=192)),
                ("recorded_role", models.CharField(max_length=192)),
                ("recorded_kind", models.CharField(max_length=16)),
                ("recorded_is_automated", models.BooleanField()),
                ("intended_purpose", models.CharField(max_length=64)),
                ("permission", models.CharField(max_length=32)),
                ("status", models.CharField(max_length=16)),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("requester_binding_seal", models.CharField(max_length=64)),
                ("recorder_binding_seal", models.CharField(max_length=64)),
                ("fixed_authority_seal", models.CharField(max_length=64)),
                ("record_seal", models.CharField(max_length=64, unique=True)),
                ("ledger_seal", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "canonical_account_creation_allocation_ledger",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("allocation_id", "allocation_version"),
                        name="acct_create_alloc_id_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("canonical_account_namespace", "canonical_account_id"),
                        name="acct_create_alloc_acct_uq",
                    ),
                    models.UniqueConstraint(
                        fields=(
                            "requester_actor_id",
                            "requester_user_id",
                            "request_fingerprint_hash",
                        ),
                        name="acct_create_alloc_req_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            artifact_type="canonical_account_creation_allocation",
                            canonical_account_namespace="account",
                            intended_purpose="simulated_account_create",
                            intended_underlying_unified_account_namespace="simulated-account-row",
                            owner="account",
                            permission="identity_allocation_only",
                            recorded_is_automated=True,
                            recorded_kind="service",
                            recorded_role="canonical_account_identity_allocator",
                            requester_is_authenticated=True,
                            requester_kind="human",
                            requester_role="account_creator",
                            schema="canonical-account-creation-allocation.v1",
                            status="inactive",
                        ),
                        name="acct_create_alloc_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            allocated_at__lt=models.F("valid_until"),
                            persisted_at=models.F("allocated_at"),
                            requested_row_user_id=models.F("requester_user_id"),
                        ),
                        name="acct_create_alloc_clock_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CanonicalAccountCreationBindingModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("allocation_content_hash", models.CharField(max_length=64, unique=True)),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=64)),
                ("schema", models.CharField(max_length=64)),
                ("binding_id", models.CharField(max_length=192)),
                ("binding_version", models.CharField(max_length=192)),
                ("physical_observation_id", models.CharField(max_length=192)),
                ("physical_observation_version", models.CharField(max_length=192)),
                ("physical_identity_hash", models.CharField(max_length=64)),
                ("physical_content_hash", models.CharField(max_length=64, unique=True)),
                ("account_namespace_claim", models.CharField(max_length=192)),
                ("account_id_claim", models.CharField(max_length=192)),
                ("underlying_unified_account_namespace_claim", models.CharField(max_length=192)),
                ("underlying_unified_account_id_claim", models.PositiveBigIntegerField()),
                ("recorded_service_id", models.CharField(max_length=192)),
                ("recorded_role", models.CharField(max_length=192)),
                ("recorded_kind", models.CharField(max_length=16)),
                ("recorded_is_automated", models.BooleanField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField(db_index=True)),
                ("account_claim_hash", models.CharField(max_length=64, unique=True)),
                ("underlying_claim_hash", models.CharField(max_length=64, unique=True)),
                ("permission", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=16)),
                ("binding_state", models.CharField(max_length=32)),
                ("owner_assignment_state", models.CharField(max_length=32)),
                ("canonical_payload", models.JSONField()),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("allocation_binding_seal", models.CharField(max_length=64)),
                ("physical_binding_seal", models.CharField(max_length=64)),
                ("recorder_binding_seal", models.CharField(max_length=64)),
                ("fixed_authority_seal", models.CharField(max_length=64)),
                ("record_seal", models.CharField(max_length=64, unique=True)),
                ("ledger_seal", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
                (
                    "allocation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="creation_binding",
                        to="account.canonicalaccountcreationallocationmodel",
                    ),
                ),
            ],
            options={
                "db_table": "canonical_account_creation_binding_ledger",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("binding_id", "binding_version"), name="acct_create_bind_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("account_namespace_claim", "account_id_claim"),
                        name="acct_create_bind_acct_uq",
                    ),
                    models.UniqueConstraint(
                        fields=(
                            "underlying_unified_account_namespace_claim",
                            "underlying_unified_account_id_claim",
                        ),
                        name="acct_create_bind_under_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            artifact_type="canonical_account_creation_binding",
                            binding_state="pending_owner_approval",
                            owner="account",
                            owner_assignment_state="unknown",
                            permission="identity_binding_evidence_only",
                            recorded_is_automated=True,
                            recorded_kind="service",
                            recorded_role="canonical_account_creation_binder",
                            schema="canonical-account-creation-binding.v1",
                            status="inactive",
                        ),
                        name="acct_create_bind_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            persisted_at=models.F("recorded_at"),
                            recorded_at__lt=models.F("valid_until"),
                        ),
                        name="acct_create_bind_clock_ck",
                    ),
                ],
            },
        ),
    ]
