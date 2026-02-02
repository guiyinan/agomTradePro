"""
混合股票数据适配器

支持多数据源自动切换和降级策略：
1. AKShare（默认，免费）
2. Tushare（备用，需要token）
3. 本地缓存

功能：
- 自动重试失败的请求
- 自动切换到备用数据源
- 缓存减少重复请求
- 健康状态监控
"""

import pandas as pd
import logging
from typing import Optional, List
from datetime import datetime, date

from shared.infrastructure.resilience import (
    retry_on_error,
    cached,
    _health_manager,
    MaxRetriesExceeded,
    DataSourceUnavailable
)

logger = logging.getLogger(__name__)


class HybridStockAdapter:
    """混合股票数据适配器 - 自动切换数据源"""

    def __init__(self, tushare_token: Optional[str] = None):
        """
        初始化混合适配器

        Args:
            tushare_token: Tushare API token（可选）
        """
        self.tushare_token = tushare_token
        self._akshare_adapter = None
        self._tushare_adapter = None

    @property
    def akshare(self):
        """延迟初始化 AKShare 适配器"""
        if self._akshare_adapter is None:
            from .akshare_stock_adapter import AKShareStockAdapter
            self._akshare_adapter = AKShareStockAdapter()
        return self._akshare_adapter

    @property
    def tushare(self):
        """延迟初始化 Tushare 适配器"""
        if self._tushare_adapter is None:
            if not self.tushare_token:
                raise ValueError("Tushare token 未配置")
            from .tushare_stock_adapter import TushareStockAdapter
            self._tushare_adapter = TushareStockAdapter()
        return self._tushare_adapter

    @retry_on_error(
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0,
        exceptions=(ConnectionError, TimeoutError, Exception)
    )
    @cached(ttl=3600)  # 缓存1小时
    def fetch_stock_list_a(self) -> pd.DataFrame:
        """
        获取全部 A 股列表（带缓存和重试）

        Returns:
            DataFrame with columns:
                stock_code, name, industry, area, market, list_date
        """
        # 优先使用 AKShare
        try:
            if _health_manager.is_healthy('akshare'):
                logger.info("使用 AKShare 获取股票列表")
                df = self.akshare.fetch_stock_list_a()
                if not df.empty:
                    _health_manager.record_success('akshare')
                    return df
                else:
                    _health_manager.record_failure('akshare', '返回空数据')
        except Exception as e:
            _health_manager.record_failure('akshare', str(e))
            logger.warning(f"AKShare 获取股票列表失败: {e}")

        # 降级到 Tushare
        if self.tushare_token and _health_manager.is_healthy('tushare'):
            try:
                logger.info("降级使用 Tushare 获取股票列表")
                df = self.tushare.fetch_stock_list()
                if not df.empty:
                    _health_manager.record_success('tushare')
                    return df
                else:
                    _health_manager.record_failure('tushare', '返回空数据')
            except Exception as e:
                _health_manager.record_failure('tushare', str(e))
                logger.warning(f"Tushare 获取股票列表失败: {e}")

        raise DataSourceUnavailable("所有数据源均不可用")

    def fetch_stock_info(self, stock_code: str) -> dict:
        """
        获取单个股票详细信息（带缓存）

        Args:
            stock_code: 股票代码

        Returns:
            dict: 股票详细信息
        """
        @cached(ttl=1800, key_func=lambda code: f'stock_info_{code}')
        def _fetch(code: str) -> dict:
            # 尝试 AKShare
            try:
                if _health_manager.is_healthy('akshare'):
                    info = self.akshare.fetch_stock_info(code)
                    if info:
                        _health_manager.record_success('akshare')
                        return info
            except Exception as e:
                _health_manager.record_failure('akshare', str(e))

            # 降级到 Tushare
            if self.tushare_token and _health_manager.is_healthy('tushare'):
                try:
                    info = self.tushare.fetch_stock_basic_info(code)
                    if info:
                        _health_manager.record_success('tushare')
                        return info
                except Exception as e:
                    _health_manager.record_failure('tushare', str(e))

            return {}

        return _fetch(stock_code)

    @retry_on_error(max_retries=2, initial_delay=0.5)
    def fetch_daily_data(
        self,
        stock_code: str,
        start_date: str = None,
        end_date: str = None
    ) -> pd.DataFrame:
        """
        获取日线数据（带缓存）

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame: 日线数据
        """
        # 生成缓存键
        cache_key = f"daily_{stock_code}_{start_date}_{end_date}"

        # 尝试从缓存获取
        from shared.infrastructure.resilience import _cache_manager
        cached = _cache_manager.get(cache_key, max_age=300)  # 5分钟缓存
        if cached is not None:
            logger.debug(f"从缓存获取日线数据: {stock_code}")
            return cached

        # 尝试 AKShare
        try:
            if _health_manager.is_healthy('akshare'):
                df = self.akshare.fetch_daily_data(stock_code, start_date, end_date)
                if not df.empty:
                    _health_manager.record_success('akshare')
                    _cache_manager.set(cache_key, df, ttl=300)
                    return df
        except Exception as e:
            _health_manager.record_failure('akshare', str(e))
            logger.warning(f"AKShare 获取日线数据失败: {e}")

        # 降级到 Tushare
        if self.tushare_token and _health_manager.is_healthy('tushare'):
            try:
                df = self.tushare.fetch_daily_data(
                    stock_code,
                    start_date.replace('-', '') if start_date else '',
                    end_date.replace('-', '') if end_date else ''
                )
                if not df.empty:
                    _health_manager.record_success('tushare')
                    _cache_manager.set(cache_key, df, ttl=300)
                    return df
            except Exception as e:
                _health_manager.record_failure('tushare', str(e))
                logger.warning(f"Tushare 获取日线数据失败: {e}")

        return pd.DataFrame()

    @cached(ttl=60)  # 实时行情缓存1分钟
    def fetch_realtime_data(self, stock_code: str) -> dict:
        """
        获取实时行情

        Args:
            stock_code: 股票代码

        Returns:
            dict: 实时行情数据
        """
        # 实时数据优先使用 AKShare（更快）
        try:
            data = self.akshare.fetch_realtime_data(stock_code)
            if data:
                return data
        except Exception as e:
            logger.warning(f"获取实时行情失败: {e}")

        return {}

    def fetch_index_data(self, index_code: str = '000001') -> pd.DataFrame:
        """
        获取指数数据

        Args:
            index_code: 指数代码

        Returns:
            DataFrame: 指数数据
        """
        @cached(ttl=300, key_func=lambda code: f"index_{code}")
        def _fetch(code: str) -> pd.DataFrame:
            # 尝试 AKShare
            try:
                df = self.akshare.fetch_index_data(code)
                if not df.empty:
                    return df
            except Exception as e:
                logger.warning(f"AKShare 获取指数数据失败: {e}")

            return pd.DataFrame()

        return _fetch(index_code)

    def get_health_status(self) -> dict:
        """获取所有数据源的健康状态"""
        return {
            'akshare': _health_manager.get_health_status('akshare'),
            'tushare': _health_manager.get_health_status('tushare'),
        }
