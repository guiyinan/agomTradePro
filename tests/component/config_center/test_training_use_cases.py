from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User

from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.config_center.application.use_cases import (
    ConflictError,
    GetQlibRuntimeConfigUseCase,
    TriggerQlibTrainingUseCase,
)
from apps.config_center.infrastructure.models import QlibTrainingRunModel


def _activate_test_qlib_runtime(tmp_path) -> None:
    """Seed one explicit typed runtime profile for Qlib use-case tests."""

    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)
    bootstrap_values = {
        "data_center.provider.failover_tolerance": 0.01,
        "data_center.provider.enable_failover": True,
        "alpha.qlib.enabled": True,
        "alpha.qlib.provider_uri": str(provider_dir),
        "alpha.qlib.region": "CN",
        "alpha.qlib.model_path": str(model_dir),
        "alpha.qlib.default_universe": "csi300",
        "alpha.qlib.default_feature_set_id": "v1",
        "alpha.qlib.default_label_id": "return_5d",
        "alpha.qlib.train_queue_name": "qlib_train",
        "alpha.qlib.infer_queue_name": "qlib_infer",
        "alpha.qlib.allow_auto_activate": False,
        "alpha.runtime.fixed_provider": "",
        "alpha.runtime.pool_mode": "strict_valuation",
        "config_center.market.color_convention": "cn_a_share",
        "config_center.market.benchmark_code_map": {},
        "config_center.market.asset_proxy_code_map": {},
    }
    activate_runtime_profile_patch(
        environment="development",
        patch={
            key: bootstrap_values[key] for key in bootstrap_values if key.startswith("alpha.qlib.")
        },
        bootstrap_values=bootstrap_values,
        actor="pytest",
        reason="typed qlib test fixture",
    )


@pytest.mark.django_db
def test_get_runtime_config_use_case_exposes_training_state(tmp_path):
    actor = User.objects.create_user(
        username="config_staff_reader",
        password="pass12345",
        is_staff=True,
    )
    _activate_test_qlib_runtime(tmp_path)

    payload = GetQlibRuntimeConfigUseCase().execute(actor=actor)

    assert payload["configured"] is True
    assert payload["enabled"] is True
    assert payload["default_feature_set_id"] == "v1"
    assert payload["training_task_running"] is False


@pytest.mark.django_db
def test_trigger_training_use_case_rejects_when_pending_run_exists(tmp_path):
    actor = User.objects.create_user(
        username="config_superuser_pending",
        password="pass12345",
        is_staff=True,
        is_superuser=True,
    )
    _activate_test_qlib_runtime(tmp_path)

    QlibTrainingRunModel.objects.create(
        model_name="existing_model",
        model_type="LGBModel",
        status=QlibTrainingRunModel.STATUS_PENDING,
        resolved_train_config={},
    )

    with pytest.raises(ConflictError):
        TriggerQlibTrainingUseCase().execute(
            actor=actor,
            payload={
                "model_name": "new_model",
                "model_type": "LGBModel",
            },
        )


@pytest.mark.django_db
def test_trigger_training_use_case_creates_run_and_queues_task(monkeypatch, tmp_path):
    _activate_test_qlib_runtime(tmp_path)

    monkeypatch.setattr(
        "apps.config_center.application.use_cases.current_app.send_task",
        lambda task_name, kwargs, queue: SimpleNamespace(id=f"{queue}-task-1"),
    )
    user = User.objects.create_user(username="config_admin", password="pass12345")
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=["is_staff", "is_superuser"])

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


@pytest.mark.django_db
def test_trigger_training_use_case_rejects_non_superuser(tmp_path):
    actor = User.objects.create_user(
        username="config_staff_only",
        password="pass12345",
        is_staff=True,
        is_superuser=False,
    )
    _activate_test_qlib_runtime(tmp_path)

    with pytest.raises(PermissionError, match="superuser"):
        TriggerQlibTrainingUseCase().execute(
            actor=actor,
            payload={
                "model_name": "lgb_csi300",
                "model_type": "LGBModel",
            },
        )
