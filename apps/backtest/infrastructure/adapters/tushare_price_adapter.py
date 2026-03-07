"""
Tushare Asset Price Adapter.

使用 Tushare Pro API 获取资产价格数据。
"""

import logging
from datetime import date, timedelta
from typing import Optional

from shared.config.secrets import get_secrets
try:
    import tushare as ts
except ImportError:
    ts = None

from .base import (
    BaseAssetPriceAdapter,
    AssetPricePoint,
    AssetPriceUnavailableError,
    AssetPriceValidationError,
    get_asset_class_tickers,
)

logger = logging.getLogger(__name__)


def get_tushare_asset_tickers() -> dict[str, Optional[str]]:
    """Tushare 可支持的资产代理代码映射。"""
    configured = get_asset_class_tickers()
    return {
        "a_share_growth": configured.get("a_share_growth"),
        "a_share_value": configured.get("a_share_value"),
        "china_bond": None,
        "gold": None,
        "commodity": None,
        "cash": "CASH",
    }


class TushareAssetPriceAdapter(BaseAssetPriceAdapter):
    """
    Tushare 资产价格适配器

    支持获取股票指数的日线数据。
    对于不支持的资产类别（债券、黄金、商品），返回 None。
    """

    source_name = "tushare"

    def __init__(self, token: Optional[str] = None):
        """
        初始化 Tushare 适配器

        Args:
            token: Tushare Pro API token，如果为 None 则从配置读取
        """
        if ts is None:
            raise ImportError("tushare 库未安装，请运行: pip install tushare")

        self._token = token or get_secrets().data_sources.tushare_token
        self._pro = None

    def _get_pro(self):
        """获取 Tushare Pro API 实例（延迟初始化）"""
        if self._pro is None:
            if not self._token:
                raise AssetPriceUnavailableError("Tushare token 未配置")
            self._pro = ts.pro_api(self._token)
        return self._pro

    def supports(self, asset_class: str) -> bool:
        """检查是否支持指定资产类别"""
        # 现金总是支持
        if asset_class == "cash":
            return True
        # 检查是否在支持列表中且有对应的 ticker
        ticker = get_tushare_asset_tickers().get(asset_class)
        return ticker is not None

    def get_price(
        self,
        asset_class: str,
        as_of_date: date
    ) -> Optional[float]:
        """
        获取指定资产在指定日期的价格

        Args:
            asset_class: 资产类别
            as_of_date: 查询日期

        Returns:
            Optional[float]: 收盘价，如果不支持或不可用则返回 None
        """
        # 现金固定为 1.0
        if asset_class == "cash":
            return 1.0

        # 检查是否支持
        if not self.supports(asset_class):
            logger.warning(f"Tushare 不支持资产类别: {asset_class}")
            return None

        ticker = get_tushare_asset_tickers()[asset_class]

        try:
            pro = self._get_pro()

            # 获取指定日期的收盘价
            # 注意：Tushare 的日线数据包含交易日历，如果查询日期非交易日，需要向前查找
            df = pro.index_daily(
                ts_code=ticker,
                start_date=as_of_date.strftime("%Y%m%d"),
                end_date=as_of_date.strftime("%Y%m%d")
            )

            if df is None or df.empty:
                # 如果指定日期没有数据，尝试向前查找最近的交易日
                df = pro.index_daily(
                    ts_code=ticker,
                    start_date=(as_of_date - timedelta(days=10)).strftime("%Y%m%d"),
                    end_date=as_of_date.strftime("%Y%m%d")
                )
                if df is not None and not df.empty:
                    # 返回最近一个交易日的收盘价
                    return float(df.iloc[-1]['close'])
                return None

            return float(df.iloc[0]['close'])

        except Exception as e:
            logger.error(f"获取 {asset_class} 在 {as_of_date} 的价格失败: {e}")
            raise AssetPriceUnavailableError(f"获取价格失败: {e}") from e

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date
    ) -> list[AssetPricePoint]:
        """
        获取指定资产在日期范围内的价格序列

        Args:
            asset_class: 资产类别
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[AssetPricePoint]: 价格数据点列表
        """
        # 现金：生成每日固定价格
        if asset_class == "cash":
            points = []
            current = start_date
            while current <= end_date:
                points.append(AssetPricePoint(
                    asset_class=asset_class,
                    price=1.0,
                    as_of_date=current,
                    source=self.source_name
                ))
                current += timedelta(days=1)
            return points

        # 检查是否支持
        if not self.supports(asset_class):
            logger.warning(f"Tushare 不支持资产类别: {asset_class}")
            return []

        ticker = get_tushare_asset_tickers()[asset_class]

        try:
            pro = self._get_pro()

            # 获取日期范围内的日线数据
            df = pro.index_daily(
                ts_code=ticker,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d")
            )

            if df is None or df.empty:
                return []

            # 转换为 AssetPricePoint 列表
            points = []
            for _, row in df.iterrows():
                trade_date = date.fromisoformat(row['trade_date'])
                points.append(AssetPricePoint(
                    asset_class=asset_class,
                    price=float(row['close']),
                    as_of_date=trade_date,
                    source=self.source_name
                ))

            return points

        except Exception as e:
            logger.error(f"获取 {asset_class} 从 {start_date} 到 {end_date} 的价格序列失败: {e}")
            raise AssetPriceUnavailableError(f"获取价格序列失败: {e}") from e
