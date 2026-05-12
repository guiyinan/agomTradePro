"""
高频指标数据获取器（Regime 滞后性改进方案 Phase 1）。

包含日度级别的债券收益率、信用利差、商品指数、汇率等高频指标获取逻辑。
这些指标用于减少 Regime 判定的滞后性，从 3-6 个月降低到 1-2 周。

参考文档: docs/development/regime-lag-improvement-plan.md
"""

import logging
from datetime import date

import pandas as pd

from ..base import DataValidationError, MacroDataPoint
from .common import resolve_indicator_units

logger = logging.getLogger(__name__)
SUPPORTED_INDICATOR_CODES = {
    "CN_BOND_10Y",
    "CN_BOND_5Y",
    "CN_BOND_2Y",
    "CN_BOND_1Y",
    "CN_TERM_SPREAD_10Y1Y",
    "CN_TERM_SPREAD_10Y2Y",
    "CN_CORP_YIELD_AAA",
    "CN_CORP_YIELD_AA",
    "CN_CREDIT_SPREAD",
    "CN_NHCI",
    "CN_FX_CENTER",
    "US_BOND_10Y",
    "USD_INDEX",
    "VIX_INDEX",
}


class HighFrequencyIndicatorFetcher:
    """高频指标获取器

    用于获取日度级别的债券收益率、信用利差、商品指数、汇率等高频指标。
    """

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn
        self._bond_cache: pd.DataFrame | None = None

    def _get_bond_yields(self) -> pd.DataFrame | None:
        """获取中美国债收益率数据（带缓存）

        使用 ak.bond_zh_us_rate() 获取中美两国国债收益率数据。
        该函数返回的 DataFrame 包含以下列：
        - 日期
        - 中国国债收益率2年, 5年, 10年, 30年
        - 美国国债收益率2年, 5年, 10年, 30年
        - 中国国债收益率10年-2年
        - 美国国债收益率10年-2年
        """
        if self._bond_cache is not None:
            return self._bond_cache

        try:
            df = self.ak.bond_zh_us_rate()
            if df.empty:
                logger.warning("国债收益率数据为空")
                return None

            # 复制数据避免修改原始数据
            df = df.copy()

            # 第一列是日期
            df['date'] = pd.to_datetime(df.iloc[:, 0], errors='coerce')

            # 根据列名映射中英文
            # 中国国债收益率列
            for col in df.columns:
                col_lower = str(col).lower()
                # 识别中国国债收益率
                if '中国' in col and '2年' in col or '2y' in col_lower:
                    df['CN_BOND_2Y'] = pd.to_numeric(df[col], errors='coerce')
                elif '中国' in col and '5年' in col or '5y' in col_lower:
                    df['CN_BOND_5Y'] = pd.to_numeric(df[col], errors='coerce')
                elif '中国' in col and '10年' in col or '10y' in col_lower:
                    df['CN_BOND_10Y'] = pd.to_numeric(df[col], errors='coerce')
                elif '中国' in col and '30年' in col or '30y' in col_lower:
                    df['CN_BOND_30Y'] = pd.to_numeric(df[col], errors='coerce')
                # 识别美国国债收益率
                elif '美国' in col and '2年' in col or ('us' in col_lower and '2' in col):
                    df['US_BOND_2Y'] = pd.to_numeric(df[col], errors='coerce')
                elif '美国' in col and '5年' in col or ('us' in col_lower and '5' in col):
                    df['US_BOND_5Y'] = pd.to_numeric(df[col], errors='coerce')
                elif '美国' in col and '10年' in col or ('us' in col_lower and '10' in col):
                    df['US_BOND_10Y'] = pd.to_numeric(df[col], errors='coerce')
                elif '美国' in col and '30年' in col or ('us' in col_lower and '30' in col):
                    df['US_BOND_30Y'] = pd.to_numeric(df[col], errors='coerce')

            # 计算期限利差（10年 - 2年）
            if 'CN_BOND_10Y' in df.columns and 'CN_BOND_2Y' in df.columns:
                df['CN_TERM_SPREAD_10Y2Y'] = df['CN_BOND_10Y'] - df['CN_BOND_2Y']

            if 'US_BOND_10Y' in df.columns and 'US_BOND_2Y' in df.columns:
                df['US_TERM_SPREAD_10Y2Y'] = df['US_BOND_10Y'] - df['US_BOND_2Y']

            self._bond_cache = df
            return df

        except Exception as e:
            logger.error(f"获取国债收益率失败: {e}")
            return None

    def fetch_bond_yield(
        self,
        term: str,
        start_date: date,
        end_date: date,
        country: str = "CN"
    ) -> list[MacroDataPoint]:
        """获取国债收益率

        Args:
            term: 期限 ('10Y', '5Y', '2Y')
            start_date: 起始日期
            end_date: 结束日期
            country: 国家代码 ('CN' 或 'US')
        """
        prefix = country + "_BOND_"
        indicator_code = prefix + term

        if indicator_code not in SUPPORTED_INDICATOR_CODES:
            logger.warning(f"未知的国债指标: {indicator_code}")
            return []

        try:
            df = self._get_bond_yields()
            if df is None or indicator_code not in df.columns:
                logger.warning(f"数据中不包含 {indicator_code}")
                return []

            # 过滤日期范围
            df_filtered = df[df['date'].dt.date >= start_date]
            df_filtered = df_filtered[df_filtered['date'].dt.date <= end_date]

            data_points = []
            unit, original_unit = resolve_indicator_units(indicator_code)
            for _, row in df_filtered[['date', indicator_code]].dropna().iterrows():
                try:
                    point = MacroDataPoint(
                        code=indicator_code,
                        value=float(row[indicator_code]),
                        observed_at=row['date'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 {indicator_code} 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            return []

    def fetch_term_spread(
        self,
        long_term: str = "10Y",
        short_term: str = "2Y",
        start_date: date | None = None,
        end_date: date | None = None,
        country: str = "CN"
    ) -> list[MacroDataPoint]:
        """计算期限利差（长端收益率 - 短端收益率）

        Args:
            long_term: 长端期限 ('10Y')
            short_term: 短端期限 ('2Y')
            start_date: 起始日期
            end_date: 结束日期
            country: 国家代码 ('CN' 或 'US')
        """
        prefix = country + "_TERM_SPREAD_"
        indicator_code = prefix + long_term + short_term

        try:
            df = self._get_bond_yields()
            if df is None or indicator_code not in df.columns:
                # 如果预计算的利差不存在，尝试动态计算
                long_code = f"{country}_BOND_{long_term}"
                short_code = f"{country}_BOND_{short_term}"

                if long_code not in df.columns or short_code not in df.columns:
                    logger.warning(f"无法计算 {indicator_code}: 缺少基础数据")
                    return []

                df = df[['date', long_code, short_code]].copy()
                df['spread'] = df[long_code] - df[short_code]
            else:
                df = df[['date', indicator_code]].copy()
                df['spread'] = df[indicator_code]

            # 应用日期过滤
            if start_date:
                df = df[df['date'].dt.date >= start_date]
            if end_date:
                df = df[df['date'].dt.date <= end_date]

            data_points = []
            unit, original_unit = resolve_indicator_units(indicator_code)
            for _, row in df[['date', 'spread']].dropna().iterrows():
                try:
                    # 利差以基点（BP）为单位，1% = 100BP
                    spread_bp = row['spread'] * 100
                    point = MacroDataPoint(
                        code=indicator_code,
                        value=spread_bp,
                        observed_at=row['date'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 {indicator_code} 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"计算 {indicator_code} 失败: {e}")
            return []

    def fetch_nhci(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取南华商品指数

        南华商品指数反映工业品通胀和实体经济需求。
        使用 ak.macro_china_commodity_price_index()
        """
        indicator_code = 'CN_NHCI'

        try:
            # AKShare 获取中国商品价格指数
            df = self.ak.macro_china_commodity_price_index()
            if df.empty:
                logger.warning("南华商品指数数据为空")
                return []

            df = df.copy()
            # 第一列是日期
            df['date'] = pd.to_datetime(df.iloc[:, 0], errors='coerce')
            # 第二列是指数值
            df['value'] = pd.to_numeric(df.iloc[:, 1], errors='coerce')

            df = df[['date', 'value']].dropna()
            df = df[
                (df['date'].dt.date >= start_date) &
                (df['date'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(indicator_code)
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code=indicator_code,
                        value=float(row['value']),
                        observed_at=row['date'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 {indicator_code} 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            return []

    def fetch_fx_center_rate(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取人民币汇率中间价

        注意: AKShare 的 fx_spot_quote 只返回当前报价，不返回历史数据。
        历史汇率数据需要从其他数据源获取。
        """
        indicator_code = 'CN_FX_CENTER'

        try:
            # AKShare 的 fx_spot_quote 只返回当前报价
            df = self.ak.fx_spot_quote()
            if df.empty:
                logger.warning("人民币汇率数据为空")
                return []

            # 查找 USD/CNY 行
            usd_cny_row = df[df.iloc[:, 0].str.contains("USD/CNY", na=False)]

            if usd_cny_row.empty:
                logger.warning("未找到 USD/CNY 汇率数据")
                return []

            # 取买入价
            rate = pd.to_numeric(usd_cny_row.iloc[0, 1], errors='coerce')

            if pd.isna(rate):
                logger.warning("USD/CNY 汇率数据无效")
                return []

            # 只返回当前一天的报价（因为 FX API 不支持历史数据）
            data_points = []
            unit, original_unit = resolve_indicator_units(indicator_code)
            try:
                point = MacroDataPoint(
                    code=indicator_code,
                    value=float(rate),
                    observed_at=date.today(),
                    source=self.source_name,
                    unit=unit,
                    original_unit=original_unit,
                )
                self._validate(point)
                data_points.append(point)
            except (ValueError, DataValidationError) as e:
                logger.warning(f"跳过无效 {indicator_code} 数据: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            return []

    def fetch_us_bond_10y(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取美国10年期国债收益率

        从 bond_zh_us_rate() 数据中提取。
        """
        return self.fetch_bond_yield("10Y", start_date, end_date, country="US")

    def fetch_credit_spread(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """计算信用利差

        注意: 当前 AKShare 不直接提供企业债收益率数据。
        此方法为占位符，实际数据需要从其他数据源（如 Wind）获取。
        """
        indicator_code = 'CN_CREDIT_SPREAD'

        logger.warning(
            f"{indicator_code}: AKShare 不直接提供企业债收益率数据。"
            "需要从其他数据源（如 Wind、中债登）获取。"
        )

        return []

    def fetch_corp_bond_yield(
        self,
        rating: str,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取企业债收益率

        注意: 当前 AKShare 不直接提供企业债收益率数据。
        此方法为占位符，实际数据需要从其他数据源（如 Wind）获取。
        """
        indicator_code = f'CN_CORP_YIELD_{rating}'

        logger.warning(
            f"{indicator_code}: AKShare 不直接提供企业债收益率数据。"
            "需要从其他数据源（如 Wind、中债登）获取。"
        )

        return []

    def fetch_usd_index(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取美元指数

        注意: 当前 AKShare 不直接提供美元指数历史数据。
        此方法为占位符，实际数据需要从其他数据源获取。
        """
        indicator_code = 'USD_INDEX'

        logger.warning(
            f"{indicator_code}: AKShare 不直接提供美元指数历史数据。"
            "需要从其他数据源（如 FRED、Bloomberg）获取。"
        )

        return []

    def fetch_vix_index(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取VIX波动率指数

        注意: 当前 AKShare 的 VIX 相关函数主要是中国指数的 QVIX，
        并非 CBOE VIX 指数。
        此方法为占位符，实际数据需要从其他数据源获取。
        """
        indicator_code = 'VIX_INDEX'

        logger.warning(
            f"{indicator_code}: AKShare 不直接提供 CBOE VIX 指数数据。"
            "需要从其他数据源（如 FRED、CBOE）获取。"
        )

        return []

    def clear_cache(self):
        """清除缓存"""
        self._bond_cache = None
