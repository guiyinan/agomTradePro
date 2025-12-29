"""
AKShare Data Adapter.

Infrastructure layer - fetches China macro data from AKShare.
"""

import pandas as pd
from datetime import date, timedelta
from typing import List, Optional
import logging

from .base import (
    BaseMacroAdapter,
    MacroDataPoint,
    DataSourceUnavailableError,
    DataValidationError,
)

logger = logging.getLogger(__name__)


class AKShareAdapter(BaseMacroAdapter):
    """
    AKShare 数据适配器

    支持的中国宏观数据：
    - PMI（制造业采购经理指数）
    - CPI（居民消费价格指数）
    - PPI（工业生产者出厂价格指数）
    - M2（货币供应量）
    - 工业增加值
    - 社会消费品零售总额
    """

    source_name = "akshare"

    # 支持的指标代码映射
    SUPPORTED_INDICATORS = {
        "CN_PMI": "PMI",
        "CN_CPI": "CPI",
        "CN_PPI": "PPI",
        "CN_M2": "M2",
        "CN_VALUE_ADDED": "工业增加值",
        "CN_RETAIL_SALES": "社会消费品零售总额",
        "CN_GDP": "GDP",
    }

    def __init__(self):
        """初始化 AKShare 适配器"""
        self._ak = None

    @property
    def ak(self):
        """延迟初始化 akshare"""
        if self._ak is None:
            try:
                import akshare as ak
                self._ak = ak
                logger.info("AKShare 初始化成功")
            except ImportError:
                raise DataSourceUnavailableError("akshare 库未安装，请运行: pip install akshare")
            except Exception as e:
                raise DataSourceUnavailableError(f"AKShare 初始化失败: {e}")
        return self._ak

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持指定指标"""
        return indicator_code in self.SUPPORTED_INDICATORS

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
                f"AKShare 不支持的指标: {indicator_code}，"
                f"支持的指标: {list(self.SUPPORTED_INDICATORS.keys())}"
            )

        try:
            if indicator_code == "CN_PMI":
                return self._fetch_pmi(start_date, end_date)
            elif indicator_code == "CN_CPI":
                return self._fetch_cpi(start_date, end_date)
            elif indicator_code == "CN_PPI":
                return self._fetch_ppi(start_date, end_date)
            elif indicator_code == "CN_M2":
                return self._fetch_m2(start_date, end_date)
            elif indicator_code == "CN_VALUE_ADDED":
                return self._fetch_value_added(start_date, end_date)
            elif indicator_code == "CN_RETAIL_SALES":
                return self._fetch_retail_sales(start_date, end_date)
            elif indicator_code == "CN_GDP":
                return self._fetch_gdp(start_date, end_date)
            else:
                return []

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            raise DataSourceUnavailableError(f"获取数据失败: {e}")

    def _fetch_pmi(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国 PMI 数据

        数据来源: 中国物流与采购联合会
        发布时间: 次月1日
        """
        try:
            # AKShare PMI 接口
            df = self.ak.macro_china_pmi()

            if df.empty:
                logger.warning("PMI 数据为空")
                return []

            # 打印列名用于调试
            logger.debug(f"PMI 数据列名: {df.columns.tolist()}")

            # 处理可能的列名变化
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '制造业-指数' if '制造业-指数' in df.columns else df.columns[1]

            # 处理日期列 - 先尝试中文格式，然后尝试其他格式
            def parse_chinese_date(date_str):
                """解析中文日期格式"""
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']

            # 筛选日期范围
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    # PMI 次月1日发布，发布延迟约1天
                    point = MacroDataPoint(
                        code="CN_PMI",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    # 发布时间会根据 PUBLICATION_LAGS 自动计算
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 PMI 数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 PMI 数据失败: {e}")
            raise

    def _fetch_cpi(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国 CPI 数据

        数据来源: 国家统计局
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_cpi()

            if df.empty:
                logger.warning("CPI 数据为空")
                return []

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '全国-当月' if '全国-当月' in df.columns else df.columns[1]

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']

            # 筛选日期范围
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    point = MacroDataPoint(
                        code="CN_CPI",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 CPI 数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 CPI 数据失败: {e}")
            raise

    def _fetch_ppi(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国 PPI 数据

        数据来源: 国家统计局
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_ppi()

            if df.empty:
                logger.warning("PPI 数据为空")
                return []

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '当月' if '当月' in df.columns else df.columns[1]

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']

            # 筛选日期范围
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    point = MacroDataPoint(
                        code="CN_PPI",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 PPI 数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 PPI 数据失败: {e}")
            raise

    def _fetch_m2(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国 M2 货币供应量数据

        数据来源: 中国人民银行
        发布时间: 月后10-15日
        """
        try:
            df = self.ak.macro_china_money_supply()

            if df.empty:
                logger.warning("M2 数据为空")
                return []

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = 'M2' if 'M2' in df.columns else df.columns[1]

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']

            # 筛选日期范围
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    # M2 单位是亿元，可以转换为万亿元
                    value_in_trillion = value / 10000

                    point = MacroDataPoint(
                        code="CN_M2",
                        value=value_in_trillion,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 M2 数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 M2 数据失败: {e}")
            raise

    def _fetch_value_added(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取工业增加值数据

        数据来源: 国家统计局
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_industry_value_added()

            if df.empty:
                logger.warning("工业增加值数据为空")
                return []

            # 处理日期列
            df['date'] = pd.to_datetime(df['月份'], format="%Y年%m月")
            df = df[['date', '工业增加值-同比增长']].dropna()
            df.columns = ['observed_at', 'value']

            # 筛选日期范围
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    point = MacroDataPoint(
                        code="CN_VALUE_ADDED",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效工业增加值数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取工业增加值数据失败: {e}")
            raise

    def _fetch_retail_sales(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取社会消费品零售总额数据

        数据来源: 国家统计局
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_retail_sales()

            if df.empty:
                logger.warning("社零数据为空")
                return []

            # 处理日期列
            df['date'] = pd.to_datetime(df['月份'], format="%Y年%m月")
            df = df[['date', '社会消费品零售总额-同比增长']].dropna()
            df.columns = ['observed_at', 'value']

            # 筛选日期范围
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    point = MacroDataPoint(
                        code="CN_RETAIL_SALES",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效社零数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取社零数据失败: {e}")
            raise

    def _fetch_gdp(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国 GDP 数据

        数据来源: 国家统计局
        发布时间: 季后20日左右
        """
        try:
            df = self.ak.macro_china_gdp()

            if df.empty:
                logger.warning("GDP 数据为空")
                return []

            # 处理日期列
            df['date'] = pd.to_datetime(df['季度'], format="%Y年第%s季度")
            df = df[['date', '国内生产总值-当季值']].dropna()
            df.columns = ['observed_at', 'value']

            # 筛选日期范围
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    point = MacroDataPoint(
                        code="CN_GDP",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 GDP 数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 GDP 数据失败: {e}")
            raise
