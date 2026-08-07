"""Materialize legacy Qlib settings into the canonical runtime profile once."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any

from django.db import migrations
from django.utils import timezone

QLIB_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("alpha.qlib.enabled", "qlib_enabled"),
    ("alpha.qlib.provider_uri", "qlib_provider_uri"),
    ("alpha.qlib.region", "qlib_region"),
    ("alpha.qlib.model_path", "qlib_model_path"),
    ("alpha.qlib.default_universe", "qlib_default_universe"),
    ("alpha.qlib.default_feature_set_id", "qlib_default_feature_set_id"),
    ("alpha.qlib.default_label_id", "qlib_default_label_id"),
    ("alpha.qlib.train_queue_name", "qlib_train_queue_name"),
    ("alpha.qlib.infer_queue_name", "qlib_infer_queue_name"),
    ("alpha.qlib.allow_auto_activate", "qlib_allow_auto_activate"),
)
QLIB_KEYS = frozenset(key for key, _field_name in QLIB_FIELD_MAP)


def _runtime_environment() -> str:
    """Resolve the database's runtime environment with the production rule."""

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    return "production" if settings_module.endswith(".production") else "development"


def _hash_values(values: dict[str, object]) -> str:
    """Return the runtime control plane's deterministic snapshot hash."""

    serialized = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def materialize_qlib_runtime_profile(apps: Any, schema_editor: Any) -> None:
    """Copy Qlib values once while preserving any existing canonical values."""

    legacy_model = apps.get_model("config_center", "SystemSettingsModel")
    profile_model = apps.get_model("config_center", "RuntimeConfigProfileModel")
    value_model = apps.get_model("config_center", "RuntimeConfigValueModel")
    revision_model = apps.get_model("config_center", "RuntimeConfigRevisionModel")
    snapshot_model = apps.get_model("config_center", "RuntimeConfigSnapshotModel")

    environment = _runtime_environment()
    active = (
        profile_model.objects.filter(environment=environment, status="active")
        .order_by("-version")
        .first()
    )
    existing_rows = list(
        value_model.objects.filter(profile_id=active.profile_id).order_by("definition_key")
        if active is not None
        else ()
    )
    existing_by_key = {row.definition_key: row for row in existing_rows}
    latest_snapshot = (
        snapshot_model.objects.filter(profile_key=active.profile_key)
        .order_by("-generated_at")
        .first()
        if active is not None
        else None
    )
    if (
        active is not None
        and QLIB_KEYS.issubset(existing_by_key)
        and latest_snapshot is not None
        and latest_snapshot.profile_id == active.profile_id
        and latest_snapshot.profile_version == active.version
        and QLIB_KEYS.issubset(latest_snapshot.resolved_values or {})
    ):
        return

    legacy = legacy_model.objects.filter(pk=1).first()
    if legacy is None and not QLIB_KEYS.issubset(existing_by_key):
        # Fresh installs must configure a complete typed snapshot explicitly.
        return

    qlib_values = {
        definition_key: getattr(legacy, field_name)
        for definition_key, field_name in QLIB_FIELD_MAP
        if legacy is not None
    }
    next_profile_id = uuid.uuid4()
    next_values: dict[str, dict[str, object]] = {
        row.definition_key: {
            "value_json": row.value_json,
            "secret_ref": row.secret_ref,
            "source": row.source,
            "validation_status": row.validation_status,
            "validation_error": row.validation_error,
        }
        for row in existing_rows
    }
    for definition_key, value in qlib_values.items():
        next_values.setdefault(
            definition_key,
            {
                "value_json": value,
                "secret_ref": "",
                "source": "legacy_materialization_0014",
                "validation_status": "valid",
                "validation_error": "",
            },
        )

    resolved_values = {
        key: payload["value_json"]
        for key, payload in next_values.items()
        if not str(payload["secret_ref"] or "").strip()
    }
    snapshot_hash = _hash_values(resolved_values)
    now = timezone.now()
    version = (
        max(
            profile_model.objects.filter(
                profile_key=active.profile_key if active is not None else environment
            ).values_list("version", flat=True),
            default=0,
        )
        + 1
    )
    profile_key = active.profile_key if active is not None else environment
    if active is not None:
        profile_model.objects.filter(environment=environment, status="active").update(
            status="superseded"
        )
    profile_model.objects.create(
        profile_id=next_profile_id,
        profile_key=profile_key,
        environment=environment,
        version=version,
        status="active",
        based_on_profile=str(active.profile_id) if active is not None else "",
        content_hash=snapshot_hash,
        created_by="migration:0014",
        activated_by="migration:0014",
        created_at=now,
        activated_at=now,
        change_reason="Materialize legacy Qlib runtime values into Config Center",
    )
    value_model.objects.bulk_create(
        [
            value_model(
                value_id=uuid.uuid4(),
                profile_id=next_profile_id,
                definition_key=key,
                **payload,
            )
            for key, payload in sorted(next_values.items())
        ]
    )
    before_projection = (
        dict(latest_snapshot.resolved_values or {}) if latest_snapshot is not None else {}
    )
    revision_model.objects.create(
        revision_id=uuid.uuid4(),
        profile_id=next_profile_id,
        before_hash=str(active.content_hash or "") if active is not None else "",
        after_hash=snapshot_hash,
        changed_keys=sorted(QLIB_KEYS),
        before_projection=before_projection,
        after_projection=resolved_values,
        actor="migration:0014",
        reason="Materialize legacy Qlib runtime values into Config Center",
        changed_at=now,
        validation_evidence={"valid": True, "materialized_keys": sorted(QLIB_KEYS)},
    )
    snapshot_model.objects.create(
        snapshot_id=uuid.uuid4(),
        profile_id=next_profile_id,
        profile_key=profile_key,
        profile_version=version,
        snapshot_hash=snapshot_hash,
        resolved_values=resolved_values,
        generated_at=now,
        effective_from=now,
        validation_report={"valid": True, "materialized_keys": sorted(QLIB_KEYS)},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0013_materialize_decision_runtime_state"),
    ]

    operations = [
        migrations.RunPython(materialize_qlib_runtime_profile, migrations.RunPython.noop),
    ]
