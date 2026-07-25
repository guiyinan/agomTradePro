"""
Data Center 金融指标数据获取器。

包含外汇储备、LPR、SHIBOR、存款准备金率、信贷数据等金融指标的获取逻辑。
"""

import logging
import re
from calendar import monthrange
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from shared.numeric import safe_float

from ..base import DataValidationError, MacroDataPoint
from .common import resolve_indicator_units

logger = logging.getLogger(__name__)


ValidateDataPoint = Callable[[MacroDataPoint], None]
SortAndDeduplicate = Callable[[list[MacroDataPoint]], list[MacroDataPoint]]


def parse_chinese_date(date_value: object) -> str:
    """解析中文月份格式为期末日期。"""
    date_text = str(date_value)
    if "年" in date_text and "月" in date_text:
        match = re.fullmatch(r"\s*(\d{4})年(\d{1,2})月份?\s*", date_text)
        if match:
            year, month = match.groups()
            year_int = int(year)
            month_int = int(month)
            if not 1 <= month_int <= 12:
                return date_text
            last_day = monthrange(year_int, month_int)[1]
            return f"{year}-{month.zfill(2)}-{last_day:02d}"
    return date_text


def parse_chinese_full_date(date_value: object) -> str:
    """解析完整中文日期格式 (YYYY年MM月DD日)"""
    date_text = str(date_value)
    if "年" in date_text and "月" in date_text and "日" in date_text:
        match = re.fullmatch(
            r"\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*",
            date_text,
        )
        if match:
            year, month, day = match.groups()
            try:
                parsed = date(int(year), int(month), int(day))
            except ValueError:
                return date_text
            else:
                return parsed.isoformat()
    return date_text


def _required_float(value: object, *, strip_chars: str = ",") -> float:
    """Parse one required finite numeric value from an external payload."""

    parsed = safe_float(value, strip_chars=strip_chars)
    if parsed is None:
        raise ValueError(f"invalid required numeric value: {value!r}")
    return parsed


def _safe_percent_point(value: object) -> float:
    """Return a required rate value in percentage points."""

    return _required_float(value, strip_chars=",%")


def _require_column(
    dataframe: Any,
    candidates: tuple[str, ...],
    *,
    indicator_code: str,
) -> str:
    """Resolve a semantic source column without positional guessing."""

    for candidate in candidates:
        if candidate in dataframe.columns:
            return candidate
    raise DataValidationError(
        f"{indicator_code} 数据缺少必需列 {list(candidates)}，" f"当前列: {list(dataframe.columns)}"
    )


class FinancialIndicatorFetcher:
    """金融指标获取器"""

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

    def fetch_fx_reserves(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国外汇储备余额数据。"""
        try:
            df = self.ak.macro_china_fx_gold()
            if df.empty:
                logger.warning("外汇储备数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_FX_RESERVES",
            )
            value_col = _require_column(
                df,
                ("国家外汇储备-数值",),
                indicator_code="CN_FX_RESERVES",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_FX_RESERVES")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_FX_RESERVES",
                        value=_required_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效外汇储备数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取外汇储备数据失败: {e}")
            raise

    def fetch_lpr(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国 LPR 数据"""
        try:
            df = self.ak.macro_china_lpr()
            if df.empty:
                logger.warning("LPR 数据为空")
                return []

            date_col = _require_column(
                df,
                ("TRADE_DATE", "日期"),
                indicator_code="CN_LPR",
            )
            value_col = _require_column(
                df,
                ("LPR1Y", "1年期"),
                indicator_code="CN_LPR",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col],
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_LPR")
            for _, row in df.iterrows():
                try:
                    value_decimal = _safe_percent_point(row["value"])
                    point = MacroDataPoint(
                        code="CN_LPR",
                        value=value_decimal,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 LPR 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 LPR 数据失败: {e}")
            raise

    def fetch_shibor(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国 SHIBOR 数据"""
        try:
            df = self.ak.macro_china_shibor_all()
            if df.empty:
                logger.warning("SHIBOR 数据为空")
                return []

            date_col = _require_column(
                df,
                ("日期",),
                indicator_code="CN_SHIBOR",
            )
            value_col = _require_column(
                df,
                ("O/N-定价", "隔夜", "O/N"),
                indicator_code="CN_SHIBOR",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col],
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_SHIBOR")
            for _, row in df.iterrows():
                try:
                    value_decimal = _safe_percent_point(row["value"])
                    point = MacroDataPoint(
                        code="CN_SHIBOR",
                        value=value_decimal,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 SHIBOR 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 SHIBOR 数据失败: {e}")
            raise

    def fetch_rrr(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国存款准备金率数据"""
        try:
            df = self.ak.macro_china_reserve_requirement_ratio()
            if df.empty:
                logger.warning("存款准备金率数据为空")
                return []

            date_col = _require_column(
                df,
                ("生效时间",),
                indicator_code="CN_RRR",
            )
            value_col = _require_column(
                df,
                ("大型金融机构-调整后",),
                indicator_code="CN_RRR",
            )

            df = df.copy()
            df["observed_at"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_full_date),
                format="mixed",
                errors="coerce",
            )
            df["value"] = pd.to_numeric(df[value_col], errors="coerce")
            df = df[["observed_at", "value"]].dropna()
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_RRR")
            for _, row in df.iterrows():
                try:
                    value_decimal = _safe_percent_point(row["value"])
                    point = MacroDataPoint(
                        code="CN_RRR",
                        value=value_decimal,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效存款准备金率数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取存款准备金率数据失败: {e}")
            raise

    def fetch_new_credit(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国新增信贷数据"""
        try:
            df = self.ak.macro_china_new_financial_credit()
            if df.empty:
                logger.warning("新增信贷数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_NEW_CREDIT",
            )
            value_col = _require_column(
                df,
                ("当月",),
                indicator_code="CN_NEW_CREDIT",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_NEW_CREDIT")
            for _, row in df.iterrows():
                try:
                    value = _required_float(row["value"])
                    point = MacroDataPoint(
                        code="CN_NEW_CREDIT",
                        value=value,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效新增信贷数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取新增信贷数据失败: {e}")
            raise

    def fetch_rmb_deposit(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取新增人民币存款总额数据。"""
        try:
            df = self.ak.macro_rmb_deposit()
            if df.empty:
                logger.warning("人民币存款数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_RMB_DEPOSIT",
            )
            value_col = _require_column(
                df,
                ("新增存款-数量",),
                indicator_code="CN_RMB_DEPOSIT",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_RMB_DEPOSIT")
            for _, row in df.iterrows():
                try:
                    value = _required_float(row["value"])
                    point = MacroDataPoint(
                        code="CN_RMB_DEPOSIT",
                        value=value,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效人民币存款数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取人民币存款数据失败: {e}")
            raise

    def fetch_rmb_loan(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取新增人民币贷款总额数据。"""
        try:
            df = self.ak.macro_rmb_loan()
            if df.empty:
                logger.warning("人民币贷款数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_RMB_LOAN",
            )
            value_col = _require_column(
                df,
                ("新增人民币贷款-总额",),
                indicator_code="CN_RMB_LOAN",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_RMB_LOAN")
            for _, row in df.iterrows():
                try:
                    value = _required_float(row["value"])
                    point = MacroDataPoint(
                        code="CN_RMB_LOAN",
                        value=value,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效人民币贷款数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取人民币贷款数据失败: {e}")
            raise

    def fetch_dr007(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取 DR007 数据"""
        try:
            if not hasattr(self.ak, "repo_rate_hist"):
                logger.warning("当前 akshare 版本不支持 repo_rate_hist, 无法获取 DR007")
                return []

            frames: list[Any] = []
            window_start = start_date
            while window_start <= end_date:
                window_end = min(window_start + timedelta(days=364), end_date)
                try:
                    chunk = self.ak.repo_rate_hist(
                        start_date=window_start.strftime("%Y%m%d"),
                        end_date=window_end.strftime("%Y%m%d"),
                    )
                except Exception as exc:
                    logger.warning(
                        "DR007 区间 %s ~ %s 获取失败，跳过该窗口: %s",
                        window_start,
                        window_end,
                        exc,
                    )
                    window_start = window_end + timedelta(days=1)
                    continue
                if chunk is not None and not chunk.empty:
                    frames.append(chunk)
                window_start = window_end + timedelta(days=1)

            if not frames:
                logger.warning("DR007 数据为空")
                return []
            df = pd.concat(frames, ignore_index=True)

            date_col = _require_column(
                df,
                ("date", "日期"),
                indicator_code="CN_DR007",
            )
            value_col = _require_column(
                df,
                ("FDR007", "DR007"),
                indicator_code="CN_DR007",
            )

            df["date"] = pd.to_datetime(
                df[date_col],
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_DR007")
            for _, row in df.iterrows():
                try:
                    value_decimal = _safe_percent_point(row["value"])
                    point = MacroDataPoint(
                        code="CN_DR007",
                        value=value_decimal,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 DR007 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 DR007 数据失败: {e}")
            raise

    def fetch_pboc_open_market(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取央行公开市场操作净投放数据"""
        try:
            if not hasattr(self.ak, "macro_china_pboc_open_market"):
                logger.warning(
                    "当前 akshare 版本不支持 macro_china_pboc_open_market, 无法获取央行公开市场操作数据"
                )
                return []

            df = self.ak.macro_china_pboc_open_market()
            if df.empty:
                logger.warning("央行公开市场操作数据为空")
                return []

            date_col = _require_column(
                df,
                ("日期",),
                indicator_code="CN_PBOC_NET_INJECTION",
            )
            value_col = _require_column(
                df,
                ("净投放",),
                indicator_code="CN_PBOC_NET_INJECTION",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col],
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_PBOC_NET_INJECTION")
            for _, row in df.iterrows():
                try:
                    value_text = (
                        str(row["value"]).replace("亿元", "").replace("亿", "").replace("元", "")
                    )
                    value = _required_float(value_text)

                    point = MacroDataPoint(
                        code="CN_PBOC_NET_INJECTION",
                        value=value,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效央行公开市场操作数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取央行公开市场操作数据失败: {e}")
            raise
