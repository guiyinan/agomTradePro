from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User

from apps.config_center.application.use_cases import (
    ConflictError,
    GetQlibRuntimeConfigUseCase,
    TriggerQlibTrainingUseCase,
)
from apps.config_center.infrastructure.models import QlibTrainingRunModel, SystemSettingsModel


@pytest.mark.django_db
def test_get_runtime_config_use_case_exposes_training_state(tmp_path):
    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)

    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.qlib_enabled = True
    settings_obj.qlib_provider_uri = str(provider_dir)
    settings_obj.qlib_model_path = str(model_dir)
    settings_obj.save(
        update_fields=[
            "qlib_enabled",
            "qlib_provider_uri",
            "qlib_model_path",
            "updated_at",
        ]
    )

    payload = GetQlibRuntimeConfigUseCase().execute()

    assert payload["configured"] is True
    assert payload["enabled"] is True
    assert payload["default_feature_set_id"] == "v1"
    assert payload["training_task_running"] is False


@pytest.mark.django_db
def test_trigger_training_use_case_rejects_when_pending_run_exists(tmp_path):
    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)

    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.qlib_enabled = True
    settings_obj.qlib_provider_uri = str(provider_dir)
    settings_obj.qlib_model_path = str(model_dir)
    settings_obj.save(
        update_fields=[
            "qlib_enabled",
            "qlib_provider_uri",
            "qlib_model_path",
            "updated_at",
        ]
    )

    QlibTrainingRunModel.objects.create(
        model_name="existing_model",
        model_type="LGBModel",
        status=QlibTrainingRunModel.STATUS_PENDING,
        resolved_train_config={},
    )

    with pytest.raises(ConflictError):
        TriggerQlibTrainingUseCase().execute(
            actor=SimpleNamespace(is_authenticated=False),
            payload={
                "model_name": "new_model",
                "model_type": "LGBModel",
            },
        )


@pytest.mark.django_db
def test_trigger_training_use_case_creates_run_and_queues_task(monkeypatch, tmp_path):
    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)

    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.qlib_enabled = True
    settings_obj.qlib_provider_uri = str(provider_dir)
    settings_obj.qlib_model_path = str(model_dir)
    settings_obj.save(
        update_fields=[
            "qlib_enabled",
            "qlib_provider_uri",
            "qlib_model_path",
            "updated_at",
        ]
    )

    monkeypatch.setattr(
        "apps.config_center.application.use_cases.qlib_train_model.apply_async",
        lambda kwargs, queue: SimpleNamespace(id=f"{queue}-task-1"),
    )
    user = User.objects.create_user(username="config_admin", password="pass12345")

    result = TriggerQlibTrainingUseCase().execute(
        actor=user,
        payload={
            "model_name": "lgb_csi300",
            "model_type": "LGBModel",
        },
    )

    run = QlibTrainingRunModel.objects.get(run_id=result["run_id"])

    assert result["task_id"] == "qlib_train-task-1"
    assert result["resolved_train_config"]["feature_set_id"] == "v1"
    assert run.status == QlibTrainingRunModel.STATUS_PENDING
    assert run.celery_task_id == "qlib_train-task-1"
