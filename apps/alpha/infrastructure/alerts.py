"""
Alert Configuration

Alpha 模块告警配置和通知机制。
"""

import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from django.conf import settings
from django.utils import timezone

from shared.infrastructure.metrics import AlertManager, AlertRule, MetricValue, get_alpha_metrics

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """告警严重级别"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class AlertNotification:
    """告警通知"""

    rule_name: str
    severity: AlertSeverity
    message: str
    metric_name: str
    current_value: float
    threshold: float
    timestamp: datetime
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rule_name.strip() or not self.metric_name.strip():
            raise ValueError("Alert notification identifiers must be non-empty")
        if not math.isfinite(self.current_value) or not math.isfinite(self.threshold):
            raise ValueError("Alert notification values must be finite")
        if timezone.is_naive(self.timestamp):
            raise ValueError("Alert notification timestamp must be timezone-aware")
        object.__setattr__(
            self,
            "labels",
            MappingProxyType(
                {
                    str(key).strip(): str(value).strip()
                    for key, value in self.labels.items()
                    if str(key).strip() and str(value).strip()
                }
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """转换为字典"""
        return {
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "message": self.message,
            "metric_name": self.metric_name,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
            "labels": dict(self.labels),
        }


class AlertNotifier:
    """
    告警通知器

    负责发送告警通知到不同的渠道。
    """

    def __init__(self) -> None:
        self._handlers: list[Callable[[AlertNotification], None]] = []

    def register_handler(self, handler: Callable[[AlertNotification], None]) -> None:
        """注册告警处理器"""
        self._handlers.append(handler)

    def notify(self, notification: AlertNotification) -> None:
        """发送告警通知"""
        for handler in self._handlers:
            try:
                handler(notification)
            except Exception as exc:
                logger.error(
                    "Alpha alert handler failed: %s",
                    type(exc).__name__,
                )


class LogAlertHandler:
    """日志告警处理器"""

    def __call__(self, notification: AlertNotification) -> None:
        """将告警记录到日志"""
        log_func = logger.warning

        if notification.severity == AlertSeverity.CRITICAL:
            log_func = logger.error
        elif notification.severity == AlertSeverity.INFO:
            log_func = logger.info

        log_func(
            "[%s] %s: %s labels=%s",
            notification.severity.value.upper(),
            notification.rule_name,
            notification.message,
            notification.labels,
        )


class AlphaAlertConfig:
    """
    Alpha 模块告警配置

    定义所有告警规则和通知处理器。
    """

    # Provider 相关告警
    PROVIDER_UNAVAILABLE = AlertRule(
        name="provider_unavailable",
        metric_name="alpha_provider_success_rate",
        condition="lt",
        threshold=0.5,
        severity="critical",
        duration_seconds=60,
        message_template="Alpha Provider 成功率过低: {value:.2%} < {threshold:.2%}",
    )

    HIGH_LATENCY = AlertRule(
        name="high_latency",
        metric_name="alpha_provider_latency_ms",
        condition="gt",
        threshold=5000,
        severity="warning",
        duration_seconds=300,
        message_template="Alpha Provider 延迟过高: {value:.0f}ms > {threshold:.0f}ms",
    )

    STALE_DATA = AlertRule(
        name="stale_data",
        metric_name="alpha_provider_staleness_days",
        condition="gt",
        threshold=3.0,
        severity="warning",
        duration_seconds=3600,
        message_template="Alpha 数据陈旧: {value:.1f} 天 > {threshold:.1f} 天",
    )

    # 覆盖率告警
    LOW_COVERAGE = AlertRule(
        name="low_coverage",
        metric_name="alpha_coverage_ratio",
        condition="lt",
        threshold=0.7,
        severity="warning",
        duration_seconds=600,
        message_template="Alpha 覆盖率过低: {value:.2%} < {threshold:.2%}",
    )

    # IC 相关告警
    IC_DRIFT = AlertRule(
        name="ic_drift",
        metric_name="alpha_ic_drift",
        condition="lt",
        threshold=-0.03,
        severity="warning",
        duration_seconds=86400,
        message_template="IC 值显著漂移: {value:.4f} < {threshold:.4f}",
    )

    RANK_IC_LOW = AlertRule(
        name="rank_ic_low",
        metric_name="alpha_rank_ic_rolling",
        condition="lt",
        threshold=0.02,
        severity="warning",
        duration_seconds=43200,
        message_template="Rank IC 过低: {value:.4f} < {threshold:.4f}",
    )

    # 队列告警
    QUEUE_BACKLOG = AlertRule(
        name="queue_backlog",
        metric_name="qlib_infer_queue_lag",
        condition="gt",
        threshold=100,
        severity="warning",
        duration_seconds=300,
        message_template="Qlib 推理队列积压: {value:.0f} 个任务 > {threshold:.0f}",
    )

    TRAIN_QUEUE_BACKLOG = AlertRule(
        name="train_queue_backlog",
        metric_name="qlib_train_queue_lag",
        condition="gt",
        threshold=10,
        severity="warning",
        duration_seconds=600,
        message_template="Qlib 训练队列积压: {value:.0f} 个任务 > {threshold:.0f}",
    )

    # 缓存告警
    LOW_CACHE_HIT_RATE = AlertRule(
        name="low_cache_hit_rate",
        metric_name="alpha_cache_hit_rate",
        condition="lt",
        threshold=0.3,
        severity="info",
        duration_seconds=1800,
        message_template="缓存命中率过低: {value:.2%} < {threshold:.2%}",
    )

    @classmethod
    def get_all_rules(cls) -> list[AlertRule]:
        """Return fresh rules with validated runtime overrides applied."""

        base_rules = [
            cls.PROVIDER_UNAVAILABLE,
            cls.HIGH_LATENCY,
            cls.STALE_DATA,
            cls.LOW_COVERAGE,
            cls.IC_DRIFT,
            cls.RANK_IC_LOW,
            cls.QUEUE_BACKLOG,
            cls.TRAIN_QUEUE_BACKLOG,
            cls.LOW_CACHE_HIT_RATE,
        ]
        raw_overrides = getattr(settings, "ALPHA_ALERT_RULE_OVERRIDES", {})
        overrides = raw_overrides if isinstance(raw_overrides, Mapping) else {}
        return [cls._apply_override(rule, overrides.get(rule.name)) for rule in base_rules]

    @staticmethod
    def _apply_override(rule: AlertRule, raw_override: object) -> AlertRule:
        """Apply one validated settings override without mutating the catalog."""

        if not isinstance(raw_override, Mapping):
            return replace(rule)

        threshold = raw_override.get("threshold", rule.threshold)
        duration = raw_override.get("duration_seconds", rule.duration_seconds)
        severity = raw_override.get("severity", rule.severity)
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold))
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 0
            or severity not in {item.value for item in AlertSeverity}
        ):
            logger.warning("Invalid Alpha alert rule override ignored: %s", rule.name)
            return replace(rule)
        return replace(
            rule,
            threshold=float(threshold),
            duration_seconds=duration,
            severity=str(severity),
        )

    @classmethod
    def get_rules_by_severity(cls, severity: str) -> list[AlertRule]:
        """按严重级别获取告警规则"""
        return [r for r in cls.get_all_rules() if r.severity == severity]

    @classmethod
    def get_critical_rules(cls) -> list[AlertRule]:
        """获取严重告警规则"""
        return cls.get_rules_by_severity("critical")

    @classmethod
    def get_warning_rules(cls) -> list[AlertRule]:
        """获取警告告警规则"""
        return cls.get_rules_by_severity("warning")

    @classmethod
    def get_info_rules(cls) -> list[AlertRule]:
        """获取信息告警规则"""
        return cls.get_rules_by_severity("info")


class AlphaAlertManager(AlertManager):
    """
    Alpha 告警管理器

    继承自 AlertManager，增加 Alpha 特定的告警处理。
    """

    def __init__(self) -> None:
        # 使用 Alpha 专用的告警规则
        super().__init__(rules=AlphaAlertConfig.get_all_rules())
        self._notified_states: set[str] = set()

        # 初始化通知器
        self._notifier = AlertNotifier()
        self._notifier.register_handler(LogAlertHandler())

        # 可选：注册其他通知处理器
        # self._setup_email_notifier()
        # self._setup_webhook_notifier()

    def evaluate_with_notification(self) -> list[AlertNotification]:
        """
        评估告警规则并发送通知

        Returns:
            触发的告警通知列表
        """
        metrics = get_alpha_metrics()

        notifications: list[AlertNotification] = []

        for rule in self.rules:
            metric_series = metrics.registry.get_metrics(rule.metric_name)
            if not metric_series:
                self._clear_rule_states(rule.name)
                continue

            observed_keys: set[str] = set()
            for metric in metric_series:
                key = self._state_key(rule.name, metric)
                observed_keys.add(key)
                if not math.isfinite(metric.value):
                    self._clear_state(key)
                    continue

                alert_message = rule.evaluate(metric.value)
                if not alert_message:
                    self._clear_state(key)
                    continue

                now = time.monotonic()
                first_triggered_at = self._alert_states.get(key)
                if first_triggered_at is None:
                    self._alert_states[key] = now
                    continue
                if now - first_triggered_at < rule.duration_seconds or key in self._notified_states:
                    continue

                notification = AlertNotification(
                    rule_name=rule.name,
                    severity=AlertSeverity(rule.severity),
                    message=alert_message,
                    metric_name=rule.metric_name,
                    current_value=metric.value,
                    threshold=rule.threshold,
                    timestamp=timezone.now(),
                    labels=dict(metric.labels),
                )
                notifications.append(notification)
                self._notified_states.add(key)
                self._notifier.notify(notification)

            self._clear_unobserved_rule_states(rule.name, observed_keys)

        return notifications

    def evaluate_all(self) -> list[str]:
        """Evaluate and format newly triggered incidents for task payloads."""

        return [
            (
                f"[{notification.severity.value.upper()}] "
                f"{notification.rule_name}: {notification.message}"
            )
            for notification in self.evaluate_with_notification()
        ]

    @staticmethod
    def _state_key(rule_name: str, metric: MetricValue) -> str:
        labels = "|".join(f"{key}={value}" for key, value in sorted(metric.labels.items()))
        return f"{rule_name}|{labels}"

    def _clear_state(self, key: str) -> None:
        self._alert_states.pop(key, None)
        self._notified_states.discard(key)

    def _clear_rule_states(self, rule_name: str) -> None:
        prefix = f"{rule_name}|"
        for key in [state_key for state_key in self._alert_states if state_key.startswith(prefix)]:
            self._clear_state(key)

    def _clear_unobserved_rule_states(
        self,
        rule_name: str,
        observed_keys: set[str],
    ) -> None:
        prefix = f"{rule_name}|"
        for key in [
            state_key
            for state_key in self._alert_states
            if state_key.startswith(prefix) and state_key not in observed_keys
        ]:
            self._clear_state(key)

    def get_alert_summary(self) -> dict[str, object]:
        """
        获取告警摘要

        Returns:
            包含告警统计信息的字典
        """
        metrics = get_alpha_metrics()

        metric_summary: dict[str, list[dict[str, object]]] = {}
        summary: dict[str, object] = {
            "total_rules": len(self.rules),
            "critical_rules": len(AlphaAlertConfig.get_critical_rules()),
            "warning_rules": len(AlphaAlertConfig.get_warning_rules()),
            "info_rules": len(AlphaAlertConfig.get_info_rules()),
            "active_alerts": len(self._alert_states),
            "metrics": metric_summary,
        }

        # 添加当前指标值
        for rule in self.rules:
            metric_summary[rule.metric_name] = [
                {
                    "value": metric.value,
                    "labels": dict(metric.labels),
                    "is_finite": math.isfinite(metric.value),
                }
                for metric in metrics.registry.get_metrics(rule.metric_name)
            ]

        return summary


_alpha_alert_manager: AlphaAlertManager | None = None


def get_alpha_alert_manager() -> AlphaAlertManager:
    """Return the process-stable manager used by periodic Celery evaluation."""

    global _alpha_alert_manager
    if _alpha_alert_manager is None:
        _alpha_alert_manager = AlphaAlertManager()
    return _alpha_alert_manager
