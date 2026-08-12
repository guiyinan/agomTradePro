"""Merge the runtime materialization and backup-secret cutover histories."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0015_materialize_remaining_runtime_groups"),
        ("config_center", "0015_remove_legacy_backup_secret_columns"),
    ]

    operations = []
