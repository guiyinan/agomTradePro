"""
Terminal Infrastructure Repositories.

仓储实现，负责领域实体与ORM模型之间的转换。
"""

import logging
from typing import Optional

from ..domain.entities import TerminalAuditEntry, TerminalCommand
from ..domain.interfaces import TerminalAuditRepository, TerminalCommandRepository
from .models import TerminalAuditLogORM
from .models import TerminalCommandORM as TerminalCommandModel

logger = logging.getLogger(__name__)


class DjangoTerminalCommandRepository:
    """
    基于Django ORM的终端命令仓储实现
    """

    def get_by_id(self, command_id: str) -> TerminalCommand | None:
        """根据ID获取命令"""
        try:
            model = TerminalCommandModel._default_manager.get(pk=int(command_id))
            return model.to_entity()
        except (TerminalCommandModel.DoesNotExist, ValueError) as e:
            logger.debug(f"Command not found by id: {command_id}, error: {e}")
            return None

    def get_by_name(self, name: str) -> TerminalCommand | None:
        """根据名称获取命令"""
        try:
            model = TerminalCommandModel._default_manager.get(name=name)
            return model.to_entity()
        except TerminalCommandModel.DoesNotExist:
            logger.debug(f"Command not found by name: {name}")
            return None

    def get_all_active(self) -> list[TerminalCommand]:
        """获取所有活跃命令"""
        models = TerminalCommandModel._default_manager.filter(is_active=True)
        return [m.to_entity() for m in models]

    def get_by_category(self, category: str) -> list[TerminalCommand]:
        """按分类获取命令"""
        models = TerminalCommandModel._default_manager.filter(
            category=category,
            is_active=True
        )
        return [m.to_entity() for m in models]

    def get_all(self) -> list[TerminalCommand]:
        """获取所有命令（包括非活跃）"""
        models = TerminalCommandModel._default_manager.all()
        return [m.to_entity() for m in models]

    def save(self, command: TerminalCommand) -> TerminalCommand:
        """保存命令"""
        model = TerminalCommandModel.from_entity(command)
        model.full_clean()
        model.save()
        return model.to_entity()

    def delete(self, command_id: str) -> bool:
        """删除命令"""
        try:
            deleted, _ = TerminalCommandModel._default_manager.filter(pk=int(command_id)).delete()
            return deleted > 0
        except ValueError:
            return False

    def exists_by_name(self, name: str, exclude_id: str | None = None) -> bool:
        """检查名称是否存在"""
        qs = TerminalCommandModel._default_manager.filter(name=name)
        if exclude_id:
            qs = qs.exclude(pk=int(exclude_id))
        return qs.exists()

    def get_filtered_active(
        self,
        enabled_in_terminal: bool = True,
    ) -> list[TerminalCommand]:
        """获取过滤后的活跃命令"""
        qs = TerminalCommandModel._default_manager.filter(
            is_active=True,
            enabled_in_terminal=enabled_in_terminal,
        )
        return [m.to_entity() for m in qs]


class DjangoTerminalAuditRepository:
    """基于 Django ORM 的终端审计日志仓储实现"""

    def save(self, entry: TerminalAuditEntry) -> TerminalAuditEntry:
        """保存审计条目"""
        model = TerminalAuditLogORM(
            user_id=entry.user_id,
            username=entry.username,
            session_id=entry.session_id,
            command_name=entry.command_name,
            risk_level=entry.risk_level,
            mode=entry.mode,
            params_summary=entry.params_summary[:500] if entry.params_summary else '',
            confirmation_required=entry.confirmation_required,
            confirmation_status=entry.confirmation_status,
            result_status=entry.result_status,
            error_message=entry.error_message,
            duration_ms=entry.duration_ms,
        )
        model.save()
        return model.to_entity()

    def get_recent(
        self,
        limit: int = 50,
        username: str | None = None,
        command_name: str | None = None,
        result_status: str | None = None,
    ) -> list[TerminalAuditEntry]:
        """获取最近的审计条目"""
        qs = TerminalAuditLogORM._default_manager.all()
        if username:
            qs = qs.filter(username=username)
        if command_name:
            qs = qs.filter(command_name=command_name)
        if result_status:
            qs = qs.filter(result_status=result_status)
        return [m.to_entity() for m in qs[:limit]]


# 仓储工厂函数
def get_terminal_command_repository() -> TerminalCommandRepository:
    """获取终端命令仓储实例"""
    return DjangoTerminalCommandRepository()


def get_terminal_audit_repository() -> TerminalAuditRepository:
    """获取终端审计日志仓储实例"""
    return DjangoTerminalAuditRepository()
