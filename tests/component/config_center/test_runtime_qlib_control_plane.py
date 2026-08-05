from __future__ import annotations

import pytest

from apps.config_center.infrastructure.config_summary_repository import (
    DjangoConfigCenterSummaryRepository,
)


@pytest.mark.django_db
def test_runtime_qlib_summary_prefers_typed_snapshot(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _typed_runtime(environment: str) -> dict[str, object]:
        captured["environment"] = environment
        return {
            "enabled": True,
            "provider_uri": "/srv/qlib/cn_data",
            "region": "CN",
            "model_path": "/srv/qlib/models",
            "default_universe": "csi300",
            "default_feature_set_id": "v1",
            "default_label_id": "return_5d",
            "train_queue_name": "qlib_train",
            "infer_queue_name": "qlib_infer",
            "allow_auto_activate": False,
            "is_configured": True,
        }

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.production")
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.get_active_qlib_runtime_config",
        _typed_runtime,
    )
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.SystemSettingsModel.get_runtime_qlib_config",
        lambda: (_ for _ in ()).throw(AssertionError("legacy SystemSettings path used")),
    )

    result = DjangoConfigCenterSummaryRepository().get_runtime_qlib_config()

    assert result["provider_uri"] == "/srv/qlib/cn_data"
    assert result["is_configured"] is True
    assert captured == {"environment": "production"}


@pytest.mark.django_db
def test_runtime_qlib_summary_blocks_when_snapshot_missing(monkeypatch) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.development")
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.get_active_qlib_runtime_config",
        lambda _environment: None,
    )
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.SystemSettingsModel.get_runtime_qlib_config",
        lambda: (_ for _ in ()).throw(AssertionError("legacy SystemSettings path used")),
    )

    assert DjangoConfigCenterSummaryRepository().get_runtime_qlib_config() == {
        "enabled": False,
        "is_configured": False,
        "status": "blocked",
        "source": "config_center_runtime_profile",
        "must_not_use_for_decision": True,
        "blocked_reason": "runtime_config_snapshot_unavailable",
    }
