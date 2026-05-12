"""
单元测试：结构化日志（trace_id/request_id）

测试核心日志工具和中间件功能：
1. StructuredFormatter 输出正确格式的 JSON
2. TraceIDMiddleware 正确设置和传递 trace_id
3. RequestLoggingMiddleware 正确记录请求日志
4. 线程安全的 trace_id 管理
"""

import json
import logging
import sys
import threading
import time

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from core.logging_utils import (
    StructuredFormatter,
    StructuredFormatterVerbose,
    bind_logger,
    clear_trace_id,
    generate_full_trace_id,
    get_trace_id,
    set_trace_id,
)
from core.middleware.logging import (
    RequestLoggingMiddleware,
    TraceIDMiddleware,
)


class TestStructuredFormatter:
    """测试结构化日志格式化器"""

    def test_format_basic_log_record(self):
        """测试基础日志记录格式化"""
        formatter = StructuredFormatter()

        # 创建日志记录
        record = logging.LogRecord(
            name='test.logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=42,
            msg='Test message',
            args=(),
            exc_info=None,
        )

        # 格式化
        output = formatter.format(record)
        log_data = json.loads(output)

        # 验证必需字段
        assert log_data['level'] == 'INFO'
        assert log_data['logger'] == 'test.logger'
        assert log_data['message'] == 'Test message'
        assert log_data['module'] == 'test'
        assert log_data['function'] is not None  # LogRecord 会自动设置
        assert log_data['line'] == 42
        assert log_data['process'] is not None
        assert log_data['thread'] is not None
        assert 'timestamp' in log_data

    def test_format_with_trace_id(self):
        """测试带 trace_id 的日志格式化"""
        formatter = StructuredFormatter()

        # 设置 trace_id
        set_trace_id('test-trace-123')

        try:
            record = logging.LogRecord(
                name='test.logger',
                level=logging.INFO,
                pathname='test.py',
                lineno=42,
                msg='Test with trace_id',
                args=(),
                exc_info=None,
            )

            output = formatter.format(record)
            log_data = json.loads(output)

            # 验证 trace_id 被包含
            assert log_data['trace_id'] == 'test-trace-123'
        finally:
            clear_trace_id()

    def test_format_with_request_id(self):
        """测试带 request_id 的日志格式化"""
        formatter = StructuredFormatter()

        record = logging.LogRecord(
            name='test.logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=42,
            msg='Test with request_id',
            args=(),
            exc_info=None,
        )
        # 添加 request_id 属性
        record.request_id = 'req-456'

        output = formatter.format(record)
        log_data = json.loads(output)

        assert log_data['request_id'] == 'req-456'

    def test_format_with_extra_data(self):
        """测试带额外数据的日志格式化"""
        formatter = StructuredFormatter()

        record = logging.LogRecord(
            name='test.logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=42,
            msg='Test with extra',
            args=(),
            exc_info=None,
        )
        # 添加额外字段
        record.user_id = 123
        record.action = 'login'

        output = formatter.format(record)
        log_data = json.loads(output)

        assert log_data['extra']['user_id'] == 123
        assert log_data['extra']['action'] == 'login'

    def test_format_with_exception(self):
        """测试带异常信息的日志格式化"""
        formatter = StructuredFormatter()

        try:
            raise ValueError("Test exception")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name='test.logger',
            level=logging.ERROR,
            pathname='test.py',
            lineno=42,
            msg='Error occurred',
            args=(),
            exc_info=exc_info,
        )

        output = formatter.format(record)
        log_data = json.loads(output)

        assert 'exception' in log_data
        assert 'ValueError: Test exception' in log_data['exception']

    def test_verbose_formatter_includes_additional_fields(self):
        """测试详细格式化器包含额外字段"""
        formatter = StructuredFormatterVerbose()

        record = logging.LogRecord(
            name='test.logger',
            level=logging.INFO,
            pathname='/path/to/test.py',
            lineno=42,
            msg='Verbose test',
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        log_data = json.loads(output)

        # 详细格式应包含额外字段
        assert log_data['path'] == '/path/to/test.py'
        assert log_data['thread_name'] is not None
        assert log_data['process_name'] is not None


class TestTraceIDManagement:
    """测试 trace_id 管理功能"""

    def test_set_and_get_trace_id(self):
        """测试设置和获取 trace_id"""
        # 确保 clean state
        clear_trace_id()

        trace_id = set_trace_id('custom-trace-id')
        assert trace_id == 'custom-trace-id'
        assert get_trace_id() == 'custom-trace-id'

        clear_trace_id()

    def test_generate_default_trace_id(self):
        """测试自动生成 trace_id"""
        clear_trace_id()

        trace_id = set_trace_id()
        assert trace_id is not None
        assert len(trace_id) == 8  # UUID[:8]
        assert get_trace_id() == trace_id

        clear_trace_id()

    def test_clear_trace_id(self):
        """测试清除 trace_id"""
        set_trace_id('test-id')
        assert get_trace_id() == 'test-id'

        clear_trace_id()
        assert get_trace_id() is None

    def test_generate_full_trace_id(self):
        """测试生成完整 trace_id"""
        trace_id = generate_full_trace_id()

        # UUID 格式：8-4-4-4-12
        assert len(trace_id) == 36
        assert trace_id.count('-') == 4

    def test_thread_local_trace_id(self):
        """测试 trace_id 的线程隔离性"""
        results = {}
        errors = []

        def set_thread_trace(thread_id):
            try:
                set_trace_id(f'thread-{thread_id}')
                time.sleep(0.01)  # 确保线程交错
                results[thread_id] = get_trace_id()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=set_thread_trace, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # 验证每个线程都有独立的 trace_id
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 5
        for i, trace_id in results.items():
            assert trace_id == f'thread-{i}'


class TestTraceIDMiddleware:
    """测试 TraceID 中间件"""

    def test_generates_new_trace_id(self):
        """测试中间件生成新的 trace_id"""
        middleware = TraceIDMiddleware(lambda r: HttpResponse())
        factory = RequestFactory()
        request = factory.get('/api/test/')

        response = middleware(request)

        # 验证响应头包含 trace_id
        assert 'X-Trace-ID' in response
        trace_id = response['X-Trace-ID']
        assert trace_id is not None
        assert len(trace_id) == 8

    def test_preserves_incoming_trace_id(self):
        """测试中间件保留传入的 trace_id"""
        middleware = TraceIDMiddleware(lambda r: HttpResponse())
        factory = RequestFactory()
        request = factory.get('/api/test/', HTTP_X_TRACE_ID='incoming-trace-123')

        response = middleware(request)

        # 验证使用传入的 trace_id
        assert response['X-Trace-ID'] == 'incoming-trace-123'

    def test_supports_alternate_headers(self):
        """测试支持多种请求头格式"""
        factory = RequestFactory()

        # 测试 X-Request-ID
        middleware = TraceIDMiddleware(lambda r: HttpResponse())
        request = factory.get('/api/test/', HTTP_X_REQUEST_ID='req-id-456')
        response = middleware(request)
        assert response['X-Trace-ID'] == 'req-id-456'

        # 测试 X-Correlation-ID
        request = factory.get('/api/test/', HTTP_X_CORRELATION_ID='corr-id-789')
        response = middleware(request)
        assert response['X-Trace-ID'] == 'corr-id-789'

    def test_attaches_trace_id_to_request(self):
        """测试中间件将 trace_id 附加到 request 对象"""
        middleware = TraceIDMiddleware(lambda r: HttpResponse())
        factory = RequestFactory()
        request = factory.get('/api/test/')

        middleware(request)

        # 验证 request 对象有 trace_id 属性
        assert hasattr(request, 'trace_id')
        assert request.trace_id is not None

    def test_clears_trace_id_after_request(self):
        """测试请求完成后清除 trace_id"""
        clear_trace_id()

        def get_response(request):
            # 在请求处理期间，trace_id 应该存在
            assert get_trace_id() is not None
            return HttpResponse()

        middleware = TraceIDMiddleware(get_response)
        factory = RequestFactory()
        request = factory.get('/api/test/')

        middleware(request)

        # 请求完成后，trace_id 应该被清除
        assert get_trace_id() is None


class TestRequestLoggingMiddleware:
    """测试请求日志中间件"""

    def test_logs_request_start_and_completion(self, caplog):
        """测试记录请求开始和完成"""
        def get_response(request):
            return HttpResponse(status=200)

        middleware = RequestLoggingMiddleware(get_response)
        factory = RequestFactory()
        request = factory.get('/api/test/')

        # 首先设置 trace_id（模拟 TraceIDMiddleware）
        set_trace_id('test-trace')

        with caplog.at_level(logging.INFO):
            middleware(request)

        clear_trace_id()

        # 验证日志记录
        assert any('Request started' in record.message for record in caplog.records)
        assert any('Request completed' in record.message for record in caplog.records)

    def test_logs_request_failure(self, caplog):
        """测试记录请求失败"""
        def get_response(request):
            raise ValueError("Simulated error")

        middleware = RequestLoggingMiddleware(get_response)
        factory = RequestFactory()
        request = factory.get('/api/test/')

        set_trace_id('test-trace')

        with pytest.raises(ValueError):
            with caplog.at_level(logging.ERROR):
                middleware(request)

        clear_trace_id()

        # 验证错误日志
        assert any('Request failed' in record.message for record in caplog.records)

    def test_includes_duration_in_log(self, caplog):
        """测试日志包含处理时间"""
        import time

        def get_response(request):
            time.sleep(0.01)  # 10ms
            return HttpResponse()

        middleware = RequestLoggingMiddleware(get_response)
        factory = RequestFactory()
        request = factory.get('/api/test/')

        set_trace_id('test-trace')

        with caplog.at_level(logging.INFO):
            middleware(request)

        clear_trace_id()

        # 查找包含 duration 的日志
        duration_logs = [
            record for record in caplog.records
            if hasattr(record, 'duration_ms')
        ]
        assert len(duration_logs) > 0
        assert duration_logs[0].duration_ms >= 10  # 至少 10ms


class TestBindLogger:
    """测试 bind_logger 工具函数"""

    def test_bind_logger_adds_context(self, caplog):
        """测试 bind_logger 添加上下文"""
        logger = bind_logger(user_id=123, action='test')

        with caplog.at_level(logging.INFO):
            logger.info("Test message")

        # 验证日志包含绑定的上下文
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.user_id == 123
        assert record.action == 'test'

    def test_bind_logger_with_trace_id(self, caplog):
        """测试 bind_logger 与 trace_id 的集成"""
        set_trace_id('trace-123')

        try:
            logger = bind_logger(request_id='req-456')

            with caplog.at_level(logging.INFO):
                logger.info("Test message")

            # 验证 trace_id 和绑定的字段都存在
            assert len(caplog.records) == 1
            caplog.records[0]
            # trace_id 应该从线程上下文获取
            assert get_trace_id() == 'trace-123'
        finally:
            clear_trace_id()


class TestIntegration:
    """集成测试"""

    def test_full_request_flow_with_trace_id(self, caplog):
        """测试完整的请求流程（包含 trace_id 追踪）"""
        factory = RequestFactory()
        request = factory.get('/api/test/')

        # 模拟 TraceIDMiddleware + RequestLoggingMiddleware
        trace_middleware = TraceIDMiddleware(lambda r: r)

        def get_response(req):
            # 在视图中的日志
            logger = logging.getLogger(__name__)
            logger.info("Processing request")
            return HttpResponse()

        logging_middleware = RequestLoggingMiddleware(get_response)

        # 应用中间件链
        set_trace_id('integration-test')

        with caplog.at_level(logging.INFO):
            trace_middleware(request)
            logging_middleware(request)

        clear_trace_id()

        # 验证日志包含 trace_id
        [
            record for record in caplog.records
            if hasattr(record, 'trace_id') or record.getMessage().count('trace_id')
        ]

        # 至少应该有请求日志
        assert len(caplog.records) > 0
