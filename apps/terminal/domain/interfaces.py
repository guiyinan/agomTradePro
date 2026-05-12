"""
Terminal Domain Interfaces - Repository Protocols.

定义仓储接口协议，供基础设施层实现。
"""

from typing import Protocol

from .entities import TerminalAuditEntry, TerminalCommand


class TerminalCommandRepository(Protocol):
    """
    终端命令仓储接口

    定义命令持久化的抽象接口。
    """

    def get_by_id(self, command_id: str) -> TerminalCommand | None:
        """根据ID获取命令"""
        ...

    def get_by_name(self, name: str) -> TerminalCommand | None:
        """根据名称获取命令"""
        ...

    def get_all_active(self) -> list[TerminalCommand]:
        """获取所有活跃命令"""
        ...

    def get_by_category(self, category: str) -> list[TerminalCommand]:
        """按分类获取命令"""
        ...

    def save(self, command: TerminalCommand) -> TerminalCommand:
        """保存命令"""
        ...

    def delete(self, command_id: str) -> bool:
        """删除命令"""
        ...

    def exists_by_name(self, name: str, exclude_id: str | None = None) -> bool:
        """检查名称是否存在"""
        ...


class TerminalAuditRepository(Protocol):
    """终端审计日志仓储接口"""

    def save(self, entry: TerminalAuditEntry) -> TerminalAuditEntry:
        """保存审计条目"""
        ...

    def get_recent(
        self,
        limit: int = 50,
        username: str | None = None,
        command_name: str | None = None,
        result_status: str | None = None,
    ) -> list[TerminalAuditEntry]:
        """获取最近的审计条目"""
        ...
