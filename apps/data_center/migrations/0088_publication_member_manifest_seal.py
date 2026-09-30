from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0087_canonical_publication_pointer"),
    ]

    operations = [
        migrations.AddField(
            model_name="canonicalpublicationmodel",
            name="member_manifest_hash",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="canonicalpublicationmodel",
            name="members_sealed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
