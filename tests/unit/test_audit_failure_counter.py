"""
Unit tests for Audit Failure Counter Module

测试审计失败计数器的功能：
1. 失败记录功能
2. 计数获取和重置
3. 按组件分组统计
4. 最近失败记录
5. 健康状态判断
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from django.db import DatabaseError

from apps.audit.infrastructure.failure_counter import (
    AuditFailureCounter,
    FailureRecord,
    FailureStats,
)


class _ThreadSafeCache:
    def __init__(self) -> None:
        self._values: dict[str, object] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> object | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> bool:
        del timeout
        with self._lock:
            self._values[key] = value
        return True

    def add(self, key: str, value: object, timeout: int | None = None) -> bool:
        del timeout
        with self._lock:
            if key in self._values:
                return False
            self._values[key] = value
            return True

    def incr(self, key: str) -> int:
        with self._lock:
            value = self._values.get(key)
            if not isinstance(value, int):
                raise ValueError("missing counter")
            value += 1
            self._values[key] = value
            return value

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._values.pop(key, None) is not None

    def delete_many(self, keys: list[str]) -> None:
        with self._lock:
            for key in keys:
                self._values.pop(key, None)


class TestFailureRecord:
    """测试 FailureRecord 数据类"""

    def test_to_dict(self):
        """测试转换为字典"""
        record = FailureRecord(
            timestamp=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC),
            component="database",
            reason="Connection timeout",
        )

        result = record.to_dict()

        assert result["timestamp"] == "2026-03-04T12:00:00+00:00"
        assert result["component"] == "database"
        assert result["reason"] == "Connection timeout"


class TestFailureStats:
    """测试 FailureStats 数据类"""

    def test_default_values(self):
        """测试默认值"""
        stats = FailureStats()

        assert stats.total_count == 0
        assert stats.by_component == {}
        assert stats.recent_failures == []

    def test_to_dict(self):
        """测试转换为字典"""
        stats = FailureStats(
            total_count=5,
            by_component={"database": 3, "validation": 2},
            recent_failures=[
                FailureRecord(
                    timestamp=datetime.now(UTC),
                    component="database",
                    reason="Test failure",
                )
            ],
        )

        result = stats.to_dict()

        assert result["total_count"] == 5
        assert result["by_component"] == {"database": 3, "validation": 2}
        assert len(result["recent_failures"]) == 1
        assert result["recent_failures"][0]["component"] == "database"


class TestAuditFailureCounter:
    """测试 AuditFailureCounter 类"""

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_record_failure_increments_count(self, mock_cache):
        """测试记录失败会增加计数"""
        # 模拟 cache 返回空（初始状态）
        mock_cache.get.return_value = None

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        counter.record_failure("database", "Connection timeout")

        # 验证保存了更新后的统计
        call_args = mock_cache.set.call_args
        assert call_args is not None

        saved_stats = call_args[0][1]  # 第二个参数是保存的 stats
        assert saved_stats["total_count"] == 1
        assert saved_stats["by_component"]["database"] == 1
        assert len(saved_stats["recent_failures"]) == 1

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_record_failure_with_existing_stats(self, mock_cache):
        """测试在已有统计上记录失败"""
        # 模拟 cache 返回已有统计
        existing_stats = {
            "total_count": 3,
            "by_component": {"database": 2, "validation": 1},
            "recent_failures": [],
        }
        mock_cache.get.return_value = existing_stats

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        counter.record_failure("database", "Another timeout")

        # 验证更新
        call_args = mock_cache.set.call_args
        saved_stats = call_args[0][1]

        assert saved_stats["total_count"] == 4
        assert saved_stats["by_component"]["database"] == 3

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_record_failure_limits_recent_failures(self, mock_cache):
        """测试最近失败记录数量限制"""
        # 创建一个可以累积的 mock cache
        saved_data = {}

        def mock_set_side_effect(key, value, timeout=None):
            saved_data[key] = value

        def mock_get_side_effect(key):
            return saved_data.get(key)

        mock_cache.set.side_effect = mock_set_side_effect
        mock_cache.get.side_effect = mock_get_side_effect

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        # 记录超过 MAX_RECENT_FAILURES 的失败
        for i in range(15):
            counter.record_failure("database", f"Failure {i}")

        # 获取最后保存的统计
        call_args = mock_cache.set.call_args_list[-1]
        saved_stats = call_args[0][1]

        # 验证只保留了最近 10 条
        assert len(saved_stats["recent_failures"]) == 10

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_get_failure_count(self, mock_cache):
        """测试获取失败次数"""
        mock_cache.get.return_value = {"total_count": 7, "by_component": {}, "recent_failures": []}

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        count = counter.get_failure_count()

        assert count == 7

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_get_failure_stats(self, mock_cache):
        """测试获取完整统计信息"""
        mock_cache.get.return_value = {
            "total_count": 5,
            "by_component": {"database": 3, "validation": 2},
            "recent_failures": [
                {
                    "timestamp": "2026-03-04T12:00:00+00:00",
                    "component": "database",
                    "reason": "Timeout",
                }
            ],
        }

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        stats = counter.get_failure_stats()

        assert isinstance(stats, FailureStats)
        assert stats.total_count == 5
        assert stats.by_component == {"database": 3, "validation": 2}
        assert len(stats.recent_failures) == 1
        assert stats.recent_failures[0].component == "database"

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_reset(self, mock_cache):
        """测试重置计数器"""
        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        counter.reset()

        # 验证调用了 cache.delete
        mock_cache.delete.assert_called_once()

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_get_health_status_ok(self, mock_cache):
        """测试健康状态 - OK"""
        mock_cache.get.return_value = {"total_count": 5, "by_component": {}, "recent_failures": []}

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        status = counter.get_health_status(threshold=10)

        assert status["status"] == "OK"
        assert status["total_count"] == 5
        assert status["threshold"] == 10

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_get_health_status_warning(self, mock_cache):
        """测试健康状态 - WARNING"""
        mock_cache.get.return_value = {"total_count": 15, "by_component": {}, "recent_failures": []}

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        status = counter.get_health_status(threshold=10)

        assert status["status"] == "WARNING"

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_get_health_status_error(self, mock_cache):
        """测试健康状态 - ERROR"""
        mock_cache.get.return_value = {"total_count": 25, "by_component": {}, "recent_failures": []}

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        status = counter.get_health_status(threshold=10)

        assert status["status"] == "ERROR"

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_increment_component_count(self, mock_cache):
        """测试快捷方法增加组件计数"""
        mock_cache.get.return_value = None

        from apps.audit.infrastructure.failure_counter import AuditFailureCounter

        counter = AuditFailureCounter()

        new_count = counter.increment_component_count("database")

        # 验证返回了正确的计数
        assert new_count == 1

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_record_failure_redacts_sensitive_reason_and_traceback(
        self,
        mock_cache,
        caplog,
    ):
        mock_cache.get.return_value = None
        counter = AuditFailureCounter()

        counter.record_failure(
            "database",
            "postgresql://admin:raw-secret@example.test/audit",
            exc_info=True,
        )

        saved_stats = mock_cache.set.call_args.args[1]
        assert saved_stats["recent_failures"][0]["reason"] == "database_failure"
        assert "raw-secret" not in str(saved_stats)
        assert "raw-secret" not in caplog.text
        assert "postgresql://" not in caplog.text
        assert "traceback suppressed" in caplog.text.lower()

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_corrupted_cache_payload_degrades_to_empty_stats(self, mock_cache):
        mock_cache.get.return_value = {
            "total_count": "many",
            "by_component": {"database": "bad", None: 3},
            "recent_failures": [
                {"timestamp": "not-a-date", "component": [], "reason": object()},
                "not-an-object",
            ],
        }
        counter = AuditFailureCounter()

        stats = counter.get_failure_stats()

        assert stats.total_count == 0
        assert stats.by_component == {}
        assert stats.recent_failures == []

    @patch("apps.audit.infrastructure.failure_counter.cache")
    def test_cache_read_failure_logs_only_exception_type(
        self,
        mock_cache,
        caplog,
    ):
        mock_cache.get.side_effect = RuntimeError("redis://admin:cache-secret@example.test/0")
        counter = AuditFailureCounter()

        stats = counter.get_failure_stats()

        assert stats.total_count == 0
        assert "cache-secret" not in caplog.text
        assert "redis://" not in caplog.text
        assert "exception_type=RuntimeError" in caplog.text

    @pytest.mark.parametrize("threshold", [True, 0, -1, 1_000_001])
    def test_health_status_rejects_invalid_threshold(self, threshold):
        counter = AuditFailureCounter()

        with pytest.raises(ValueError, match="audit_failure_threshold_invalid"):
            counter.get_health_status(threshold=threshold)

    @patch("apps.audit.infrastructure.failure_counter.caches")
    def test_named_cache_backend_is_honored(self, mock_caches):
        named_cache = Mock()
        mock_caches.__getitem__.return_value = named_cache

        counter = AuditFailureCounter(cache_backend="audit")

        assert counter._cache is named_cache
        mock_caches.__getitem__.assert_called_once_with("audit")

    def test_shared_cache_atomic_counts_survive_concurrent_counter_instances(self):
        shared_cache = _ThreadSafeCache()
        first = AuditFailureCounter()
        second = AuditFailureCounter()
        first._cache = shared_cache
        second._cache = shared_cache

        def record(index: int) -> None:
            counter = first if index % 2 == 0 else second
            counter.record_failure("database", "DatabaseError")

        with ThreadPoolExecutor(max_workers=16) as executor:
            list(executor.map(record, range(100)))

        stats = first.get_failure_stats()
        assert stats.total_count == 100
        assert stats.by_component == {"database": 100}
        assert len(stats.recent_failures) <= 10


class TestGlobalFunctions:
    """测试全局快捷函数"""

    @patch("apps.audit.infrastructure.failure_counter.AuditFailureCounter")
    def test_get_audit_failure_counter(self, mock_counter_class):
        """测试获取计数器单例"""

        from apps.audit.infrastructure import failure_counter
        from apps.audit.infrastructure.failure_counter import get_audit_failure_counter

        # 重置单例
        failure_counter._failure_counter = None

        mock_counter = Mock()
        mock_counter_class.return_value = mock_counter

        result = get_audit_failure_counter()

        assert result == mock_counter

    @patch("apps.audit.infrastructure.failure_counter.get_audit_failure_counter")
    def test_record_audit_failure(self, mock_get_counter):
        """测试快捷记录失败函数"""
        from apps.audit.infrastructure.failure_counter import record_audit_failure

        mock_counter = Mock()
        mock_get_counter.return_value = mock_counter

        record_audit_failure("database", "Test failure")

        mock_counter.record_failure.assert_called_once_with("database", "Test failure", False)

    @patch("apps.audit.infrastructure.failure_counter.get_audit_failure_counter")
    def test_get_audit_failure_count(self, mock_get_counter):
        """测试快捷获取计数函数"""
        from apps.audit.infrastructure.failure_counter import get_audit_failure_count

        mock_counter = Mock()
        mock_counter.get_failure_count.return_value = 42
        mock_get_counter.return_value = mock_counter

        count = get_audit_failure_count()

        assert count == 42

    @patch("apps.audit.infrastructure.failure_counter.get_audit_failure_counter")
    def test_get_audit_failure_stats(self, mock_get_counter):
        """测试快捷获取统计函数"""
        from apps.audit.infrastructure.failure_counter import get_audit_failure_stats

        mock_stats = FailureStats(total_count=10)
        mock_counter = Mock()
        mock_counter.get_failure_stats.return_value = mock_stats
        mock_get_counter.return_value = mock_counter

        stats = get_audit_failure_stats()

        assert stats.total_count == 10

    @patch("apps.audit.infrastructure.failure_counter.get_audit_failure_counter")
    def test_reset_audit_failure_counter(self, mock_get_counter):
        """测试快捷重置函数"""
        from apps.audit.infrastructure.failure_counter import reset_audit_failure_counter

        mock_counter = Mock()
        mock_get_counter.return_value = mock_counter

        reset_audit_failure_counter()

        mock_counter.reset.assert_called_once()


class TestIntegrationWithUseCase:
    """测试与 Use Case 的集成"""

    def test_log_operation_use_case_records_failure_on_exception(self):
        """测试 LogOperationUseCase 在异常时记录失败"""
        from apps.audit.application.use_cases import LogOperationRequest, LogOperationUseCase

        # Mock repository 抛出异常
        mock_repo = Mock()
        mock_repo.save_operation_log.side_effect = DatabaseError(
            "postgresql://user:secret@internal/db"
        )

        # 使用 patch 装饰器来 mock failure_counter 模块中的函数
        with patch("apps.audit.infrastructure.failure_counter.record_audit_failure") as mock_record:
            use_case = LogOperationUseCase(audit_repository=mock_repo)

            request = LogOperationRequest(
                request_id="test-123",
                user_id=1,
                username="testuser",
                source="MCP",
                operation_type="MCP_CALL",  # 使用正确的 OperationType 枚举值
                module="test",
                action="READ",  # 使用正确的 OperationAction 枚举值
            )

            response = use_case.execute(request)

            # 验证返回失败响应
            assert response.success is False
            assert response.error == "审计日志写入失败"

            # 验证记录了失败
            assert mock_record.called
            call_args = mock_record.call_args
            assert call_args[1]["component"] == "database"

    def test_repository_records_failure_on_save_error(self):
        """测试 Repository 在保存失败时记录错误"""
        from apps.audit.domain.entities import OperationAction, OperationSource, OperationType
        from apps.audit.infrastructure.repositories import DjangoAuditRepository

        # 创建一个 mock log entity
        mock_log = Mock()
        mock_log.id = "test-123"
        mock_log.request_id = "req-123"
        mock_log.user_id = 1
        mock_log.username = "testuser"
        mock_log.source = OperationSource.MCP  # 使用正确的枚举值
        mock_log.operation_type = OperationType.MCP_CALL  # 使用正确的枚举值
        mock_log.module = "test"
        mock_log.action = OperationAction.READ  # 使用正确的枚举值
        mock_log.resource_type = None
        mock_log.resource_id = None
        mock_log.mcp_tool_name = None
        mock_log.mcp_client_id = None
        mock_log.mcp_role = None
        mock_log.sdk_version = None
        mock_log.request_method = None
        mock_log.request_path = None
        mock_log.request_params = None
        mock_log.response_status = None
        mock_log.response_message = None
        mock_log.error_code = None
        mock_log.duration_ms = None
        mock_log.checksum = None
        mock_log.ip_address = None
        mock_log.user_agent = None
        mock_log.client_id = None

        repo = DjangoAuditRepository()

        # 使用 patch 来 mock 模块级别的函数
        # 注意：OperationLogModel 在 repositories.py 中是本地导入的，需要 mock 正确的位置
        with patch("apps.audit.infrastructure.failure_counter.record_audit_failure") as mock_record:
            # 需要导入实际的模型类来进行 mock
            from apps.audit.infrastructure.models import OperationLogModel

            with patch.object(OperationLogModel._default_manager, "create") as mock_create:
                # Mock create 抛出异常
                mock_create.side_effect = Exception("DB error")

                # 验证抛出异常
                with pytest.raises(Exception, match="DB error"):
                    repo.save_operation_log(mock_log)

                # 验证记录了失败
                assert mock_record.called
