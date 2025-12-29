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
        # 基础指标
        "CN_PMI": "PMI",
        "CN_NON_MAN_PMI": "非制造业PMI",
        "CN_CPI": "CPI",
        "CN_CPI_NATIONAL_YOY": "全国CPI同比",
        "CN_CPI_NATIONAL_MOM": "全国CPI环比",
        "CN_CPI_URBAN_YOY": "城市CPI同比",
        "CN_CPI_URBAN_MOM": "城市CPI环比",
        "CN_CPI_RURAL_YOY": "农村CPI同比",
        "CN_CPI_RURAL_MOM": "农村CPI环比",
        "CN_PPI": "PPI",
        "CN_PPI_YOY": "PPI同比",
        "CN_M2": "M2",
        "CN_VALUE_ADDED": "工业增加值",
        "CN_RETAIL_SALES": "社会消费品零售总额",
        "CN_GDP": "GDP",

        # 贸易数据
        "CN_EXPORTS": "出口同比增长",
        "CN_IMPORTS": "进口同比增长",
        "CN_TRADE_BALANCE": "贸易差额",

        # 房产数据
        "CN_NEW_HOUSE_PRICE": "新房价格指数",

        # 价格数据
        "CN_OIL_PRICE": "成品油价格",

        # 就业数据
        "CN_UNEMPLOYMENT": "城镇调查失业率",

        # 金融数据
        "CN_FX_RESERVES": "外汇储备",
        "CN_LPR": "LPR",
        "CN_SHIBOR": "SHIBOR",
        "CN_RRR": "存款准备金率",

        # 信贷数据
        "CN_NEW_CREDIT": "新增信贷",
        "CN_RMB_DEPOSIT": "人民币存款",
        "CN_RMB_LOAN": "人民币贷款",
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
            elif indicator_code == "CN_NON_MAN_PMI":
                return self._fetch_non_man_pmi(start_date, end_date)
            elif indicator_code == "CN_CPI":
                return self._fetch_cpi(start_date, end_date)
            elif indicator_code in ["CN_CPI_NATIONAL_YOY", "CN_CPI_NATIONAL_MOM",
                                   "CN_CPI_URBAN_YOY", "CN_CPI_URBAN_MOM",
                                   "CN_CPI_RURAL_YOY", "CN_CPI_RURAL_MOM"]:
                return self._fetch_cpi_detailed(start_date, end_date, indicator_code)
            elif indicator_code == "CN_PPI":
                return self._fetch_ppi(start_date, end_date)
            elif indicator_code == "CN_PPI_YOY":
                return self._fetch_ppi_yoy(start_date, end_date)
            elif indicator_code == "CN_M2":
                return self._fetch_m2(start_date, end_date)
            elif indicator_code == "CN_VALUE_ADDED":
                return self._fetch_value_added(start_date, end_date)
            elif indicator_code == "CN_RETAIL_SALES":
                return self._fetch_retail_sales(start_date, end_date)
            elif indicator_code == "CN_GDP":
                return self._fetch_gdp(start_date, end_date)
            elif indicator_code == "CN_EXPORTS":
                return self._fetch_exports(start_date, end_date)
            elif indicator_code == "CN_IMPORTS":
                return self._fetch_imports(start_date, end_date)
            elif indicator_code == "CN_TRADE_BALANCE":
                return self._fetch_trade_balance(start_date, end_date)
            elif indicator_code == "CN_UNEMPLOYMENT":
                return self._fetch_unemployment(start_date, end_date)
            elif indicator_code == "CN_FX_RESERVES":
                return self._fetch_fx_reserves(start_date, end_date)
            elif indicator_code == "CN_LPR":
                return self._fetch_lpr(start_date, end_date)
            elif indicator_code == "CN_SHIBOR":
                return self._fetch_shibor(start_date, end_date)
            elif indicator_code == "CN_RRR":
                return self._fetch_rrr(start_date, end_date)
            elif indicator_code == "CN_NEW_HOUSE_PRICE":
                return self._fetch_new_house_price(start_date, end_date)
            elif indicator_code == "CN_OIL_PRICE":
                return self._fetch_oil_price(start_date, end_date)
            elif indicator_code == "CN_NEW_CREDIT":
                return self._fetch_new_credit(start_date, end_date)
            elif indicator_code == "CN_RMB_DEPOSIT":
                return self._fetch_rmb_deposit(start_date, end_date)
            elif indicator_code == "CN_RMB_LOAN":
                return self._fetch_rmb_loan(start_date, end_date)
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

    def _fetch_cpi_detailed(
        self,
        start_date: date,
        end_date: date,
        indicator_code: str
    ) -> List[MacroDataPoint]:
        """
        获取中国 CPI 细分数据

        数据来源: 国家统计局/同花顺
        发布时间: 月后10日左右

        支持的细分指标:
        - CN_CPI_NATIONAL_YOY: 全国CPI同比
        - CN_CPI_NATIONAL_MOM: 全国CPI环比
        - CN_CPI_URBAN_YOY: 城市CPI同比
        - CN_CPI_URBAN_MOM: 城市CPI环比
        - CN_CPI_RURAL_YOY: 农村CPI同比
        - CN_CPI_RURAL_MOM: 农村CPI环比
        """
        try:
            df = self.ak.macro_china_cpi()

            if df.empty:
                logger.warning("CPI 细分数据为空")
                return []

            # 映射指标代码到列索引（基于AKShare返回的列顺序）
            # 列顺序: 月份, 全国-当月, 全国-当月同比, 全国-当月环比, 全国-累计,
            #       城市-当月, 城市-当月同比, 城市-当月环比, 城市-累计,
            #       农村-当月, 农村-当月同比, 农村-当月环比, 农村-累计
            column_index_mapping = {
                "CN_CPI_NATIONAL_YOY": 2,  # 全国-当月同比
                "CN_CPI_NATIONAL_MOM": 3,  # 全国-当月环比
                "CN_CPI_URBAN_YOY": 6,     # 城市-当月同比
                "CN_CPI_URBAN_MOM": 7,     # 城市-当月环比
                "CN_CPI_RURAL_YOY": 10,    # 农村-当月同比
                "CN_CPI_RURAL_MOM": 11,    # 农村-当月环比
            }

            value_col_idx = column_index_mapping.get(indicator_code)
            if value_col_idx is None or value_col_idx >= len(df.columns):
                logger.warning(f"CPI 指标 {indicator_code} 对应的列索引 {value_col_idx} 不存在")
                return []

            # 处理日期列
            date_col_idx = 0  # 月份列

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', df.columns[value_col_idx]]].copy()
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
                    # CPI 同比/环比数据是百分比字符串，需要转换为小数
                    value_raw = row['value']
                    if isinstance(value_raw, str):
                        # 移除百分号并转换为小数
                        value = float(value_raw.replace('%', '')) / 100
                    else:
                        value = float(value_raw)

                    point = MacroDataPoint(
                        code=indicator_code,
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 CPI 细分数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 CPI 细分数据失败: {e}")
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
            # 修复: 使用正确的API函数名 macro_china_gyzjz
            df = self.ak.macro_china_gyzjz()

            if df.empty:
                logger.warning("工业增加值数据为空")
                return []

            # 使用列索引避免编码问题
            # 0: 月份, 1: 同比增长, 2: 累计增长, 3: 发布时间
            date_col_idx = 0
            value_col_idx = 1  # 同比增长

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_date), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')

            # 先dropna，再筛选日期范围
            df = df[['observed_at', 'value']].dropna()

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

        数据来源: 国家统计局/东方财富
        发布时间: 月后10日左右

        列索引: 0=月份, 1=当月, 2=同比增长, 3=环比增长, 4=累计, 5=累计-同比增长
        """
        try:
            # 修复: 正确的API函数名是 macro_china_consumer_goods_retail
            df = self.ak.macro_china_consumer_goods_retail()

            if df.empty:
                logger.warning("社零数据为空")
                return []

            # 使用列索引避免编码问题
            date_col_idx = 0   # 月份
            value_col_idx = 2  # 同比增长

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_date), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')

            # 筛选日期范围
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            df = df[['observed_at', 'value']].dropna()

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

            # 使用列索引避免编码问题
            # 0: 季度, 1: 国内生产总值-当季值, 2: 国内生产总值-同比增长
            date_col_idx = 0
            value_col_idx = 1  # 当季值

            # 处理中文季度格式 (如: "2024年第1季度" 或 "2024年1-3月")
            def parse_chinese_quarter(date_str):
                import re
                date_str = str(date_str)

                # 处理 "2024年第1季度" 格式
                match = re.match(r'(\d{4})年[第](\d+)[季度季度]', date_str)
                if match:
                    year, quarter = match.groups()
                    quarter_to_month = {'1': '03', '2': '06', '3': '09', '4': '12'}
                    return f"{year}-{quarter_to_month.get(quarter, '12')}-01"

                # 处理 "2024年1-3月" 格式
                match = re.match(r'(\d{4})年(\d+)-(\d+)月', date_str)
                if match:
                    year = match.group(1)
                    end_month = match.group(3)
                    return f"{year}-{end_month.zfill(2)}-01"

                return date_str

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_quarter), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')

            # 先dropna，再筛选日期范围
            df = df[['observed_at', 'value']].dropna()

            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    # 单位转换：亿元 -> 万亿元
                    value_in_trillion = value / 10000

                    point = MacroDataPoint(
                        code="CN_GDP",
                        value=value_in_trillion,
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

    def _fetch_exports(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国出口数据

        数据来源: 海关总署
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_exports_yoy()

            if df.empty:
                logger.warning("出口数据为空")
                return []

            # 处理日期列
            date_col = '日期' if '日期' in df.columns else df.columns[1]
            value_col = '值' if '值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
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
                        code="CN_EXPORTS",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效出口数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取出口数据失败: {e}")
            raise

    def _fetch_imports(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国进口数据

        数据来源: 海关总署
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_imports_yoy()

            if df.empty:
                logger.warning("进口数据为空")
                return []

            # 处理日期列
            date_col = '日期' if '日期' in df.columns else df.columns[1]
            value_col = '值' if '值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
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
                        code="CN_IMPORTS",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效进口数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取进口数据失败: {e}")
            raise

    def _fetch_trade_balance(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国贸易差额数据

        数据来源: 海关总署
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_trade_balance()

            if df.empty:
                logger.warning("贸易差额数据为空")
                return []

            # 处理日期列
            date_col = '日期' if '日期' in df.columns else df.columns[1]
            value_col = '值' if '值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
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

                    # 单位转换：亿美元转换为亿元美元
                    value_in_billion = value / 10000

                    point = MacroDataPoint(
                        code="CN_TRADE_BALANCE",
                        value=value_in_billion,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效贸易差额数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取贸易差额数据失败: {e}")
            raise

    def _fetch_unemployment(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国城镇调查失业率数据

        数据来源: 国家统计局
        发布时间: 月后15日左右
        """
        try:
            df = self.ak.macro_china_urban_unemployment()

            if df.empty:
                logger.warning("失业率数据为空")
                return []

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '城镇调查失业率' if '城镇调查失业率' in df.columns else df.columns[1]

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

                    # 百分数转换为小数
                    value_decimal = value / 100 if value > 1 else value

                    point = MacroDataPoint(
                        code="CN_UNEMPLOYMENT",
                        value=value_decimal,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效失业率数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取失业率数据失败: {e}")
            raise

    def _fetch_fx_reserves(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国外汇储备数据

        数据来源: 中国人民银行
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_fx_gold()

            if df.empty:
                logger.warning("外汇储备数据为空")
                return []

            # 打印列名用于调试
            logger.debug(f"外汇储备数据列名: {df.columns.tolist()}")

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            # 外汇储备期末值
            value_col = '外汇储备-期末值' if '外汇储备-期末值' in df.columns else df.columns[4]

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
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

                    # 单位转换：亿美元转换为万亿美元
                    value_in_trillion = value / 10000

                    point = MacroDataPoint(
                        code="CN_FX_RESERVES",
                        value=value_in_trillion,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效外汇储备数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取外汇储备数据失败: {e}")
            raise

    def _fetch_lpr(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国 LPR (贷款市场报价利率) 数据

        数据来源: 全国银行间同业拆借中心
        发布时间: 每月20日
        """
        try:
            df = self.ak.macro_china_lpr()

            if df.empty:
                logger.warning("LPR 数据为空")
                return []

            # 处理日期列
            date_col = '日期' if '日期' in df.columns else df.columns[0]
            value_col = '1年期' if '1年期' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col], format='mixed')
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

                    # 百分数转换为小数
                    value_decimal = value / 100 if value > 1 else value

                    point = MacroDataPoint(
                        code="CN_LPR",
                        value=value_decimal,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 LPR 数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 LPR 数据失败: {e}")
            raise

    def _fetch_shibor(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国 SHIBOR (上海银行间同业拆放利率) 数据

        数据来源: 全国银行间同业拆借中心
        发布时间: 每日
        """
        try:
            df = self.ak.macro_china_shibor_all()

            if df.empty:
                logger.warning("SHIBOR 数据为空")
                return []

            # 处理日期列
            date_col = '日期' if '日期' in df.columns else df.columns[0]
            # 使用隔夜利率作为主要指标
            value_col = '隔夜' if '隔夜' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col], format='mixed')
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

                    # 百分数转换为小数
                    value_decimal = value / 100 if value > 1 else value

                    point = MacroDataPoint(
                        code="CN_SHIBOR",
                        value=value_decimal,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 SHIBOR 数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 SHIBOR 数据失败: {e}")
            raise

    def _fetch_non_man_pmi(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国非制造业PMI数据

        数据来源: 中国物流与采购联合会
        发布时间: 次月1日
        """
        try:
            df = self.ak.macro_china_non_man_pmi()

            if df.empty:
                logger.warning("非制造业PMI 数据为空")
                return []

            # 处理日期列
            date_col = '日期' if '日期' in df.columns else df.columns[1]
            value_col = '今值' if '今值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
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
                        code="CN_NON_MAN_PMI",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效非制造业PMI数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取非制造业PMI数据失败: {e}")
            raise

    def _fetch_ppi_yoy(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国PPI同比数据

        数据来源: 国家统计局
        发布时间: 月后10日左右
        """
        try:
            df = self.ak.macro_china_ppi()

            if df.empty:
                logger.warning("PPI同比数据为空")
                return []

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            # PPI同比在第3列（索引2）
            value_col_idx = 2

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', df.columns[value_col_idx]]].copy()
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
                        code="CN_PPI_YOY",
                        value=value,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效PPI同比数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取PPI同比数据失败: {e}")
            raise

    def _fetch_rrr(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国存款准备金率数据

        数据来源: 中国人民银行
        发布时间: 不定期调整
        """
        try:
            df = self.ak.macro_china_reserve_requirement_ratio()

            if df.empty:
                logger.warning("存款准备金率数据为空")
                return []

            # 使用列索引（基于AKShare返回的列顺序）
            # 0: 公布时间, 2: 大型存款类金融机构-调整前
            date_col_idx = 0
            value_col_idx = 2  # 大型存款类金融机构-调整前

            # 处理中文日期格式（YYYY年MM月DD日）
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', str(date_str))
                    if match:
                        year, month, day = match.groups()
                        return f'{year}-{month.zfill(2)}-{day.zfill(2)}'
                return date_str

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_date), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')

            # 先dropna，再筛选日期范围
            df = df[['observed_at', 'value']].dropna()

            # 将observed_at转换为date进行比较
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    # 百分数转换为小数
                    value_decimal = value / 100 if value > 1 else value

                    point = MacroDataPoint(
                        code="CN_RRR",
                        value=value_decimal,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效存款准备金率数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取存款准备金率数据失败: {e}")
            raise

    def _fetch_new_house_price(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国新房价格指数数据

        数据来源: 国家统计局/东方财富
        发布时间: 月后15日左右
        注意: API只提供北京和上海的数据，使用北京作为代表
        """
        try:
            df = self.ak.macro_china_new_house_price()

            if df.empty:
                logger.warning("新房价格指数数据为空")
                return []

            # 处理日期列 - 日期格式是 YYYY-MM-DD
            date_col_idx = 0  # 日期列
            region_col_idx = 1  # 地区列
            value_col_idx = 2  # 新建商品住宅价格指数-同比

            # 只取北京数据（API没有全国数据，用北京作为代表）
            df_filtered = df[df.iloc[:, region_col_idx] == '北京'].copy()

            if df_filtered.empty:
                logger.warning("新房价格指数中北京数据为空")
                return []

            df_filtered['observed_at'] = pd.to_datetime(df_filtered.iloc[:, date_col_idx], format='mixed', errors='coerce')
            df_filtered['value'] = pd.to_numeric(df_filtered.iloc[:, value_col_idx], errors='coerce')

            # 先dropna，再筛选日期范围
            df_filtered = df_filtered[['observed_at', 'value']].dropna()

            # 筛选日期范围
            df_filtered = df_filtered[
                (df_filtered['observed_at'].dt.date >= start_date) &
                (df_filtered['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            for _, row in df_filtered.iterrows():
                try:
                    observed_at = row['observed_at'].date()
                    value = float(row['value'])

                    # 转换为同比百分比（基数100，所以减去100）
                    value_yoy = (value - 100) / 100

                    point = MacroDataPoint(
                        code="CN_NEW_HOUSE_PRICE",
                        value=value_yoy,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效新房价格指数数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取新房价格指数数据失败: {e}")
            raise

    def _fetch_oil_price(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国成品油价格数据

        数据来源: 国家发改委
        发布时间: 不定期调整
        """
        try:
            df = self.ak.energy_oil_hist()

            if df.empty:
                logger.warning("成品油价格数据为空")
                return []

            # 处理日期列
            date_col = '调价日期' if '调价日期' in df.columns else df.columns[0]
            # 使用汽油最高零售价
            value_col = '汽油最高零售价' if '汽油最高零售价' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
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

                    # 单位转换：元/吨 ->千元/吨
                    value_in_k = value / 1000

                    point = MacroDataPoint(
                        code="CN_OIL_PRICE",
                        value=value_in_k,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效成品油价格数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取成品油价格数据失败: {e}")
            raise

    def _fetch_new_credit(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取中国新增信贷数据

        数据来源: 中国人民银行
        发布时间: 月后10-15日
        """
        try:
            df = self.ak.macro_china_new_financial_credit()

            if df.empty:
                logger.warning("新增信贷数据为空")
                return []

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            # 使用当月新增值
            value_col_idx = 1  # 当月新增

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', df.columns[value_col_idx]]].copy()
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

                    # 单位转换：亿元 -> 万亿元
                    value_in_trillion = value / 10000

                    point = MacroDataPoint(
                        code="CN_NEW_CREDIT",
                        value=value_in_trillion,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效新增信贷数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取新增信贷数据失败: {e}")
            raise

    def _fetch_rmb_deposit(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取人民币存款余额数据

        数据来源: 中国人民银行
        发布时间: 月后10-15日
        """
        try:
            df = self.ak.macro_rmb_deposit()

            if df.empty:
                logger.warning("人民币存款数据为空")
                return []

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            # 使用住户存款-当月值
            value_col = '住户存款-当月值' if '住户存款-当月值' in df.columns else df.columns[2]

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
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
                    value_str = row['value']

                    # 处理字符串格式的数值
                    if isinstance(value_str, str):
                        value_str = value_str.replace('%', '').replace(',', '')
                    value = float(value_str)

                    # 单位转换：亿元 -> 万亿元
                    value_in_trillion = value / 10000

                    point = MacroDataPoint(
                        code="CN_RMB_DEPOSIT",
                        value=value_in_trillion,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效人民币存款数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取人民币存款数据失败: {e}")
            raise

    def _fetch_rmb_loan(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取人民币贷款余额数据

        数据来源: 中国人民银行
        发布时间: 月后10-15日
        """
        try:
            df = self.ak.macro_rmb_loan()

            if df.empty:
                logger.warning("人民币贷款数据为空")
                return []

            # 处理日期列
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            # 使用当月新增人民币贷款-总量
            value_col_idx = 1

            # 处理中文日期格式
            def parse_chinese_date(date_str):
                import re
                if '年' in str(date_str) and '月' in str(date_str):
                    match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
                    if match:
                        year, month = match.groups()
                        return f"{year}-{month.zfill(2)}"
                return date_str

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', df.columns[value_col_idx]]].copy()
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
                    value_str = row['value']

                    # 处理字符串格式的数值
                    if isinstance(value_str, str):
                        value_str = value_str.replace('%', '').replace(',', '')
                    value = float(value_str)

                    # 单位转换：亿元 -> 万亿元
                    value_in_trillion = value / 10000

                    point = MacroDataPoint(
                        code="CN_RMB_LOAN",
                        value=value_in_trillion,
                        observed_at=observed_at,
                        source=self.source_name
                    )
                    self._validate_data_point(point)
                    data_points.append(point)

                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效人民币贷款数据: {row}, 错误: {e}")
                    continue

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取人民币贷款数据失败: {e}")
            raise
