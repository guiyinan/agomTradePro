"""
Django Management Command: Initialize Prompt Templates

Usage:
    python manage.py init_prompt_templates
    python manage.py init_prompt_templates --force
    python manage.py init_prompt_templates --chains-only
    python manage.py init_prompt_templates --templates-only

Options:
    --force: Force reload all templates (overwrite existing)
    --chains-only: Only load chain configurations
    --templates-only: Only load prompt templates
    --dry-run: Show what would be loaded without loading
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.prompt.infrastructure.fixtures.templates import (
    get_predefined_chains,
    get_predefined_templates,
)
from apps.prompt.infrastructure.models import ChainConfigORM, PromptTemplateORM
from apps.prompt.infrastructure.repositories import DjangoChainRepository, DjangoPromptRepository


class Command(BaseCommand):
    help = "初始化预定义的Prompt模板和链配置"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            dest="force",
            help="强制重新加载所有模板（覆盖已存在的）",
        )
        parser.add_argument(
            "--chains-only",
            action="store_true",
            dest="chains_only",
            help="只加载链配置",
        )
        parser.add_argument(
            "--templates-only",
            action="store_true",
            dest="templates_only",
            help="只加载Prompt模板",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="显示将要加载的内容但不实际加载",
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Validate options and initialize the selected fixtures atomically."""

        del args
        force = self._boolean_option(options, "force")
        chains_only = self._boolean_option(options, "chains_only")
        templates_only = self._boolean_option(options, "templates_only")
        dry_run = self._boolean_option(options, "dry_run")
        if chains_only and templates_only:
            raise CommandError("--chains-only and --templates-only are mutually exclusive")

        self.stdout.write(self.style.SUCCESS("\n========================================"))
        self.stdout.write(self.style.SUCCESS("  AgomTradePro Prompt模板初始化工具"))
        self.stdout.write(self.style.SUCCESS("========================================\n"))

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN 模式 - 不会实际写入数据库\n"))

        template_count = 0
        chain_count = 0
        template_skipped = 0
        chain_skipped = 0
        try:
            with transaction.atomic():
                if not chains_only:
                    self.stdout.write(">>> 加载Prompt模板...")
                    template_count, template_skipped = self.load_templates(force, dry_run)
                if not templates_only:
                    self.stdout.write(">>> 加载链配置...")
                    chain_count, chain_skipped = self.load_chains(force, dry_run)
        except Exception as exc:
            raise CommandError(f"Prompt initialization failed ({type(exc).__name__})") from exc

        self.stdout.write("\n" + "=" * 40)
        self.stdout.write(self.style.SUCCESS("初始化完成!"))
        self.stdout.write("=" * 40)
        if not chains_only:
            self.stdout.write(
                f"  Prompt模板: {template_count} 个已加载, {template_skipped} 个已跳过"
            )
        if not templates_only:
            self.stdout.write(f"  链配置: {chain_count} 个已加载, {chain_skipped} 个已跳过")
        self.stdout.write("=" * 40 + "\n")

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    "提示: 使用 `python manage.py init_prompt_templates --force` 强制重新加载"
                )
            )
        self.stdout.write("")

    @staticmethod
    def _boolean_option(options: dict[str, Any], name: str) -> bool:
        """Return one strict boolean management option."""

        value = options.get(name, False)
        if not isinstance(value, bool):
            raise CommandError(f"{name} must be a boolean")
        return value

    def load_templates(self, force: bool, dry_run: bool) -> tuple[int, int]:
        """Create, update, preview, or preserve governed prompt templates."""

        templates = get_predefined_templates()
        repository = DjangoPromptRepository()
        count = 0
        skipped = 0

        for template in templates:
            existing_orm = PromptTemplateORM._default_manager.filter(name=template.name).first()
            if existing_orm:
                if force:
                    if dry_run:
                        self.stdout.write(f"  [FORCE] {template.name} - 将覆盖")
                    else:
                        template_id = existing_orm.pk
                        if (
                            template_id is None
                            or repository.update_template(int(template_id), template) is None
                        ):
                            raise RuntimeError("prompt template update was rejected")
                        self.stdout.write(self.style.SUCCESS(f"  [更新] {template.name}"))
                    count += 1
                else:
                    self.stdout.write(f"  [跳过] {template.name} - 已存在")
                    skipped += 1
            else:
                if dry_run:
                    self.stdout.write(f"  [新建] {template.name}")
                else:
                    repository.create_template(template)
                    self.stdout.write(self.style.SUCCESS(f"  [新建] {template.name}"))
                count += 1

        return count, skipped

    def load_chains(self, force: bool, dry_run: bool) -> tuple[int, int]:
        """Create, update, preview, or preserve governed prompt chains."""

        chains = get_predefined_chains()
        repository = DjangoChainRepository()
        count = 0
        skipped = 0

        for chain in chains:
            existing_orm = ChainConfigORM._default_manager.filter(name=chain.name).first()
            if existing_orm:
                if force:
                    if dry_run:
                        self.stdout.write(f"  [FORCE] {chain.name} - 将覆盖")
                    else:
                        chain_id = existing_orm.pk
                        if (
                            chain_id is None
                            or repository.update_chain(int(chain_id), chain) is None
                        ):
                            raise RuntimeError("prompt chain update was rejected")
                        self.stdout.write(self.style.SUCCESS(f"  [更新] {chain.name}"))
                    count += 1
                else:
                    self.stdout.write(f"  [跳过] {chain.name} - 已存在")
                    skipped += 1
            else:
                if dry_run:
                    self.stdout.write(f"  [新建] {chain.name}")
                else:
                    repository.create_chain(chain)
                    self.stdout.write(self.style.SUCCESS(f"  [新建] {chain.name}"))
                count += 1

        return count, skipped


# 为了向后兼容，保留旧的加载函数
def load_predefined_templates(repository: DjangoPromptRepository | None = None) -> int:
    """
    向后兼容函数：加载预定义模板

    Args:
        repository: DjangoPromptRepository实例（可选）

    Returns:
        成功加载的模板数量
    """
    if repository is None:
        repository = DjangoPromptRepository()

    import io
    from contextlib import redirect_stdout

    from django.core.management import call_command

    # 捕获命令输出
    f = io.StringIO()
    with redirect_stdout(f):
        call_command("init_prompt_templates", "--templates-only", "--force")

    # 返回模板数量
    return len(get_predefined_templates())


def load_predefined_chains(repository: DjangoChainRepository | None = None) -> int:
    """
    向后兼容函数：加载预定义链配置

    Args:
        repository: DjangoChainRepository实例（可选）

    Returns:
        成功加载的链配置数量
    """
    if repository is None:
        repository = DjangoChainRepository()

    import io
    from contextlib import redirect_stdout

    from django.core.management import call_command

    # 捕获命令输出
    f = io.StringIO()
    with redirect_stdout(f):
        call_command("init_prompt_templates", "--chains-only", "--force")

    # 返回链配置数量
    return len(get_predefined_chains())
