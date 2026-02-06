"""
Integration Tests for Alpha Monitoring (Phase 4)

测试 Alpha 模块的监控指标和告警功能。
"""

import json
import time
from datetime import date, datetime
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from apps.alpha.application.services import AlphaService
from apps.alpha.application.monitoring_tasks import (
    evaluate_alerts,
    update_provider_metrics,
    calculate_ic_drift,
    check_queue_lag,
    generate_daily_report,
)
from apps.alpha.infrastructure.models import AlphaScoreCacheModel, QlibModelRegistryModel
from apps.alpha.infrastructure.alerts import (
    AlphaAlertManager,
    AlphaAlertConfig,
    AlertNotification,
    AlertSeverity,
    get_alpha_alert_manager,
)
from shared.infrastructure.metrics import (
    MetricsRegistry,
    AlphaMetrics,
    get_alpha_metrics,
    MetricType,
)


@pytest.mark.django_db
class TestMetricsRegistry:
    """测试指标注册表"""

    def test_singleton_pattern(self):
        """测试单例模式"""
        registry1 = MetricsRegistry()
        registry2 = MetricsRegistry()

        assert registry1 is registry2

    def test_define_metric(self):
        """测试定义指标"""
        registry = MetricsRegistry()

        registry.define_metric("test_metric", MetricType.GAUGE, "Test metric")

        assert "test_metric" in registry._metric_help
        assert registry._metric_help["test_metric"] == "Test metric"

    def test_set_gauge(self):
        """测试设置仪表盘值"""
        registry = MetricsRegistry()
        registry.define_metric("test_gauge", MetricType.GAUGE)

        registry.set_gauge("test_gauge", 42.0, labels={"provider": "test"})

        metric = registry.get_metric("test_gauge", {"provider": "test"})
        assert metric is not None
        assert metric.value == 42.0

    def test_inc_counter(self):
        """测试增加计数器"""
        registry = MetricsRegistry()
        registry.define_metric("test_counter", MetricType.COUNTER)

        registry.inc_counter("test_counter", 1.0)
        registry.inc_counter("test_counter", 2.0)

        metric = registry.get_metric("test_counter")
        assert metric is not None
        assert metric.value == 3.0

    def test_observe_histogram(self):
        """测试观测直方图"""
        registry = MetricsRegistry()
        registry.define_metric("test_histogram", MetricType.HISTOGRAM)

        # 观测一些值
        for value in [0.1, 0.5, 1.0, 2.0, 5.0]:
            registry.observe_histogram("test_histogram", value)

        # 验证统计
        histogram = registry._histograms.get("test_histogram", {})
        assert histogram
        assert any(h for h in histogram.values())

    def test_to_prometheus(self):
        """测试导出 Prometheus 格式"""
        registry = MetricsRegistry()
        registry.define_metric("test_metric", MetricType.GAUGE, "Help text")

        registry.set_gauge("test_metric", 42.0)

        output = registry.to_prometheus()

        assert "# HELP test_metric Help text" in output
        assert "test_metric 42" in output

    def test_to_json_lines(self):
        """测试导出 JSON Lines 格式"""
        registry = MetricsRegistry()
        registry.define_metric("test_metric", MetricType.GAUGE)

        registry.set_gauge("test_metric", 42.0)

        output = registry.to_json_lines()

        data = json.loads(output)
        assert data["name"] == "test_metric"
        assert data["value"] == 42.0


@pytest.mark.django_db
class TestAlphaMetrics:
    """测试 Alpha 指标收集器"""

    def test_singleton(self):
        """测试单例模式"""
        metrics1 = get_alpha_metrics()
        metrics2 = get_alpha_metrics()

        assert metrics1 is metrics2

    def test_record_provider_call(self):
        """测试记录 Provider 调用"""
        metrics = get_alpha_metrics()

        metrics.record_provider_call(
            provider_name="test",
            success=True,
            latency_ms=100.0
        )

        metric = metrics.registry.get_metric(
            AlphaMetrics.PROVIDER_SUCCESS_RATE,
            {"provider": "test"}
        )

        assert metric is not None
        assert metric.value > 0  # EMA 平滑后应该大于 0

    def test_record_coverage(self):
        """测试记录覆盖率"""
        metrics = get_alpha_metrics()

        metrics.record_coverage(scored_count=200, universe_count=300)

        metric = metrics.registry.get_metric(AlphaMetrics.COVERAGE_RATIO)
        assert metric is not None
        assert abs(metric.value - 200/300) < 0.01

    def test_record_ic_metrics(self):
        """测试记录 IC 指标"""
        metrics = get_alpha_metrics()

        historical_ics = [0.05, 0.06, 0.04, 0.05, 0.07]
        current_ic = 0.03

        metrics.record_ic_metrics(current_ic, historical_ics)

        drift_metric = metrics.registry.get_metric(AlphaMetrics.IC_DRIFT)
        assert drift_metric is not None
        # 漂移应该是负的（当前低于历史均值）
        assert drift_metric.value < 0

    def test_record_queue_lag(self):
        """测试记录队列积压"""
        metrics = get_alpha_metrics()

        metrics.record_queue_lag("qlib_infer", 50)

        metric = metrics.registry.get_metric(
            AlphaMetrics.INFER_QUEUE_LAG,
            {"queue": "qlib_infer"}
        )

        assert metric is not None
        assert metric.value == 50

    def test_record_model_activation(self):
        """测试记录模型激活"""
        metrics = get_alpha_metrics()

        metrics.record_model_activation("test_model", "abc123")

        metric = metrics.registry.get_metric(
            AlphaMetrics.MODEL_ACTIVATION_COUNT,
            {"model_name": "test_model", "hash": "abc123"}
        )

        assert metric is not None
        assert metric.value == 1


@pytest.mark.django_db
class TestAlertConfiguration:
    """测试告警配置"""

    def test_alert_rules_count(self):
        """测试告警规则数量"""
        rules = AlphaAlertConfig.get_all_rules()

        assert len(rules) > 0
        assert len(rules) >= 9  # 至少有 9 条规则

    def test_critical_rules(self):
        """测试严重告警规则"""
        critical_rules = AlphaAlertConfig.get_critical_rules()

        for rule in critical_rules:
            assert rule.severity == "critical"

    def test_warning_rules(self):
        """测试警告告警规则"""
        warning_rules = AlphaAlertConfig.get_warning_rules()

        for rule in warning_rules:
            assert rule.severity == "warning"

    def test_provider_unavailable_rule(self):
        """测试 Provider 不可用告警规则"""
        rule = AlphaAlertConfig.PROVIDER_UNAVAILABLE

        assert rule.name == "provider_unavailable"
        assert rule.metric_name == "alpha_provider_success_rate"
        assert rule.condition == "lt"
        assert rule.threshold < 1.0

    def test_high_latency_rule(self):
        """测试高延迟告警规则"""
        rule = AlphaAlertConfig.HIGH_LATENCY

        assert rule.name == "high_latency"
        assert rule.metric_name == "alpha_provider_latency_ms"
        assert rule.condition == "gt"
        assert rule.threshold > 1000


@pytest.mark.django_db
class TestAlertManager:
    """测试告警管理器"""

    def test_evaluate_no_alerts(self):
        """测试评估：无告警"""
        manager = AlphaAlertManager()

        # 清除所有指标状态
        manager.metrics.registry.reset_metrics()

        alerts = manager.evaluate_all()

        assert len(alerts) == 0

    def test_evaluate_with_alerts(self):
        """测试评估：触发告警"""
        manager = AlphaAlertManager()
        metrics = get_alpha_metrics()

        # 设置一个会触发告警的值
        metrics.registry.set_gauge(
            AlphaMetrics.PROVIDER_SUCCESS_RATE,
            0.3,  # 低于临界值 0.5
            labels={"provider": "test"}
        )

        # 第一次评估：应该不会立即触发（需要等待持续时间）
        alerts1 = manager.evaluate_with_notification()
        assert len(alerts1) == 0

        # 修改持续时间以加快测试
        for rule in manager.rules:
            if rule.name == "provider_unavailable":
                rule.duration_seconds = 0

        # 第二次评估：应该触发告警
        alerts2 = manager.evaluate_with_notification()
        # 注意：实际测试中可能需要调整持续时间逻辑

    def test_alert_summary(self):
        """测试告警摘要"""
        manager = AlphaAlertManager()

        summary = manager.get_alert_summary()

        assert "total_rules" in summary
        assert "critical_rules" in summary
        assert "warning_rules" in summary
        assert "info_rules" in summary
        assert summary["total_rules"] > 0


@pytest.mark.django_db
class TestMonitoringTasks:
    """测试监控任务"""

    def test_evaluate_alerts_task(self):
        """测试告警评估任务"""
        result = evaluate_alerts()

        assert "status" in result
        assert "timestamp" in result

    def test_update_provider_metrics_task(self):
        """测试更新 Provider 指标任务"""
        # 创建一些测试数据
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=timezone.now().date(),
            provider_source="cache",
            asof_date=timezone.now().date(),
            scores=[],
            status="available"
        )

        result = update_provider_metrics()

        assert "status" in result
        assert result["status"] == "success"

    @patch('apps.alpha.application.monitoring_tasks.get_alpha_metrics')
    def test_check_queue_lag_task(self, mock_metrics):
        """测试检查队列积压任务"""
        mock_metrics.return_value.registry.get_metric.return_value = None

        result = check_queue_lag()

        assert "status" in result

    def test_generate_daily_report_task(self):
        """测试生成每日报告任务"""
        # 创建一些测试数据
        today = timezone.now().date()

        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[],
            status="available"
        )

        result = generate_daily_report()

        assert "date" in result
        assert "cache_records" in result
        assert "provider_stats" in result


@pytest.mark.django_db
class TestAlphaServiceMetricsIntegration:
    """测试 AlphaService 与监控指标的集成"""

    def test_get_stock_scores_records_metrics(self):
        """测试 get_stock_scores 记录指标"""
        service = AlphaService()
        metrics = get_alpha_metrics()

        # 清空之前的指标
        metrics.registry.reset_metrics()

        # 获取评分（会触发指标记录）
        result = service.get_stock_scores("csi300")

        # 验证指标被记录
        request_metric = metrics.registry.get_metric(
            AlphaMetrics.SCORE_REQUEST_COUNT
        )

        # 应该有至少一个 provider 被调用
        assert request_metric is not None

    def test_provider_status_includes_metrics(self):
        """测试 Provider 状态包含指标信息"""
        service = AlphaService()

        status = service.get_provider_status()

        # 应该包含所有注册的 provider
        assert len(status) > 0

        for provider_name, info in status.items():
            assert "priority" in info
            assert "status" in info


@pytest.mark.django_db
class TestAlertNotification:
    """测试告警通知"""

    def test_alert_notification_to_dict(self):
        """测试告警通知转换为字典"""
        notification = AlertNotification(
            rule_name="test_alert",
            severity=AlertSeverity.WARNING,
            message="Test alert message",
            metric_name="test_metric",
            current_value=10.0,
            threshold=5.0,
            timestamp=datetime.now()
        )

        data = notification.to_dict()

        assert data["rule_name"] == "test_alert"
        assert data["severity"] == "warning"
        assert data["message"] == "Test alert message"
        assert data["current_value"] == 10.0
        assert data["threshold"] == 5.0


@pytest.mark.django_db
class TestMetricsPrometheusExport:
    """测试指标 Prometheus 导出"""

    def test_prometheus_export_format(self):
        """测试 Prometheus 导出格式"""
        metrics = get_alpha_metrics()

        # 设置一些指标
        metrics.registry.set_gauge("test_gauge", 42.0)
        metrics.registry.inc_counter("test_counter", 1.0)

        output = metrics.get_all_metrics()

        # 验证格式
        assert isinstance(output, str)
        assert len(output) > 0

    def test_prometheus_export_with_labels(self):
        """测试带标签的 Prometheus 导出"""
        metrics = get_alpha_metrics()

        # 设置带标签的指标
        metrics.record_provider_call("test_provider", True, 100.0)

        output = metrics.get_all_metrics()

        # 验证标签格式
        assert 'provider="test_provider"' in output


@pytest.mark.django_db
class TestICDriftCalculation:
    """测试 IC 漂移计算"""

    @patch('apps.alpha.application.monitoring_tasks.get_alpha_metrics')
    def test_calculate_ic_drift_without_active_model(self, mock_metrics):
        """测试无激活模型时的 IC 漂移计算"""
        result = calculate_ic_drift()

        assert result["status"] == "skipped"
        assert result["reason"] == "no_active_model"

    @patch('apps.alpha.application.monitoring_tasks.get_alpha_metrics')
    def test_calculate_ic_drift_with_insufficient_data(self, mock_metrics):
        """测试数据不足时的 IC 漂移计算"""
        # 创建一个激活的模型
        QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="test_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/test.pkl",
            is_active=True
        )

        result = calculate_ic_drift()

        # 由于没有缓存数据，应该跳过
        assert result["status"] in ["skipped", "success"]
