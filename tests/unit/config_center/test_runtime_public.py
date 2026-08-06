from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.config_center.application import runtime_public
from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeProfileStatus,
)

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _profile(*, version: int = 1) -> RuntimeConfigProfile:
    return RuntimeConfigProfile(
        profile_id="profile-1",
        profile_key="data-center-development",
        environment="development",
        version=version,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="profile-hash",
        created_at=NOW,
        activated_at=NOW,
    )


def _snapshot(*, profile_id: str = "profile-1", version: int = 1) -> RuntimeConfigSnapshot:
    return RuntimeConfigSnapshot(
        snapshot_id="snapshot-1",
        profile_id=profile_id,
        profile_key="data-center-development",
        profile_version=version,
        snapshot_hash="snapshot-hash",
        resolved_values={"data_center.provider.failover_tolerance": 0.025},
        generated_at=NOW,
    )


def test_active_runtime_value_requires_profile_snapshot_identity_match(monkeypatch) -> None:
    profile = _profile(version=2)
    snapshot = _snapshot(version=2)
    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _environment: profile)
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )

    assert (
        runtime_public.get_active_runtime_value(
            environment="development",
            definition_key="data_center.provider.failover_tolerance",
        )
        == 0.025
    )


@pytest.mark.parametrize(
    ("snapshot_profile_id", "snapshot_version"),
    [("other-profile", 2), ("profile-1", 1)],
)
def test_active_runtime_value_fails_closed_for_stale_snapshot(
    monkeypatch,
    snapshot_profile_id: str,
    snapshot_version: int,
) -> None:
    profile = _profile(version=2)
    snapshot = _snapshot(profile_id=snapshot_profile_id, version=snapshot_version)
    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _environment: profile)
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )

    assert (
        runtime_public.get_active_runtime_value(
            environment="development",
            definition_key="data_center.provider.failover_tolerance",
        )
        is None
    )


def test_active_runtime_value_rejects_blank_lookup_keys(monkeypatch) -> None:
    called = False

    def _unexpected_lookup(_environment: str) -> RuntimeConfigProfile:
        nonlocal called
        called = True
        return _profile()

    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", _unexpected_lookup)

    assert runtime_public.get_active_runtime_value(environment="", definition_key="key") is None
    assert (
        runtime_public.get_active_runtime_value(environment="development", definition_key="")
        is None
    )
    assert called is False


def test_active_qlib_runtime_config_requires_complete_typed_snapshot(monkeypatch, tmp_path) -> None:
    provider_path = tmp_path / "cn_data"
    provider_path.mkdir()
    values = {
        "alpha.qlib.enabled": True,
        "alpha.qlib.provider_uri": str(provider_path),
        "alpha.qlib.region": "CN",
        "alpha.qlib.model_path": str(tmp_path / "models"),
        "alpha.qlib.default_universe": "csi300",
        "alpha.qlib.default_feature_set_id": "v1",
        "alpha.qlib.default_label_id": "return_5d",
        "alpha.qlib.train_queue_name": "qlib_train",
        "alpha.qlib.infer_queue_name": "qlib_infer",
        "alpha.qlib.allow_auto_activate": False,
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: (
            values.get(definition_key) if environment == "development" else None
        ),
    )

    result = runtime_public.get_active_qlib_runtime_config("development")

    assert result is not None
    assert result["provider_uri"] == str(provider_path)
    assert result["is_configured"] is True


def test_active_domain_runtime_config_requires_complete_typed_snapshot(monkeypatch) -> None:
    values: dict[str, object] = {
        "alpha.runtime.fixed_provider": "",
        "alpha.runtime.pool_mode": "strict_valuation",
        "config_center.market.color_convention": "cn_a_share",
        "config_center.market.benchmark_code_map": {"equity_default_index": "000300.SH"},
        "config_center.market.asset_proxy_code_map": {"A_SHARE_GROWTH": "000300.SH"},
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: (
            values.get(definition_key) if environment == "development" else None
        ),
    )

    result = runtime_public.get_active_domain_runtime_config("development")

    assert result == {
        "alpha_fixed_provider": "",
        "alpha_pool_mode": "strict_valuation",
        "market_color_convention": "cn_a_share",
        "benchmark_code_map": {"equity_default_index": "000300.SH"},
        "asset_proxy_code_map": {"A_SHARE_GROWTH": "000300.SH"},
    }

    values.pop("config_center.market.asset_proxy_code_map")
    assert runtime_public.get_active_domain_runtime_config("development") is None


def test_active_backup_delivery_config_requires_policy_and_secret_refs(monkeypatch) -> None:
    values: dict[str, object] = {
        "backup.enabled": True,
        "backup.recipient_email": "owner@example.test",
        "backup.app_base_url": "https://example.test",
        "backup.mail_from_email": "noreply@example.test",
        "backup.smtp_host": "smtp.example.test",
        "backup.smtp_port": 587,
        "backup.smtp_username": "mailer",
        "backup.smtp_use_tls": True,
        "backup.smtp_use_ssl": False,
        "backup.interval_days": 7,
        "backup.link_ttl_days": 2,
        "backup.password_hint": "vault-a",
        "backup.archive_password": "system_settings.backup_password_encrypted",
        "backup.smtp_password": "system_settings.backup_smtp_password_encrypted",
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: (
            values.get(definition_key) if environment == "development" else None
        ),
    )

    result = runtime_public.get_active_backup_delivery_config("development")

    assert result is not None
    assert result["backup_smtp_port"] == 587
    assert result["backup_archive_password_ref"].startswith("system_settings.")

    values.pop("backup.smtp_password")
    assert runtime_public.get_active_backup_delivery_config("development") is None


@pytest.mark.parametrize(
    "missing_key",
    ["alpha.qlib.provider_uri", "alpha.qlib.allow_auto_activate"],
)
def test_active_qlib_runtime_config_fails_closed_for_partial_or_wrong_snapshot(
    monkeypatch,
    missing_key: str,
) -> None:
    values: dict[str, object] = {
        "alpha.qlib.enabled": True,
        "alpha.qlib.provider_uri": "/missing/provider",
        "alpha.qlib.region": "CN",
        "alpha.qlib.model_path": "/missing/models",
        "alpha.qlib.default_universe": "csi300",
        "alpha.qlib.default_feature_set_id": "v1",
        "alpha.qlib.default_label_id": "return_5d",
        "alpha.qlib.train_queue_name": "qlib_train",
        "alpha.qlib.infer_queue_name": "qlib_infer",
        "alpha.qlib.allow_auto_activate": False,
    }
    values.pop(missing_key)
    if missing_key == "alpha.qlib.allow_auto_activate":
        values[missing_key] = "false"
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: values.get(definition_key),
    )

    assert runtime_public.get_active_qlib_runtime_config("development") is None
