"""Materialize the decision gate and retire runtime singleton fallback."""

from django.db import migrations, models
from django.utils import timezone

ALLOWED_STATUSES = {"active", "maintenance", "validating", "blocked"}
MISSING_STATE_REASON = "决策运行状态尚未初始化。"


def materialize_decision_runtime_state(apps, schema_editor) -> None:
    """Copy an explicit legacy gate once or seed a fail-closed state."""

    state_model = apps.get_model("config_center", "DecisionRuntimeStateModel")
    if state_model.objects.filter(pk=1).exists():
        return

    legacy_model = apps.get_model("config_center", "SystemSettingsModel")
    legacy = legacy_model.objects.filter(pk=1).first()
    now = timezone.now()
    if legacy is None:
        state_model.objects.create(
            state_id=1,
            status="blocked",
            reason=MISSING_STATE_REASON,
            changed_at=now,
            changed_by="migration:0013",
        )
        return

    status = str(legacy.decision_runtime_status or "").strip().lower()
    reason = str(legacy.decision_runtime_reason or "").strip()
    changed_at = legacy.decision_runtime_changed_at
    changed_by = str(legacy.decision_runtime_changed_by or "").strip()
    if status not in ALLOWED_STATUSES:
        status = "blocked"
        reason = "旧决策运行状态无效，迁移已阻断。"
    elif status == "active" and (changed_at is None or not changed_by):
        status = "blocked"
        reason = MISSING_STATE_REASON
    elif status != "active" and not reason:
        status = "blocked"
        reason = "旧决策运行状态缺少阻断原因。"

    state_model.objects.create(
        state_id=1,
        status=status,
        reason=reason,
        changed_at=changed_at or getattr(legacy, "updated_at", None) or now,
        changed_by=changed_by or "migration:0013",
        release_ref=str(legacy.decision_runtime_release_ref or "").strip(),
        expected_resume_at=legacy.decision_runtime_expected_resume_at,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0012_qlib_training_run_lock"),
    ]

    operations = [
        migrations.AlterField(
            model_name="decisionruntimestatemodel",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "active"),
                    ("maintenance", "maintenance"),
                    ("validating", "validating"),
                    ("blocked", "blocked"),
                ],
                db_index=True,
                default="blocked",
                max_length=16,
            ),
        ),
        migrations.RunPython(materialize_decision_runtime_state, migrations.RunPython.noop),
    ]
