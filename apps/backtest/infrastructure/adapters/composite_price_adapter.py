"""
Composite Asset Price Adapter.

组合多个数据源，支持 failover 和默认价格配置。
"""

import logging
import math
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from .base import (
    AssetPriceAdapterProtocol,
    AssetPricePoint,
    AssetPriceUnavailableError,
    AssetPriceValidationError,
    get_asset_class_tickers,
)

logger = logging.getLogger(__name__)


DEFAULT_PRICES: dict[str, float] = {}


def _normalized_asset_class(value: object) -> str:
    """Return a bounded asset-class key."""

    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise ValueError("asset_class must be a non-empty bounded string")
    normalized = value.strip()
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("asset_class contains control characters")
    return normalized


def _plain_date(value: object, *, field_name: str) -> date:
    """Require a plain date rather than a datetime or dynamic value."""

    if type(value) is not date:
        raise ValueError(f"{field_name} must be a date")
    return value


def _positive_price(value: object) -> float | None:
    """Narrow an external value to a finite positive price."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric > 0 else None


def _adapter_source_name(adapter: object) -> str:
    """Return a log-safe adapter identifier without invoking exception text."""

    try:
        source_name = getattr(adapter, "source_name", "unknown")
    except Exception:
        return type(adapter).__name__
    if not isinstance(source_name, str) or not source_name.strip():
        return type(adapter).__name__
    normalized = "".join(
        character for character in source_name.strip()[:128] if ord(character) >= 32
    )
    return normalized or type(adapter).__name__


def _log_adapter_failure(adapter: object, operation: str, exc: Exception) -> None:
    """Log failover diagnostics without upstream URLs, credentials, or traceback."""

    logger.warning(
        "asset price adapter failed: source=%s operation=%s exception_type=%s",
        _adapter_source_name(adapter),
        operation,
        type(exc).__name__,
    )


class CompositeAssetPriceAdapter:
    """
    组合资产价格适配器

    支持多个数据源的 failover 机制，当主数据源失败时自动切换到备用数据源。
    如果所有数据源都失败，仅在显式注入 default_prices 时才返回默认价格。
    """

    source_name = "composite"

    def __init__(
        self,
        adapters: Sequence[AssetPriceAdapterProtocol],
        use_defaults: bool = False,
        default_prices: dict[str, float] | None = None,
    ) -> None:
        """
        初始化组合适配器

        Args:
            adapters: 数据源适配器列表（按优先级排序）
        use_defaults: 当所有数据源都失败时，是否使用注入的默认价格
            default_prices: 默认价格配置
        """
        if not isinstance(use_defaults, bool):
            raise ValueError("use_defaults must be a boolean")
        self._adapters = tuple(adapters)
        self._use_defaults = use_defaults
        raw_defaults = DEFAULT_PRICES if default_prices is None else default_prices
        normalized_defaults: dict[str, float] = {}
        for raw_asset_class, raw_price in raw_defaults.items():
            asset_class = _normalized_asset_class(raw_asset_class)
            price = _positive_price(raw_price)
            if price is None:
                raise ValueError(f"default price must be finite and positive: {asset_class}")
            normalized_defaults[asset_class] = price
        self._default_prices = normalized_defaults

        # 内部缓存
        self._price_cache: dict[tuple[str, date], float] = {}

    def supports(self, asset_class: str) -> bool:
        """检查是否支持指定资产类别（至少一个适配器支持或存在默认价格）"""
        asset_class = _normalized_asset_class(asset_class)
        if self._use_defaults and asset_class in self._default_prices:
            return True
        for adapter in self._adapters:
            try:
                if adapter.supports(asset_class) is True:
                    return True
            except Exception as exc:
                _log_adapter_failure(adapter, "supports", exc)
        return False

    def get_price(
        self,
        asset_class: str,
        as_of_date: date,
        use_cache: bool = True,
    ) -> float | None:
        """
        获取指定资产在指定日期的价格

        按优先级尝试各个数据源，直到有一个成功返回。

        Args:
            asset_class: 资产类别
            as_of_date: 查询日期
            use_cache: 是否使用缓存

        Returns:
            Optional[float]: 价格，如果不可用则返回默认价格或 None
        """
        asset_class = _normalized_asset_class(asset_class)
        as_of_date = _plain_date(as_of_date, field_name="as_of_date")
        if not isinstance(use_cache, bool):
            raise ValueError("use_cache must be a boolean")

        # 检查缓存
        cache_key = (asset_class, as_of_date)
        if use_cache and cache_key in self._price_cache:
            return self._price_cache[cache_key]

        # 现金固定为 1.0
        if asset_class == "cash":
            return 1.0

        # 尝试各个数据源
        last_error: Exception | None = None
        for adapter in self._adapters:
            try:
                if adapter.supports(asset_class) is not True:
                    continue
                price = adapter.get_price(asset_class, as_of_date)
                normalized_price = _positive_price(price)
                if normalized_price is not None:
                    # 缓存成功结果
                    self._price_cache[cache_key] = normalized_price
                    return normalized_price
            except Exception as exc:
                last_error = exc
                _log_adapter_failure(adapter, "get_price", exc)
                continue

        # 所有数据源都失败，返回默认价格
        if self._use_defaults and asset_class in self._default_prices:
            default_price = self._default_prices[asset_class]
            logger.warning(
                "all asset price sources unavailable; using configured default: asset=%s",
                asset_class,
            )
            self._price_cache[cache_key] = default_price
            return default_price

        # 如果不使用默认价格且没有找到有效价格
        if last_error:
            raise AssetPriceUnavailableError(
                f"asset_price_unavailable:{asset_class}:{as_of_date.isoformat()}"
            ) from last_error

        return None

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date,
    ) -> list[AssetPricePoint]:
        """
        获取指定资产在日期范围内的价格序列

        Args:
            asset_class: 资产类别
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[AssetPricePoint]: 价格数据点列表
        """
        asset_class = _normalized_asset_class(asset_class)
        start_date = _plain_date(start_date, field_name="start_date")
        end_date = _plain_date(end_date, field_name="end_date")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")

        # 尝试各个数据源
        for adapter in self._adapters:
            try:
                if adapter.supports(asset_class) is not True:
                    continue
                raw_points = adapter.get_prices(asset_class, start_date, end_date)
                normalized_points = self._normalize_points(
                    raw_points,
                    asset_class=asset_class,
                    start_date=start_date,
                    end_date=end_date,
                )
                if normalized_points:
                    return normalized_points
            except Exception as exc:
                _log_adapter_failure(adapter, "get_prices", exc)
                continue

        # 所有数据源都失败，使用默认价格生成每日序列
        if self._use_defaults and asset_class in self._default_prices:
            default_price = self._default_prices[asset_class]
            logger.warning(
                "all asset price series unavailable; using configured default: asset=%s",
                asset_class,
            )
            default_points: list[AssetPricePoint] = []
            current = start_date
            while current <= end_date:
                default_points.append(
                    AssetPricePoint(
                        asset_class=asset_class,
                        price=default_price,
                        as_of_date=current,
                        source="default",
                    )
                )
                current += timedelta(days=1)
            return default_points

        return []

    def clear_cache(self) -> None:
        """清空价格缓存"""
        self._price_cache.clear()

    def get_supported_assets(self) -> list[str]:
        """获取支持的资产类别列表"""
        candidates = set(get_asset_class_tickers())
        if self._use_defaults:
            candidates.update(self._default_prices)
        return sorted(asset_class for asset_class in candidates if self.supports(asset_class))

    @staticmethod
    def _normalize_points(
        points: object,
        *,
        asset_class: str,
        start_date: date,
        end_date: date,
    ) -> list[AssetPricePoint]:
        """Filter, deduplicate, and order one untrusted adapter series."""

        if not isinstance(points, list):
            return []
        by_date: dict[date, AssetPricePoint] = {}
        for point in points:
            if (
                not isinstance(point, AssetPricePoint)
                or point.asset_class != asset_class
                or point.as_of_date < start_date
                or point.as_of_date > end_date
                or _positive_price(point.price) is None
            ):
                continue
            by_date[point.as_of_date] = point
        return [by_date[point_date] for point_date in sorted(by_date)]


class DataCenterAssetPriceAdapter:
    """Asset-class price adapter backed by data_center facts."""

    source_name = "data_center"

    def __init__(self) -> None:
        from apps.data_center.application.price_service import UnifiedPriceService
        from apps.data_center.infrastructure.repositories import PriceBarRepository

        self._bars = PriceBarRepository()
        self._price_service = UnifiedPriceService()

    def supports(self, asset_class: str) -> bool:
        asset_class = _normalized_asset_class(asset_class)
        return asset_class == "cash" or asset_class in get_asset_class_tickers()

    def get_price(
        self,
        asset_class: str,
        as_of_date: date,
    ) -> float | None:
        asset_class = _normalized_asset_class(asset_class)
        as_of_date = _plain_date(as_of_date, field_name="as_of_date")
        if asset_class == "cash":
            return 1.0

        ticker = get_asset_class_tickers().get(asset_class)
        if not ticker:
            return None
        return _positive_price(self._price_service.get_price(ticker, trade_date=as_of_date))

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date,
    ) -> list[AssetPricePoint]:
        asset_class = _normalized_asset_class(asset_class)
        start_date = _plain_date(start_date, field_name="start_date")
        end_date = _plain_date(end_date, field_name="end_date")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if asset_class == "cash":
            points: list[AssetPricePoint] = []
            current = start_date
            while current <= end_date:
                points.append(
                    AssetPricePoint(
                        asset_class=asset_class,
                        price=1.0,
                        as_of_date=current,
                        source=self.source_name,
                    )
                )
                current += timedelta(days=1)
            return points

        ticker = get_asset_class_tickers().get(asset_class)
        if not ticker:
            return []

        try:
            bars = self._bars.get_bars(ticker, start=start_date, end=end_date, limit=5000)
        except Exception as exc:
            logger.warning(
                "data_center price series read failed: asset=%s exception_type=%s",
                asset_class,
                type(exc).__name__,
            )
            return []

        points = []
        for bar in reversed(bars):
            price = _positive_price(bar.close)
            if price is None or type(bar.bar_date) is not date:
                continue
            try:
                points.append(
                    AssetPricePoint(
                        asset_class=asset_class,
                        price=price,
                        as_of_date=bar.bar_date,
                        source=str(bar.source or self.source_name),
                    )
                )
            except AssetPriceValidationError:
                continue
        return points


def create_default_price_adapter(
    tushare_token: str | None = None,
    tushare_http_url: str | None = None,
) -> CompositeAssetPriceAdapter:
    """
    创建默认的资产价格适配器

    Args:
        tushare_token: Tushare API token（可选）
        tushare_http_url: Tushare 自定义 HTTP URL（可选）

    Returns:
        CompositeAssetPriceAdapter: 组合适配器
    """
    from .tushare_price_adapter import TushareAssetPriceAdapter

    adapters: list[AssetPriceAdapterProtocol] = []

    try:
        adapters.append(DataCenterAssetPriceAdapter())
    except Exception as exc:
        logger.warning(
            "failed to initialize Data Center price adapter: exception_type=%s",
            type(exc).__name__,
        )

    # 添加 Tushare 适配器（如果提供了 token）
    if tushare_token:
        try:
            adapters.append(
                TushareAssetPriceAdapter(
                    token=tushare_token,
                    http_url=tushare_http_url,
                )
            )
        except Exception as exc:
            logger.warning(
                "failed to initialize Tushare price adapter: exception_type=%s",
                type(exc).__name__,
            )

    return CompositeAssetPriceAdapter(
        adapters=adapters,
        use_defaults=False,
        default_prices=DEFAULT_PRICES.copy(),
    )
