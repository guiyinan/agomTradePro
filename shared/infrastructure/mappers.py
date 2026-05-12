"""
Entity-ORM Mapper Base Classes

提供 Domain Entity 与 Infrastructure ORM Model 之间的双向转换。
遵循四层架构约束：Domain 层不依赖 Django ORM。
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Generic, Optional, TypeVar

TEntity = TypeVar('TEntity')
TModel = TypeVar('TModel')


class EntityMapper(Generic[TEntity, TModel], ABC):
    """
    Entity-ORM Mapper 基类

    职责：
    1. to_entity: ORM Model → Domain Entity
    2. to_model: Domain Entity → ORM Model
    3. batch_to_entities: 批量转换
    4. batch_to_models: 批量转换

    约束：
    - Domain 层不导入此模块
    - 只在 Infrastructure 层使用
    """

    @abstractmethod
    def to_entity(self, model: TModel) -> TEntity:
        """将 ORM Model 转换为 Domain Entity"""
        pass

    @abstractmethod
    def to_model(self, entity: TEntity, model: TModel | None = None) -> TModel:
        """将 Domain Entity 转换为 ORM Model"""
        pass

    def batch_to_entities(self, models: list[TModel]) -> list[TEntity]:
        """批量转换为 Entities"""
        return [self.to_entity(m) for m in models]

    def batch_to_models(self, entities: list[TEntity]) -> list[TModel]:
        """批量转换为 Models"""
        return [self.to_model(e) for e in entities]


class DataclassMapper(EntityMapper[TEntity, TModel], ABC):
    """
    基于 dataclass 的 Mapper 实现

    适用于 Domain Entity 是 dataclass 的场景。
    """

    def _convert_value(self, value, target_type):
        """转换值类型"""
        if value is None:
            return None

        if isinstance(value, target_type):
            return value

        if hasattr(target_type, '__origin__'):
            return value

        if target_type is float and isinstance(value, (int, str, Decimal)):
            return float(value)
        if target_type is int and isinstance(value, (str, float)):
            return int(value)
        if target_type is str and not isinstance(value, str):
            return str(value)
        if target_type is Decimal and isinstance(value, (int, float, str)):
            return Decimal(str(value))

        return value


# Mapper 注册表
_mapper_registry: dict = {}


def register_mapper(entity_class: type, mapper_class: type[EntityMapper]):
    """注册 Mapper"""
    _mapper_registry[entity_class] = mapper_class


def get_mapper(entity_class: type) -> type[EntityMapper] | None:
    """获取 Entity 对应的 Mapper 类"""
    return _mapper_registry.get(entity_class)
