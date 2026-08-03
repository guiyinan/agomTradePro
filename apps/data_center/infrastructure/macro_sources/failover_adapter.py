"""
Failover macro-source adapter.

Infrastructure layer - provides automatic failover between multiple data sources.
"""

import logging
import math
from collections.abc import Sequence
from datetime import date

from apps.data_center.domain.rules import macro_series_are_consistent

from .base import (
    DataSourceUnavailableError,
    MacroAdapterProtocol,
    MacroDataPoint,
)

logger = logging.getLogger(__name__)

RUNTIME_FAILOVER_TOLERANCE_KEY = "data_center.provider.failover_tolerance"
RUNTIME_FAILOVER_ENABLED_KEY = "data_center.provider.enable_failover"


def _resolve_failover_tolerance(
    persisted_tolerance: float,
    *,
    environment: str,
) -> float:
    """Prefer the active Config Center snapshot for provider consistency checks.

    ``DataProviderSettings`` remains a short-lived compatibility source while
    existing profiles are migrated.  It is deliberately passed in by the
    caller; this helper never invents a module-level tolerance when the runtime
    profile is absent.  Malformed runtime values also fall back to the already
    validated owner setting and are logged for remediation.
    """

    try:
        from apps.config_center.application.runtime_public import (
            get_active_runtime_value,
        )

        raw_value = get_active_runtime_value(
            environment=environment,
            definition_key=RUNTIME_FAILOVER_TOLERANCE_KEY,
        )
    except Exception as exc:
        logger.warning(
            "Config Center failover tolerance unavailable; using owner setting " "(error_type=%s)",
            type(exc).__name__,
        )
        return float(persisted_tolerance)

    if raw_value is None:
        logger.info(
            "Config Center failover tolerance is not active for environment %s; "
            "using owner compatibility setting",
            environment,
        )
        return float(persisted_tolerance)

    try:
        if isinstance(raw_value, bool):
            raise ValueError("boolean is not a numeric tolerance")
        if not isinstance(raw_value, (int, float, str)):
            raise ValueError("runtime value is not a numeric scalar")
        resolved = float(raw_value)
        if not math.isfinite(resolved) or not 0.0 <= resolved <= 1.0:
            raise ValueError("tolerance must be finite and between 0 and 1")
    except (TypeError, ValueError) as exc:
        logger.error(
            "Invalid Config Center failover tolerance; using owner setting " "(error=%s)",
            str(exc),
        )
        return float(persisted_tolerance)
    logger.info("Using Config Center failover tolerance for environment %s", environment)
    return resolved


def _resolve_failover_enabled(
    persisted_enabled: bool,
    *,
    environment: str,
) -> bool:
    """Prefer Config Center's typed failover switch with an explicit owner fallback."""

    try:
        from apps.config_center.application.runtime_public import (
            get_active_runtime_value,
        )

        raw_value = get_active_runtime_value(
            environment=environment,
            definition_key=RUNTIME_FAILOVER_ENABLED_KEY,
        )
    except Exception as exc:
        logger.warning(
            "Config Center failover switch unavailable; using owner setting " "(error_type=%s)",
            type(exc).__name__,
        )
        return bool(persisted_enabled)

    if raw_value is None:
        logger.info(
            "Config Center failover switch is not active for environment %s; "
            "using owner compatibility setting",
            environment,
        )
        return bool(persisted_enabled)
    if not isinstance(raw_value, bool):
        logger.error(
            "Invalid Config Center failover switch; using owner setting " "(value_type=%s)",
            type(raw_value).__name__,
        )
        return bool(persisted_enabled)
    logger.info("Using Config Center failover switch for environment %s", environment)
    return raw_value


class FailoverAdapter(MacroAdapterProtocol):
    """
    容错切换适配器

    按优先级尝试多个数据源，主数据源失败时自动切换备用源。
    支持配置数据一致性校验，避免静默使用错误数据。
    """

    source_name = "failover"

    def __init__(
        self,
        adapters: Sequence[MacroAdapterProtocol],
        validate_consistency: bool = True,
        tolerance: float = 0.01,
    ) -> None:
        """
        Args:
            adapters: 数据源适配器列表（按优先级排序）
            validate_consistency: 是否校验数据一致性
            tolerance: 容差比例（1%）
        """
        if not adapters:
            raise ValueError("至少需要一个适配器")
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(float(tolerance))
            or not 0.0 <= float(tolerance) <= 1.0
        ):
            raise ValueError("tolerance must be finite and between 0 and 1")

        self.adapters = tuple(adapters)
        self.validate_consistency = validate_consistency
        self.tolerance = float(tolerance)

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持指定指标（任一适配器支持即可）"""
        return any(adapter.supports(indicator_code) for adapter in self.adapters)

    def fetch(self, indicator_code: str, start_date: date, end_date: date) -> list[MacroDataPoint]:
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
        last_error: Exception | None = None
        successful_data: list[MacroDataPoint] | None = None
        successful_source: str | None = None
        successful_index: int | None = None
        fallback_validation_attempted = False
        fallback_validation_failed = False

        # 按优先级尝试每个适配器
        for i, adapter in enumerate(self.adapters):
            if not adapter.supports(indicator_code):
                continue

            try:
                logger.info(
                    "尝试使用 %s 获取 %s 数据...",
                    adapter.source_name,
                    indicator_code,
                )
                data = adapter.fetch(indicator_code, start_date, end_date)

                if not data:
                    logger.warning("%s 返回空数据", adapter.source_name)
                    continue

                # 第一个成功的数据源
                if successful_data is None:
                    successful_data = data
                    successful_source = adapter.source_name
                    successful_index = i
                    logger.info(
                        "成功从 %s 获取 %s 条数据",
                        adapter.source_name,
                        len(data),
                    )

                    # 如果不校验一致性，直接返回
                    if not self.validate_consistency:
                        return data

                else:
                    # 校验与主数据源的一致性
                    consistent = self._validate_consistency(successful_data, data)
                    if successful_index is not None and successful_index > 0:
                        fallback_validation_attempted = True
                    if consistent:
                        logger.info(
                            "备用源 %s 数据一致性校验通过",
                            adapter.source_name,
                        )
                    else:
                        logger.warning(
                            "备用源 %s 与已选源 %s 无法通过一致性校验，" "容差为 %.2f%%",
                            adapter.source_name,
                            successful_source,
                            self.tolerance * 100,
                        )
                        if successful_index is not None and successful_index > 0:
                            fallback_validation_failed = True
                            break

            except DataSourceUnavailableError as exc:
                last_error = exc
                logger.warning(
                    "%s 获取数据失败 (error_type=%s)",
                    adapter.source_name,
                    type(exc).__name__,
                )
                continue

            except Exception as exc:
                last_error = exc
                logger.error(
                    "%s 发生异常 (error_type=%s)",
                    adapter.source_name,
                    type(exc).__name__,
                )
                continue

        if fallback_validation_failed:
            raise DataSourceUnavailableError("fallback source failed consistency validation")
        if successful_data is not None:
            if (
                self.validate_consistency
                and successful_index is not None
                and successful_index > 0
                and not fallback_validation_attempted
            ):
                logger.warning(
                    "切换到备用源 %s，但没有其他可用数据源执行交叉校验",
                    successful_source,
                )
            return successful_data

        # 所有适配器都失败
        error_type = type(last_error).__name__ if last_error is not None else "none"
        raise DataSourceUnavailableError(
            f"所有数据源均无法获取 {indicator_code} 数据 (error_type={error_type})"
        )

    def _validate_consistency(
        self, primary_data: list[MacroDataPoint], backup_data: list[MacroDataPoint]
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
            logger.warning("数据一致性校验失败: 主备数据至少一侧为空")
            return False

        primary_by_code: dict[str, dict[date, float]] = {}
        backup_by_code: dict[str, dict[date, float]] = {}
        for point in primary_data:
            if not math.isfinite(float(point.value)):
                return False
            primary_by_code.setdefault(point.code, {})[point.observed_at] = float(point.value)
        for point in backup_data:
            if not math.isfinite(float(point.value)):
                return False
            backup_by_code.setdefault(point.code, {})[point.observed_at] = float(point.value)

        compared = False
        for code in set(primary_by_code) & set(backup_by_code):
            is_consistent, max_diff_ratio = macro_series_are_consistent(
                primary_by_code[code],
                backup_by_code[code],
                tolerance=self.tolerance,
            )
            if max_diff_ratio is None:
                continue
            compared = True
            if not is_consistent:
                logger.warning(
                    "数据一致性校验失败: code=%s 最大差异比例 %.2f%% > 容差 %.2f%%",
                    code,
                    max_diff_ratio * 100,
                    self.tolerance * 100,
                )
                return False

        if not compared:
            logger.warning("数据一致性校验失败: 主备数据没有可比较的同指标同日期点")
            return False
        return True


class MultiSourceAdapter(MacroAdapterProtocol):
    """
    多数据源聚合适配器

    从多个数据源获取数据并合并，去重后返回。
    适用于同一指标可以从多个来源获取的场景。
    """

    source_name = "multi_source"

    def __init__(self, adapters: Sequence[MacroAdapterProtocol]) -> None:
        """
        Args:
            adapters: 数据源适配器列表
        """
        if not adapters:
            raise ValueError("至少需要一个适配器")

        self.adapters = tuple(adapters)

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持指定指标（任一适配器支持即可）"""
        return any(adapter.supports(indicator_code) for adapter in self.adapters)

    def fetch(self, indicator_code: str, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """
        从所有支持的适配器获取数据并合并

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 合并去重后的数据点列表
        """
        all_data: list[MacroDataPoint] = []

        for adapter in self.adapters:
            if not adapter.supports(indicator_code):
                continue

            try:
                data = adapter.fetch(indicator_code, start_date, end_date)
                all_data.extend(data)
                logger.info(f"从 {adapter.source_name} 获取 {len(data)} 条数据")

            except Exception as exc:
                logger.warning(
                    "%s 获取数据失败 (error_type=%s)",
                    adapter.source_name,
                    type(exc).__name__,
                )
                continue

        if not all_data:
            raise DataSourceUnavailableError(f"所有数据源均无法获取 {indicator_code} 数据")

        # 去重（保留最新的）
        seen: dict[tuple[str, date], MacroDataPoint] = {}
        for point in all_data:
            key = (point.code, point.observed_at)
            # 优先保留发布时间较新的
            current = seen.get(key)
            if current is None or (point.published_at or date.min) > (
                current.published_at or date.min
            ):
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
            from apps.data_center.composition import (
                load_data_provider_settings,
            )

            settings_obj = load_data_provider_settings()

            runtime_environment = (
                "production" if not bool(getattr(settings, "DEBUG", True)) else "development"
            )
            default_source = settings_obj.default_source
            enable_failover = _resolve_failover_enabled(
                settings_obj.enable_failover,
                environment=runtime_environment,
            )
            tolerance = _resolve_failover_tolerance(
                settings_obj.failover_tolerance,
                environment=runtime_environment,
            )

            logger.info(
                f"从数据库加载数据源设置: default={default_source}, "
                f"failover={enable_failover}, tolerance={tolerance}"
            )
        else:
            # Django 未配置，使用默认值
            default_source = "akshare"
            enable_failover = True
            tolerance = 0.01
            logger.warning("Django 未配置，使用默认数据源设置")
    except Exception as exc:
        # 数据库未初始化或其他错误，使用默认值
        default_source = "akshare"
        enable_failover = True
        tolerance = 0.01
        logger.warning(
            "无法从数据库读取设置，使用默认值 (error_type=%s)",
            type(exc).__name__,
        )

    # 初始化适配器
    akshare_adapter: MacroAdapterProtocol | None = None
    tushare_adapter: MacroAdapterProtocol | None = None

    try:
        akshare_adapter = AKShareAdapter()
        logger.info("已初始化 AKShare 适配器")
    except Exception as exc:
        logger.warning(
            "AKShare 适配器初始化失败 (error_type=%s)",
            type(exc).__name__,
        )

    try:
        tushare_adapter = TushareAdapter(
            token=tushare_token,
            http_url=tushare_http_url,
        )
        logger.info("已初始化 Tushare 适配器")
    except Exception as exc:
        logger.warning(
            "Tushare 适配器初始化失败 (error_type=%s)",
            type(exc).__name__,
        )

    # 根据设置返回适配器
    if default_source == "akshare":
        primary, backup = akshare_adapter, tushare_adapter
        primary_name = "AKShare"
    elif default_source == "tushare":
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
    adapters: list[MacroAdapterProtocol] = [
        adapter for adapter in (primary, backup) if adapter is not None
    ]
    if not adapters:
        raise DataSourceUnavailableError("无法初始化任何数据源适配器")

    logger.info(f"创建容错适配器: 优先级={' → '.join([a.source_name for a in adapters])}")
    return FailoverAdapter(adapters=adapters, validate_consistency=True, tolerance=tolerance)
