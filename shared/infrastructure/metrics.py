"""
Monitoring Metrics Infrastructure

Alpha 模块监控指标定义和导出。
支持 Prometheus 格式和日志格式。

仅使用 Python 标准库。
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """指标类型"""
    COUNTER = "counter"      # 单调递增计数器
    GAUGE = "gauge"          # 可增减的仪表盘
    HISTOGRAM = "histogram"  # 分布直方图
    SUMMARY = "summary"      # 摘要统计


@dataclass
class MetricValue:
    """单个指标值"""
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime | None = None
    metric_type: MetricType = MetricType.GAUGE

    def to_prometheus(self) -> str:
        """转换为 Prometheus 格式"""
        if self.timestamp is None:
            self.timestamp = datetime.now(UTC)

        # 格式: metric_name{label1="value1",label2="value2"} value timestamp
        label_str = ""
        if self.labels:
            label_pairs = [f'{k}="{v}"' for k, v in self.labels.items()]
            label_str = "{" + ",".join(label_pairs) + "}"

        timestamp_ms = int(self.timestamp.timestamp() * 1000)

        return f"{self.name}{label_str} {self.value} {timestamp_ms}\n"

    def to_json(self) -> str:
        """转换为 JSON 格式"""
        return json.dumps({
            "name": self.name,
            "value": self.value,
            "labels": self.labels,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "type": self.metric_type.value
        })


@dataclass
class HistogramBucket:
    """直方图桶"""
    upper_bound: float
    count: int


@dataclass
class HistogramValue:
    """直方图指标值"""
    name: str
    buckets: list[HistogramBucket] = field(default_factory=list)
    sum: float = 0.0
    count: int = 0
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime | None = None

    def observe(self, value: float):
        """观测一个值"""
        self.count += 1
        self.sum += value

        # 更新桶计数
        for bucket in self.buckets:
            if value <= bucket.upper_bound:
                bucket.count += 1

    def to_prometheus(self) -> str:
        """转换为 Prometheus 格式"""
        if self.timestamp is None:
            self.timestamp = datetime.now(UTC)

        lines = []
        timestamp_ms = int(self.timestamp.timestamp() * 1000)

        # 格式化标签
        label_str = ""
        if self.labels:
            label_pairs = [f'{k}="{v}"' for k, v in self.labels.items()]
            label_str = "{" + ",".join(label_pairs) + "}"

        # 输出桶
        for bucket in self.buckets:
            le_label = label_str.replace("}", ',le="') if label_str else "{le="
            bucket_label = f'{self.name}_bucket{le_label}{bucket.upper_bound}'
            lines.append(f"{bucket_label} {bucket.count} {timestamp_ms}")

        # 输出 +Inf 桶
        le_label = label_str.replace("}", ',le="') if label_str else "{le="
        inf_label = f'{self.name}_bucket{le_label}+Inf"'
        lines.append(f"{inf_label} {self.count} {timestamp_ms}")

        # 输出 sum 和 count
        lines.append(f"{self.name}_sum{label_str} {self.sum} {timestamp_ms}")
        lines.append(f"{self.name}_count{label_str} {self.count} {timestamp_ms}")

        return "\n".join(lines) + "\n"


class MetricsRegistry:
    """
    指标注册表

    单例模式，管理所有监控指标。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        current_test = os.getenv("PYTEST_CURRENT_TEST")
        if self._initialized:
            # Keep singleton semantics, but isolate metrics across pytest test cases.
            if current_test and getattr(self, "_last_pytest_test", None) != current_test:
                self.reset_metrics()
                self._last_pytest_test = current_test
            return

        # 存储: {metric_name: {label_tuple: MetricValue}}
        self._counters: dict[str, dict[tuple, MetricValue]] = defaultdict(dict)
        self._gauges: dict[str, dict[tuple, MetricValue]] = defaultdict(dict)
        self._histograms: dict[str, dict[tuple, HistogramValue]] = defaultdict(dict)

        # 指标元数据
        self._metric_help: dict[str, str] = {}

        self._last_pytest_test = current_test

        self._initialized = True

    def _make_label_key(self, labels: dict[str, str]) -> tuple:
        """将标签字典转换为不可变的键"""
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def define_metric(self, name: str, metric_type: MetricType, help_text: str = ""):
        """定义指标元数据"""
        self._metric_help[name] = help_text
        logger.debug(f"定义指标: {name} ({metric_type.value})")

    def inc_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None
    ):
        """增加计数器"""
        label_key = self._make_label_key(labels or {})

        if label_key not in self._counters[name]:
            self._counters[name][label_key] = MetricValue(
                name=name,
                value=0.0,
                labels=labels or {},
                metric_type=MetricType.COUNTER
            )

        self._counters[name][label_key].value += value

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None
    ):
        """设置仪表盘值"""
        label_key = self._make_label_key(labels or {})

        if label_key not in self._gauges[name]:
            self._gauges[name][label_key] = MetricValue(
                name=name,
                value=value,
                labels=labels or {},
                metric_type=MetricType.GAUGE
            )
        else:
            self._gauges[name][label_key].value = value

    def observe_histogram(
        self,
        name: str,
        value: float,
        buckets: list[float] | None = None,
        labels: dict[str, str] | None = None
    ):
        """观测直方图值"""
        if buckets is None:
            buckets = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

        label_key = self._make_label_key(labels or {})

        if label_key not in self._histograms[name]:
            self._histograms[name][label_key] = HistogramValue(
                name=name,
                buckets=[HistogramBucket(b, 0) for b in buckets],
                labels=labels or {}
            )

        self._histograms[name][label_key].observe(value)

    def get_metric(self, name: str, labels: dict[str, str] | None = None) -> MetricValue | None:
        """获取指标值"""
        label_key = self._make_label_key(labels or {})

        # 先查 gauge
        if label_key in self._gauges[name]:
            return self._gauges[name][label_key]

        # 再查 counter
        if label_key in self._counters[name]:
            return self._counters[name][label_key]

        # 未指定 labels 时，兼容返回同名指标的聚合值
        if labels is None:
            if self._gauges[name]:
                total = sum(metric.value for metric in self._gauges[name].values())
                return MetricValue(name=name, value=total, metric_type=MetricType.GAUGE)
            if self._counters[name]:
                total = sum(metric.value for metric in self._counters[name].values())
                return MetricValue(name=name, value=total, metric_type=MetricType.COUNTER)

        return None

    def to_prometheus(self) -> str:
        """导出所有指标为 Prometheus 格式"""
        lines = []

        # 添加 HELP 信息
        for name, help_text in self._metric_help.items():
            lines.append(f"# HELP {name} {help_text}")

        # 导出 counters
        for _metric_name, label_dict in self._counters.items():
            for metric_value in label_dict.values():
                lines.append(metric_value.to_prometheus().strip())

        # 导出 gauges
        for _metric_name, label_dict in self._gauges.items():
            for metric_value in label_dict.values():
                lines.append(metric_value.to_prometheus().strip())

        # 导出 histograms
        for _metric_name, label_dict in self._histograms.items():
            for histogram_value in label_dict.values():
                lines.append(histogram_value.to_prometheus().strip())

        return "\n".join(lines) + "\n"

    def to_json_lines(self) -> str:
        """导出所有指标为 JSON Lines 格式（日志友好）"""
        lines = []

        # 导出 counters
        for metric_name, label_dict in self._counters.items():
            for metric_value in label_dict.values():
                lines.append(metric_value.to_json())

        # 导出 gauges
        for metric_name, label_dict in self._gauges.items():
            for metric_value in label_dict.values():
                lines.append(metric_value.to_json())

        # 导出 histograms（简化版）
        for metric_name, label_dict in self._histograms.items():
            for histogram_value in label_dict.values():
                lines.append(json.dumps({
                    "name": metric_name,
                    "count": histogram_value.count,
                    "sum": histogram_value.sum,
                    "labels": histogram_value.labels,
                    "timestamp": histogram_value.timestamp.isoformat() if histogram_value.timestamp else None,
                    "type": "histogram"
                }))

        return "\n".join(lines) + "\n"

    def reset_metrics(self, pattern: str | None = None):
        """重置指标"""
        if pattern:
            # 重置匹配模式的指标
            for name in list(self._counters.keys()):
                if pattern in name:
                    del self._counters[name]
            for name in list(self._gauges.keys()):
                if pattern in name:
                    del self._gauges[name]
            for name in list(self._histograms.keys()):
                if pattern in name:
                    del self._histograms[name]
        else:
            # 重置所有指标
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# ============================================================================
# Alpha 模块专用指标
# ============================================================================

class AlphaMetrics:
    """
    Alpha 模块指标收集器

    定义所有 Alpha 相关的监控指标。
    """

    # 指标名称常量
    PROVIDER_SUCCESS_RATE = "alpha_provider_success_rate"
    PROVIDER_LATENCY_MS = "alpha_provider_latency_ms"
    PROVIDER_STALENESS_DAYS = "alpha_provider_staleness_days"
    COVERAGE_RATIO = "alpha_coverage_ratio"
    IC_DRIFT = "alpha_ic_drift"
    RANK_IC_ROLLING = "alpha_rank_ic_rolling"
    INFER_QUEUE_LAG = "qlib_infer_queue_lag"
    TRAIN_QUEUE_LAG = "qlib_train_queue_lag"
    MODEL_ACTIVATION_COUNT = "qlib_model_activation_count"
    MODEL_ROLLBACK_COUNT = "qlib_model_rollback_count"
    CACHE_HIT_RATE = "alpha_cache_hit_rate"
    SCORE_REQUEST_COUNT = "alpha_score_request_count"

    def __init__(self):
        self.registry = MetricsRegistry()
        self._setup_metrics()

    def _setup_metrics(self):
        """初始化指标定义"""
        # Provider 相关
        self.registry.define_metric(
            self.PROVIDER_SUCCESS_RATE,
            MetricType.GAUGE,
            "Alpha Provider 成功率（0-1）"
        )
        self.registry.define_metric(
            self.PROVIDER_LATENCY_MS,
            MetricType.HISTOGRAM,
            "Alpha Provider 延迟（毫秒）"
        )
        self.registry.define_metric(
            self.PROVIDER_STALENESS_DAYS,
            MetricType.GAUGE,
            "Alpha Provider 数据陈旧天数"
        )

        # 覆盖率
        self.registry.define_metric(
            self.COVERAGE_RATIO,
            MetricType.GAUGE,
            "Alpha 信号覆盖率（0-1）"
        )

        # IC 相关
        self.registry.define_metric(
            self.IC_DRIFT,
            MetricType.GAUGE,
            "IC 值漂移（与历史均值差值）"
        )
        self.registry.define_metric(
            self.RANK_IC_ROLLING,
            MetricType.GAUGE,
            "滚动 Rank IC 值"
        )

        # 队列相关
        self.registry.define_metric(
            self.INFER_QUEUE_LAG,
            MetricType.GAUGE,
            "推理队列积压数量"
        )
        self.registry.define_metric(
            self.TRAIN_QUEUE_LAG,
            MetricType.GAUGE,
            "训练队列积压数量"
        )

        # 模型管理
        self.registry.define_metric(
            self.MODEL_ACTIVATION_COUNT,
            MetricType.COUNTER,
            "模型激活次数"
        )
        self.registry.define_metric(
            self.MODEL_ROLLBACK_COUNT,
            MetricType.COUNTER,
            "模型回滚次数"
        )

        # 缓存相关
        self.registry.define_metric(
            self.CACHE_HIT_RATE,
            MetricType.GAUGE,
            "缓存命中率（0-1）"
        )
        self.registry.define_metric(
            self.SCORE_REQUEST_COUNT,
            MetricType.COUNTER,
            "评分请求总数"
        )

    def record_provider_call(
        self,
        provider_name: str,
        success: bool,
        latency_ms: float,
        staleness_days: float | None = None
    ):
        """记录 Provider 调用"""
        labels = {"provider": provider_name}

        # 成功率（使用指数移动平均）
        current = self.registry.get_metric(self.PROVIDER_SUCCESS_RATE, labels)
        if current is None:
            success_rate = 1.0 if success else 0.0
        else:
            alpha = 0.1  # 平滑因子
            success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * current.value

        self.registry.set_gauge(self.PROVIDER_SUCCESS_RATE, success_rate, labels)

        # 延迟
        self.registry.observe_histogram(self.PROVIDER_LATENCY_MS, latency_ms, labels=labels)

        # 陈旧度
        if staleness_days is not None:
            self.registry.set_gauge(self.PROVIDER_STALENESS_DAYS, staleness_days, labels)

        # 请求计数
        self.registry.inc_counter(self.SCORE_REQUEST_COUNT, 1.0, labels)

    def record_coverage(self, scored_count: int, universe_count: int):
        """记录覆盖率"""
        if universe_count > 0:
            ratio = scored_count / universe_count
            self.registry.set_gauge(self.COVERAGE_RATIO, ratio)

    def record_ic_metrics(
        self,
        current_ic: float,
        historical_ics: list[float],
        window: int = 20
    ):
        """记录 IC 指标"""
        if not historical_ics:
            return

        # 计算历史均值
        historical_mean = sum(historical_ics[-window:]) / min(len(historical_ics), window)

        # IC 漂移
        drift = current_ic - historical_mean
        self.registry.set_gauge(self.IC_DRIFT, drift)

        # Rank IC（假设 current_ic 就是 Rank IC）
        self.registry.set_gauge(self.RANK_IC_ROLLING, current_ic)

    def record_queue_lag(self, queue_name: str, lag_count: int):
        """记录队列积压"""
        metric_name = (
            self.INFER_QUEUE_LAG if "infer" in queue_name.lower()
            else self.TRAIN_QUEUE_LAG
        )
        self.registry.set_gauge(metric_name, float(lag_count), labels={"queue": queue_name})

    def record_model_activation(self, model_name: str, artifact_hash: str):
        """记录模型激活"""
        self.registry.inc_counter(
            self.MODEL_ACTIVATION_COUNT,
            1.0,
            labels={"model_name": model_name, "hash": artifact_hash[:8]}
        )

    def record_model_rollback(self, model_name: str, from_hash: str, to_hash: str):
        """记录模型回滚"""
        self.registry.inc_counter(
            self.MODEL_ROLLBACK_COUNT,
            1.0,
            labels={
                "model_name": model_name,
                "from": from_hash[:8],
                "to": to_hash[:8]
            }
        )

    def record_cache_hit(self, hit: bool):
        """记录缓存命中"""
        current = self.registry.get_metric(self.CACHE_HIT_RATE)
        if current is None:
            hit_rate = 1.0 if hit else 0.0
        else:
            alpha = 0.1
            hit_rate = alpha * (1.0 if hit else 0.0) + (1 - alpha) * current.value

        self.registry.set_gauge(self.CACHE_HIT_RATE, hit_rate)

    def get_all_metrics(self) -> str:
        """获取所有指标（Prometheus 格式）"""
        return self.registry.to_prometheus()

    def get_metrics_json(self) -> str:
        """获取所有指标（JSON 格式）"""
        return self.registry.to_json_lines()

    def log_metrics(self):
        """将指标记录到日志"""
        logger.info("=== Alpha 模块监控指标 ===")
        logger.info(self.get_metrics_json())


# 全局单例
_alpha_metrics: AlphaMetrics | None = None


def get_alpha_metrics() -> AlphaMetrics:
    """获取 Alpha 指标收集器单例"""
    global _alpha_metrics
    if _alpha_metrics is None:
        _alpha_metrics = AlphaMetrics()
    return _alpha_metrics


# ============================================================================
# 装饰器：自动记录指标
# ============================================================================

def track_provider_latency(provider_name: str):
    """
    装饰器：自动记录 Provider 调用延迟

    使用方法：
    @track_provider_latency("qlib")
    def get_stock_scores(...):
        ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            success = True
            result = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                raise e
            finally:
                latency_ms = (time.time() - start) * 1000
                metrics = get_alpha_metrics()
                metrics.record_provider_call(
                    provider_name=provider_name,
                    success=success,
                    latency_ms=latency_ms
                )

        return wrapper
    return decorator


# ============================================================================
# 告警规则
# ============================================================================

@dataclass
class AlertRule:
    """告警规则"""
    name: str
    metric_name: str
    condition: str  # "gt", "lt", "eq", "ne"
    threshold: float
    severity: str  # "info", "warning", "critical"
    duration_seconds: int = 300  # 持续多久才触发
    message_template: str = ""

    def evaluate(self, current_value: float) -> str | None:
        """评估是否触发告警"""
        triggered = False

        if self.condition == "gt" and current_value > self.threshold:
            triggered = True
        elif self.condition == "lt" and current_value < self.threshold:
            triggered = True
        elif self.condition == "eq" and current_value == self.threshold:
            triggered = True
        elif self.condition == "ne" and current_value != self.threshold:
            triggered = True

        if triggered:
            return self.message_template.format(
                metric=self.metric_name,
                value=current_value,
                threshold=self.threshold
            )

        return None


class AlertManager:
    """
    告警管理器

    评估指标并生成告警。
    """

    # 预定义的 Alpha 模块告警规则
    ALPHA_ALERT_RULES = [
        AlertRule(
            name="provider_unavailable",
            metric_name="alpha_provider_success_rate",
            condition="lt",
            threshold=0.5,
            severity="critical",
            duration_seconds=60,
            message_template="Alpha Provider 成功率过低: {value:.2%} < {threshold:.2%}"
        ),
        AlertRule(
            name="high_latency",
            metric_name="alpha_provider_latency_ms",
            condition="gt",
            threshold=5000,
            severity="warning",
            duration_seconds=300,
            message_template="Alpha Provider 延迟过高: {value:.0f}ms > {threshold:.0f}ms"
        ),
        AlertRule(
            name="stale_data",
            metric_name="alpha_provider_staleness_days",
            condition="gt",
            threshold=3.0,
            severity="warning",
            duration_seconds=3600,
            message_template="Alpha 数据陈旧: {value:.1f} 天 > {threshold:.1f} 天"
        ),
        AlertRule(
            name="low_coverage",
            metric_name="alpha_coverage_ratio",
            condition="lt",
            threshold=0.7,
            severity="warning",
            duration_seconds=600,
            message_template="Alpha 覆盖率过低: {value:.2%} < {threshold:.2%}"
        ),
        AlertRule(
            name="ic_drift",
            metric_name="alpha_ic_drift",
            condition="lt",
            threshold=-0.03,
            severity="warning",
            duration_seconds=86400,
            message_template="IC 值显著漂移: {value:.4f} < {threshold:.4f}"
        ),
        AlertRule(
            name="queue_backlog",
            metric_name="qlib_infer_queue_lag",
            condition="gt",
            threshold=100,
            severity="warning",
            duration_seconds=300,
            message_template="Qlib 推理队列积压: {value:.0f} 个任务 > {threshold:.0f}"
        ),
    ]

    def __init__(self, rules: list[AlertRule] | None = None):
        self.rules = rules or self.ALPHA_ALERT_RULES
        self.metrics = get_alpha_metrics()
        self._alert_states: dict[str, float] = {}  # 记录首次触发时间

    def evaluate_all(self) -> list[str]:
        """评估所有告警规则"""
        alerts = []

        for rule in self.rules:
            # 获取当前指标值（简化：取第一个匹配的）
            metric = self.metrics.registry.get_metric(rule.metric_name)

            if metric is None:
                continue

            alert_message = rule.evaluate(metric.value)

            if alert_message:
                # 检查是否持续足够长时间
                now = time.time()
                key = rule.name

                if key not in self._alert_states:
                    self._alert_states[key] = now
                    continue  # 首次触发，等待确认

                if now - self._alert_states[key] >= rule.duration_seconds:
                    alerts.append(f"[{rule.severity.upper()}] {rule.name}: {alert_message}")
            else:
                # 恢复正常，清除状态
                self._alert_states.pop(rule.name, None)

        return alerts

    def log_alerts(self):
        """将告警记录到日志"""
        alerts = self.evaluate_all()

        if alerts:
            logger.warning("=== Alpha 模块告警 ===")
            for alert in alerts:
                logger.warning(alert)
        else:
            logger.debug("告警检查: 无告警")
