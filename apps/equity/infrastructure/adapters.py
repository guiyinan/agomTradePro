"""
个股分析模块 Infrastructure 层适配器

实现 Domain 层定义的协议接口，连接外部模块（regime、macro）。
遵循四层架构：Infrastructure 层可以导入其他模块的 ORM 和仓储。
"""

from typing import Dict, List, Optional
from datetime import date
from decimal import Decimal
import logging

from ..domain.ports import RegimeDataPort, MarketDataPort, StockPoolPort

logger = logging.getLogger(__name__)


class RegimeRepositoryAdapter(RegimeDataPort):
    """
    Regime 数据仓储适配器

    适配 regime 模块的 DjangoRegimeRepository，实现 Domain 层定义的协议。
    """

    def __init__(self):
        # 延迟导入，避免循环依赖
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository
        self._regime_repo = DjangoRegimeRepository()

    def get_snapshots_in_range(
        self,
        start_date: date,
        end_date: date
    ) -> List:
        """
        获取日期范围内的 Regime 快照列表

        Args:
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            List[RegimeSnapshot]: 快照列表，按时间升序排列
        """
        return self._regime_repo.get_snapshots_in_range(start_date, end_date)

    def get_snapshot_by_date(
        self,
        observed_at: date
    ) -> Optional:
        """
        按日期获取 Regime 快照

        Args:
            observed_at: 观测日期

        Returns:
            Optional[RegimeSnapshot]: 快照实体，不存在则返回 None
        """
        return self._regime_repo.get_snapshot_by_date(observed_at)


class MarketDataRepositoryAdapter(MarketDataPort):
    """
    市场数据仓储适配器

    从 macro 模块获取指数数据，计算收益率。
    """

    def __init__(self):
        # 延迟导入，避免循环依赖
        from apps.macro.infrastructure.models import MacroIndicator
        self._model = MacroIndicator
        # 默认使用沪深 300 作为市场基准
        self._default_index_code = "000300.SH"

    def get_index_daily_returns(
        self,
        index_code: str,
        start_date: date,
        end_date: date
    ) -> Dict[date, float]:
        """
        获取指数日收益率

        从 MacroIndicator 表获取指数日线价格数据，计算收益率。

        Args:
            index_code: 指数代码（如 000300.SH 表示沪深 300）
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            {日期: 收益率}，收益率以小数表示（如 0.01 表示 1%）
        """
        try:
            # 从 macro_indicator 表获取指数数据
            # 查询指定指数代码在日期范围内的数据
            from django.db.models import Q

            queryset = self._model.objects.filter(
                code=index_code,
                observed_at__gte=start_date,
                observed_at__lte=end_date
            ).order_by('observed_at')

            # 提取数据点
            data_points = []
            for item in queryset:
                if item.value and item.value > 0:
                    data_points.append((item.observed_at, float(item.value)))

            # 计算收益率
            returns = {}
            for i in range(1, len(data_points)):
                prev_date, prev_price = data_points[i - 1]
                curr_date, curr_price = data_points[i]

                if prev_price > 0:
                    daily_return = (curr_price - prev_price) / prev_price
                    returns[curr_date] = daily_return

            return returns

        except Exception as e:
            logger.error(f"获取指数 {index_code} 收益率失败: {e}")
            return {}


class StockPoolRepositoryAdapter(StockPoolPort):
    """
    股票池仓储适配器

    使用 Django 缓存和数据库存储股票池信息。
    """

    def __init__(self):
        from django.core.cache import cache
        self._cache = cache
        self._cache_key_prefix = "equity:stock_pool"

    def get_current_pool(self) -> List[str]:
        """
        获取当前股票池

        Returns:
            股票代码列表
        """
        from django.core.cache import cache

        pool_key = f"{self._cache_key_prefix}:current"
        cached_pool = cache.get(pool_key)

        if cached_pool:
            return cached_pool

        # 如果缓存没有，从数据库读取
        return self._load_pool_from_db()

    def save_pool(
        self,
        stock_codes: List[str],
        regime: str,
        as_of_date: date
    ) -> None:
        """
        保存股票池

        Args:
            stock_codes: 股票代码列表
            regime: 当前的 Regime
            as_of_date: 截止日期
        """
        from django.core.cache import cache
        import json

        # 保存到缓存（24 小时过期）
        pool_key = f"{self._cache_key_prefix}:current"
        cache.set(pool_key, stock_codes, timeout=86400)

        # 保存元数据
        meta_key = f"{self._cache_key_prefix}:meta"
        meta = {
            'regime': regime,
            'as_of_date': as_of_date.isoformat(),
            'count': len(stock_codes),
            'updated_at': date.today().isoformat()
        }
        cache.set(meta_key, json.dumps(meta), timeout=86400)

        # 同时保存到数据库（持久化）
        self._save_pool_to_db(stock_codes, regime, as_of_date)

    def get_latest_pool_info(self) -> Optional[dict]:
        """
        获取最新的股票池信息

        Returns:
            包含股票池元数据的字典，或 None
        """
        from django.core.cache import cache
        import json

        meta_key = f"{self._cache_key_prefix}:meta"
        meta_str = cache.get(meta_key)

        if meta_str:
            return json.loads(meta_str)

        return self._load_pool_meta_from_db()

    def _load_pool_from_db(self) -> List[str]:
        """从数据库加载股票池"""
        try:
            from .models import StockPoolSnapshot

            latest = StockPoolSnapshot.objects.filter(
                is_active=True
            ).order_by('-created_at').first()

            if latest:
                return latest.stock_codes

            return []

        except Exception as e:
            logger.error(f"从数据库加载股票池失败: {e}")
            return []

    def _save_pool_to_db(
        self,
        stock_codes: List[str],
        regime: str,
        as_of_date: date
    ) -> None:
        """保存股票池到数据库"""
        try:
            from .models import StockPoolSnapshot

            # 先将旧的快照设为非活跃
            StockPoolSnapshot.objects.filter(is_active=True).update(is_active=False)

            # 创建新快照
            StockPoolSnapshot.objects.create(
                stock_codes=stock_codes,
                regime=regime,
                as_of_date=as_of_date,
                is_active=True
            )

        except Exception as e:
            logger.error(f"保存股票池到数据库失败: {e}")

    def _load_pool_meta_from_db(self) -> Optional[dict]:
        """从数据库加载股票池元数据"""
        try:
            from .models import StockPoolSnapshot

            latest = StockPoolSnapshot.objects.filter(
                is_active=True
            ).order_by('-created_at').first()

            if latest:
                return {
                    'regime': latest.regime,
                    'as_of_date': latest.as_of_date.isoformat(),
                    'count': len(latest.stock_codes),
                    'updated_at': latest.created_at.date().isoformat()
                }

            return None

        except Exception as e:
            logger.error(f"从数据库加载股票池元数据失败: {e}")
            return None
