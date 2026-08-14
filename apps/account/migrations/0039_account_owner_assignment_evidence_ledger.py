import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0038_account_identity_raw_source_ledger"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountOwnerAssignmentSubjectModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("evidence_id", models.CharField(max_length=192)),
                ("evidence_version", models.CharField(max_length=192)),
                ("subject_identity_hash", models.CharField(max_length=64, unique=True)),
                ("row_owner", models.CharField(max_length=32)),
                ("row_artifact_type", models.CharField(max_length=64)),
                ("row_observation_id", models.CharField(max_length=192)),
                ("row_observation_version", models.CharField(max_length=192)),
                ("row_content_hash", models.CharField(max_length=64)),
                ("account_namespace", models.CharField(max_length=192)),
                ("account_id", models.CharField(max_length=192)),
                ("underlying_unified_account_namespace", models.CharField(max_length=192)),
                ("underlying_unified_account_id", models.PositiveBigIntegerField()),
                ("row_observed_at", models.DateTimeField()),
                ("row_recorded_at", models.DateTimeField()),
                ("row_valid_until", models.DateTimeField()),
                ("row_binding_hash", models.CharField(max_length=64, unique=True)),
                ("receipt_owner", models.CharField(max_length=32)),
                ("receipt_artifact_type", models.CharField(max_length=64)),
                ("receipt_id", models.CharField(max_length=192)),
                ("receipt_version", models.CharField(max_length=192)),
                ("receipt_content_hash", models.CharField(max_length=64)),
                ("provenance_kind", models.CharField(max_length=32)),
                ("assignment_state", models.CharField(max_length=32)),
                ("assigned_owner_user_id", models.PositiveBigIntegerField(null=True)),
                ("receipt_account_namespace", models.CharField(max_length=192)),
                ("receipt_account_id", models.CharField(max_length=192)),
                ("receipt_underlying_namespace", models.CharField(max_length=192)),
                ("receipt_underlying_id", models.PositiveBigIntegerField()),
                ("receipt_row_id", models.CharField(max_length=192)),
                ("receipt_row_version", models.CharField(max_length=192)),
                ("receipt_row_content_hash", models.CharField(max_length=64)),
                ("receipt_claimant_actor_id", models.CharField(max_length=192)),
                ("receipt_claimant_user_id", models.PositiveBigIntegerField()),
                ("receipt_claimant_role", models.CharField(max_length=192)),
                ("receipt_claimant_kind", models.CharField(max_length=16)),
                ("receipt_claimant_is_staff", models.BooleanField()),
                ("receipt_issued_at", models.DateTimeField()),
                ("receipt_recorded_at", models.DateTimeField()),
                ("receipt_valid_until", models.DateTimeField()),
                ("provenance_binding_hash", models.CharField(max_length=64, unique=True)),
                ("claimant_actor_id", models.CharField(max_length=192)),
                ("claimant_user_id", models.PositiveBigIntegerField()),
                ("claimant_role", models.CharField(max_length=192)),
                ("claimant_kind", models.CharField(max_length=16)),
                ("claimant_is_staff", models.BooleanField()),
                ("requested_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
            ],
            options={
                "db_table": "account_owner_assignment_subject",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["account_namespace", "account_id", "recorded_at"],
                        name="acct_own_asg_subj_pit_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("evidence_id", "evidence_version"), name="acct_own_asg_subj_id_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("account_namespace", "account"),
                            ("claimant_kind", "human"),
                            ("receipt_claimant_kind", "human"),
                            ("receipt_owner", "account"),
                            ("row_artifact_type", "unified_account_row_observation"),
                            ("row_owner", "simulated_trading"),
                            ("underlying_unified_account_namespace", "simulated-account-row"),
                        ),
                        name="acct_own_asg_subj_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("row_observed_at__lte", models.F("row_recorded_at")),
                            ("row_recorded_at__lte", models.F("requested_at")),
                            ("receipt_issued_at__lte", models.F("receipt_recorded_at")),
                            ("receipt_recorded_at__lte", models.F("requested_at")),
                            ("requested_at", models.F("recorded_at")),
                            ("recorded_at", models.F("persisted_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                            ("valid_until__lte", models.F("row_valid_until")),
                            ("valid_until__lte", models.F("receipt_valid_until")),
                        ),
                        name="acct_own_asg_subj_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("receipt_account_namespace", models.F("account_namespace")),
                            ("receipt_account_id", models.F("account_id")),
                            (
                                "receipt_underlying_namespace",
                                models.F("underlying_unified_account_namespace"),
                            ),
                            ("receipt_underlying_id", models.F("underlying_unified_account_id")),
                            ("receipt_row_id", models.F("row_observation_id")),
                            ("receipt_row_version", models.F("row_observation_version")),
                            ("receipt_row_content_hash", models.F("row_content_hash")),
                            ("receipt_claimant_actor_id", models.F("claimant_actor_id")),
                            ("receipt_claimant_user_id", models.F("claimant_user_id")),
                            ("receipt_claimant_role", models.F("claimant_role")),
                            ("receipt_claimant_kind", models.F("claimant_kind")),
                            ("receipt_claimant_is_staff", models.F("claimant_is_staff")),
                        ),
                        name="acct_own_asg_subj_bind_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("assigned_owner_user_id", models.F("claimant_user_id")),
                                ("assignment_state", "authoritative"),
                                ("provenance_kind__in", ("creation", "manual_reclaim")),
                            ),
                            models.Q(
                                ("assigned_owner_user_id__isnull", True),
                                ("assignment_state", "legacy_default"),
                                ("provenance_kind", "migration"),
                            ),
                            _connector="OR",
                        ),
                        name="acct_own_asg_subj_assign_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AccountOwnerAssignmentEvidenceModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("subject_content_hash", models.CharField(max_length=64, unique=True)),
                ("owner", models.CharField(max_length=32)),
                ("artifact_type", models.CharField(max_length=64)),
                ("schema", models.CharField(max_length=64)),
                ("evidence_id", models.CharField(max_length=192)),
                ("evidence_version", models.CharField(max_length=192)),
                ("identity_hash", models.CharField(max_length=64, unique=True)),
                ("account_namespace", models.CharField(max_length=192)),
                ("account_id", models.CharField(max_length=192)),
                ("underlying_unified_account_namespace", models.CharField(max_length=192)),
                ("underlying_unified_account_id", models.PositiveBigIntegerField()),
                ("assignment_state", models.CharField(max_length=32)),
                ("assigned_owner_user_id", models.PositiveBigIntegerField(null=True)),
                ("row_observation_owner", models.CharField(max_length=32)),
                ("row_observation_artifact_type", models.CharField(max_length=64)),
                ("row_observation_id", models.CharField(max_length=192)),
                ("row_observation_version", models.CharField(max_length=192)),
                ("row_observation_content_hash", models.CharField(max_length=64)),
                ("provenance_kind", models.CharField(max_length=32)),
                ("provenance_ref_owner", models.CharField(max_length=32)),
                ("provenance_ref_artifact_type", models.CharField(max_length=64)),
                ("provenance_ref_id", models.CharField(max_length=192)),
                ("provenance_ref_version", models.CharField(max_length=192)),
                ("provenance_ref_content_hash", models.CharField(max_length=64)),
                ("claimant_actor_id", models.CharField(max_length=192)),
                ("claimant_user_id", models.PositiveBigIntegerField()),
                ("claimant_role", models.CharField(max_length=192)),
                ("claimant_kind", models.CharField(max_length=16)),
                ("claimant_is_staff", models.BooleanField()),
                ("approved_actor_id", models.CharField(max_length=192)),
                ("approved_user_id", models.PositiveBigIntegerField()),
                ("approved_role", models.CharField(max_length=192)),
                ("approved_kind", models.CharField(max_length=16)),
                ("approved_is_staff", models.BooleanField()),
                ("issued_at", models.DateTimeField()),
                ("approved_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("valid_until", models.DateTimeField()),
                ("supersedes_content_hash", models.CharField(max_length=64, null=True)),
                ("root_claim_hash", models.CharField(max_length=64, null=True)),
                ("permission", models.CharField(max_length=32)),
                ("status", models.CharField(max_length=16)),
                ("blocker_codes", models.JSONField()),
                ("canonical_payload", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("ledger_header_hash", models.CharField(max_length=64, unique=True)),
                ("persisted_at", models.DateTimeField()),
                (
                    "subject",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approved_evidence",
                        to="account.accountownerassignmentsubjectmodel",
                    ),
                ),
            ],
            options={
                "db_table": "account_owner_assignment_evidence",
                "abstract": False,
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=[
                            "account_namespace",
                            "account_id",
                            "row_observation_id",
                            "recorded_at",
                        ],
                        name="acct_own_asg_ev_chain_ix",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("evidence_id", "evidence_version"), name="acct_own_asg_ev_id_uq"
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("root_claim_hash__isnull", False)),
                        fields=("root_claim_hash",),
                        name="acct_own_asg_ev_root_uq",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("supersedes_content_hash__isnull", False)),
                        fields=("supersedes_content_hash",),
                        name="acct_own_asg_ev_next_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("account_namespace", "account"),
                            ("approved_is_staff", True),
                            ("approved_kind", "human"),
                            ("artifact_type", "account_owner_assignment_evidence"),
                            ("claimant_kind", "human"),
                            ("owner", "account"),
                            ("permission", "evidence_only"),
                            ("provenance_ref_owner", "account"),
                            ("row_observation_artifact_type", "unified_account_row_observation"),
                            ("row_observation_owner", "simulated_trading"),
                            ("schema", "account-owner-assignment-evidence.v1"),
                            ("status", "inactive"),
                            ("underlying_unified_account_namespace", "simulated-account-row"),
                        ),
                        name="acct_own_asg_ev_fixed_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("issued_at__lte", models.F("approved_at")),
                            ("approved_at__lte", models.F("recorded_at")),
                            ("recorded_at", models.F("persisted_at")),
                            ("recorded_at__lt", models.F("valid_until")),
                        ),
                        name="acct_own_asg_ev_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("root_claim_hash__isnull", False),
                                ("supersedes_content_hash__isnull", True),
                            ),
                            models.Q(
                                ("root_claim_hash__isnull", True),
                                ("supersedes_content_hash__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="acct_own_asg_ev_link_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("claimant_actor_id", models.F("approved_actor_id")), _negated=True
                            ),
                            models.Q(
                                ("claimant_user_id", models.F("approved_user_id")), _negated=True
                            ),
                        ),
                        name="acct_own_asg_ev_actor_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("assigned_owner_user_id", models.F("claimant_user_id")),
                                ("assignment_state", "authoritative"),
                                ("provenance_kind__in", ("creation", "manual_reclaim")),
                            ),
                            models.Q(
                                ("assigned_owner_user_id__isnull", True),
                                ("assignment_state", "legacy_default"),
                                ("provenance_kind", "migration"),
                            ),
                            _connector="OR",
                        ),
                        name="acct_own_asg_ev_assign_ck",
                    ),
                ],
            },
        ),
    ]
