"""Admin registrations for config center."""

from django.contrib import admin

from apps.config_center.application.access_policies import (
    QlibAccessDeniedError,
    ensure_can_trigger_qlib_training,
    ensure_can_view_qlib_center,
)
from apps.config_center.infrastructure.models import (
    QlibTrainingProfileModel,
    QlibTrainingRunModel,
)


class QlibPermissionAdminMixin:
    """Apply the same staff-read / superuser-write policy inside Django admin."""

    @staticmethod
    def _allows_view(user) -> bool:
        try:
            ensure_can_view_qlib_center(user)
        except QlibAccessDeniedError:
            return False
        return True

    @staticmethod
    def _allows_write(user) -> bool:
        try:
            ensure_can_trigger_qlib_training(user)
        except QlibAccessDeniedError:
            return False
        return True

    def has_module_permission(self, request):
        return self._allows_view(request.user)

    def has_view_permission(self, request, obj=None):
        return self._allows_view(request.user)

    def has_add_permission(self, request):
        return self._allows_write(request.user)

    def has_change_permission(self, request, obj=None):
        return self._allows_write(request.user)

    def has_delete_permission(self, request, obj=None):
        return self._allows_write(request.user)


@admin.register(QlibTrainingProfileModel)
class QlibTrainingProfileAdmin(QlibPermissionAdminMixin, admin.ModelAdmin):
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
class QlibTrainingRunAdmin(QlibPermissionAdminMixin, admin.ModelAdmin):
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
        "profile",
        "requested_by",
        "model_name",
        "model_type",
        "status",
        "resolved_train_config",
        "celery_task_id",
        "result_model_name",
        "result_artifact_hash",
        "result_metrics",
        "registry_result",
        "error_message",
        "requested_at",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    )
