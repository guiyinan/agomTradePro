from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.config_center.infrastructure.models import (
    AlphaUniverseConfigModel,
    QlibTrainingRunModel,
    SystemSettingsModel,
)
from apps.config_center.infrastructure.repositories import ConfigCenterSettingsRepository


def _activate_typed_qlib_runtime(
    provider_dir: Path,
    model_dir: Path,
) -> dict[str, object]:
    """Publish one complete typed Qlib runtime for Classic compatibility tests."""

    return ConfigCenterSettingsRepository().update_runtime_config(
        {
            "enabled": True,
            "provider_uri": str(provider_dir),
            "region": "CN",
            "model_root": str(model_dir),
            "default_universe": "csi300",
            "default_feature_set_id": "v1",
            "default_label_id": "return_5d",
            "train_queue_name": "qlib_train",
            "infer_queue_name": "qlib_infer",
            "allow_auto_activate": False,
            "alpha_fixed_provider": "",
            "alpha_pool_mode": "strict_valuation",
        },
        actor="pytest",
    )


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
    assert "当前 Classic 页面仅在兼容期内保留" in content
    assert "/tui/?screen=system.qlib-center&amp;action=config_center.qlib_runtime" in content


@pytest.mark.django_db
def test_qlib_tui_screen_exposes_complete_admin_task_contract():
    user = get_user_model().objects.create_user(
        username="qlib_tui_admin",
        password="pass12345",
        is_staff=True,
    )
    QlibTrainingRunModel.objects.create(
        status=QlibTrainingRunModel.STATUS_SUCCEEDED,
        model_name="contract-model",
        model_type="LGBModel",
    )
    client = Client()
    client.force_login(user)

    response = client.get("/api/tui/screens/system.qlib-center/")

    assert response.status_code == 200
    payload = response.json()
    screen = payload["screen"]
    assert screen["key"] == "system.qlib-center"
    assert screen["audience"] == "admin"
    assert screen["default_action_key"] == "config_center.qlib_runtime"
    assert screen["user_experience"]["primary_task"]
    assert screen["user_experience"]["primary_outcome"]
    assert screen["dashboard_panels"][0]["user_priority"] == "p0"

    actions = {action["key"]: action for action in payload["actions"]}
    assert set(actions) >= {
        "config_center.qlib_runtime",
        "config_center.qlib_runtime_update",
        "config_center.alpha_universes",
        "config_center.alpha_universe_members",
        "config_center.alpha_universe_save",
        "config_center.training_profiles",
        "config_center.training_profile_save",
        "config_center.training_runs",
        "config_center.training_run_detail",
        "config_center.training_run_trigger",
    }
    for action_key in (
        "config_center.qlib_runtime_update",
        "config_center.alpha_universe_save",
        "config_center.training_profile_save",
        "config_center.training_run_trigger",
    ):
        assert actions[action_key]["confirmation_required"] is True


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
    runtime_payload = ConfigCenterSettingsRepository().build_runtime_config_payload()
    assert runtime_payload["enabled"] is True
    assert runtime_payload["default_universe"] == "csi500"
    assert runtime_payload["default_feature_set_id"] == "alpha158"
    assert runtime_payload["default_label_id"] == "return_10d"
    settings_obj.refresh_from_db()
    assert settings_obj.qlib_enabled is False


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

    runtime_payload = _activate_typed_qlib_runtime(provider_dir, model_dir)
    assert runtime_payload["enabled"] is True

    monkeypatch.setattr(
        "apps.config_center.application.use_cases.current_app.send_task",
        lambda task_name, kwargs, queue: SimpleNamespace(id="task-page-1"),
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


@pytest.mark.django_db
def test_qlib_config_center_page_saves_alpha_universe_for_superuser():
    user = get_user_model().objects.create_user(
        username="universe_superuser",
        password="pass12345",
        is_staff=True,
        is_superuser=True,
    )

    client = Client()
    client.force_login(user)
    response = client.post(
        "/settings/config-center/qlib/",
        data={
            "action": "save_alpha_universe",
            "universe_id": "manual_universe",
            "name": "手工池",
            "source_type": "manual",
            "stock_codes_text": "688001\n300750",
            "filters_json": "{}",
            "is_active": "on",
            "description": "page test",
        },
    )

    assert response.status_code == 302
    model = AlphaUniverseConfigModel.objects.get(universe_id="manual_universe")
    assert model.stock_codes == ["688001.SH", "300750.SZ"]
