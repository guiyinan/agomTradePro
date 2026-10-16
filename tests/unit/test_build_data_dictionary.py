"""Data dictionary projection builder extracts ORM models deterministically."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_data_dictionary import (
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    build_data_dictionary,
    render_markdown,
)

SAMPLE_MODELS = '''"""Sample models for extraction tests."""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AbstractAuditModel(models.Model):
    """Abstract audit base."""

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class OrderModel(models.Model):
    """订单模型。

    第二行不应进入投影。
    """

    class Status(models.TextChoices):
        """订单状态。"""

        DRAFT = "draft", "草稿"
        SENT = "sent", "已发送"

    symbol = models.CharField("资产代码", max_length=32, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        help_text=_("状态"),
    )
    owner = models.ForeignKey(
        "account.UserModel",
        on_delete=models.CASCADE,
        related_name="orders",
        null=True,
    )
    note = models.TextField(blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "demo_order"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["symbol", "-updated_at"], name="demo_order_idx")]


class NotAModel:
    pass
'''

SAMPLE_PACKAGE_MODELS = '''"""Models inside a models/ package."""

from django.db import models


class PackageModel(models.Model):
    flag = models.BooleanField(default=False)
'''


def _write_sample_tree(apps_root: Path) -> None:
    infrastructure = apps_root / "demo" / "infrastructure"
    infrastructure.mkdir(parents=True)
    (infrastructure / "models.py").write_text(SAMPLE_MODELS, encoding="utf-8")
    package_dir = infrastructure / "models"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "extra.py").write_text(SAMPLE_PACKAGE_MODELS, encoding="utf-8")
    migrations = infrastructure / "migrations"
    migrations.mkdir()
    (migrations / "0001_initial.py").write_text(
        "from django.db import migrations, models\n\n"
        "class MigrationModel(models.Model):\n"
        "    ghost = models.CharField(max_length=8)\n",
        encoding="utf-8",
    )


def _extract_demo_models(apps_root: Path) -> dict[str, dict[str, object]]:
    payload = build_data_dictionary(apps_root)
    apps = payload["apps"]
    assert isinstance(apps, dict)
    demo = apps["demo"]
    assert isinstance(demo, dict)
    models = demo["models"]
    assert isinstance(models, list)
    return {str(model["class_name"]): model for model in models if isinstance(model, dict)}


def test_extracts_plain_foreign_key_and_meta_fields(tmp_path: Path) -> None:
    """Plain fields, FK targets, and Meta options are captured from source."""

    apps_root = tmp_path / "apps"
    _write_sample_tree(apps_root)

    models = _extract_demo_models(apps_root)
    order = models["OrderModel"]
    assert order["source_file"] == "infrastructure/models.py"
    assert order["docstring"] == "订单模型。"
    assert order["bases"] == ["models.Model"]
    meta = order["meta"]
    assert isinstance(meta, dict)
    assert meta["db_table"] == "demo_order"
    assert meta["ordering"] == ["-updated_at"]
    assert meta["indexes"] == (
        "[models.Index(fields=['symbol', '-updated_at'], name='demo_order_idx')]"
    )

    fields = {str(field["name"]): field for field in order["fields"]}
    symbol = fields["symbol"]
    assert symbol["field_type"] == "CharField"
    assert symbol["positional_args"] == ["'资产代码'"]
    assert symbol["kwargs"]["max_length"] == 32
    assert symbol["db_index"] is True

    owner = fields["owner"]
    assert owner["field_type"] == "ForeignKey"
    assert owner["positional_args"] == ["'account.UserModel'"]
    assert owner["kwargs"]["on_delete"] == "models.CASCADE"
    assert owner["null"] is True

    note = fields["note"]
    assert "null" not in note
    assert "unique" not in note


def test_extracts_abstract_choices_and_non_constant_defaults(tmp_path: Path) -> None:
    """Abstract Meta, TextChoices members, and unparse fallback are captured."""

    apps_root = tmp_path / "apps"
    _write_sample_tree(apps_root)

    models = _extract_demo_models(apps_root)
    abstract = models["AbstractAuditModel"]
    assert abstract["abstract"] is True

    order = models["OrderModel"]
    choices = order["choices_classes"]
    assert isinstance(choices, dict)
    assert choices["Status"] == {"DRAFT": ["draft", "草稿"], "SENT": ["sent", "已发送"]}

    fields = {str(field["name"]): field for field in order["fields"]}
    status = fields["status"]
    assert status["kwargs"]["default"] == "Status.DRAFT"
    assert status["kwargs"]["choices"] == "Status.choices"
    assert status["kwargs"]["help_text"] == "_('状态')"
    updated_at = fields["updated_at"]
    assert updated_at["kwargs"]["default"] == "timezone.now"


def test_scans_models_package_and_skips_migrations(tmp_path: Path) -> None:
    """``models/`` packages are scanned; ``migrations`` content is excluded."""

    apps_root = tmp_path / "apps"
    _write_sample_tree(apps_root)

    models = _extract_demo_models(apps_root)
    assert "PackageModel" in models
    assert models["PackageModel"]["source_file"] == "infrastructure/models/extra.py"
    assert "MigrationModel" not in models
    assert "NotAModel" not in models


def test_committed_json_matches_regeneration() -> None:
    """The committed JSON projection is in sync with the source tree."""

    committed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    assert committed == build_data_dictionary()


def test_committed_markdown_matches_regeneration() -> None:
    """The committed Markdown rendering is in sync with the source tree."""

    committed = DEFAULT_MARKDOWN_OUTPUT.read_text(encoding="utf-8")
    assert committed == render_markdown(build_data_dictionary())
