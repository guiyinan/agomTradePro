"""
Failover Data Adapter.

Infrastructure layer - provides automatic failover between multiple data sources.
"""

import logging
from datetime import date
from typing import List, Optional

from .base import (
    DataSourceUnavailableError,
    MacroAdapterProtocol,
    MacroDataPoint,
)

logger = logging.getLogger(__name__)


class FailoverAdapter(MacroAdapterProtocol):
    """
    容错切换适配器

    按优先级尝试多个数据源，主数据源失败时自动切换备用源。
    支持配置数据一致性校验，避免静默使用错误数据。
    """

    source_name = "failover"

    def __init__(
        self,
        adapters: list[MacroAdapterProtocol],
        validate_consistency: bool = True,
        tolerance: float = 0.01
    ):
        """
        Args:
            adapters: 数据源适配器列表（按优先级排序）
            validate_consistency: 是否校验数据一致性
            tolerance: 容差比例（1%）
        """
        if not adapters:
            raise ValueError("至少需要一个适配器")

        self.adapters = adapters
        self.validate_consistency = validate_consistency
        self.tolerance = tolerance

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持指定指标（任一适配器支持即可）"""
        return any(adapter.supports(indicator_code) for adapter in self.adapters)

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """
        获取指定指标的数据（带容错切换）

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 数据点列表

        Raises:
            DataSourceUnavailableError: 所有数据源都失败
        """
        last_error = None
        successful_data = None
        successful_source = None

        # 按优先级尝试每个适配器
        for i, adapter in enumerate(self.adapters):
            if not adapter.supports(indicator_code):
                continue

            try:
                logger.info(f"尝试使用 {adapter.source_name} 获取 {indicator_code} 数据...")
                data = adapter.fetch(indicator_code, start_date, end_date)

                if not data:
                    logger.warning(f"{adapter.source_name} 返回空数据")
                    continue

                # 第一个成功的数据源
                if successful_data is None:
                    successful_data = data
                    successful_source = adapter.source_name
                    logger.info(f"成功从 {adapter.source_name} 获取 {len(data)} 条数据")

                    # 如果不校验一致性，直接返回
                    if not self.validate_consistency or i == len(self.adapters) - 1:
                        return data

                else:
                    # 校验与主数据源的一致性
                    if self._validate_consistency(successful_data, data):
                        logger.info(f"备用源 {adapter.source_name} 数据一致性校验通过")
                    else:
                        logger.warning(
                            f"备用源 {adapter.source_name} 与主源 {successful_source} "
                            f"数据差异超过容差 ({self.tolerance*100}%)，"
                            f"建议使用主源数据"
                        )

            except DataSourceUnavailableError as e:
                last_error = e
                logger.warning(f"{adapter.source_name} 获取数据失败: {e}")
                continue

            except Exception as e:
                last_error = e
                logger.error(f"{adapter.source_name} 发生异常: {e}")
                continue

        if successful_data:
            return successful_data

        # 所有适配器都失败
        error_msg = f"所有数据源均无法获取 {indicator_code} 数据"
        if last_error:
            error_msg += f": {last_error}"
        raise DataSourceUnavailableError(error_msg)

    def _validate_consistency(
        self,
        primary_data: list[MacroDataPoint],
        backup_data: list[MacroDataPoint]
    ) -> bool:
        """
        校验主备数据源的一致性

        Args:
            primary_data: 主数据源数据
            backup_data: 备用数据源数据

        Returns:
            bool: 是否在容差范围内
        """
        if not primary_data or not backup_data:
            return True

        # 找到相同日期的数据点进行比较
        primary_dict = {(p.code, p.observed_at): p.value for p in primary_data}
        backup_dict = {(b.code, b.observed_at): b.value for b in backup_data}

        # 比较共同的数据点
        common_keys = set(primary_dict.keys()) & set(backup_dict.keys())

        if not common_keys:
            return True

        max_diff_ratio = 0.0
        for key in common_keys:
            primary_value = primary_dict[key]
            backup_value = backup_dict[key]

            if primary_value == 0:
                continue

            diff_ratio = abs(backup_value - primary_value) / abs(primary_value)
            max_diff_ratio = max(max_diff_ratio, diff_ratio)

        if max_diff_ratio > self.tolerance:
            logger.warning(
                f"数据一致性校验失败: "
                f"最大差异比例 {max_diff_ratio*100:.2f}% "
                f"> 容差 {self.tolerance*100:.2f}%"
            )
            return False

        return True


class MultiSourceAdapter(MacroAdapterProtocol):
    """
    多数据源聚合适配器

    从多个数据源获取数据并合并，去重后返回。
    适用于同一指标可以从多个来源获取的场景。
    """

    source_name = "multi_source"

    def __init__(self, adapters: list[MacroAdapterProtocol]):
        """
        Args:
            adapters: 数据源适配器列表
        """
        if not adapters:
            raise ValueError("至少需要一个适配器")

        self.adapters = adapters

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持指定指标（任一适配器支持即可）"""
        return any(adapter.supports(indicator_code) for adapter in self.adapters)

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """
        从所有支持的适配器获取数据并合并

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 合并去重后的数据点列表
        """
        all_data = []

        for adapter in self.adapters:
            if not adapter.supports(indicator_code):
                continue

            try:
                data = adapter.fetch(indicator_code, start_date, end_date)
                all_data.extend(data)
                logger.info(f"从 {adapter.source_name} 获取 {len(data)} 条数据")

            except Exception as e:
                logger.warning(f"{adapter.source_name} 获取数据失败: {e}")
                continue

        if not all_data:
            raise DataSourceUnavailableError(f"所有数据源均无法获取 {indicator_code} 数据")

        # 去重（保留最新的）
        seen = {}
        for point in all_data:
            key = (point.code, point.observed_at)
            # 优先保留发布时间较新的
            if key not in seen or point.published_at > seen[key].published_at:
                seen[key] = point

        merged_data = list(seen.values())
        merged_data.sort(key=lambda x: x.observed_at)

        logger.info(f"合并后共 {len(merged_data)} 条数据")
        return merged_data


def create_default_adapter(
    tushare_token: str | None = None,
    tushare_http_url: str | None = None,
) -> "MacroAdapterProtocol":
    """
    创建默认的容错适配器配置（从数据库读取设置）

    Args:
        tushare_token: Tushare Token（可选，优先从数据库读取）
        tushare_http_url: Tushare 自定义 HTTP URL（可选）

    Returns:
        MacroAdapterProtocol: 配置好的适配器（可能是单个或 FailoverAdapter）
    """
    from .akshare_adapter import AKShareAdapter
    from .tushare_adapter import TushareAdapter

    # 尝试从数据库加载设置
    try:
        import django
        from django.conf import settings
        if settings.configured:
            django.setup()
            from apps.data_center.infrastructure.models import DataProviderSettingsModel
            settings_obj = DataProviderSettingsModel.load()

            default_source = settings_obj.default_source
            enable_failover = settings_obj.enable_failover
            tolerance = settings_obj.failover_tolerance

            logger.info(
                f"从数据库加载数据源设置: default={default_source}, "
                f"failover={enable_failover}, tolerance={tolerance}"
            )
        else:
            # Django 未配置，使用默认值
            default_source = 'akshare'
            enable_failover = True
            tolerance = 0.01
            logger.warning("Django 未配置，使用默认数据源设置")
    except Exception as e:
        # 数据库未初始化或其他错误，使用默认值
        default_source = 'akshare'
        enable_failover = True
        tolerance = 0.01
        logger.warning(f"无法从数据库读取设置，使用默认值: {e}")

    # 初始化适配器
    akshare_adapter = None
    tushare_adapter = None

    try:
        akshare_adapter = AKShareAdapter()
        logger.info("已初始化 AKShare 适配器")
    except Exception as e:
        logger.warning(f"AKShare 适配器初始化失败: {e}")

    try:
        tushare_adapter = TushareAdapter(
            token=tushare_token,
            http_url=tushare_http_url,
        )
        logger.info("已初始化 Tushare 适配器")
    except Exception as e:
        logger.warning(f"Tushare 适配器初始化失败: {e}")

    # 根据设置返回适配器
    if default_source == 'akshare':
        primary, backup = akshare_adapter, tushare_adapter
        primary_name = "AKShare"
    elif default_source == 'tushare':
        primary, backup = tushare_adapter, akshare_adapter
        primary_name = "Tushare"
    else:  # failover 模式，默认 AKShare 优先
        primary, backup = akshare_adapter, tushare_adapter
        primary_name = "AKShare"

    # 如果不启用容错或没有备用源，直接返回主适配器
    if not enable_failover or backup is None:
        if primary is None:
            raise DataSourceUnavailableError("无法初始化任何数据源适配器")
        logger.info(f"使用单一数据源: {primary_name}")
        return primary

    # 构建适配器列表
    adapters = [a for a in [primary, backup] if a is not None]
    if not adapters:
        raise DataSourceUnavailableError("无法初始化任何数据源适配器")

    logger.info(
        f"创建容错适配器: 优先级={' → '.join([a.source_name for a in adapters])}"
    )
    return FailoverAdapter(
        adapters=adapters,
        validate_consistency=True,
        tolerance=tolerance
    )
