"""
PMI Sub-items Data Fetcher（Regime 滞后性改进 Phase 3）

从手动维护的数据文件获取 PMI 分项指标：
- 新订单指数 (CN_PMI_NEW_ORDER)
- 产成品库存指数 (CN_PMI_INVENTORY)
- 原材料库存指数 (CN_PMI_RAW_MAT)
- 采购量指数 (CN_PMI_PURCHASE)

如果数据文件不存在或为空，返回空列表（系统优雅降级）。

参考文档: docs/development/regime-lag-improvement-plan.md
"""

import pandas as pd
from datetime import date, timedelta
from typing import List, Optional, Dict
import logging
import json
import os

from ..base import MacroDataPoint, DataValidationError

logger = logging.getLogger(__name__)

# PMI 分项指标单位映射
PMI_SUBITEM_UNITS = {
    "CN_PMI_NEW_ORDER": ("指数", "指数"),
    "CN_PMI_INVENTORY": ("指数", "指数"),
    "CN_PMI_RAW_MAT": ("指数", "指数"),
    "CN_PMI_PURCHASE": ("指数", "指数"),
    "CN_PMI_PRODUCTION": ("指数", "指数"),  # 生产指数
    "CN_PMI_EMPLOYMENT": ("指数", "指数"),  # 从业人员指数
    "CN_PMI_SUPPLIER_DELIVERY": ("指数", "指数"),  # 供应商配送时间
}

# 手动数据文件路径
MANUAL_DATA_FILE = os.path.join(
    os.path.dirname(__file__),  # infrastructure/adapters/
    "..", "..", "..",  # 回到 apps/macro/
    "data", "pmi_subitems_manual.json"
)


class PMISubitemsFetcher:
    """PMI 分项指标获取器

    从手动维护的 JSON 文件读取 PMI 分项数据。
    如果文件不存在或为空，返回空列表（系统可优雅降级）。
    """

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn
        self._data_file_path = os.path.abspath(MANUAL_DATA_FILE)

    def _load_manual_data(self) -> List[Dict]:
        """从手动维护的文件加载数据"""
        if not os.path.exists(self._data_file_path):
            logger.warning(f"PMI 分项数据文件不存在: {self._data_file_path}")
            return []

        try:
            with open(self._data_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            records = data.get('data', [])
            if not records:
                logger.warning(f"PMI 分项数据文件为空: {self._data_file_path}")
                return []

            logger.info(f"从 {self._data_file_path} 加载了 {len(records)} 条记录")
            return records

        except json.JSONDecodeError as e:
            logger.error(f"PMI 分项数据文件 JSON 解析失败: {e}")
            return []
        except Exception as e:
            logger.error(f"加载 PMI 分项数据失败: {e}")
            return []

    def _convert_to_data_points(
        self,
        records: List[Dict],
        field_name: str,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """将记录转换为数据点列表"""
        data_points = []
        unit, original_unit = PMI_SUBITEM_UNITS.get(indicator_code, ("指数", "指数"))

        for record in records:
            # 检查是否在日期范围内
            reporting_period_str = record.get('reporting_period', record.get('date', ''))
            try:
                if isinstance(reporting_period_str, str) and len(reporting_period_str) == 10:
                    reporting_period = date.fromisoformat(reporting_period_str)
                else:
                    continue
            except (ValueError, TypeError):
                continue

            if not (start_date <= reporting_period <= end_date):
                continue

            # 获取字段值
            value = record.get(field_name)
            if value is None:
                continue

            try:
                value_float = float(value)
            except (ValueError, TypeError):
                continue

            try:
                point = MacroDataPoint(
                    code=indicator_code,
                    value=value_float,
                    observed_at=reporting_period,
                    source=self.source_name,
                    unit=unit,
                    original_unit=original_unit,
                )
                self._validate(point)
                data_points.append(point)
            except (ValueError, DataValidationError) as e:
                logger.warning(f"跳过无效 PMI 数据: {record}, 错误: {e}")

        return data_points

    def fetch_pmi_new_order(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取 PMI 新订单指数

        新订单指数是 PMI 的先行指标，反映市场需求状况。
        通常领先整体经济活动 1-2 个月。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 新订单指数数据点列表
        """
        indicator_code = 'CN_PMI_NEW_ORDER'
        records = self._load_manual_data()

        if not records:
            logger.info(f"{indicator_code}: 无可用数据，返回空列表（系统可正常降级）")
            return []

        data_points = self._convert_to_data_points(
            records, 'new_order', indicator_code, start_date, end_date
        )

        logger.info(f"{indicator_code}: 获取到 {len(data_points)} 条记录")
        return self._sort_and_deduplicate(data_points)

    def fetch_pmi_inventory(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取 PMI 产成品库存指数

        产成品库存反映企业库存周期：
        - 库存下降：需求旺盛，企业去库存
        - 库存上升：需求放缓，企业补库存

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 产成品库存指数数据点列表
        """
        indicator_code = 'CN_PMI_INVENTORY'
        records = self._load_manual_data()

        if not records:
            logger.info(f"{indicator_code}: 无可用数据，返回空列表（系统可正常降级）")
            return []

        data_points = self._convert_to_data_points(
            records, 'inventory_finished', indicator_code, start_date, end_date
        )

        logger.info(f"{indicator_code}: 获取到 {len(data_points)} 条记录")
        return self._sort_and_deduplicate(data_points)

    def fetch_pmi_raw_material(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取 PMI 原材料库存指数

        原材料库存反映企业采购意愿和对未来的预期。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 原材料库存指数数据点列表
        """
        indicator_code = 'CN_PMI_RAW_MAT'
        records = self._load_manual_data()

        if not records:
            logger.info(f"{indicator_code}: 无可用数据，返回空列表（系统可正常降级）")
            return []

        data_points = self._convert_to_data_points(
            records, 'inventory_raw_material', indicator_code, start_date, end_date
        )

        logger.info(f"{indicator_code}: 获取到 {len(data_points)} 条记录")
        return self._sort_and_deduplicate(data_points)

    def fetch_pmi_purchase(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取 PMI 采购量指数

        采购量指数反映企业生产活跃度。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 采购量指数数据点列表
        """
        indicator_code = 'CN_PMI_PURCHASE'
        records = self._load_manual_data()

        if not records:
            logger.info(f"{indicator_code}: 无可用数据，返回空列表（系统可正常降级）")
            return []

        data_points = self._convert_to_data_points(
            records, 'purchase', indicator_code, start_date, end_date
        )

        logger.info(f"{indicator_code}: 获取到 {len(data_points)} 条记录")
        return self._sort_and_deduplicate(data_points)

    def fetch_pmi_production(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取 PMI 生产指数

        生产指数反映企业生产活动活跃度。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 生产指数数据点列表
        """
        indicator_code = 'CN_PMI_PRODUCTION'
        records = self._load_manual_data()

        if not records:
            logger.info(f"{indicator_code}: 无可用数据，返回空列表（系统可正常降级）")
            return []

        data_points = self._convert_to_data_points(
            records, 'production', indicator_code, start_date, end_date
        )

        logger.info(f"{indicator_code}: 获取到 {len(data_points)} 条记录")
        return self._sort_and_deduplicate(data_points)

    def fetch_pmi_employment(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取 PMI 从业人员指数

        从业人员指数反映就业状况。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 从业人员指数数据点列表
        """
        indicator_code = 'CN_PMI_EMPLOYMENT'
        records = self._load_manual_data()

        if not records:
            logger.info(f"{indicator_code}: 无可用数据，返回空列表（系统可正常降级）")
            return []

        data_points = self._convert_to_data_points(
            records, 'employment', indicator_code, start_date, end_date
        )

        logger.info(f"{indicator_code}: 获取到 {len(data_points)} 条记录")
        return self._sort_and_deduplicate(data_points)
