"""
网络弹性工具模块

提供处理不稳定网络连接的工具：
1. 重试机制
2. 超时控制
3. 降级策略
4. 缓存装饰器
"""

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


class NetworkError(Exception):
    """网络错误"""
    pass


class DataSourceUnavailable(Exception):
    """数据源不可用"""
    pass


class MaxRetriesExceeded(Exception):
    """超过最大重试次数"""
    pass


def retry_on_error(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable | None = None
):
    """
    重试装饰器 - 指数退避重试

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）
        backoff_factor: 退避因子（每次重试延迟倍增）
        max_delay: 最大延迟（秒）
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调函数

    Example:
        @retry_on_error(max_retries=3, exceptions=(ConnectionError,))
        def fetch_data():
            return api_call()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} retries: {e}"
                        )
                        raise MaxRetriesExceeded(
                            f"{func.__name__} 超过最大重试次数 {max_retries}"
                        ) from e

                    # 计算下次重试延迟
                    current_delay = min(delay, max_delay)
                    logger.warning(
                        f"{func.__name__} 第 {attempt + 1} 次尝试失败: {e}, "
                        f"{current_delay:.1f}秒后重试..."
                    )

                    # 调用重试回调
                    if on_retry:
                        on_retry(attempt + 1, e)

                    time.sleep(current_delay)

                    # 指数退避
                    delay *= backoff_factor

            raise last_exception  # type: ignore

        return wrapper
    return decorator


def timeout(seconds: float = 30.0):
    """
    超时装饰器 - 限制函数执行时间

    Args:
        seconds: 超时时间（秒）

    Example:
        @timeout(seconds=10)
        def fetch_data():
            return slow_api_call()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError(f"{func.__name__} 执行超时 ({seconds}秒)")

            # 设置超时信号
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(seconds))

            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            return result

        return wrapper
    return decorator


def circuit_breaker(
    failure_threshold: int = 5,
    reset_timeout: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,)
):
    """
    熔断器装饰器 - 连续失败时快速失败

    Args:
        failure_threshold: 失败阈值，超过后打开断路器
        reset_timeout: 重置超时（秒）
        exceptions: 计入失败的异常类型

    Example:
        @circuit_breaker(failure_threshold=3, reset_timeout=30)
        def fetch_data():
            return api_call()
    """
    class CircuitBreakerState:
        def __init__(self):
            self.failure_count = 0
            self.last_failure_time = None
            self.state = 'closed'  # closed, open, half-open

    state = CircuitBreakerState()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()

            # 检查是否需要重置
            if state.state == 'open':
                if now - state.last_failure_time >= reset_timeout:
                    logger.info(f"{func.__name__} 断路器进入半开状态")
                    state.state = 'half-open'
                else:
                    raise DataSourceUnavailable(
                        f"{func.__name__} 断路器打开，服务暂时不可用"
                    )

            try:
                result = func(*args, **kwargs)

                # 成功，重置失败计数
                if state.state == 'half-open':
                    logger.info(f"{func.__name__} 断路器恢复正常")
                    state.state = 'closed'

                state.failure_count = 0
                return result

            except exceptions as e:
                state.failure_count += 1
                state.last_failure_time = now

                if state.failure_count >= failure_threshold:
                    state.state = 'open'
                    logger.error(
                        f"{func.__name__} 失败次数达到阈值 {failure_threshold}，"
                        f"断路器打开 {reset_timeout} 秒"
                    )

                raise e

        return wrapper
    return decorator


def fallback_to(
    fallback_func: Callable,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    log_fallback: bool = True
):
    """
    降级装饰器 - 失败时使用备用函数

    Args:
        fallback_func: 备用函数
        exceptions: 触发降级的异常类型
        log_fallback: 是否记录降级日志

    Example:
        def fetch_from_cache():
            return get_cached_data()

        @fallback_to(fetch_from_cache)
        def fetch_data():
            return api_call()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)

            except exceptions as e:
                if log_fallback:
                    logger.warning(
                        f"{func.__name__} 失败: {e}, 降级到 {fallback_func.__name__}"
                    )

                return fallback_func(*args, **kwargs)

        return wrapper
    return decorator


class CacheManager:
    """缓存管理器 - 简单的内存缓存实现"""

    def __init__(self):
        self._cache = {}
        self._timestamps = {}

    def get(self, key: str, max_age: float | None = None) -> Any | None:
        """获取缓存

        Args:
            key: 缓存键
            max_age: 最大有效时间（秒），None 表示不过期

        Returns:
            缓存值，如果不存在或已过期则返回 None
        """
        if key not in self._cache:
            return None

        # 检查过期
        if max_age is not None:
            timestamp = self._timestamps.get(key, 0)
            if time.time() - timestamp > max_age:
                del self._cache[key]
                del self._timestamps[key]
                return None

        return self._cache[key]

    def set(self, key: str, value: Any, ttl: float | None = None):
        """设置缓存

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 有效时间（秒），None 表示永久
        """
        self._cache[key] = value
        self._timestamps[key] = time.time()

        # 如果设置了 TTL，使用 Django 的缓存
        if ttl is not None:
            try:
                from django.core.cache import cache
                cache.set(key, value, ttl)
            except ImportError:
                pass

    def delete(self, key: str):
        """删除缓存"""
        if key in self._cache:
            del self._cache[key]
        if key in self._timestamps:
            del self._timestamps[key]

        try:
            from django.core.cache import cache
            cache.delete(key)
        except ImportError:
            pass

    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._timestamps.clear()

        try:
            from django.core.cache import cache
            cache.clear()
        except ImportError:
            pass


# 全局缓存管理器
_cache_manager = CacheManager()


def cached(
    ttl: float = 3600,
    key_func: Callable | None = None,
    cache_null: bool = False
):
    """
    缓存装饰器

    Args:
        ttl: 缓存时间（秒）
        key_func: 自定义缓存键生成函数
        cache_null: 是否缓存 None 值

    Example:
        @cached(ttl=3600)
        def fetch_stock_list():
            return api_call()

        @cached(ttl=600, key_func=lambda code: f'stock_{code}')
        def fetch_stock_info(code):
            return api_call(code)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # 使用函数名和参数生成键
                args_str = '_'.join(str(a) for a in args)
                kwargs_str = '_'.join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = f"{func.__name__}_{args_str}_{kwargs_str}"

            # 尝试从缓存获取
            cached_value = _cache_manager.get(cache_key, max_age=ttl)
            if cached_value is not None:
                logger.debug(f"{func.__name__} 缓存命中: {cache_key}")
                return cached_value

            # 缓存未命中，调用原函数
            result = func(*args, **kwargs)

            # 不缓存 None 值（除非指定）
            if result is not None or cache_null:
                _cache_manager.set(cache_key, result, ttl=ttl)

            return result

        # 添加清除缓存方法
        def invalidate(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                args_str = '_'.join(str(a) for a in args)
                kwargs_str = '_'.join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = f"{func.__name__}_{args_str}_{kwargs_str}"

            _cache_manager.delete(cache_key)

        wrapper.invalidate = invalidate

        return wrapper
    return decorator


def with_cache_stats(func: Callable) -> Callable:
    """缓存统计装饰器 - 记录缓存命中率"""
    stats = {'hits': 0, 'misses': 0}

    @wraps(func)
    def wrapper(*args, **kwargs):
        stats['misses'] += 1
        return func(*args, **kwargs)

    wrapper.get_cache_stats = lambda: stats.copy()
    return wrapper


class DataSourceHealth:
    """数据源健康状态管理"""

    def __init__(self):
        self._health = {}  # {source_name: {last_check, last_success, last_error, failure_count}}
        self._threshold = 3  # 连续失败次数阈值

    def record_success(self, source: str):
        """记录成功"""
        if source not in self._health:
            self._health[source] = {}

        self._health[source].update({
            'last_check': time.time(),
            'last_success': time.time(),
            'failure_count': 0
        })

        logger.debug(f"{source} 健康状态: 正常")

    def record_failure(self, source: str, error: str):
        """记录失败"""
        if source not in self._health:
            self._health[source] = {
                'failure_count': 0
            }

        self._health[source].update({
            'last_check': time.time(),
            'last_error': error,
            'failure_count': self._health[source].get('failure_count', 0) + 1
        })

        logger.warning(
            f"{source} 健康状态: 异常 "
            f"(失败次数: {self._health[source]['failure_count']})"
        )

    def is_healthy(self, source: str) -> bool:
        """检查数据源是否健康"""
        if source not in self._health:
            return True  # 未知状态，认为健康

        return self._health[source]['failure_count'] < self._threshold

    def get_health_status(self, source: str) -> dict:
        """获取健康状态详情"""
        return self._health.get(source, {
            'failure_count': 0,
            'last_check': None,
            'last_success': None
        })


# 全局健康状态管理器
_health_manager = DataSourceHealth()
