"""Data Center fetchers for monthly customs trade indicators."""

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
TradeValueParser = Callable[[Any], float]

_DATE_COLUMN = "月份"
_EXPORT_AMOUNT_COLUMN = "当月出口额-金额"
_EXPORT_YOY_COLUMN = "当月出口额-同比增长"
_IMPORT_AMOUNT_COLUMN = "当月进口额-金额"
_IMPORT_YOY_COLUMN = "当月进口额-同比增长"
_AKSHARE_CUSTOMS_AMOUNT_UNIT = "千美元"


def parse_trade_month(value: object) -> str:
    """Normalize a complete customs month label to its month-start date."""

    raw = str(value).strip()
    match = re.fullmatch(r"(\d{4})年(\d{1,2})月份?", raw)
    if match is None:
        return raw

    year, month_text = match.groups()
    month = int(month_text)
    if not 1 <= month <= 12:
        return raw
    return f"{year}-{month:02d}-01"


def _require_columns(
    dataframe: Any,
    required_columns: tuple[str, ...],
    *,
    indicator_code: str,
) -> None:
    """Reject customs schema drift instead of guessing columns by position."""

    missing = [column for column in required_columns if column not in dataframe.columns]
    if missing:
        raise DataValidationError(
            f"{indicator_code} 数据缺少必需列 {missing}，当前列: {list(dataframe.columns)}"
        )


def _parse_positive_customs_amount(value: object) -> float:
    """Parse one non-missing monthly customs amount."""

    parsed = parse_required_float(value)
    if parsed <= 0:
        raise DataValidationError(f"海关当月金额必须大于 0: {parsed}")
    return parsed


class TradeIndicatorFetcher:
    """Fetch monthly customs amounts, growth rates, and derived balance."""

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

    def _fetch_customs_series(
        self,
        *,
        indicator_code: str,
        required_value_columns: tuple[str, ...],
        value_parser: TradeValueParser,
        start_date: date,
        end_date: date,
        source_unit: str | None = None,
    ) -> list[MacroDataPoint]:
        """Build one series from the canonical monthly customs dataset."""

        df = self.ak.macro_china_hgjck()
        if df.empty:
            logger.warning("%s 数据为空", indicator_code)
            return []

        _require_columns(
            df,
            (_DATE_COLUMN, *required_value_columns),
            indicator_code=indicator_code,
        )
        df = df.copy()
        df["observed_at"] = pd.to_datetime(
            df[_DATE_COLUMN].apply(parse_trade_month),
            format="mixed",
            errors="coerce",
        )
        df = df.dropna(subset=["observed_at"])
        df = df[(df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)]

        unit_kwargs: dict[str, str] = {}
        if source_unit is not None:
            unit_kwargs = {
                "source_type": self.source_name,
                "source_unit": source_unit,
            }
        unit, original_unit = resolve_indicator_units(
            indicator_code,
            **unit_kwargs,
        )

        data_points: list[MacroDataPoint] = []
        selected_columns = ["observed_at", *required_value_columns]
        for _, row in df[selected_columns].iterrows():
            try:
                point = MacroDataPoint(
                    code=indicator_code,
                    value=value_parser(row),
                    observed_at=row["observed_at"].date(),
                    source=self.source_name,
                    unit=unit,
                    original_unit=original_unit,
                )
                self._validate(point)
                data_points.append(point)
            except (ValueError, DataValidationError) as exc:
                logger.warning(
                    "跳过无效 %s 数据: %s, 错误: %s",
                    indicator_code,
                    row,
                    exc,
                )

        return self._sort_and_deduplicate(data_points)

    def fetch_exports(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Fetch monthly exports in the AKShare source unit, thousand USD."""

        return self._fetch_customs_series(
            indicator_code="CN_EXPORTS",
            required_value_columns=(_EXPORT_AMOUNT_COLUMN,),
            value_parser=lambda row: _parse_positive_customs_amount(row[_EXPORT_AMOUNT_COLUMN]),
            start_date=start_date,
            end_date=end_date,
            source_unit=_AKSHARE_CUSTOMS_AMOUNT_UNIT,
        )

    def fetch_export_yoy(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Fetch monthly export year-on-year growth in percentage points."""

        return self._fetch_customs_series(
            indicator_code="CN_EXPORT_YOY",
            required_value_columns=(_EXPORT_YOY_COLUMN,),
            value_parser=lambda row: parse_required_float(row[_EXPORT_YOY_COLUMN]),
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_imports(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Fetch monthly imports in the AKShare source unit, thousand USD."""

        return self._fetch_customs_series(
            indicator_code="CN_IMPORTS",
            required_value_columns=(_IMPORT_AMOUNT_COLUMN,),
            value_parser=lambda row: _parse_positive_customs_amount(row[_IMPORT_AMOUNT_COLUMN]),
            start_date=start_date,
            end_date=end_date,
            source_unit=_AKSHARE_CUSTOMS_AMOUNT_UNIT,
        )

    def fetch_import_yoy(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Fetch monthly import year-on-year growth in percentage points."""

        return self._fetch_customs_series(
            indicator_code="CN_IMPORT_YOY",
            required_value_columns=(_IMPORT_YOY_COLUMN,),
            value_parser=lambda row: parse_required_float(row[_IMPORT_YOY_COLUMN]),
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_trade_balance(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Derive monthly trade balance from same-period exports and imports."""

        return self._fetch_customs_series(
            indicator_code="CN_TRADE_BALANCE",
            required_value_columns=(
                _EXPORT_AMOUNT_COLUMN,
                _IMPORT_AMOUNT_COLUMN,
            ),
            value_parser=lambda row: (
                _parse_positive_customs_amount(row[_EXPORT_AMOUNT_COLUMN])
                - _parse_positive_customs_amount(row[_IMPORT_AMOUNT_COLUMN])
            ),
            start_date=start_date,
            end_date=end_date,
            source_unit=_AKSHARE_CUSTOMS_AMOUNT_UNIT,
        )
