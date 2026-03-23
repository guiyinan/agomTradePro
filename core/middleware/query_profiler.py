"""
Query Profiler Middleware for Slow SQL Detection

检测和记录慢 SQL 查询的中间件，提供：
- 每个请求的 SQL 查询统计（数量、总时间）
- 慢查询记录（超过阈值的单个查询）
- 结构化日志输出
- Prometheus 指标集成

使用示例:
    # 在 settings.py 中配置
    QUERY_PROFILER_ENABLED = True
    SLOW_QUERY_THRESHOLD_MS = 100

    # 日志输出格式
    {
        "event": "slow_query",
        "sql": "SELECT * FROM ...",
        "duration_ms": 150.5,
        "threshold_ms": 100,
        "trace_id": "abc123",
        "request_path": "/api/regime/"
    }
"""

import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_SLOW_QUERY_THRESHOLD_MS = 100
DEFAULT_QUERY_PROFILER_ENABLED = False


def get_profiler_config() -> tuple[bool, int]:
    """
    获取查询分析器配置

    Returns:
        (enabled, threshold_ms): 是否启用和阈值（毫秒）
    """
    enabled = getattr(settings, 'QUERY_PROFILER_ENABLED', DEFAULT_QUERY_PROFILER_ENABLED)
    threshold = getattr(settings, 'SLOW_QUERY_THRESHOLD_MS', DEFAULT_SLOW_QUERY_THRESHOLD_MS)
    return enabled, threshold


def normalize_sql(sql: str, max_length: int = 200) -> str:
    """
    规范化 SQL 语句，提取查询模式

    将参数值替换为占位符，以便相同模式的查询可以聚合分析。

    Args:
        sql: 原始 SQL 语句
        max_length: 最大返回长度

    Returns:
        规范化后的 SQL 语句

    Examples:
        >>> normalize_sql("SELECT * FROM table WHERE id = 123")
        "SELECT * FROM table WHERE id = ?"
    """
    if not sql:
        return ""

    # 移除多余的空白
    sql = re.sub(r'\s+', ' ', sql.strip())

    # 替换字符串字面量
    sql = re.sub(r"'[^']*'", "?", sql)
    sql = re.sub(r'"[^"]*"', "?", sql)

    # 替换数字字面值
    sql = re.sub(r'\b\d+\b', "?", sql)

    # 替换 UUID
    sql = re.sub(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        "?",
        sql,
        flags=re.IGNORECASE
    )

    # 截断过长的 SQL
    if len(sql) > max_length:
        sql = sql[:max_length] + "..."

    return sql


def extract_operation_type(sql: str) -> str:
    """
    从 SQL 语句中提取操作类型

    Args:
        sql: SQL 语句

    Returns:
        操作类型（SELECT/INSERT/UPDATE/DELETE/OTHER）
    """
    sql_upper = sql.strip().upper()

    for op in ['SELECT', 'INSERT', 'UPDATE', 'DELETE']:
        if sql_upper.startswith(op):
            return op

    return 'OTHER'


class QueryProfilerMiddleware:
    """
    查询性能分析中间件

    功能：
    1. 记录每个请求的 SQL 查询数量和总时间
    2. 记录超过阈值的慢查询
    3. 将慢查询信息写入结构化日志
    4. 记录 Prometheus 指标

    注意：
    - 需要 DEBUG=True 或 django.db.connection.queries 启用
    - 可通过配置 QUERY_PROFILER_ENABLED 关闭
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.enabled, self.threshold_ms = get_profiler_config()

        if self.enabled:
            logger.info(
                f"QueryProfiler enabled with threshold {self.threshold_ms}ms",
                extra={'threshold_ms': self.threshold_ms}
            )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """处理请求并分析查询"""
        if not self.enabled:
            return self.get_response(request)

        # 记录请求开始时间
        start_time = time.time()

        # 确保查询记录已启用
        force_debug_cursor = connection.force_debug_cursor
        connection.force_debug_cursor = True

        try:
            # 执行请求
            response = self.get_response(request)

            # 分析查询
            duration = time.time() - start_time
            self._analyze_queries(request, duration)

            return response

        finally:
            # 恢复原始设置
            connection.force_debug_cursor = force_debug_cursor

    def _analyze_queries(self, request: HttpRequest, request_duration: float) -> None:
        """分析本次请求的查询情况"""
        try:
            queries = connection.queries
            query_count = len(queries)

            if query_count == 0:
                return

            # 计算总查询时间
            total_query_time = sum(float(q['time']) for q in queries)

            # 获取 trace_id
            trace_id = getattr(request, 'trace_id', '-')

            # 记录查询统计
            logger.info(
                f"Request queries: {query_count} queries, "
                f"{total_query_time * 1000:.1f}ms total, "
                f"{request_duration * 1000:.1f}ms request",
                extra={
                    'event': 'query_summary',
                    'query_count': query_count,
                    'total_query_time_ms': round(total_query_time * 1000, 2),
                    'request_duration_ms': round(request_duration * 1000, 2),
                    'trace_id': trace_id,
                    'request_path': request.path,
                    'request_method': request.method,
                }
            )

            # 检测慢查询
            slow_queries = []
            query_patterns = defaultdict(list)

            for query in queries:
                sql = query['sql']
                duration_ms = float(query['time']) * 1000
                operation = extract_operation_type(sql)

                # 记录 Prometheus 指标
                self._record_query_metrics(operation, duration_ms)

                # 检测慢查询
                if duration_ms >= self.threshold_ms:
                    slow_queries.append({
                        'sql': sql,
                        'duration_ms': duration_ms,
                        'operation': operation,
                    })

                # 按模式聚合
                pattern = normalize_sql(sql)
                query_patterns[pattern].append(duration_ms)

            # 记录慢查询详情
            if slow_queries:
                self._log_slow_queries(request, slow_queries, trace_id)

            # 记录查询模式统计
            if query_patterns:
                self._log_query_patterns(request, query_patterns, trace_id)

            # 记录重复查询（N+1 问题检测）
            self._detect_n_plus_one(request, query_patterns, trace_id)

        except Exception as e:
            logger.warning(f"Query analysis failed: {e}", exc_info=True)

    def _log_slow_queries(
        self,
        request: HttpRequest,
        slow_queries: list[dict],
        trace_id: str,
    ) -> None:
        """记录慢查询详情"""
        for i, query in enumerate(slow_queries, 1):
            sql = query['sql']
            duration_ms = query['duration_ms']
            operation = query['operation']

            logger.warning(
                f"Slow query #{i}/{len(slow_queries)}: {operation} "
                f"took {duration_ms:.1f}ms (threshold: {self.threshold_ms}ms)",
                extra={
                    'event': 'slow_query',
                    'sql': sql[:500],  # 限制长度
                    'sql_hash': hash(normalize_sql(sql)),
                    'duration_ms': round(duration_ms, 2),
                    'threshold_ms': self.threshold_ms,
                    'operation': operation,
                    'trace_id': trace_id,
                    'request_path': request.path,
                    'request_method': request.method,
                }
            )

    def _log_query_patterns(
        self,
        request: HttpRequest,
        query_patterns: dict[str, list[float]],
        trace_id: str,
    ) -> None:
        """记录查询模式统计"""
        # 按总耗时排序
        sorted_patterns = sorted(
            query_patterns.items(),
            key=lambda x: sum(x[1]),
            reverse=True
        )

        # 只记录最慢的 5 个模式
        top_patterns = sorted_patterns[:5]

        for pattern, durations in top_patterns:
            total_time = sum(durations)
            count = len(durations)
            avg_time = total_time / count

            logger.debug(
                f"Query pattern: {count}x, "
                f"{total_time:.1f}ms total, {avg_time:.1f}ms avg",
                extra={
                    'event': 'query_pattern',
                    'pattern': pattern[:200],
                    'count': count,
                    'total_time_ms': round(total_time, 2),
                    'avg_time_ms': round(avg_time, 2),
                    'trace_id': trace_id,
                    'request_path': request.path,
                }
            )

    def _detect_n_plus_one(
        self,
        request: HttpRequest,
        query_patterns: dict[str, list[float]],
        trace_id: str,
    ) -> None:
        """检测 N+1 查询问题"""
        for pattern, durations in query_patterns.items():
            # 如果相同模式查询超过 5 次，可能是 N+1 问题
            if len(durations) > 5 and 'SELECT' in pattern.upper():
                total_time = sum(durations)

                logger.warning(
                    f"Potential N+1 query detected: "
                    f"{len(durations)} similar SELECT queries, "
                    f"{total_time:.1f}ms total",
                    extra={
                        'event': 'n_plus_one_warning',
                        'pattern': pattern[:200],
                        'count': len(durations),
                        'total_time_ms': round(total_time, 2),
                        'trace_id': trace_id,
                        'request_path': request.path,
                    }
                )

    def _record_query_metrics(self, operation: str, duration_ms: float) -> None:
        """记录 Prometheus 指标"""
        try:
            from core.metrics import db_query_latency_seconds

            db_query_latency_seconds.labels(
                database='default',
                operation=operation.lower()
            ).observe(duration_ms / 1000)  # 转换为秒

        except Exception as e:
            logger.warning(f"Failed to record query metrics: {e}")


class QuerySummary:
    """
    查询摘要数据类

    用于聚合和统计查询性能数据。
    """

    def __init__(self):
        self.total_queries: int = 0
        self.total_time_ms: float = 0
        self.slow_queries: int = 0
        self.operation_counts: dict[str, int] = defaultdict(int)
        self.slow_query_patterns: dict[str, list[float]] = defaultdict(list)

    def add_query(self, sql: str, duration_ms: float, threshold_ms: float = 100) -> None:
        """
        添加一条查询记录

        Args:
            sql: SQL 语句
            duration_ms: 查询耗时（毫秒）
            threshold_ms: 慢查询阈值（毫秒）
        """
        self.total_queries += 1
        self.total_time_ms += duration_ms

        operation = extract_operation_type(sql)
        self.operation_counts[operation] += 1

        if duration_ms >= threshold_ms:
            self.slow_queries += 1
            pattern = normalize_sql(sql)
            self.slow_query_patterns[pattern].append(duration_ms)

    def get_summary(self) -> dict:
        """
        获取统计摘要

        Returns:
            统计摘要字典
        """
        return {
            'total_queries': self.total_queries,
            'total_time_ms': round(self.total_time_ms, 2),
            'slow_queries': self.slow_queries,
            'avg_time_ms': round(self.total_time_ms / self.total_queries, 2) if self.total_queries > 0 else 0,
            'operation_counts': dict(self.operation_counts),
            'slow_query_patterns': {
                pattern: {
                    'count': len(durations),
                    'total_ms': round(sum(durations), 2),
                    'avg_ms': round(sum(durations) / len(durations), 2),
                    'max_ms': round(max(durations), 2),
                }
                for pattern, durations in self.slow_query_patterns.items()
            },
        }
