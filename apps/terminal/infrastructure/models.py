"""
Terminal Infrastructure Models.

重新导出prompt模块中的TerminalCommandORM，保持向后兼容。
新模块通过仓储层实现解耦。

注意：TerminalCommandORM实际定义在apps.prompt.infrastructure.models中
"""

# 重新导出，保持向后兼容
from apps.prompt.infrastructure.models import TerminalCommandORM

__all__ = ['TerminalCommandORM']