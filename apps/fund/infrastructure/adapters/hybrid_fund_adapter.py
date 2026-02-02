"""
混合基金数据适配器

支持多数据源自动切换和降级策略
"""

import pandas as pd
import logging
from typing import Optional
from datetime import datetime, date

from shared.infrastructure.resilience import (
    retry_on_error,
    cached,
    _health_manager,
    DataSourceUnavailable
)

logger = logging.getLogger(__name__)


class HybridFundAdapter:
    """混合基金数据适配器 - 自动切换数据源"""

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
            from .akshare_fund_adapter import AkShareFundAdapter
            self._akshare_adapter = AkShareFundAdapter()
        return self._akshare_adapter

    @property
    def tushare(self):
        """延迟初始化 Tushare 适配器"""
        if self._tushare_adapter is None:
            if not self.tushare_token:
                raise ValueError("Tushare token 未配置")
            from .tushare_fund_adapter import TushareFundAdapter
            self._tushare_adapter = TushareFundAdapter(self.tushare_token)
        return self._tushare_adapter

    @retry_on_error(
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0,
        exceptions=(ConnectionError, TimeoutError, Exception)
    )
    @cached(ttl=7200)  # 缓存2小时
    def fetch_fund_list_em(self) -> pd.DataFrame:
        """
        获取全部基金列表（带缓存和重试）

        Returns:
            DataFrame: 基金列表
        """
        # 优先使用 AKShare
        try:
            if _health_manager.is_healthy('akshare_fund'):
                logger.info("使用 AKShare 获取基金列表")
                df = self.akshare.fetch_fund_list_em()
                if df is not None and not df.empty:
                    _health_manager.record_success('akshare_fund')
                    return df
                else:
                    _health_manager.record_failure('akshare_fund', '返回空数据')
        except Exception as e:
            _health_manager.record_failure('akshare_fund', str(e))
            logger.warning(f"AKShare 获取基金列表失败: {e}")

        # 降级到 Tushare
        if self.tushare_token and _health_manager.is_healthy('tushare_fund'):
            try:
                logger.info("降级使用 Tushare 获取基金列表")
                df = self.tushare.fetch_fund_list()
                if not df.empty:
                    _health_manager.record_success('tushare_fund')
                    return df
            except Exception as e:
                _health_manager.record_failure('tushare_fund', str(e))
                logger.warning(f"Tushare 获取基金列表失败: {e}")

        raise DataSourceUnavailable("所有数据源均不可用")

    def fetch_fund_info_em(self, fund_code: str) -> pd.DataFrame:
        """
        获取单个基金详细信息

        Args:
            fund_code: 基金代码

        Returns:
            DataFrame: 基金信息
        """
        @cached(ttl=1800, key_func=lambda code: f'fund_info_{code}')
        def _fetch(code: str) -> pd.DataFrame:
            # 尝试 AKShare
            try:
                if _health_manager.is_healthy('akshare_fund'):
                    df = self.akshare.fetch_fund_info_em(code)
                    if df is not None and not df.empty:
                        _health_manager.record_success('akshare_fund')
                        return df
            except Exception as e:
                _health_manager.record_failure('akshare_fund', str(e))

            return pd.DataFrame()

        return _fetch(fund_code)

    def fetch_fund_nav_em(self, fund_code: str) -> pd.DataFrame:
        """
        获取基金净值历史数据

        Args:
            fund_code: 基金代码

        Returns:
            DataFrame: 净值数据
        """
        @cached(ttl=300, key_func=lambda code: f'fund_nav_{code}')
        def _fetch(code: str) -> pd.DataFrame:
            # 尝试 AKShare
            try:
                if _health_manager.is_healthy('akshare_fund'):
                    df = self.akshare.fetch_fund_nav_em(code)
                    if df is not None and not df.empty:
                        _health_manager.record_success('akshare_fund')
                        return df
            except Exception as e:
                _health_manager.record_failure('akshare_fund', str(e))

            return pd.DataFrame()

        return _fetch(fund_code)

    def get_health_status(self) -> dict:
        """获取所有数据源的健康状态"""
        return {
            'akshare_fund': _health_manager.get_health_status('akshare_fund'),
            'tushare_fund': _health_manager.get_health_status('tushare_fund'),
        }
