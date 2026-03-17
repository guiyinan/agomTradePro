"""
Terminal Infrastructure Repositories.

仓储实现，负责领域实体与ORM模型之间的转换。
"""

from typing import Optional
import logging

from ..domain.entities import TerminalCommand
from ..domain.interfaces import TerminalCommandRepository
from .models import TerminalCommandORM as TerminalCommandModel


logger = logging.getLogger(__name__)


class DjangoTerminalCommandRepository:
    """
    基于Django ORM的终端命令仓储实现
    """
    
    def get_by_id(self, command_id: str) -> Optional[TerminalCommand]:
        """根据ID获取命令"""
        try:
            model = TerminalCommandModel._default_manager.get(pk=int(command_id))
            return model.to_entity()
        except (TerminalCommandModel.DoesNotExist, ValueError) as e:
            logger.debug(f"Command not found by id: {command_id}, error: {e}")
            return None
    
    def get_by_name(self, name: str) -> Optional[TerminalCommand]:
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
    
    def exists_by_name(self, name: str, exclude_id: Optional[str] = None) -> bool:
        """检查名称是否存在"""
        qs = TerminalCommandModel._default_manager.filter(name=name)
        if exclude_id:
            qs = qs.exclude(pk=int(exclude_id))
        return qs.exists()


# 仓储工厂函数
def get_terminal_command_repository() -> TerminalCommandRepository:
    """获取终端命令仓储实例"""
    return DjangoTerminalCommandRepository()
