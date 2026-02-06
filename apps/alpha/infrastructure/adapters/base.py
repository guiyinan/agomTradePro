"""
Base Alpha Provider Adapter

Alpha 提供者的基类实现，包含通用功能和装饰器。
"""

import logging
import time
import traceback
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from datetime import date

from ...domain.entities import AlphaResult, StockScore
from ...domain.interfaces import AlphaProvider, AlphaProviderStatus


logger = logging.getLogger(__name__)


def qlib_safe(default_return: Any = None):
    """
    Qlib 安全装饰器

    捕获 Qlib 相关的所有异常，防止 Qlib 故障影响主系统。
    支持 ImportError（未安装）和运行时异常。

    Args:
        default_return: 异常时的默认返回值

    Example:
        >>> @qlib_safe(default_return=AlphaResult.success([]))
        ... def load_model(self):
        ...     import qlib
        ...     return qlib.load_model(...)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ImportError as e:
                logger.error(f"Qlib 未安装或导入失败: {e}")
                return default_return
            except Exception as e:
                logger.error(
                    f"Qlib 调用失败: {e}\n{traceback.format_exc()}",
                    exc_info=True
                )
                return default_return
        return wrapper
    return decorator


def provider_safe(default_success: bool = False):
    """
    Provider 安全装饰器

    捕获 Provider 执行过程中的所有异常，返回默认结果。

    Args:
        default_success: 默认的 success 值

    Example:
        >>> @provider_safe()
        ... def get_stock_scores(self, universe, date, top_n):
        ...     # Provider 实现
        ...     pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> AlphaResult:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Provider 调用失败: {e}\n{traceback.format_exc()}",
                    exc_info=True
                )
                # 获取 self 作为第一个参数（实例方法）
                if args:
                    provider = args[0]
                    source = getattr(provider, "name", "unknown")
                else:
                    source = "unknown"

                return AlphaResult(
                    success=default_success,
                    scores=[],
                    source=source,
                    timestamp=date.today().isoformat(),
                    status="unavailable",
                    error_message=str(e),
                )
        return wrapper
    return decorator


class BaseAlphaProvider(AlphaProvider):
    """
    Alpha 提供者基类

    实现 AlphaProvider 接口的通用功能，子类只需实现核心逻辑。

    Attributes:
        _initialized: 是否已初始化
        _config: Provider 配置

    Example:
        >>> class MyProvider(BaseAlphaProvider):
        ...     @property
        ...     def name(self) -> str:
        ...         return "my_provider"
        ...
        ...     @property
        ...     def priority(self) -> int:
        ...         return 100
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化 Provider

        Args:
            config: Provider 配置字典
        """
        self._initialized = False
        self._config = config or {}

    def initialize(self) -> None:
        """
        初始化 Provider

        子类可覆盖此方法进行自定义初始化。
        """
        self._initialized = True

    def supports(self, universe_id: str) -> bool:
        """
        检查是否支持指定的股票池

        默认实现支持所有股票池。子类可覆盖以限制支持范围。

        Args:
            universe_id: 股票池标识

        Returns:
            是否支持
        """
        return True

    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: date
    ) -> Dict[str, float]:
        """
        获取因子暴露（默认实现）

        默认返回空字典，子类可覆盖以提供实际因子暴露。

        Args:
            stock_code: 股票代码
            trade_date: 交易日期

        Returns:
            因子暴露字典
        """
        return {}

    def _create_success_result(
        self,
        scores: List[StockScore],
        latency_ms: Optional[int] = None,
        staleness_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AlphaResult:
        """
        创建成功结果

        Args:
            scores: 股票评分列表
            latency_ms: 延迟
            staleness_days: 数据陈旧天数
            metadata: 额外元数据

        Returns:
            AlphaResult
        """
        return AlphaResult(
            success=True,
            scores=scores,
            source=self.name,
            timestamp=date.today().isoformat(),
            status="available",
            latency_ms=latency_ms,
            staleness_days=staleness_days,
            metadata=metadata or {},
        )

    def _create_error_result(
        self,
        error_message: str,
        status: str = "unavailable"
    ) -> AlphaResult:
        """
        创建错误结果

        Args:
            error_message: 错误信息
            status: 状态

        Returns:
            AlphaResult
        """
        return AlphaResult(
            success=False,
            scores=[],
            source=self.name,
            timestamp=date.today().isoformat(),
            status=status,
            error_message=error_message,
        )

    def _create_degraded_result(
        self,
        scores: List[StockScore],
        staleness_days: int,
        reason: str = ""
    ) -> AlphaResult:
        """
        创建降级结果

        Args:
            scores: 股票评分列表
            staleness_days: 数据陈旧天数
            reason: 降级原因

        Returns:
            AlphaResult
        """
        return AlphaResult(
            success=True,
            scores=scores,
            source=self.name,
            timestamp=date.today().isoformat(),
            status="degraded",
            staleness_days=staleness_days,
            metadata={"reason": reason},
        )

    @staticmethod
    def measure_latency(func: Callable) -> Callable:
        """
        延迟测量装饰器

        自动测量函数执行时间并添加到结果中。

        Args:
            func: 要测量的函数

        Returns:
            包装后的函数

        Example:
            >>> @BaseAlphaProvider.measure_latency
            ... def get_stock_scores(self, ...):
            ...     result = self._compute_scores(...)
            ...     result.latency_ms = self._last_latency
            ...     return result
        """
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start_time = time.time()
            try:
                result = func(self, *args, **kwargs)
                if isinstance(result, AlphaResult):
                    result.latency_ms = int((time.time() - start_time) * 1000)
                return result
            except Exception as e:
                logger.error(f"Function {func.__name__} failed: {e}")
                raise
        return wrapper


def create_stock_score(
    code: str,
    score: float,
    rank: int,
    source: str,
    factors: Optional[Dict[str, float]] = None,
    confidence: float = 0.5,
    **kwargs
) -> StockScore:
    """
    创建 StockScore 的便捷函数

    Args:
        code: 股票代码
        score: 评分
        rank: 排名
        source: 来源
        factors: 因子暴露
        confidence: 置信度
        **kwargs: 其他字段

    Returns:
        StockScore 实例
    """
    return StockScore(
        code=code,
        score=score,
        rank=rank,
        factors=factors or {},
        source=source,
        confidence=confidence,
        **kwargs
    )
