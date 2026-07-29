"""
List Qlib Models Management Command

列出所有 Qlib 模型的 Django 管理命令。
"""

import logging
from argparse import ArgumentParser
from pathlib import PureWindowsPath
from typing import Any, TypedDict

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class ModelSummary(TypedDict):
    """Counts displayed for one model family."""

    total: int
    active: int


def _safe_display(value: object, *, max_length: int = 128) -> str:
    """Return bounded single-line command output."""

    return "".join(
        character if ord(character) >= 32 else " " for character in str(value or "")
    ).strip()[:max_length]


def _artifact_filename(model_path: object) -> str:
    """Display only an artifact filename, never a credential-bearing path."""

    normalized = _safe_display(model_path, max_length=500)
    if not normalized or "://" in normalized:
        return "N/A"
    return _safe_display(PureWindowsPath(normalized).name, max_length=128) or "N/A"


class Command(BaseCommand):
    """
    列出 Qlib 模型命令

    用法:
        python manage.py list_models [options]

    选项:
        --model-name: 按模型名称过滤
        --universe: 按股票池过滤
        --active: 只显示激活的模型
    """

    help = "List all Qlib models"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--model-name",
            type=str,
            dest="model_name",
            help="Filter by model name",
        )
        parser.add_argument(
            "--universe",
            type=str,
            dest="universe",
            help="Filter by universe",
        )
        parser.add_argument(
            "--active",
            action="store_true",
            dest="active_only",
            help="Show only active models",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """执行命令"""
        from apps.alpha.infrastructure.models import QlibModelRegistryModel

        model_name = options.get("model_name")
        universe = options.get("universe")
        active_only = options.get("active_only", False)
        for option_name, value in (("--model-name", model_name), ("--universe", universe)):
            if value is not None and (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 100
                or any(ord(character) < 32 for character in value)
            ):
                raise CommandError(f"{option_name} is invalid")
        if not isinstance(active_only, bool):
            raise CommandError("--active must be boolean")

        # 构建查询
        queryset = QlibModelRegistryModel._default_manager.all()

        if model_name:
            queryset = queryset.filter(model_name__icontains=model_name)

        if universe:
            queryset = queryset.filter(universe=universe)

        if active_only:
            queryset = queryset.filter(is_active=True)

        # 按创建时间排序
        queryset = queryset.order_by("-created_at")

        # 显示结果
        models = list(queryset)

        if not models:
            self.stdout.write(self.style.WARNING("  没有找到模型"))
            return

        self.stdout.write(self.style.SUCCESS(f"  找到 {len(models)} 个模型"))
        self.stdout.write("")

        for model in models:
            active_flag = " [ACTIVE]" if model.is_active else ""
            self.stdout.write(f"  {_safe_display(model.model_name)}{active_flag}")
            self.stdout.write(f"    Hash: {_safe_display(model.artifact_hash, max_length=12)}...")
            self.stdout.write(f"    类型: {_safe_display(model.model_type)}")
            self.stdout.write(f"    股票池: {_safe_display(model.universe)}")
            self.stdout.write(f'    创建: {model.created_at.strftime("%Y-%m-%d %H:%M")}')
            if model.is_active:
                activated = (
                    model.activated_at.strftime("%Y-%m-%d %H:%M") if model.activated_at else "N/A"
                )
                self.stdout.write(
                    f"    激活: {activated} by {_safe_display(model.activated_by or 'N/A')}"
                )
            self.stdout.write(f'    IC: {model.ic if model.ic else "N/A"}')
            self.stdout.write(f'    ICIR: {model.icir if model.icir else "N/A"}')
            self.stdout.write(f"    文件: {_artifact_filename(model.model_path)}")
            self.stdout.write("")

        # 按模型名称汇总
        self.stdout.write(self.style.SUCCESS("  按模型名称汇总:"))
        summary: dict[str, ModelSummary] = {}
        for model in models:
            if model.model_name not in summary:
                summary[model.model_name] = {"total": 0, "active": 0}
            summary[model.model_name]["total"] += 1
            if model.is_active:
                summary[model.model_name]["active"] += 1

        for name, stats in summary.items():
            self.stdout.write(f'    {name}: {stats["total"]} 个版本, ' f'{stats["active"]} 个激活')
