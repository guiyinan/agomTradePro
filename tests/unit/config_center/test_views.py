from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.config_center.infrastructure.models import QlibTrainingRunModel, SystemSettingsModel


@pytest.mark.django_db
def test_qlib_config_center_page_allows_staff_read(tmp_path):
    user = get_user_model().objects.create_user(
        username="config_staff",
        password="pass12345",
        is_staff=True,
    )
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

    client = Client()
    client.force_login(user)
    response = client.get("/settings/config-center/qlib/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Qlib 配置与训练中心" in content
    assert "立即触发训练" in content


@pytest.mark.django_db
def test_qlib_config_center_page_updates_runtime_for_superuser(tmp_path):
    user = get_user_model().objects.create_user(
        username="config_superuser",
        password="pass12345",
        is_staff=True,
        is_superuser=True,
    )
    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)

    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.qlib_provider_uri = str(provider_dir)
    settings_obj.qlib_model_path = str(model_dir)
    settings_obj.save(update_fields=["qlib_provider_uri", "qlib_model_path", "updated_at"])

    client = Client()
    client.force_login(user)
    response = client.post(
        "/settings/config-center/qlib/",
        data={
            "action": "update_runtime",
            "enabled": "on",
            "provider_uri": str(provider_dir),
            "region": "CN",
            "model_root": str(model_dir),
            "default_universe": "csi500",
            "default_feature_set_id": "alpha158",
            "default_label_id": "return_10d",
            "train_queue_name": "qlib_train",
            "infer_queue_name": "qlib_infer",
            "allow_auto_activate": "on",
            "alpha_fixed_provider": "qlib",
            "alpha_pool_mode": "market",
        },
    )

    assert response.status_code == 302
    settings_obj.refresh_from_db()
    assert settings_obj.qlib_enabled is True
    assert settings_obj.qlib_default_universe == "csi500"
    assert settings_obj.qlib_default_feature_set_id == "alpha158"
    assert settings_obj.qlib_default_label_id == "return_10d"


@pytest.mark.django_db
def test_qlib_config_center_page_triggers_training_for_superuser(monkeypatch, tmp_path):
    user = get_user_model().objects.create_user(
        username="train_superuser",
        password="pass12345",
        is_staff=True,
        is_superuser=True,
    )
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
        lambda kwargs, queue: SimpleNamespace(id="task-page-1"),
    )

    client = Client()
    client.force_login(user)
    response = client.post(
        "/settings/config-center/qlib/",
        data={
            "action": "trigger_training",
            "profile_key": "",
            "model_name": "lgb_csi300",
            "model_type": "LGBModel",
            "universe": "csi300",
            "feature_set_id": "v1",
            "label_id": "return_5d",
            "model_params": "{}",
            "extra_train_config": '{"source": "page_test"}',
        },
    )

    assert response.status_code == 302
    run = QlibTrainingRunModel.objects.get(model_name="lgb_csi300")
    assert run.celery_task_id == "task-page-1"
    assert run.status == QlibTrainingRunModel.STATUS_PENDING

