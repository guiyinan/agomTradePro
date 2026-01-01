"""
Mapper Layer for Domain-ORM Transformation

提供 Domain 实体与 ORM 模型之间的双向转换。
"""

from typing import TypeVar, Generic, Protocol
from abc import ABC, abstractmethod
from dataclasses import replace

# Domain Entities
from apps.macro.domain.entities import MacroIndicator, PeriodType
from apps.regime.domain.entities import RegimeSnapshot, KalmanState
from apps.signal.domain.entities import InvestmentSignal, SignalStatus
from apps.policy.domain.entities import PolicyEvent, PolicyLevel

# ORM Models
from apps.macro.infrastructure.models import MacroIndicator as MacroIndicatorORM
from apps.regime.infrastructure.models import RegimeLog
from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.policy.infrastructure.models import PolicyLog as PolicyLogORM


DomainEntity = TypeVar('DomainEntity')
OrmModel = TypeVar('OrmModel')


class BaseMapper(ABC, Generic[DomainEntity, OrmModel]):
    """基础映射器（Mapper 模式）"""

    @abstractmethod
    def to_domain(self, orm_obj: OrmModel) -> DomainEntity:
        """ORM → Domain"""
        pass

    @abstractmethod
    def to_orm(self, entity: DomainEntity) -> OrmModel:
        """Domain → ORM"""
        pass


class MacroIndicatorMapper(BaseMapper[MacroIndicator, MacroIndicatorORM]):
    """宏观指标映射器"""

    def to_domain(self, orm_obj: MacroIndicatorORM) -> MacroIndicator:
        """ORM → Domain"""
        return MacroIndicator(
            code=orm_obj.code,
            value=float(orm_obj.value),
            reporting_period=orm_obj.reporting_period,
            period_type=PeriodType(orm_obj.period_type) if orm_obj.period_type else PeriodType.DAY,
            published_at=orm_obj.published_at,
            source=orm_obj.source
        )

    def to_orm(self, entity: MacroIndicator) -> MacroIndicatorORM:
        """Domain → ORM"""
        return MacroIndicatorORM(
            code=entity.code,
            value=entity.value,
            reporting_period=entity.reporting_period,
            period_type=entity.period_type.value,
            published_at=entity.published_at,
            source=entity.source
        )


class RegimeSnapshotMapper(BaseMapper[RegimeSnapshot, RegimeLog]):
    """Regime 快照映射器"""

    def to_domain(self, orm_obj: RegimeLog) -> RegimeSnapshot:
        """ORM → Domain"""
        return RegimeSnapshot(
            growth_momentum_z=orm_obj.growth_momentum_z,
            inflation_momentum_z=orm_obj.inflation_momentum_z,
            distribution=orm_obj.distribution,
            dominant_regime=orm_obj.dominant_regime,
            confidence=orm_obj.confidence,
            observed_at=orm_obj.observed_at
        )

    def to_orm(self, entity: RegimeSnapshot) -> RegimeLog:
        """Domain → ORM"""
        return RegimeLog(
            observed_at=entity.observed_at,
            growth_momentum_z=entity.growth_momentum_z,
            inflation_momentum_z=entity.inflation_momentum_z,
            distribution=entity.distribution,
            dominant_regime=entity.dominant_regime,
            confidence=entity.confidence
        )


class InvestmentSignalMapper(BaseMapper[InvestmentSignal, InvestmentSignalModel]):
    """投资信号映射器"""

    def to_domain(self, orm_obj: InvestmentSignalModel) -> InvestmentSignal:
        """ORM → Domain"""
        return InvestmentSignal(
            id=str(orm_obj.id),
            asset_code=orm_obj.asset_code,
            asset_class=orm_obj.asset_class,
            direction=orm_obj.direction,
            logic_desc=orm_obj.logic_desc,
            invalidation_logic=orm_obj.invalidation_logic,
            invalidation_threshold=orm_obj.invalidation_threshold,
            target_regime=orm_obj.target_regime,
            created_at=orm_obj.created_at.date(),
            status=SignalStatus(orm_obj.status),
            rejection_reason=orm_obj.rejection_reason
        )

    def to_orm(self, entity: InvestmentSignal) -> InvestmentSignalModel:
        """Domain → ORM"""
        return InvestmentSignalModel(
            id=int(entity.id) if entity.id else None,
            asset_code=entity.asset_code,
            asset_class=entity.asset_class,
            direction=entity.direction,
            logic_desc=entity.logic_desc,
            invalidation_logic=entity.invalidation_logic,
            invalidation_threshold=entity.invalidation_threshold,
            target_regime=entity.target_regime,
            status=entity.status.value if isinstance(entity.status, SignalStatus) else entity.status,
            rejection_reason=entity.rejection_reason
        )


class PolicyEventMapper(BaseMapper[PolicyEvent, PolicyLogORM]):
    """政策事件映射器"""

    def to_domain(self, orm_obj: PolicyLogORM) -> PolicyEvent:
        """ORM → Domain"""
        return PolicyEvent(
            id=str(orm_obj.id),
            event_date=orm_obj.event_date,
            level=PolicyLevel(orm_obj.level),
            title=orm_obj.title,
            description=orm_obj.description,
            evidence_url=orm_obj.evidence_url
        )

    def to_orm(self, entity: PolicyEvent) -> PolicyLogORM:
        """Domain → ORM"""
        return PolicyLogORM(
            id=int(entity.id) if entity.id else None,
            event_date=entity.event_date,
            level=entity.level.value,
            title=entity.title,
            description=entity.description,
            evidence_url=entity.evidence_url
        )


# Mapper 工厂函数
def get_mapper(domain_type: type) -> BaseMapper:
    """
    根据 Domain 类型获取对应的 Mapper

    Args:
        domain_type: Domain 实体类

    Returns:
        对应的 Mapper 实例

    Raises:
        ValueError: 未知的 Domain 类型
    """
    mappers = {
        MacroIndicator: MacroIndicatorMapper(),
        RegimeSnapshot: RegimeSnapshotMapper(),
        InvestmentSignal: InvestmentSignalMapper(),
        PolicyEvent: PolicyEventMapper(),
    }

    mapper = mappers.get(domain_type)
    if mapper is None:
        raise ValueError(f"No mapper found for domain type: {domain_type}")

    return mapper
