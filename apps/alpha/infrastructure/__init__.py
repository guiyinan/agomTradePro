"""
Alpha Infrastructure Layer

Alpha 信号抽象层的基础设施层实现。
包含数据库模型、仓储实现、适配器等。
"""

from .models import AlphaScoreCacheModel, QlibModelRegistryModel

# Domain layer aliases
AlphaScoreCache = AlphaScoreCacheModel
QlibModelRegistry = QlibModelRegistryModel

__all__ = [
    "AlphaScoreCache",
    "AlphaScoreCacheModel",
    "QlibModelRegistry",
    "QlibModelRegistryModel",
]
