"""PMI sub-item fetcher backed by the governed manual data file."""

from __future__ import annotations

import json
import logging
from calendar import monthrange
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from shared.numeric import safe_float

from ..base import DataValidationError, MacroDataPoint
from .common import resolve_indicator_units

logger = logging.getLogger(__name__)

ValidateDataPoint = Callable[[MacroDataPoint], None]
SortAndDeduplicate = Callable[[list[MacroDataPoint]], list[MacroDataPoint]]
ManualRecord = dict[str, object]

MANUAL_SOURCE_NAME = "manual_pmi_subitems"
MANUAL_DATA_FILE = (
    Path(__file__).resolve().parents[4] / "macro" / "data" / "pmi_subitems_manual.json"
)


class PMISubitemsFetcher:
    """Read official PMI sub-items from the manually maintained JSON snapshot."""

    def __init__(
        self,
        ak: Any,
        source_name: str,
        validate_fn: ValidateDataPoint,
        sort_dedup_fn: SortAndDeduplicate,
    ) -> None:
        # ``ak`` and ``source_name`` remain in the shared fetcher constructor
        # contract, but this provider is an explicit manual-file source.
        self._upstream_context = (ak, source_name)
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn
        self._data_file_path = MANUAL_DATA_FILE

    def _load_manual_data(self) -> list[ManualRecord]:
        """Load and structurally validate the manually maintained payload."""

        if not self._data_file_path.is_file():
            logger.warning("PMI 分项数据文件不存在: %s", self._data_file_path)
            return []

        try:
            with self._data_file_path.open(encoding="utf-8") as file_handle:
                payload: object = json.load(file_handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise DataValidationError(
                f"PMI 分项数据文件无法读取: {self._data_file_path}: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise DataValidationError("PMI 分项数据根节点必须是对象")
        raw_records = payload.get("data")
        if raw_records is None:
            raise DataValidationError("PMI 分项数据缺少 data 数组")
        if not isinstance(raw_records, list):
            raise DataValidationError("PMI 分项 data 必须是数组")
        if not raw_records:
            logger.warning("PMI 分项数据文件为空: %s", self._data_file_path)
            return []

        records: list[ManualRecord] = []
        for index, raw_record in enumerate(raw_records):
            if not isinstance(raw_record, dict):
                raise DataValidationError(f"PMI 分项第 {index + 1} 条记录必须是对象")
            if not all(isinstance(key, str) for key in raw_record):
                raise DataValidationError(f"PMI 分项第 {index + 1} 条记录包含非字符串字段名")
            records.append(dict(raw_record))

        logger.info("从 %s 加载了 %s 条记录", self._data_file_path, len(records))
        return records

    @staticmethod
    def _parse_reporting_period(record: ManualRecord) -> date | None:
        raw_period = record.get("reporting_period", record.get("date"))
        if not isinstance(raw_period, str):
            return None
        try:
            reporting_period = date.fromisoformat(raw_period)
        except ValueError:
            return None
        if len(raw_period) != 10:
            return None
        if (
            reporting_period.day
            != monthrange(
                reporting_period.year,
                reporting_period.month,
            )[1]
        ):
            return None
        return reporting_period

    def _convert_to_data_points(
        self,
        records: list[ManualRecord],
        field_name: str,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Convert validated records into bounded monthly PMI index points."""

        if start_date > end_date:
            raise ValueError("PMI 分项起始日期不得晚于结束日期")

        unit, original_unit = resolve_indicator_units(indicator_code)
        data_points: list[MacroDataPoint] = []
        for record in records:
            reporting_period = self._parse_reporting_period(record)
            if reporting_period is None or not start_date <= reporting_period <= end_date:
                continue

            raw_value = record.get(field_name)
            if isinstance(raw_value, bool):
                logger.warning("跳过布尔 PMI 分项值: %s", record)
                continue
            value = safe_float(raw_value)
            if value is None or not 0.0 <= value <= 100.0:
                logger.warning("跳过越界或无效 PMI 分项值: %s", record)
                continue

            try:
                point = MacroDataPoint(
                    code=indicator_code,
                    value=value,
                    observed_at=reporting_period,
                    source=MANUAL_SOURCE_NAME,
                    unit=unit,
                    original_unit=original_unit,
                )
                self._validate(point)
            except (ValueError, DataValidationError) as exc:
                logger.warning("跳过无效 PMI 分项数据: %s, 错误: %s", record, exc)
                continue
            data_points.append(point)

        return data_points

    def _fetch_field(
        self,
        *,
        field_name: str,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        if start_date > end_date:
            raise ValueError("PMI 分项起始日期不得晚于结束日期")
        records = self._load_manual_data()
        if not records:
            logger.info("%s: 无可用数据，返回空列表", indicator_code)
            return []
        data_points = self._convert_to_data_points(
            records,
            field_name,
            indicator_code,
            start_date,
            end_date,
        )
        logger.info("%s: 获取到 %s 条记录", indicator_code, len(data_points))
        return self._sort_and_deduplicate(data_points)

    def fetch_pmi_new_order(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Return the PMI new-order index."""

        return self._fetch_field(
            field_name="new_order",
            indicator_code="CN_PMI_NEW_ORDER",
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_pmi_inventory(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Return the PMI finished-goods inventory index."""

        return self._fetch_field(
            field_name="inventory_finished",
            indicator_code="CN_PMI_INVENTORY",
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_pmi_raw_material(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Return the PMI raw-material inventory index."""

        return self._fetch_field(
            field_name="inventory_raw_material",
            indicator_code="CN_PMI_RAW_MAT",
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_pmi_purchase(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Return the PMI purchase-volume index."""

        return self._fetch_field(
            field_name="purchase",
            indicator_code="CN_PMI_PURCHASE",
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_pmi_production(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Return the PMI production index."""

        return self._fetch_field(
            field_name="production",
            indicator_code="CN_PMI_PRODUCTION",
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_pmi_employment(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        """Return the PMI employment index."""

        return self._fetch_field(
            field_name="employment",
            indicator_code="CN_PMI_EMPLOYMENT",
            start_date=start_date,
            end_date=end_date,
        )
