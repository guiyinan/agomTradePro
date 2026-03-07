"""
Tushare Data Adapter.

Infrastructure layer - fetches data from Tushare Pro API.
"""

import pandas as pd
from datetime import date, timedelta
from typing import List, Optional
import logging

from shared.config.secrets import get_secrets
from .base import (
    BaseMacroAdapter,
    MacroDataPoint,
    DataSourceUnavailableError,
    DataValidationError,
)

logger = logging.getLogger(__name__)


class TushareAdapter(BaseMacroAdapter):
    """
    Tushare Pro 数据适配器

    支持的数据：
    - SHIBOR 利率
    - 指数日线数据（上证指数、深证成指等）
    """

    source_name = "tushare"

    def __init__(self, token: Optional[str] = None):
        """
        Args:
            token: Tushare Pro Token（如果不提供，从环境变量读取）
        """
        if token is None:
            token = get_secrets().data_sources.tushare_token

        self.token = token
        self._pro = None

    @property
    def pro(self):
        """延迟初始化 tushare pro API"""
        if self._pro is None:
            try:
                import tushare as ts
                self._pro = ts.pro_api(self.token)
                logger.info("Tushare API 初始化成功")
            except ImportError:
                raise DataSourceUnavailableError("tushare 库未安装，请运行: pip install tushare")
            except Exception as e:
                raise DataSourceUnavailableError(f"Tushare API 初始化失败: {e}")
        return self._pro

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持指定指标"""
        return indicator_code in self._get_supported_indicators()

    def _get_supported_indicators(self) -> set[str]:
        """从数据库配置读取支持的指数指标。"""
        supported = {"SHIBOR"}
        try:
            from apps.account.infrastructure.models import SystemSettingsModel

            supported.update(SystemSettingsModel.get_settings().get_macro_index_codes())
        except Exception:
            pass
        return supported

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取指定指标的数据

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 数据点列表
        """
        if not self.supports(indicator_code):
            raise DataSourceUnavailableError(
                f"Tushare 不支持的指标: {indicator_code}，"
                f"支持的指标: {self._get_supported_indicators()}"
            )

        try:
            if indicator_code == "SHIBOR":
                return self._fetch_shibor(start_date, end_date)
            else:
                return self._fetch_index_daily(indicator_code, start_date, end_date)

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            raise DataSourceUnavailableError(f"获取数据失败: {e}")

    def _fetch_shibor(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取 SHIBOR 利率数据

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: SHIBOR 数据点列表
        """
        # Tushare SHIBOR 数据字段
        # date: 日期
        # O/N, 1W, 2W, 1M, 3M, 6M, 9M, 1Y: 各期限利率

        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        df = self.pro.shibor(start_date=start_str, end_date=end_str)

        if df.empty:
            logger.warning(f"SHIBOR 数据为空: {start_date} - {end_date}")
            return []

        # 使用 1W（1周）利率作为代表值
        # 也可以根据需要选择其他期限
        df = df[['date', '1W']].dropna()
        df.columns = ['observed_at', 'value']

        data_points = []
        for _, row in df.iterrows():
            try:
                observed_at = pd.to_datetime(row['observed_at']).date()
                value = float(row['value'])

                point = MacroDataPoint(
                    code="SHIBOR",
                    value=value,
                    observed_at=observed_at,
                    published_at=observed_at,  # SHIBOR 当日发布
                    source=self.source_name
                )
                self._validate_data_point(point)
                data_points.append(point)

            except (ValueError, DataValidationError) as e:
                logger.warning(f"跳过无效数据点: {row}, 错误: {e}")
                continue

        return self._sort_and_deduplicate(data_points)

    def _fetch_index_daily(
        self,
        ts_code: str,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取指数日线数据

        Args:
            ts_code: 指数代码（如 000001.SH）
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 指数数据点列表
        """
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        df = self.pro.index_daily(
            ts_code=ts_code,
            start_date=start_str,
            end_date=end_str
        )

        if df.empty:
            logger.warning(f"指数 {ts_code} 数据为空: {start_date} - {end_date}")
            return []

        # 使用收盘价
        df = df[['trade_date', 'close']]
        df.columns = ['observed_at', 'value']

        data_points = []
        for _, row in df.iterrows():
            try:
                # Tushare 返回的日期是 YYYYMMDD 格式
                observed_at = pd.to_datetime(row['observed_at'], format="%Y%m%d").date()
                value = float(row['value'])

                point = MacroDataPoint(
                    code=ts_code,
                    value=value,
                    observed_at=observed_at,
                    published_at=observed_at,  # 指数当日发布
                    source=self.source_name
                )
                self._validate_data_point(point)
                data_points.append(point)

            except (ValueError, DataValidationError) as e:
                logger.warning(f"跳过无效数据点: {row}, 错误: {e}")
                continue

        return self._sort_and_deduplicate(data_points)

    def fetch_shibor_latest(self) -> Optional[MacroDataPoint]:
        """
        获取最新的 SHIBOR 数据

        Returns:
            Optional[MacroDataPoint]: 最新数据点，无数据返回 None
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=7)  # 最近一周

        data_points = self._fetch_shibor(start_date, end_date)
        return data_points[-1] if data_points else None

    def fetch_index_latest(self, ts_code: str) -> Optional[MacroDataPoint]:
        """
        获取指数最新数据

        Args:
            ts_code: 指数代码

        Returns:
            Optional[MacroDataPoint]: 最新数据点，无数据返回 None
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=7)

        data_points = self._fetch_index_daily(ts_code, start_date, end_date)
        return data_points[-1] if data_points else None
