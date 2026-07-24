"""Operational contracts for Alpha model registry management commands."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.alpha.infrastructure.models import QlibModelRegistryModel


def _model(artifact_hash: str, *, active: bool = False) -> QlibModelRegistryModel:
    return QlibModelRegistryModel.objects.create(
        model_name="contract-model",
        artifact_hash=artifact_hash,
        model_type=QlibModelRegistryModel.MODEL_LGB,
        universe="csi300",
        train_config={"seed": 42},
        feature_set_id="features-v1",
        label_id="label-v1",
        data_version="2026-07-24",
        ic="0.081",
        icir="1.42",
        rank_ic="0.077",
        model_path=f"/models/{artifact_hash}.pkl",
        is_active=active,
    )


@pytest.mark.django_db
def test_list_and_activate_model_commands_cover_safe_state_transitions() -> None:
    """Listing filters registry rows and activation never silently replaces a model."""
    output = StringIO()
    call_command("list_models", stdout=output)
    assert "没有找到模型" in output.getvalue()

    first = _model("a" * 64)
    second = _model("b" * 64)
    output = StringIO()
    call_command(
        "list_models",
        model_name="contract",
        universe="csi300",
        active_only=False,
        stdout=output,
    )
    assert "找到 2 个模型" in output.getvalue()
    assert "按模型名称汇总" in output.getvalue()

    output = StringIO()
    call_command("activate_model", "missing", stdout=output)
    assert "模型不存在" in output.getvalue()

    call_command("activate_model", first.artifact_hash, stdout=StringIO())
    first.refresh_from_db()
    assert first.is_active is True
    output = StringIO()
    call_command("activate_model", first.artifact_hash, stdout=output)
    assert "已经是激活状态" in output.getvalue()

    output = StringIO()
    call_command("activate_model", second.artifact_hash, force=False, stdout=output)
    assert "使用 --force" in output.getvalue()
    second.refresh_from_db()
    assert second.is_active is False

    call_command("activate_model", second.artifact_hash, force=True, stdout=StringIO())
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True


@pytest.mark.django_db
def test_rollback_model_command_handles_hash_previous_and_missing_paths() -> None:
    """Rollback supports explicit and previous versions and reports invalid targets."""
    older = _model("c" * 64)
    newer = _model("d" * 64)
    newer.activate("test")

    output = StringIO()
    call_command(
        "rollback_model",
        model_name="contract-model",
        to_hash=None,
        prev=False,
        stdout=output,
    )
    assert "请指定 --to 或 --prev" in output.getvalue()

    call_command(
        "rollback_model",
        model_name="contract-model",
        to_hash=older.artifact_hash,
        prev=False,
        stdout=StringIO(),
    )
    older.refresh_from_db()
    newer.refresh_from_db()
    assert older.is_active is True
    assert newer.is_active is False

    newer.activate("test")
    call_command(
        "rollback_model",
        model_name="contract-model",
        to_hash=None,
        prev=True,
        stdout=StringIO(),
    )
    older.refresh_from_db()
    assert older.is_active is True

    with pytest.raises(Exception, match="模型不存在"):
        call_command(
            "rollback_model",
            model_name="contract-model",
            to_hash="missing",
            prev=False,
            stdout=StringIO(),
        )

    QlibModelRegistryModel.objects.update(is_active=False)
    output = StringIO()
    call_command(
        "rollback_model",
        model_name="contract-model",
        to_hash=None,
        prev=True,
        stdout=output,
    )
    assert "没有激活的模型" in output.getvalue()
