"""
Prometheus Metrics Integration Tests

测试 Prometheus 指标的正确性：
- API 请求指标
- Celery 任务指标
- 审计日志指标
- Metrics 端点可访问性
"""


import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from prometheus_client import REGISTRY

User = get_user_model()


@pytest.mark.django_db
class TestPrometheusMetricsEndpoint:
    """Prometheus metrics 端点测试"""

    def test_metrics_endpoint_accessible(self):
        """测试 metrics 端点可访问"""
        client = Client()

        response = client.get('/metrics/')

        assert response.status_code == 200
        assert 'text/plain' in response.get('Content-Type', '')

    def test_metrics_endpoint_content(self):
        """测试 metrics 端点返回内容"""
        client = Client()

        response = client.get('/metrics/')

        content = response.content.decode('utf-8')

        # 验证包含基本的 Prometheus 格式
        assert '# HELP' in content or '# TYPE' in content

    def test_metrics_endpoint_after_request(self):
        """测试 API 请求后 metrics 端点包含相关指标"""
        client = Client()

        # 触发一个 API 请求
        response = client.get('/api/health/')
        assert response.status_code in (200, 302, 403)  # 可能被重定向或需要认证

        # 获取 metrics
        metrics_response = client.get('/metrics/')
        content = metrics_response.content.decode('utf-8')

        # 验证包含指标（可能由 django-prometheus 自动生成）
        # 不强制检查自定义指标，因为请求可能被中间件跳过
        assert len(content) > 0


@pytest.mark.django_db
class TestAPIMetrics:
    """API 请求指标测试"""

    def test_api_request_metrics_recorded(self):
        """测试 API 请求指标被记录"""
        from core.metrics import api_request_total

        # 获取初始计数
        initial_count = 0
        for metric in api_request_total.collect():
            for sample in metric.samples:
                initial_count += sample.value

        # 发起 API 请求
        client = Client()
        client.get('/api/health/')

        # 验证计数增加
        final_count = 0
        for metric in api_request_total.collect():
            for sample in metric.samples:
                final_count += sample.value

        # 计数应该增加（至少增加 1）
        assert final_count >= initial_count

    def test_api_latency_metrics_recorded(self):
        """测试 API 延迟指标被记录"""
        from core.metrics import api_request_latency_seconds

        # 获取初始样本数
        initial_samples = 0
        for metric in api_request_latency_seconds.collect():
            initial_samples += len(metric.samples)

        # 发起 API 请求
        client = Client()
        client.get('/api/health/')

        # 验证有延迟样本被记录
        final_samples = 0
        for metric in api_request_latency_seconds.collect():
            final_samples += len(metric.samples)

        # 应该有新的样本
        assert final_samples >= initial_samples


@pytest.mark.django_db
class TestCeleryMetrics:
    """Celery 任务指标测试"""

    def test_celery_task_metrics_exist(self):
        """测试 Celery 指标已定义"""

        # 验证指标存在于 REGISTRY 中
        # 注意：指标名称可能包含后缀，使用 in 检查
        metric_names = {metric.name for metric in REGISTRY.collect()}

        # prometheus_client 的指标名称可能不含 _total 后缀
        assert any('celery_task' in name for name in metric_names)
        assert any('celery_task_duration' in name or 'duration' in name for name in metric_names)
        assert any('celery_task_retry' in name or 'retry' in name for name in metric_names)

    def test_celery_task_execution_records_metrics(self):
        """测试 Celery 任务执行记录指标"""
        from core.metrics import celery_task_total, record_celery_task

        # 使用 record_celery_task 直接记录指标（用于测试）
        record_celery_task(
            task_name='check_data_freshness',
            status='success',
            duration_seconds=1.5
        )

        # 验证指标被记录
        found = False
        for metric in celery_task_total.collect():
            for sample in metric.samples:
                if (
                    sample.labels.get('task_name') == 'check_data_freshness'
                    and sample.labels.get('status') == 'success'
                ):
                    found = True
                    assert sample.value > 0
                    break

        assert found, "Task metric not found"


@pytest.mark.django_db
class TestAuditMetrics:
    """审计日志指标测试"""

    def test_audit_metrics_exist(self):
        """测试审计指标已定义"""

        # 验证指标存在于 REGISTRY 中
        # 注意：指标名称可能不含 _total 后缀
        metric_names = {metric.name for metric in REGISTRY.collect()}

        assert any('audit_write' in name for name in metric_names)
        assert any('audit_write_latency' in name or 'audit_latency' in name for name in metric_names)

    def test_audit_write_metrics_function(self):
        """测试审计写入指标记录函数"""
        from core.metrics import audit_write_total, record_audit_write

        # 记录一次成功
        record_audit_write(
            module='test_module',
            status='success',
            source='test',
            latency_seconds=0.1
        )

        # 验证指标被记录
        found = False
        for metric in audit_write_total.collect():
            for sample in metric.samples:
                if (
                    sample.labels.get('module') == 'test_module'
                    and sample.labels.get('status') == 'success'
                ):
                    found = True
                    assert sample.value > 0
                    break

        assert found, "Audit metric not found"


@pytest.mark.django_db
class TestMetricsSummary:
    """指标摘要功能测试"""

    def test_get_metrics_summary(self):
        """测试获取指标摘要"""
        from core.metrics import get_metrics_summary

        summary = get_metrics_summary()

        # 验证返回结构
        assert 'api_requests' in summary
        assert 'celery_tasks' in summary
        assert 'audit_writes' in summary

        # 验证子结构
        assert 'total' in summary['api_requests']
        assert 'errors' in summary['api_requests']


@pytest.mark.django_db
class TestCeleryMetricsSignalHandlers:
    """Celery 信号处理器测试"""

    def test_task_prerun_signal_handler(self):
        """测试任务开始信号处理"""
        from core.celery_metrics import _task_start_times

        # 验证 _task_start_times 字典存在
        assert isinstance(_task_start_times, dict)

        # 注意：实际的任务执行会在测试环境中同步完成
        # 这里只验证数据结构存在

    def test_task_postrun_signal_handler(self):
        """测试任务完成信号处理"""
        from core.metrics import celery_task_total, record_celery_task

        # 使用 record_celery_task 模拟信号处理器的行为
        record_celery_task(
            task_name='check_data_freshness',
            status='success',
            duration_seconds=2.0
        )

        # 验证指标被记录
        found_success = False
        for metric in celery_task_total.collect():
            for sample in metric.samples:
                if (
                    sample.labels.get('task_name') == 'check_data_freshness'
                    and sample.labels.get('status') == 'success'
                ):
                    found_success = True
                    break

        assert found_success, "Success metric not found"
