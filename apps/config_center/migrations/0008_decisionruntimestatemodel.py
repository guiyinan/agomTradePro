from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("config_center", "0007_storagecapacityobservationmodel"),
    ]

    operations = [
        migrations.CreateModel(
            name="DecisionRuntimeStateModel",
            fields=[
                (
                    "state_id",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "active"),
                            ("maintenance", "maintenance"),
                            ("validating", "validating"),
                            ("blocked", "blocked"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("changed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("changed_by", models.CharField(blank=True, max_length=150)),
                ("release_ref", models.CharField(blank=True, max_length=100)),
                ("expected_resume_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "config_center_decision_runtime_state",
            },
        ),
    ]
