"""
个股分析模块 Infrastructure 层适配器

实现 Domain 层定义的协议接口，连接外部模块（regime、macro）。
遵循四层架构：Infrastructure 层可以导入其他模块的 ORM 和仓储。
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Union

import pandas as pd

from shared.config.secrets import get_secrets

from ..domain.ports import MarketDataPort, RegimeDataPort, StockPoolPort

logger = logging.getLogger(__name__)


class TushareStockAdapter:
    """兼容旧调用方的股票日线适配器。"""

    def __init__(self):
        self._pro = None

    @property
    def pro(self):
        self._ensure_initialized()
        return self._pro

    def _ensure_initialized(self) -> None:
        if self._pro is not None:
            return

        try:
            import tushare as ts
        except ImportError as exc:
            raise ImportError("请安装 tushare: pip install tushare") from exc

        token = get_secrets().data_sources.tushare_token
        if not token:
            raise ValueError("Tushare token 未配置")
        self._pro = ts.pro_api(token)

    def fetch_stock_list(self) -> pd.DataFrame:
        """获取 A 股基础信息。"""
        df = self.pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date",
        )
        if df is None or df.empty:
            return pd.DataFrame()
        if "list_date" in df.columns:
            df["list_date"] = pd.to_datetime(
                df["list_date"], format="%Y%m%d", errors="coerce"
            )
        df = df.rename(columns={"ts_code": "stock_code"})
        return df

    def fetch_daily_data(
        self,
        stock_code: str,
        start_date: str | date | datetime,
        end_date: str | date | datetime,
    ) -> pd.DataFrame:
        """获取股票日线行情。"""
        df = self.pro.daily(
            ts_code=self._normalize_stock_code(stock_code),
            start_date=self._normalize_date(start_date),
            end_date=self._normalize_date(end_date),
            fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        )
        if df is None or df.empty:
            return pd.DataFrame()

        df["trade_date"] = pd.to_datetime(
            df["trade_date"], format="%Y%m%d", errors="coerce"
        )
        return df.sort_values("trade_date").reset_index(drop=True)

    def fetch_stock_info(self, stock_code: str) -> dict:
        """获取单只股票基础信息。"""
        normalized_code = self._normalize_stock_code(stock_code)
        symbol = normalized_code.split(".")[0]

        df = self.pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date",
        )
        if df is None or df.empty:
            return {}

        matched = df[(df["ts_code"] == normalized_code) | (df["symbol"] == symbol)]
        if matched.empty:
            return {}

        info = matched.iloc[0].to_dict()
        if info.get("list_date"):
            info["list_date"] = pd.to_datetime(
                info["list_date"], format="%Y%m%d", errors="coerce"
            )
        return info

    def _normalize_stock_code(self, stock_code: str) -> str:
        code = stock_code.strip().upper()
        if "." in code:
            return code
        if code.startswith("6"):
            return f"{code}.SH"
        if code.startswith(("0", "3")):
            return f"{code}.SZ"
        if code.startswith(("4", "8")):
            return f"{code}.BJ"
        return code

    def _normalize_date(self, value: str | date | datetime) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y%m%d")
        if isinstance(value, date):
            return value.strftime("%Y%m%d")
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"无效日期格式: {value}")
        return parsed.strftime("%Y%m%d")


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
    ) -> list:
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
        from apps.account.infrastructure.models import SystemSettingsModel
        from apps.macro.infrastructure.models import MacroIndicator
        self._model = MacroIndicator
        self._default_index_code = SystemSettingsModel.get_runtime_benchmark_code(
            "equity_default_index"
        )

    def get_index_daily_returns(
        self,
        index_code: str,
        start_date: date,
        end_date: date
    ) -> dict[date, float]:
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

    def get_current_pool(self) -> list[str]:
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
        stock_codes: list[str],
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
        import json

        from django.core.cache import cache

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

    def get_latest_pool_info(self) -> dict | None:
        """
        获取最新的股票池信息

        Returns:
            包含股票池元数据的字典，或 None
        """
        import json

        from django.core.cache import cache

        meta_key = f"{self._cache_key_prefix}:meta"
        meta_str = cache.get(meta_key)

        if meta_str:
            return json.loads(meta_str)

        return self._load_pool_meta_from_db()

    def _load_pool_from_db(self) -> list[str]:
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
        stock_codes: list[str],
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

    def _load_pool_meta_from_db(self) -> dict | None:
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
