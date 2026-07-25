"""Replace persisted raw access tokens with deterministic lookup fingerprints."""

import hashlib
from typing import Any

from django.db import migrations


def hash_access_token_keys(apps: Any, schema_editor: Any) -> None:
    """Hash every legacy raw token key in place."""

    token_model = apps.get_model("account", "UserAccessTokenModel")
    for token in token_model._default_manager.only("id", "key").iterator():
        raw_key = str(token.key or "")
        if not raw_key:
            continue
        token.key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        token.save(update_fields=["key"])


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0034_enforce_single_active_macro_sizing"),
    ]

    operations = [
        migrations.RunPython(hash_access_token_keys, migrations.RunPython.noop),
    ]
