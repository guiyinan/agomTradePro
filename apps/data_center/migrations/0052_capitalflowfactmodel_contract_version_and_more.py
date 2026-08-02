from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0051_rawauditmodel_ingested_run_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="capitalflowfactmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="capitalflowfactmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="capitalflowfactmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="capitalflowfactmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="capitalflowfactmodel",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="capitalflowfactmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="capitalflowfactmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="announced_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="available_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="financialfactmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="fundnavfactmodel",
            name="available_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="fundnavfactmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="fundnavfactmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="fundnavfactmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="fundnavfactmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="fundnavfactmodel",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="fundnavfactmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="fundnavfactmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="macrofactmodel",
            name="available_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="macrofactmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="macrofactmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="macrofactmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="macrofactmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="macrofactmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="macrofactmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="newsfactmodel",
            name="available_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="newsfactmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="newsfactmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="newsfactmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="newsfactmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="newsfactmodel",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="newsfactmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="newsfactmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="pricebarmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="pricebarmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="pricebarmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="pricebarmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="pricebarmodel",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="pricebarmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="pricebarmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="quotesnapshotmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="quotesnapshotmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="quotesnapshotmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="quotesnapshotmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="quotesnapshotmodel",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="quotesnapshotmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="quotesnapshotmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="sectormembershipfactmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="sectormembershipfactmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="sectormembershipfactmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="sectormembershipfactmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="sectormembershipfactmodel",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="sectormembershipfactmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="sectormembershipfactmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="valuationfactmodel",
            name="available_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="valuationfactmodel",
            name="contract_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="valuationfactmodel",
            name="ingested_run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="valuationfactmodel",
            name="quality_status",
            field=models.CharField(db_index=True, default="accepted", max_length=40),
        ),
        migrations.AddField(
            model_name="valuationfactmodel",
            name="raw_payload_hash",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name="valuationfactmodel",
            name="revision_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="valuationfactmodel",
            name="schema_version",
            field=models.CharField(default="1.0", max_length=40),
        ),
        migrations.AddField(
            model_name="valuationfactmodel",
            name="source_record_id",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
