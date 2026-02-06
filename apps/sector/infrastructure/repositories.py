"""
板块分析模块 - 数据仓储实现

遵循项目架构约束：
- 实现 Domain 层定义的接口
- 封装 Django ORM 调用
- 返回 Domain 层实体
"""

from typing import List, Dict, Optional, Tuple
from datetime import date, timedelta
from decimal import Decimal

from django.db import models
from django.core.cache import cache

from .models import (
    SectorInfoModel,
    SectorIndexModel,
    SectorConstituentModel,
    SectorRelativeStrengthModel
)
from ..domain.entities import SectorInfo, SectorIndex, SectorRelativeStrength


class DjangoSectorRepository:
    """Django ORM 板块数据仓储

    职责：
    1. 板块基本信息 CRUD
    2. 板块指数数据 CRUD
    3. 板块成分股关系 CRUD
    4. 相对强弱指标 CRUD
    """

    # ===== 板块基本信息 =====

    def get_sector_info(self, sector_code: str) -> Optional[SectorInfo]:
        """获取板块基本信息

        Args:
            sector_code: 板块代码

        Returns:
            SectorInfo 或 None
        """
        try:
            model = SectorInfoModel._default_manager.get(sector_code=sector_code, is_active=True)
            return SectorInfo(
                sector_code=model.sector_code,
                sector_name=model.sector_name,
                level=model.level,
                parent_code=model.parent_code
            )
        except SectorInfoModel.DoesNotExist:
            return None

    def get_all_sectors(
        self,
        level: Optional[str] = None
    ) -> List[SectorInfo]:
        """获取所有板块信息

        Args:
            level: 板块级别过滤（SW1/SW2/SW3）

        Returns:
            SectorInfo 列表
        """
        queryset = SectorInfoModel._default_manager.filter(is_active=True)

        if level:
            queryset = queryset.filter(level=level)

        sectors = []
        for model in queryset:
            sectors.append(SectorInfo(
                sector_code=model.sector_code,
                sector_name=model.sector_name,
                level=model.level,
                parent_code=model.parent_code
            ))

        return sectors

    def save_sector_info(
        self,
        sector_info: SectorInfo
    ) -> bool:
        """保存板块基本信息

        Args:
            sector_info: 板块信息实体

        Returns:
            是否成功
        """
        try:
            SectorInfoModel._default_manager.update_or_create(
                sector_code=sector_info.sector_code,
                defaults={
                    'sector_name': sector_info.sector_name,
                    'level': sector_info.level,
                    'parent_code': sector_info.parent_code,
                    'is_active': True
                }
            )
            return True
        except Exception as e:
            print(f"保存板块信息失败: {e}")
            return False

    # ===== 板块指数数据 =====

    def get_sector_index(
        self,
        sector_code: str,
        trade_date: date
    ) -> Optional[SectorIndex]:
        """获取板块指数数据

        Args:
            sector_code: 板块代码
            trade_date: 交易日期

        Returns:
            SectorIndex 或 None
        """
        try:
            model = SectorIndexModel._default_manager.get(
                sector_code=sector_code,
                trade_date=trade_date
            )
            return SectorIndex(
                sector_code=model.sector_code,
                trade_date=model.trade_date,
                open_price=model.open_price,
                high=model.high,
                low=model.low,
                close=model.close,
                volume=model.volume,
                amount=model.amount,
                change_pct=model.change_pct,
                turnover_rate=model.turnover_rate
            )
        except SectorIndexModel.DoesNotExist:
            return None

    def get_sector_index_range(
        self,
        sector_code: str,
        start_date: date,
        end_date: date
    ) -> List[SectorIndex]:
        """获取板块指数时间范围数据

        Args:
            sector_code: 板块代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            SectorIndex 列表
        """
        queryset = SectorIndexModel._default_manager.filter(
            sector_code=sector_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date
        ).order_by('trade_date')

        indices = []
        for model in queryset:
            indices.append(SectorIndex(
                sector_code=model.sector_code,
                trade_date=model.trade_date,
                open_price=model.open_price,
                high=model.high,
                low=model.low,
                close=model.close,
                volume=model.volume,
                amount=model.amount,
                change_pct=model.change_pct,
                turnover_rate=model.turnover_rate
            ))

        return indices

    def save_sector_index(
        self,
        sector_index: SectorIndex
    ) -> bool:
        """保存板块指数数据

        Args:
            sector_index: 板块指数实体

        Returns:
            是否成功
        """
        try:
            SectorIndexModel._default_manager.update_or_create(
                sector_code=sector_index.sector_code,
                trade_date=sector_index.trade_date,
                defaults={
                    'open_price': sector_index.open_price,
                    'high': sector_index.high,
                    'low': sector_index.low,
                    'close': sector_index.close,
                    'volume': sector_index.volume,
                    'amount': sector_index.amount,
                    'change_pct': sector_index.change_pct,
                    'turnover_rate': sector_index.turnover_rate
                }
            )
            return True
        except Exception as e:
            print(f"保存板块指数失败: {e}")
            return False

    def get_latest_sector_index(self, sector_code: str) -> Optional[SectorIndex]:
        """获取板块最新指数数据

        Args:
            sector_code: 板块代码

        Returns:
            SectorIndex 或 None
        """
        try:
            model = SectorIndexModel._default_manager.filter(
                sector_code=sector_code
            ).order_by('-trade_date').first()

            if model:
                return SectorIndex(
                    sector_code=model.sector_code,
                    trade_date=model.trade_date,
                    open_price=model.open_price,
                    high=model.high,
                    low=model.low,
                    close=model.close,
                    volume=model.volume,
                    amount=model.amount,
                    change_pct=model.change_pct,
                    turnover_rate=model.turnover_rate
                )
            return None
        except Exception as e:
            print(f"获取板块最新指数失败: {e}")
            return None

    # ===== 相对强弱指标 =====

    def save_relative_strength(
        self,
        rs: SectorRelativeStrength
    ) -> bool:
        """保存相对强弱指标

        Args:
            rs: 相对强弱实体

        Returns:
            是否成功
        """
        try:
            SectorRelativeStrengthModel._default_manager.update_or_create(
                sector_code=rs.sector_code,
                trade_date=rs.trade_date,
                defaults={
                    'relative_strength': rs.relative_strength,
                    'momentum': rs.momentum,
                    'beta': rs.beta
                }
            )
            return True
        except Exception as e:
            print(f"保存相对强弱指标失败: {e}")
            return False

    def get_relative_strength(
        self,
        sector_code: str,
        trade_date: date
    ) -> Optional[SectorRelativeStrength]:
        """获取相对强弱指标

        Args:
            sector_code: 板块代码
            trade_date: 交易日期

        Returns:
            SectorRelativeStrength 或 None
        """
        try:
            model = SectorRelativeStrengthModel._default_manager.get(
                sector_code=sector_code,
                trade_date=trade_date
            )
            return SectorRelativeStrength(
                sector_code=model.sector_code,
                trade_date=model.trade_date,
                relative_strength=model.relative_strength,
                momentum=model.momentum,
                beta=model.beta
            )
        except SectorRelativeStrengthModel.DoesNotExist:
            return None

    # ===== 辅助方法 =====

    def batch_save_sector_indices(self, indices_df) -> int:
        """批量保存板块指数数据

        Args:
            indices_df: Pandas DataFrame，包含板块指数数据

        Returns:
            成功保存的记录数
        """
        count = 0
        for _, row in indices_df.iterrows():
            try:
                SectorIndexModel._default_manager.update_or_create(
                    sector_code=row['sector_code'],
                    trade_date=row['trade_date'],
                    defaults={
                        'open_price': row['open_price'],
                        'high': row['high'],
                        'low': row['low'],
                        'close': row['close'],
                        'volume': row['volume'],
                        'amount': row['amount'],
                        'change_pct': row['change_pct'],
                        'turnover_rate': row.get('turnover_rate')
                    }
                )
                count += 1
            except Exception as e:
                print(f"批量保存失败: {e}")
                continue

        return count

