"""Admin registrations for config center."""

from django.contrib import admin

from apps.config_center.infrastructure.models import (
    QlibTrainingProfileModel,
    QlibTrainingRunModel,
)


@admin.register(QlibTrainingProfileModel)
class QlibTrainingProfileAdmin(admin.ModelAdmin):
    list_display = (
        "profile_key",
        "name",
        "model_name",
        "model_type",
        "universe",
        "is_active",
        "updated_at",
    )
    list_filter = ("model_type", "is_active", "activate_after_train")
    search_fields = ("profile_key", "name", "model_name", "feature_set_id", "label_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(QlibTrainingRunModel)
class QlibTrainingRunAdmin(admin.ModelAdmin):
    list_display = (
        "run_id",
        "model_name",
        "model_type",
        "status",
        "requested_by",
        "requested_at",
        "finished_at",
    )
    list_filter = ("status", "model_type", "requested_at")
    search_fields = ("model_name", "model_type", "celery_task_id", "result_artifact_hash")
    readonly_fields = (
        "run_id",
        "requested_at",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    )

