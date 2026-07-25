"""Data Center fetchers for employment, housing, and refined-oil indicators."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from ..base import DataValidationError, MacroDataPoint
from .common import parse_required_float, resolve_indicator_units

logger = logging.getLogger(__name__)

ValidateDataPoint = Callable[[MacroDataPoint], None]
SortAndDeduplicate = Callable[[list[MacroDataPoint]], list[MacroDataPoint]]

_NATIONAL_UNEMPLOYMENT_ITEM = "全国城镇调查失业率"
_HOUSE_CITY = "北京"


def parse_month_period(value: object) -> str:
    """Normalize supported monthly source labels without partial matching."""

    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})(\d{2})", text)
    if match is None:
        match = re.fullmatch(r"(\d{4})年(\d{1,2})月份?", text)
    if match is None:
        return text

    year, month_text = match.groups()
    month = int(month_text)
    if not 1 <= month <= 12:
        return text
    return f"{year}-{month:02d}-01"


def _require_columns(
    dataframe: Any,
    required_columns: tuple[str, ...],
    *,
    dataset_name: str,
) -> None:
    """Reject upstream schema drift instead of guessing columns by position."""

    missing = [column for column in required_columns if column not in dataframe.columns]
    if missing:
        raise DataValidationError(
            f"{dataset_name} 数据缺少必需列 {missing}，当前列: {list(dataframe.columns)}"
        )


class OtherIndicatorFetcher:
    """Fetch employment, Beijing new-house, and refined-oil facts."""

    def __init__(
        self,
        ak: Any,
        source_name: str,
        validate_fn: ValidateDataPoint,
        sort_dedup_fn: SortAndDeduplicate,
    ) -> None:
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_unemployment(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Fetch the NBS national urban surveyed unemployment rate."""

        df = self.ak.macro_china_urban_unemployment()
        if df.empty:
            logger.warning("失业率数据为空")
            return []

        _require_columns(
            df,
            ("date", "item", "value"),
            dataset_name="城镇调查失业率",
        )
        df = df[df["item"] == _NATIONAL_UNEMPLOYMENT_ITEM].copy()
        if df.empty:
            raise DataValidationError(
                f"城镇调查失业率数据缺少指标项: {_NATIONAL_UNEMPLOYMENT_ITEM}"
            )

        df["observed_at"] = pd.to_datetime(
            df["date"].apply(parse_month_period),
            format="mixed",
            errors="coerce",
        )
        df = df[["observed_at", "value"]].dropna()
        df = df[(df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)]

        data_points: list[MacroDataPoint] = []
        unit, original_unit = resolve_indicator_units("CN_UNEMPLOYMENT")
        for _, row in df.iterrows():
            try:
                value = parse_required_float(row["value"])
                if not 0 < value <= 100:
                    raise DataValidationError(
                        f"全国城镇调查失业率必须在 0..100 之间且不能为 0: {value}"
                    )
                point = MacroDataPoint(
                    code="CN_UNEMPLOYMENT",
                    value=value,
                    observed_at=row["observed_at"].date(),
                    source=self.source_name,
                    unit=unit,
                    original_unit=original_unit,
                )
                self._validate(point)
                data_points.append(point)
            except (ValueError, DataValidationError) as exc:
                logger.warning("跳过无效失业率数据: %s, 错误: %s", row, exc)

        return self._sort_and_deduplicate(data_points)

    def fetch_new_house_price(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Fetch Beijing new-commercial-home year-on-year price change."""

        df = self.ak.macro_china_new_house_price()
        if df.empty:
            logger.warning("新房价格指数数据为空")
            return []

        value_column = "新建商品住宅价格指数-同比"
        _require_columns(
            df,
            ("日期", "城市", value_column),
            dataset_name="新建商品住宅价格指数",
        )
        df = df[df["城市"] == _HOUSE_CITY].copy()
        if df.empty:
            raise DataValidationError(f"新房价格指数数据缺少城市: {_HOUSE_CITY}")

        df["observed_at"] = pd.to_datetime(df["日期"], format="mixed", errors="coerce")
        df = df[["observed_at", value_column]].dropna()
        df = df[(df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)]

        data_points: list[MacroDataPoint] = []
        unit, original_unit = resolve_indicator_units("CN_NEW_HOUSE_PRICE")
        for _, row in df.iterrows():
            try:
                point = MacroDataPoint(
                    code="CN_NEW_HOUSE_PRICE",
                    value=parse_required_float(row[value_column]) - 100.0,
                    observed_at=row["observed_at"].date(),
                    source=self.source_name,
                    unit=unit,
                    original_unit=original_unit,
                )
                self._validate(point)
                data_points.append(point)
            except (ValueError, DataValidationError) as exc:
                logger.warning("跳过无效新房价格指数数据: %s, 错误: %s", row, exc)

        return self._sort_and_deduplicate(data_points)

    def fetch_oil_price(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Fetch the published gasoline price in its source unit, yuan per tonne."""

        df = self.ak.energy_oil_hist()
        if df.empty:
            logger.warning("成品油价格数据为空")
            return []

        _require_columns(
            df,
            ("调整日期", "汽油价格"),
            dataset_name="汽柴油历史调价",
        )
        df = df.copy()
        df["observed_at"] = pd.to_datetime(
            df["调整日期"],
            format="mixed",
            errors="coerce",
        )
        df = df[["observed_at", "汽油价格"]].dropna()
        df = df[(df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)]

        data_points: list[MacroDataPoint] = []
        unit, original_unit = resolve_indicator_units("CN_OIL_PRICE")
        for _, row in df.iterrows():
            try:
                point = MacroDataPoint(
                    code="CN_OIL_PRICE",
                    value=parse_required_float(row["汽油价格"]),
                    observed_at=row["observed_at"].date(),
                    source=self.source_name,
                    unit=unit,
                    original_unit=original_unit,
                )
                self._validate(point)
                data_points.append(point)
            except (ValueError, DataValidationError) as exc:
                logger.warning("跳过无效成品油价格数据: %s, 错误: %s", row, exc)

        return self._sort_and_deduplicate(data_points)
