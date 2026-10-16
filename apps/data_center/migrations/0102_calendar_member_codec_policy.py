"""Bind explicitly selected nullable member codecs without changing old policies."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0101_instrument_reference_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="datasetpublicationpolicymodel",
            name="member_codec_version",
            field=models.CharField(blank=True, max_length=48, null=True),
        ),
        migrations.AddConstraint(
            model_name="datasetpublicationpolicymodel",
            constraint=models.CheckConstraint(
                condition=models.Q(member_codec_version__isnull=True)
                | (
                    models.Q(member_codec_version="calendar-nullable-member-v1")
                    & ~models.Q(policy_version="legacy")
                ),
                name="dc_dataset_policy_member_codec_valid",
            ),
        ),
    ]
