"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from collections.abc import Callable
from typing import cast

from apps.simulated_trading.domain.entities import (
    FeeConfig,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
)

from .repository_helpers import _require_saved_id


def _save_fee_config_model(model: FeeConfigModel) -> None:
    """Narrow the legacy untyped model override at the ORM boundary."""

    save = cast(Callable[..., None], model.save)
    save()


class FeeConfigMapper:
    """费率配置Mapper - Domain实体 ↔ ORM模型"""

    @staticmethod
    def to_entity(model: FeeConfigModel) -> FeeConfig:
        """ORM模型 → Domain实体"""
        return FeeConfig(
            config_id=model.id,
            config_name=model.config_name,
            asset_type=model.asset_type,
            commission_rate_buy=model.commission_rate_buy,
            commission_rate_sell=model.commission_rate_sell,
            min_commission=model.min_commission,
            stamp_duty_rate=model.stamp_duty_rate,
            transfer_fee_rate=model.transfer_fee_rate,
            min_transfer_fee=model.min_transfer_fee,
            slippage_rate=model.slippage_rate,
            is_default=model.is_default,
            is_active=model.is_active,
            description=model.description,
        )

    @staticmethod
    def to_model(entity: FeeConfig) -> FeeConfigModel:
        """Domain实体 → ORM模型"""
        return FeeConfigModel(
            id=entity.config_id,
            config_name=entity.config_name,
            asset_type=entity.asset_type,
            commission_rate_buy=entity.commission_rate_buy,
            commission_rate_sell=entity.commission_rate_sell,
            min_commission=entity.min_commission,
            stamp_duty_rate=entity.stamp_duty_rate,
            transfer_fee_rate=entity.transfer_fee_rate,
            min_transfer_fee=entity.min_transfer_fee,
            slippage_rate=entity.slippage_rate,
            is_default=entity.is_default,
            is_active=entity.is_active,
            description=entity.description,
        )


class DjangoFeeConfigRepository:
    """费率配置Repository实现"""

    def create_config(
        self,
        config_name: str,
        asset_type: str,
        min_commission: float,
        commission_rate_buy: float = 0.0003,
        commission_rate_sell: float = 0.0003,
        stamp_duty_rate: float = 0.001,
        transfer_fee_rate: float = 0.00002,
        min_transfer_fee: float = 0.0,
        slippage_rate: float = 0.001,
        is_default: bool = False,
        is_active: bool = True,
        description: str = "",
    ) -> FeeConfig:
        """创建费率配置并返回实体（兼容旧接口）。"""
        config = FeeConfig(
            config_id=0,
            config_name=config_name,
            asset_type=asset_type,
            commission_rate_buy=commission_rate_buy,
            commission_rate_sell=commission_rate_sell,
            min_commission=min_commission,
            stamp_duty_rate=stamp_duty_rate,
            transfer_fee_rate=transfer_fee_rate,
            min_transfer_fee=min_transfer_fee,
            slippage_rate=slippage_rate,
            is_default=is_default,
            is_active=is_active,
            description=description,
        )
        config_id = self.save(config)
        created = self.get_by_id(config_id)
        if created is None:
            raise ValueError(f"费率配置创建失败: {config_name}")
        return created

    def save(self, config: FeeConfig) -> int:
        """
        保存费率配置

        Returns:
            配置ID
        """
        if config.config_id == 0:
            # 创建新配置
            model = FeeConfigMapper.to_model(config)
            model.id = None
            _save_fee_config_model(model)
            return _require_saved_id(model.id, "fee config")
        else:
            # 更新现有配置
            model = FeeConfigModel._default_manager.get(id=config.config_id)
            model.config_name = config.config_name
            model.asset_type = config.asset_type
            model.commission_rate_buy = config.commission_rate_buy
            model.commission_rate_sell = config.commission_rate_sell
            model.min_commission = config.min_commission
            model.stamp_duty_rate = config.stamp_duty_rate
            model.transfer_fee_rate = config.transfer_fee_rate
            model.min_transfer_fee = config.min_transfer_fee
            model.slippage_rate = config.slippage_rate
            model.is_default = config.is_default
            model.is_active = config.is_active
            model.description = config.description
            _save_fee_config_model(model)
            return int(config.config_id)

    def get_by_id(self, config_id: int) -> FeeConfig | None:
        """根据ID获取费率配置"""
        try:
            model = FeeConfigModel._default_manager.get(id=config_id)
            return FeeConfigMapper.to_entity(model)
        except FeeConfigModel.DoesNotExist:
            return None

    def get_default_config(self, asset_type: str = "all") -> FeeConfig | None:
        """获取默认费率配置"""
        model = FeeConfigModel._default_manager.filter(
            asset_type=asset_type,
            is_default=True,
            is_active=True,
        ).first()
        if model is None and asset_type != "all":
            model = FeeConfigModel._default_manager.filter(
                asset_type="all",
                is_default=True,
                is_active=True,
            ).first()
        return FeeConfigMapper.to_entity(model) if model is not None else None

    def get_all_configs(self, asset_type: str | None = None) -> list[FeeConfig]:
        """获取所有费率配置"""
        if asset_type:
            models = FeeConfigModel._default_manager.filter(asset_type=asset_type, is_active=True)
        else:
            models = FeeConfigModel._default_manager.filter(is_active=True)
        return [FeeConfigMapper.to_entity(m) for m in models]
