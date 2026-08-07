"""Preserve SHA-256 evidence when rolling back to legacy digest widths."""

from typing import Any

from django.db import migrations
from django.db.models import F
from django.db.models.functions import Substr


def normalize_sha256_digests_for_legacy_width(apps: Any, schema_editor: Any) -> None:
    """Strip the known algorithm prefix before the legacy 64-char narrowing."""

    del schema_editor
    member_model = apps.get_model("data_center", "RetentionPlanMemberModel")
    for field_name in ("payload_hash", "record_digest"):
        member_model.objects.filter(**{f"{field_name}__startswith": "sha256:"}).update(
            **{field_name: Substr(F(field_name), 8)}
        )


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0065_widen_retention_member_digests"),
    ]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            normalize_sha256_digests_for_legacy_width,
        ),
    ]
