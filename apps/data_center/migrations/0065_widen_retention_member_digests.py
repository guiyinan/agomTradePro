"""Allow algorithm-prefixed SHA-256 evidence on exact retention members."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0064_retention_exact_plan_members"),
    ]

    operations = [
        migrations.AlterField(
            model_name="retentionplanmembermodel",
            name="payload_hash",
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name="retentionplanmembermodel",
            name="record_digest",
            field=models.CharField(max_length=128),
        ),
    ]
