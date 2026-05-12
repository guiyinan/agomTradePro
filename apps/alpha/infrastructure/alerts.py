"""
Alert Configuration

Alpha 模块告警配置和通知机制。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from django.utils import timezone

from shared.infrastructure.metrics import AlertManager, AlertRule, get_alpha_metrics

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """告警严重级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertNotification:
    """告警通知"""
    rule_name: str
    severity: AlertSeverity
    message: str
    metric_name: str
    current_value: float
    threshold: float
    timestamp: datetime

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "message": self.message,
            "metric_name": self.metric_name,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
        }


class AlertNotifier:
    """
    告警通知器

    负责发送告警通知到不同的渠道。
    """

    def __init__(self):
        self._handlers: list[Callable[[AlertNotification], None]] = []

    def register_handler(self, handler: Callable[[AlertNotification], None]):
        """注册告警处理器"""
        self._handlers.append(handler)

    def notify(self, notification: AlertNotification):
        """发送告警通知"""
        for handler in self._handlers:
            try:
                handler(notification)
            except Exception as e:
                logger.error(f"告警处理器执行失败: {e}", exc_info=True)


class LogAlertHandler:
    """日志告警处理器"""

    def __call__(self, notification: AlertNotification):
        """将告警记录到日志"""
        log_func = logger.warning

        if notification.severity == AlertSeverity.CRITICAL:
            log_func = logger.error
        elif notification.severity == AlertSeverity.INFO:
            log_func = logger.info

        log_func(
            f"[{notification.severity.value.upper()}] "
            f"{notification.rule_name}: {notification.message}"
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
        message_template="Alpha Provider 成功率过低: {value:.2%} < {threshold:.2%}"
    )

    HIGH_LATENCY = AlertRule(
        name="high_latency",
        metric_name="alpha_provider_latency_ms",
        condition="gt",
        threshold=5000,
        severity="warning",
        duration_seconds=300,
        message_template="Alpha Provider 延迟过高: {value:.0f}ms > {threshold:.0f}ms"
    )

    STALE_DATA = AlertRule(
        name="stale_data",
        metric_name="alpha_provider_staleness_days",
        condition="gt",
        threshold=3.0,
        severity="warning",
        duration_seconds=3600,
        message_template="Alpha 数据陈旧: {value:.1f} 天 > {threshold:.1f} 天"
    )

    # 覆盖率告警
    LOW_COVERAGE = AlertRule(
        name="low_coverage",
        metric_name="alpha_coverage_ratio",
        condition="lt",
        threshold=0.7,
        severity="warning",
        duration_seconds=600,
        message_template="Alpha 覆盖率过低: {value:.2%} < {threshold:.2%}"
    )

    # IC 相关告警
    IC_DRIFT = AlertRule(
        name="ic_drift",
        metric_name="alpha_ic_drift",
        condition="lt",
        threshold=-0.03,
        severity="warning",
        duration_seconds=86400,
        message_template="IC 值显著漂移: {value:.4f} < {threshold:.4f}"
    )

    RANK_IC_LOW = AlertRule(
        name="rank_ic_low",
        metric_name="alpha_rank_ic_rolling",
        condition="lt",
        threshold=0.02,
        severity="warning",
        duration_seconds=43200,
        message_template="Rank IC 过低: {value:.4f} < {threshold:.4f}"
    )

    # 队列告警
    QUEUE_BACKLOG = AlertRule(
        name="queue_backlog",
        metric_name="qlib_infer_queue_lag",
        condition="gt",
        threshold=100,
        severity="warning",
        duration_seconds=300,
        message_template="Qlib 推理队列积压: {value:.0f} 个任务 > {threshold:.0f}"
    )

    TRAIN_QUEUE_BACKLOG = AlertRule(
        name="train_queue_backlog",
        metric_name="qlib_train_queue_lag",
        condition="gt",
        threshold=10,
        severity="warning",
        duration_seconds=600,
        message_template="Qlib 训练队列积压: {value:.0f} 个任务 > {threshold:.0f}"
    )

    # 缓存告警
    LOW_CACHE_HIT_RATE = AlertRule(
        name="low_cache_hit_rate",
        metric_name="alpha_cache_hit_rate",
        condition="lt",
        threshold=0.3,
        severity="info",
        duration_seconds=1800,
        message_template="缓存命中率过低: {value:.2%} < {threshold:.2%}"
    )

    @classmethod
    def get_all_rules(cls) -> list[AlertRule]:
        """获取所有告警规则"""
        return [
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

    def __init__(self):
        # 使用 Alpha 专用的告警规则
        super().__init__(rules=AlphaAlertConfig.get_all_rules())

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

        notifications = []

        for rule in self.rules:
            # 获取当前指标值
            metric = metrics.registry.get_metric(rule.metric_name)

            if metric is None:
                continue

            # 评估规则
            alert_message = rule.evaluate(metric.value)

            if alert_message:
                # 检查持续时间
                import time
                now = time.time()
                key = rule.name

                if key not in self._alert_states:
                    self._alert_states[key] = now
                    continue  # 首次触发，等待确认

                if now - self._alert_states[key] >= rule.duration_seconds:
                    # 创建告警通知
                    notification = AlertNotification(
                        rule_name=rule.name,
                        severity=AlertSeverity(rule.severity),
                        message=alert_message,
                        metric_name=rule.metric_name,
                        current_value=metric.value,
                        threshold=rule.threshold,
                        timestamp=timezone.now()
                    )

                    notifications.append(notification)

                    # 发送通知
                    self._notifier.notify(notification)
            else:
                # 恢复正常，清除状态
                self._alert_states.pop(rule.name, None)

        return notifications

    def get_alert_summary(self) -> dict:
        """
        获取告警摘要

        Returns:
            包含告警统计信息的字典
        """
        metrics = get_alpha_metrics()

        summary = {
            "total_rules": len(self.rules),
            "critical_rules": len(AlphaAlertConfig.get_critical_rules()),
            "warning_rules": len(AlphaAlertConfig.get_warning_rules()),
            "info_rules": len(AlphaAlertConfig.get_info_rules()),
            "active_alerts": len(self._alert_states),
            "metrics": {},
        }

        # 添加当前指标值
        for rule in self.rules:
            metric = metrics.registry.get_metric(rule.metric_name)
            if metric is not None:
                summary["metrics"][rule.metric_name] = {
                    "value": metric.value,
                    "labels": metric.labels,
                }

        return summary


def get_alpha_alert_manager() -> AlphaAlertManager:
    """获取 Alpha 告警管理器单例"""
    # 可以在这里实现单例模式
    return AlphaAlertManager()


# ============================================================================
# 告警阈值配置（可通过环境变量或数据库调整）
# ============================================================================

class AlertThresholds:
    """
    告警阈值配置

    可以通过环境变量或数据库动态调整。
    """

    # Provider 阈值
    PROVIDER_SUCCESS_RATE_CRITICAL = 0.5
    PROVIDER_SUCCESS_RATE_WARNING = 0.7

    PROVIDER_LATENCY_WARNING_MS = 5000
    PROVIDER_LATENCY_CRITICAL_MS = 10000

    PROVIDER_STALENESS_WARNING_DAYS = 3.0
    PROVIDER_STALENESS_CRITICAL_DAYS = 5.0

    # 覆盖率阈值
    COVERAGE_RATIO_WARNING = 0.7
    COVERAGE_RATIO_CRITICAL = 0.5

    # IC 阈值
    IC_DRIFT_WARNING = -0.03
    IC_DRIFT_CRITICAL = -0.05

    RANK_IC_WARNING = 0.02
    RANK_IC_CRITICAL = 0.01

    # 队列阈值
    QUEUE_BACKLOG_WARNING = 100
    QUEUE_BACKLOG_CRITICAL = 500

    TRAIN_QUEUE_BACKLOG_WARNING = 10
    TRAIN_QUEUE_BACKLOG_CRITICAL = 50

    # 缓存阈值
    CACHE_HIT_RATE_INFO = 0.3
    CACHE_HIT_RATE_WARNING = 0.2

    @classmethod
    def update_from_env(cls):
        """从环境变量更新阈值"""

        from environ import Env

        env = Env()

        # Provider 阈值
        cls.PROVIDER_SUCCESS_RATE_CRITICAL = env.float(
            "ALERT_PROVIDER_SUCCESS_CRITICAL",
            default=cls.PROVIDER_SUCCESS_RATE_CRITICAL
        )
        cls.PROVIDER_SUCCESS_RATE_WARNING = env.float(
            "ALERT_PROVIDER_SUCCESS_WARNING",
            default=cls.PROVIDER_SUCCESS_RATE_WARNING
        )

        cls.PROVIDER_LATENCY_WARNING_MS = env.int(
            "ALERT_PROVIDER_LATENCY_WARNING_MS",
            default=cls.PROVIDER_LATENCY_WARNING_MS
        )

        # ... 其他阈值配置

        logger.info("告警阈值已从环境变量加载")

    @classmethod
    def to_dict(cls) -> dict:
        """转换为字典（用于 API 响应）"""
        return {
            "provider": {
                "success_rate": {
                    "critical": cls.PROVIDER_SUCCESS_RATE_CRITICAL,
                    "warning": cls.PROVIDER_SUCCESS_RATE_WARNING,
                },
                "latency_ms": {
                    "warning": cls.PROVIDER_LATENCY_WARNING_MS,
                    "critical": cls.PROVIDER_LATENCY_CRITICAL_MS,
                },
                "staleness_days": {
                    "warning": cls.PROVIDER_STALENESS_WARNING_DAYS,
                    "critical": cls.PROVIDER_STALENESS_CRITICAL_DAYS,
                },
            },
            "coverage": {
                "warning": cls.COVERAGE_RATIO_WARNING,
                "critical": cls.COVERAGE_RATIO_CRITICAL,
            },
            "ic": {
                "drift_warning": cls.IC_DRIFT_WARNING,
                "drift_critical": cls.IC_DRIFT_CRITICAL,
                "rank_ic_warning": cls.RANK_IC_WARNING,
                "rank_ic_critical": cls.RANK_IC_CRITICAL,
            },
            "queue": {
                "backlog_warning": cls.QUEUE_BACKLOG_WARNING,
                "backlog_critical": cls.QUEUE_BACKLOG_CRITICAL,
            },
        }
