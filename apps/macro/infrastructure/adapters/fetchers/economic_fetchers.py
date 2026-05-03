"""
经济活动指标数据获取器。

包含工业增加值、社会消费品零售总额、GDP 等经济活动指标的获取逻辑。
"""

import logging
import re
from datetime import date
from typing import List

import pandas as pd

from ..base import DataValidationError, MacroDataPoint
from .common import pick_column, resolve_indicator_units, safe_float

logger = logging.getLogger(__name__)

# 指标单位 fallback，仅在 runtime metadata / unit rule 不可用时生效。
INDICATOR_UNITS = {
    "CN_VALUE_ADDED": ("%", "%"),
    "CN_RETAIL_SALES": ("亿元", "亿元"),
    "CN_RETAIL_SALES_YOY": ("%", "%"),
    "CN_GDP": ("亿元", "亿元"),
    "CN_GDP_YOY": ("%", "%"),
    "CN_FIXED_INVESTMENT": ("亿元", "亿元"),
    "CN_FAI_YOY": ("%", "%"),
    "CN_SOCIAL_FINANCING": ("亿元", "亿元"),
    "CN_SOCIAL_FINANCING_YOY": ("%", "%"),
}


def parse_chinese_date(date_str: str) -> str:
    """解析中文日期格式"""
    if '年' in str(date_str) and '月' in str(date_str):
        match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
        if match:
            year, month = match.groups()
            return f"{year}-{month.zfill(2)}"
    return date_str


def parse_chinese_quarter(date_str: str) -> str:
    """处理中文季度格式 (如: '2024年第1季度')"""
    date_str = str(date_str)
    match = re.match(r'(\d{4})年(?:第)?(\d)(?:-(\d))?季度', date_str)
    if match:
        year, start_quarter, end_quarter = match.groups()
        quarter = end_quarter or start_quarter
        quarter_to_month = {'1': '03', '2': '06', '3': '09', '4': '12'}
        return f"{year}-{quarter_to_month.get(quarter, '12')}-01"

    match = re.match(r'(\d{4})年(?:第)?(\d)-(\d)季度', date_str)
    if match:
        year, _, end_quarter = match.groups()
        quarter_to_month = {'1': '03', '2': '06', '3': '09', '4': '12'}
        return f"{year}-{quarter_to_month.get(end_quarter, '12')}-01"

    match = re.match(r'(\d{4})年(\d+)-(\d+)月', date_str)
    if match:
        year = match.group(1)
        end_month = match.group(3)
        return f"{year}-{end_month.zfill(2)}-01"

    return date_str


class EconomicIndicatorFetcher:
    """经济活动指标获取器"""

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_value_added(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取工业增加值数据"""
        try:
            df = self.ak.macro_china_gyzjz()
            if df.empty:
                logger.warning("工业增加值数据为空")
                return []

            date_col_idx = 0
            value_col_idx = 1

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_date), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')
            df = df[['observed_at', 'value']].dropna()
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_VALUE_ADDED",
                *INDICATOR_UNITS.get("CN_VALUE_ADDED", ("%", "%")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_VALUE_ADDED",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效工业增加值数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取工业增加值数据失败: {e}")
            raise

    def fetch_retail_sales(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取社会消费品零售总额当月值数据。"""
        try:
            df = self.ak.macro_china_consumer_goods_retail()
            if df.empty:
                logger.warning("社零数据为空")
                return []

            date_col_idx = 0
            value_col_idx = 1

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_date), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]
            df = df[['observed_at', 'value']].dropna()

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_RETAIL_SALES",
                *INDICATOR_UNITS.get("CN_RETAIL_SALES", ("亿元", "亿元")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_RETAIL_SALES",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效社零数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取社零数据失败: {e}")
            raise

    def fetch_retail_sales_yoy(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取社会消费品零售总额同比增速数据。"""
        try:
            df = self.ak.macro_china_consumer_goods_retail()
            if df.empty:
                logger.warning("社零同比数据为空")
                return []

            date_col_idx = 0
            value_col_idx = 2

            df = df.copy()
            df['observed_at'] = pd.to_datetime(
                df.iloc[:, date_col_idx].apply(parse_chinese_date),
                format='mixed',
                errors='coerce',
            )
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]
            df = df[['observed_at', 'value']].dropna()

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_RETAIL_SALES_YOY",
                *INDICATOR_UNITS.get("CN_RETAIL_SALES_YOY", ("%", "%")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_RETAIL_SALES_YOY",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效社零同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取社零同比数据失败: {e}")
            raise

    def fetch_gdp(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 GDP 数据

        注意：akshare返回的GDP数据单位是"亿元"
        """
        try:
            df = self.ak.macro_china_gdp()
            if df.empty:
                logger.warning("GDP 数据为空")
                return []

            df = df.copy()
            date_col = pick_column(df, ["季度"], 0)
            value_col = pick_column(df, ["国内生产总值-绝对值"], 1)
            df['observed_at'] = pd.to_datetime(
                df[date_col].apply(parse_chinese_quarter),
                format='mixed',
                errors='coerce',
            )
            df['value'] = pd.to_numeric(df[value_col], errors='coerce')
            df = df[['observed_at', 'value']].dropna()
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_GDP",
                *INDICATOR_UNITS.get("CN_GDP", ("亿元", "亿元")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_GDP",
                        value=safe_float(row['value']),  # 保持原始值（亿元）
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 GDP 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 GDP 数据失败: {e}")
            raise

    def fetch_gdp_yoy(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 GDP 同比数据"""
        try:
            df = self.ak.macro_china_gdp()
            if df.empty:
                logger.warning("GDP同比数据为空")
                return []

            df = df.copy()
            date_col = pick_column(df, ["季度"], 0)
            value_col = pick_column(df, ["国内生产总值-同比增长"], 2)
            df['observed_at'] = pd.to_datetime(
                df[date_col].apply(parse_chinese_quarter),
                format='mixed',
                errors='coerce',
            )
            df['value'] = pd.to_numeric(df[value_col], errors='coerce')
            df = df[['observed_at', 'value']].dropna()
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_GDP_YOY",
                *INDICATOR_UNITS.get("CN_GDP_YOY", ("%", "%")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_GDP_YOY",
                        value=safe_float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 GDP同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 GDP同比数据失败: {e}")
            raise

    def fetch_fixed_investment(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """获取固定资产投资累计值数据。"""
        try:
            df = self.ak.macro_china_gdzctz()
            if df.empty:
                logger.warning("固定资产投资数据为空")
                return []

            df = df.copy()
            date_col = pick_column(df, ["月份"], 0)
            value_col = pick_column(df, ["自年初累计"], 4)
            df["observed_at"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df["value"] = pd.to_numeric(df[value_col], errors="coerce")
            df = df[["observed_at", "value"]].dropna()
            df = df[
                (df["observed_at"].dt.date >= start_date)
                & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_FIXED_INVESTMENT",
                *INDICATOR_UNITS.get("CN_FIXED_INVESTMENT", ("亿元", "亿元")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_FIXED_INVESTMENT",
                        value=safe_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效固定资产投资数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)
        except Exception as e:
            logger.error(f"获取固定资产投资数据失败: {e}")
            raise

    def fetch_fixed_investment_yoy(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """获取固定资产投资累计同比增速。

        数据源仅稳定提供累计值，因此同比按同月累计值派生。
        """
        try:
            df = self.ak.macro_china_gdzctz()
            if df.empty:
                logger.warning("固定资产投资同比数据为空")
                return []

            df = df.copy()
            date_col = pick_column(df, ["月份"], 0)
            value_col = pick_column(df, ["自年初累计"], 4)
            df["observed_at"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df["cumulative_value"] = pd.to_numeric(df[value_col], errors="coerce")
            df = df[["observed_at", "cumulative_value"]].dropna()
            df["year"] = df["observed_at"].dt.year
            df["month"] = df["observed_at"].dt.month
            prior = (
                df[["year", "month", "cumulative_value"]]
                .rename(
                    columns={
                        "year": "prior_year",
                        "cumulative_value": "prior_cumulative_value",
                    }
                )
            )
            df["prior_year"] = df["year"] - 1
            df = df.merge(prior, on=["prior_year", "month"], how="left")
            df = df[df["prior_cumulative_value"].notna() & (df["prior_cumulative_value"] != 0)]
            df["value"] = (
                (df["cumulative_value"] / df["prior_cumulative_value"] - 1.0) * 100.0
            )
            df = df[
                (df["observed_at"].dt.date >= start_date)
                & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_FAI_YOY",
                *INDICATOR_UNITS.get("CN_FAI_YOY", ("%", "%")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_FAI_YOY",
                        value=safe_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效固定资产投资同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)
        except Exception as e:
            logger.error(f"获取固定资产投资同比数据失败: {e}")
            raise

    def fetch_social_financing(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """获取社会融资规模增量数据。"""
        try:
            df = self.ak.macro_china_shrzgm()
            if df.empty:
                logger.warning("社会融资规模数据为空")
                return []

            df = df.copy()
            date_col = pick_column(df, ["月份"], 0)
            value_col = pick_column(df, ["社会融资规模增量"], 1)
            df["observed_at"] = pd.to_datetime(
                df[date_col].astype(str),
                format="%Y%m",
                errors="coerce",
            )
            df["value"] = pd.to_numeric(df[value_col], errors="coerce")
            df = df[["observed_at", "value"]].dropna()
            df = df[
                (df["observed_at"].dt.date >= start_date)
                & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_SOCIAL_FINANCING",
                *INDICATOR_UNITS.get("CN_SOCIAL_FINANCING", ("亿元", "亿元")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_SOCIAL_FINANCING",
                        value=safe_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效社会融资规模数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)
        except Exception as e:
            logger.error(f"获取社会融资规模数据失败: {e}")
            raise

    def fetch_social_financing_yoy(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """获取社会融资规模同比增速。

        数据源提供月度增量值，因此同比按同月增量派生。
        """
        try:
            df = self.ak.macro_china_shrzgm()
            if df.empty:
                logger.warning("社会融资规模同比数据为空")
                return []

            df = df.copy()
            date_col = pick_column(df, ["月份"], 0)
            value_col = pick_column(df, ["社会融资规模增量"], 1)
            df["observed_at"] = pd.to_datetime(
                df[date_col].astype(str),
                format="%Y%m",
                errors="coerce",
            )
            df["flow_value"] = pd.to_numeric(df[value_col], errors="coerce")
            df = df[["observed_at", "flow_value"]].dropna()
            df["year"] = df["observed_at"].dt.year
            df["month"] = df["observed_at"].dt.month
            prior = (
                df[["year", "month", "flow_value"]]
                .rename(columns={"year": "prior_year", "flow_value": "prior_flow_value"})
            )
            df["prior_year"] = df["year"] - 1
            df = df.merge(prior, on=["prior_year", "month"], how="left")
            df = df[df["prior_flow_value"].notna() & (df["prior_flow_value"] != 0)]
            df["value"] = ((df["flow_value"] / df["prior_flow_value"]) - 1.0) * 100.0
            df = df[
                (df["observed_at"].dt.date >= start_date)
                & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_SOCIAL_FINANCING_YOY",
                *INDICATOR_UNITS.get("CN_SOCIAL_FINANCING_YOY", ("%", "%")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_SOCIAL_FINANCING_YOY",
                        value=safe_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效社会融资规模同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)
        except Exception as e:
            logger.error(f"获取社会融资规模同比数据失败: {e}")
            raise
