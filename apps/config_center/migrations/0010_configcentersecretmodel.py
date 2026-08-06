from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("config_center", "0009_backupdeliverystatemodel"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfigCenterSecretModel",
            fields=[
                (
                    "secret_ref",
                    models.CharField(max_length=300, primary_key=True, serialize=False),
                ),
                ("encrypted_value", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "config_center_secret"},
        ),
    ]
