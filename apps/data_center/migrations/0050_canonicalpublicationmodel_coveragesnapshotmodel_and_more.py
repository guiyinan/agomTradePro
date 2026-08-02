import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0049_quotesnapshot_fetched_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="CanonicalPublicationModel",
            fields=[
                (
                    "publication_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("publication_key", models.CharField(max_length=300)),
                ("policy_version", models.CharField(max_length=80)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("candidate", "candidate"),
                            ("published", "published"),
                            ("superseded", "superseded"),
                            ("blocked", "blocked"),
                        ],
                        default="candidate",
                        max_length=20,
                    ),
                ),
                ("selected_source", models.CharField(blank=True, db_index=True, max_length=100)),
                ("publication_hash", models.CharField(db_index=True, max_length=128)),
                ("member_count", models.PositiveIntegerField(default=0)),
                ("conflict_count", models.PositiveIntegerField(default=0)),
                ("coverage_requested_count", models.PositiveIntegerField(default=0)),
                ("coverage_eligible_count", models.PositiveIntegerField(default=0)),
                ("coverage_selected_count", models.PositiveIntegerField(default=0)),
                ("coverage_missing_count", models.PositiveIntegerField(default=0)),
                ("coverage_conflict_count", models.PositiveIntegerField(default=0)),
                ("as_of", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("superseded_at", models.DateTimeField(blank=True, null=True)),
                ("must_not_use_for_decision", models.BooleanField(default=False)),
                ("blocked_reason", models.TextField(blank=True)),
                ("created_by", models.CharField(default="system", max_length=150)),
                ("run_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "data_center_canonical_publication",
                "ordering": ["-published_at", "-created_at"],
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "publication_key", "state"],
                        name="data_center_dataset_cb44fc_idx",
                    ),
                    models.Index(
                        fields=["dataset_key", "as_of", "state"],
                        name="data_center_dataset_4cfd4b_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("dataset_key", "publication_key", "publication_hash"),
                        name="dc_publication_scope_hash_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("coverage_selected_count__lte", models.F("coverage_eligible_count"))
                        ),
                        name="dc_publication_coverage_selected_lte_eligible",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("coverage_eligible_count__lte", models.F("coverage_requested_count"))
                        ),
                        name="dc_publication_coverage_eligible_lte_requested",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CoverageSnapshotModel",
            fields=[
                (
                    "coverage_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("publication_id", models.UUIDField(db_index=True, unique=True)),
                ("requested_count", models.PositiveIntegerField(default=0)),
                ("eligible_count", models.PositiveIntegerField(default=0)),
                ("selected_count", models.PositiveIntegerField(default=0)),
                ("missing_count", models.PositiveIntegerField(default=0)),
                ("conflict_count", models.PositiveIntegerField(default=0)),
                ("generated_at", models.DateTimeField(db_index=True)),
            ],
            options={
                "db_table": "data_center_coverage_snapshot",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("selected_count__lte", models.F("eligible_count"))),
                        name="dc_coverage_selected_lte_eligible",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("eligible_count__lte", models.F("requested_count"))),
                        name="dc_coverage_eligible_lte_requested",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PublicationMemberModel",
            fields=[
                (
                    "member_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("publication_id", models.UUIDField(db_index=True)),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("natural_key", models.CharField(max_length=300)),
                ("source", models.CharField(db_index=True, max_length=100)),
                ("source_record_id", models.CharField(max_length=300)),
                ("fact_table", models.CharField(max_length=160)),
                ("fact_pk", models.CharField(max_length=160)),
                ("observed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("raw_payload_hash", models.CharField(blank=True, max_length=128)),
                ("quality_status", models.CharField(default="accepted", max_length=40)),
                ("revision_number", models.PositiveIntegerField(default=1)),
            ],
            options={
                "db_table": "data_center_publication_member",
                "ordering": ["natural_key", "source"],
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "natural_key", "observed_at"],
                        name="data_center_dataset_41b075_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("publication_id", "natural_key"),
                        name="dc_publication_member_natural_key_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="QuarantineRecordModel",
            fields=[
                (
                    "quarantine_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("provider_name", models.CharField(db_index=True, max_length=100)),
                ("natural_key", models.CharField(db_index=True, max_length=300)),
                ("reason_code", models.CharField(db_index=True, max_length=100)),
                ("reason", models.TextField()),
                ("payload_hash", models.CharField(db_index=True, max_length=128)),
                ("schema_fingerprint", models.CharField(db_index=True, max_length=128)),
                ("payload", models.JSONField(default=dict)),
                ("observed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("run_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("batch_id", models.UUIDField(blank=True, db_index=True, null=True)),
                (
                    "resolution",
                    models.CharField(
                        choices=[
                            ("open", "open"),
                            ("accepted", "accepted"),
                            ("rejected", "rejected"),
                            ("superseded", "superseded"),
                        ],
                        default="open",
                        max_length=20,
                    ),
                ),
                ("quarantined_at", models.DateTimeField(db_index=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_by", models.CharField(blank=True, max_length=150)),
            ],
            options={
                "db_table": "data_center_quarantine_record",
                "ordering": ["-quarantined_at"],
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "resolution"], name="data_center_dataset_782ccd_idx"
                    ),
                    models.Index(
                        fields=["provider_name", "reason_code"],
                        name="data_center_provide_0513d0_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SyncBatchModel",
            fields=[
                (
                    "batch_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("run_id", models.UUIDField(db_index=True)),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("provider_name", models.CharField(db_index=True, max_length=100)),
                ("idempotency_key", models.CharField(max_length=240, unique=True)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("running", "running"),
                            ("succeeded", "succeeded"),
                            ("failed", "failed"),
                            ("quarantined", "quarantined"),
                            ("skipped", "skipped"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("requested", models.PositiveIntegerField(default=0)),
                ("fetched", models.PositiveIntegerField(default=0)),
                ("validated", models.PositiveIntegerField(default=0)),
                ("quarantined", models.PositiveIntegerField(default=0)),
                ("succeeded", models.PositiveIntegerField(default=0)),
                ("failed", models.PositiveIntegerField(default=0)),
                ("stored", models.PositiveIntegerField(default=0)),
                ("published", models.PositiveIntegerField(default=0)),
                ("window_start", models.DateField(blank=True, null=True)),
                ("window_end", models.DateField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "data_center_sync_batch",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["run_id", "dataset_key"], name="data_center_run_id_3ba543_idx"
                    ),
                    models.Index(
                        fields=["provider_name", "state"], name="data_center_provide_40ab8e_idx"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SyncCheckpointModel",
            fields=[
                (
                    "checkpoint_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("run_id", models.UUIDField(db_index=True)),
                ("batch_id", models.UUIDField(db_index=True)),
                ("cursor_name", models.CharField(max_length=100)),
                ("cursor_value", models.CharField(max_length=500)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("running", "running"),
                            ("succeeded", "succeeded"),
                            ("failed", "failed"),
                            ("quarantined", "quarantined"),
                            ("skipped", "skipped"),
                        ],
                        default="succeeded",
                        max_length=20,
                    ),
                ),
                ("processed", models.PositiveIntegerField(default=0)),
                ("failed", models.PositiveIntegerField(default=0)),
                ("recorded_at", models.DateTimeField(db_index=True)),
                ("error_code", models.CharField(blank=True, max_length=80)),
            ],
            options={
                "db_table": "data_center_sync_checkpoint",
                "ordering": ["-recorded_at"],
                "indexes": [
                    models.Index(
                        fields=["run_id", "batch_id", "recorded_at"],
                        name="data_center_run_id_307416_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("batch_id", "cursor_name", "cursor_value"),
                        name="dc_checkpoint_batch_cursor_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SyncRunModel",
            fields=[
                (
                    "run_id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("dataset_key", models.CharField(db_index=True, max_length=160)),
                ("trigger", models.CharField(max_length=40)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("requested", "requested"),
                            ("fetching", "fetching"),
                            ("received", "received"),
                            ("validating", "validating"),
                            ("normalized", "normalized"),
                            ("reconciling", "reconciling"),
                            ("stored", "stored"),
                            ("publishing", "publishing"),
                            ("published", "published"),
                            ("quarantined", "quarantined"),
                            ("blocked", "blocked"),
                            ("failed", "failed"),
                        ],
                        default="requested",
                        max_length=24,
                    ),
                ),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("success", "success"),
                            ("partial", "partial"),
                            ("noop", "noop"),
                            ("blocked", "blocked"),
                            ("failed", "failed"),
                        ],
                        default="blocked",
                        max_length=16,
                    ),
                ),
                ("provider_name", models.CharField(blank=True, db_index=True, max_length=100)),
                ("contract_version", models.CharField(blank=True, max_length=40)),
                ("config_snapshot_hash", models.CharField(blank=True, max_length=128)),
                ("requested", models.PositiveIntegerField(default=0)),
                ("fetched", models.PositiveIntegerField(default=0)),
                ("validated", models.PositiveIntegerField(default=0)),
                ("quarantined", models.PositiveIntegerField(default=0)),
                ("succeeded", models.PositiveIntegerField(default=0)),
                ("failed", models.PositiveIntegerField(default=0)),
                ("stored", models.PositiveIntegerField(default=0)),
                ("published", models.PositiveIntegerField(default=0)),
                ("unchanged", models.PositiveIntegerField(default=0)),
                ("started_at", models.DateTimeField(db_index=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "data_center_sync_run",
                "ordering": ["-started_at"],
                "indexes": [
                    models.Index(
                        fields=["dataset_key", "started_at"], name="data_center_dataset_fe010d_idx"
                    ),
                    models.Index(
                        fields=["status", "outcome"], name="data_center_status_f494f6_idx"
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("stored__gte", 0)),
                        name="dc_sync_run_stored_nonnegative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("published__gte", 0)),
                        name="dc_sync_run_published_nonnegative",
                    ),
                ],
            },
        ),
    ]
