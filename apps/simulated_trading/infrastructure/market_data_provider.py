"""
市场数据提供者 - 复用现有系统模块

Infrastructure层:
- 通过shared.config.secrets获取配置
- 支持数据库配置的优先级
- 提供实时/历史价格查询
- 支持缓存优化

注意：
- 当前复用apps.equity和apps.fund的Tushare适配器
- 这些适配器已通过get_secrets()从数据库或环境变量读取配置
- 如果需要更完善的failover，可参考apps.macro的FailoverAdapter实现
"""
from typing import Optional, Dict
from datetime import date, datetime, timedelta
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """
    市场数据提供者

    复用现有系统的Tushare适配器，提供：
    - 股票实时价格
    - 基金实时净值
    - 简单内存缓存

    配置来源（优先级）：
    1. 数据库配置（DataSourceConfig表，按priority排序）
    2. 环境变量（TUSHARE_TOKEN）
    """

    def __init__(self, cache_ttl_minutes: int = 30):
        """
        初始化市场数据提供者

        Args:
            cache_ttl_minutes: 缓存有效期（分钟）
        """
        # 延迟初始化（避免启动时就必须有token）
        self._stock_adapter = None
        self._fund_adapter = None
        self.cache_ttl_minutes = cache_ttl_minutes

        # 简单内存缓存: {asset_code: (price, timestamp)}
        self._price_cache: Dict[str, tuple] = {}

    @property
    def stock_adapter(self):
        """延迟初始化股票适配器"""
        if self._stock_adapter is None:
            from apps.equity.infrastructure.adapters import TushareStockAdapter
            self._stock_adapter = TushareStockAdapter()
        return self._stock_adapter

    @property
    def fund_adapter(self):
        """延迟初始化基金适配器"""
        if self._fund_adapter is None:
            from apps.fund.infrastructure.adapters.tushare_fund_adapter import TushareFundAdapter
            self._fund_adapter = TushareFundAdapter()
        return self._fund_adapter

    def get_price(self, asset_code: str, trade_date: date = None) -> Optional[float]:
        """
        获取资产价格（收盘价）

        数据源优先级：内存缓存 → Tushare日线 → 实时价格缓存（Redis）

        Args:
            asset_code: 资产代码（如 'ASSET_CODE'）
            trade_date: 交易日期（None表示最新）

        Returns:
            价格（元），获取失败返回None
        """
        # 1. 检查内存缓存
        cached_price, cached_time = self._price_cache.get(asset_code, (None, None))
        if cached_price is not None:
            # 检查缓存是否过期
            if timezone.now() - cached_time < timedelta(minutes=self.cache_ttl_minutes):
                logger.debug(f"缓存命中: {asset_code} = {cached_price}")
                return cached_price

        # 2. 根据资产类型选择适配器
        if asset_code.endswith('.SZ') or asset_code.endswith('.SH') or asset_code.endswith('.BJ'):
            # 股票
            price = self._get_stock_price(asset_code, trade_date)
        elif asset_code.endswith('.OF') or asset_code.endswith('.OFC'):
            # 基金
            price = self._get_fund_price(asset_code, trade_date)
        else:
            # 未知类型，尝试作为股票处理
            logger.warning(f"未知资产类型: {asset_code}，尝试作为股票处理")
            price = self._get_stock_price(asset_code, trade_date)

        # 3. Fallback: 尝试从实时价格缓存获取
        if price is None:
            price = self._get_realtime_price(asset_code)

        # 4. 更新内存缓存
        if price is not None:
            self._price_cache[asset_code] = (price, timezone.now())

        return price

    def _get_realtime_price(self, asset_code: str) -> Optional[float]:
        """
        从实时价格缓存（Redis）获取最新价格

        Args:
            asset_code: 资产代码

        Returns:
            最新价格，获取失败返回None
        """
        try:
            from apps.realtime.infrastructure.repositories import RedisRealtimePriceRepository
            repo = RedisRealtimePriceRepository()
            price_data = repo.get_latest_price(asset_code)
            if price_data and price_data.price > 0:
                logger.info(f"实时缓存 fallback: {asset_code} = {price_data.price}")
                return float(price_data.price)
        except Exception as e:
            logger.debug(f"实时缓存获取失败: {asset_code}, {e}")
        return None

    def _get_stock_price(self, stock_code: str, trade_date: date = None) -> Optional[float]:
        """
        获取股票价格

        Args:
            stock_code: 股票代码
            trade_date: 交易日期（None表示最新）

        Returns:
            收盘价（元）
        """
        try:
            if trade_date is None:
                # 获取最新价格（最近一个交易日）
                trade_date = date.today()
                end_date = trade_date.strftime('%Y%m%d')
                # 往前推7天，确保能获取到数据
                start_date = (trade_date - timedelta(days=7)).strftime('%Y%m%d')
            else:
                start_date = trade_date.strftime('%Y%m%d')
                end_date = trade_date.strftime('%Y%m%d')

            # 调用TushareStockAdapter获取日线数据
            # 注意：此适配器已通过get_secrets()从数据库或环境变量读取token
            df = self.stock_adapter.fetch_daily_data(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date
            )

            if df.empty:
                logger.warning(f"未获取到数据: {stock_code} @ {trade_date}")
                return None

            # 获取最后一行的收盘价
            latest = df.iloc[-1]
            price = float(latest['close'])

            logger.debug(f"获取股票价格: {stock_code} = {price} @ {latest['trade_date'].date()}")
            return price

        except Exception as e:
            logger.error(f"获取股票价格失败: {stock_code}, 错误: {e}")
            return None

    def _get_fund_price(self, fund_code: str, trade_date: date = None) -> Optional[float]:
        """
        获取基金净值

        Args:
            fund_code: 基金代码
            trade_date: 交易日期

        Returns:
            单位净值（元）
        """
        try:
            if trade_date is None:
                trade_date = date.today()
                end_date = trade_date.strftime('%Y%m%d')
                start_date = (trade_date - timedelta(days=7)).strftime('%Y%m%d')
            else:
                start_date = trade_date.strftime('%Y%m%d')
                end_date = trade_date.strftime('%Y%m%d')

            # 调用TushareFundAdapter获取净值数据
            df = self.fund_adapter.fetch_fund_daily(
                fund_code=fund_code,
                start_date=start_date,
                end_date=end_date
            )

            if df.empty:
                logger.warning(f"未获取到基金净值: {fund_code} @ {trade_date}")
                return None

            # 获取最后一行的单位净值
            latest = df.iloc[-1]
            nav = float(latest['unit_nav'])

            logger.debug(f"获取基金净值: {fund_code} = {nav} @ {latest['end_date']}")
            return nav

        except Exception as e:
            logger.error(f"获取基金净值失败: {fund_code}, 错误: {e}")
            return None

    def get_latest_price(self, asset_code: str) -> Optional[float]:
        """
        获取最新价格（快捷方法）

        Args:
            asset_code: 资产代码

        Returns:
            最新价格
        """
        return self.get_price(asset_code, trade_date=None)

    def clear_cache(self):
        """清空价格缓存"""
        self._price_cache.clear()
        logger.info("价格缓存已清空")

    def get_batch_prices(self, asset_codes: list, trade_date: date = None) -> Dict[str, Optional[float]]:
        """
        批量获取价格

        Args:
            asset_codes: 资产代码列表
            trade_date: 交易日期

        Returns:
            {asset_code: price}
        """
        prices = {}
        for code in asset_codes:
            prices[code] = self.get_price(code, trade_date)
        return prices
