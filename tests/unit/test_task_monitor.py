"""
Unit Tests for Task Monitor Module

任务监控模块单元测试。
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.task_monitor.application.tasks import backup_database_task
from apps.task_monitor.application.use_cases import (
    GetTaskStatusUseCase,
    ListTasksUseCase,
)
from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskFailureAlert,
    TaskPriority,
    TaskStatus,
)
from apps.task_monitor.infrastructure.backup_service import DatabaseBackupResult
from apps.task_monitor.infrastructure.models import TaskExecutionModel
from apps.task_monitor.infrastructure.repositories import (
    CeleryHealthChecker,
    DjangoTaskRecordRepository,
)


class TestTaskExecutionRecord:
    """测试 TaskExecutionRecord 实体"""

    def test_to_dict(self):
        """测试转换为字典"""
        now = timezone.now()
        record = TaskExecutionRecord(
            task_id="test-id-123",
            task_name="test.task",
            status=TaskStatus.SUCCESS,
            args=(),
            kwargs={},
            started_at=now,
            finished_at=now + timedelta(seconds=10),
            result="OK",
            exception=None,
            traceback=None,
            runtime_seconds=10.0,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue="default",
            worker="worker1@localhost",
        )

        result = record.to_dict()

        assert result["task_id"] == "test-id-123"
        assert result["task_name"] == "test.task"
        assert result["status"] == "success"
        assert result["runtime_seconds"] == 10.0
        assert result["priority"] == "normal"


class TestTaskFailureAlert:
    """测试 TaskFailureAlert 实体"""

    def test_should_alert_on_final_failure(self):
        """测试最终失败时应该告警"""
        alert = TaskFailureAlert(
            task_id="test-id",
            task_name="test.task",
            exception="Test error",
            traceback=None,
            retries=3,
            max_retries=3,
            is_final_failure=True,
            triggered_at=datetime.now(),
        )

        assert alert.should_alert() is True
        assert alert.get_severity() == "critical"

    def test_should_not_alert_on_retry(self):
        """测试重试时不应该告警"""
        alert = TaskFailureAlert(
            task_id="test-id",
            task_name="test.task",
            exception="Test error",
            traceback=None,
            retries=1,
            max_retries=3,
            is_final_failure=False,
            triggered_at=datetime.now(),
        )

        assert alert.should_alert() is False


class TestDjangoTaskRecordRepository:
    """测试 DjangoTaskRecordRepository"""

    @pytest.fixture
    def repository(self):
        """创建仓储实例"""
        return DjangoTaskRecordRepository()

    @pytest.fixture
    def sample_record(self):
        """创建示例记录"""
        now = timezone.now()
        return TaskExecutionRecord(
            task_id="test-id-123",
            task_name="test.task",
            status=TaskStatus.SUCCESS,
            args=(),
            kwargs={"key": "value"},
            started_at=now,
            finished_at=now + timedelta(seconds=10),
            result="OK",
            exception=None,
            traceback=None,
            runtime_seconds=10.0,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue="default",
            worker="worker1@localhost",
        )

    def test_save_and_get_by_task_id(self, repository, sample_record, db):
        """测试保存和获取记录"""
        # 保存记录
        record_id = repository.save(sample_record)
        assert record_id is not None

        # 获取记录
        retrieved = repository.get_by_task_id("test-id-123")
        assert retrieved is not None
        assert retrieved.task_id == "test-id-123"
        assert retrieved.task_name == "test.task"
        assert retrieved.status == TaskStatus.SUCCESS

    def test_save_update_existing_record(self, repository, sample_record, db):
        """测试更新现有记录"""
        # 保存初始记录
        repository.save(sample_record)

        # 更新记录
        updated_record = TaskExecutionRecord(
            task_id="test-id-123",
            task_name="test.task",
            status=TaskStatus.FAILURE,
            args=(),
            kwargs={"key": "value"},
            started_at=sample_record.started_at,
            finished_at=timezone.now(),
            result=None,
            exception="Test error",
            traceback=None,
            runtime_seconds=15.0,
            retries=1,
            priority=TaskPriority.NORMAL,
            queue="default",
            worker="worker1@localhost",
        )
        repository.save(updated_record)

        # 验证更新
        retrieved = repository.get_by_task_id("test-id-123")
        assert retrieved.status == TaskStatus.FAILURE
        assert retrieved.retries == 1

    def test_save_serializes_non_json_task_payload(self, repository, db):
        """测试保存包含 date/Decimal/UUID 的任务参数"""
        now = timezone.now()
        sample_date = date(2026, 5, 7)
        sample_uuid = uuid4()
        record = TaskExecutionRecord(
            task_id="json-safe-123",
            task_name="test.task",
            status=TaskStatus.STARTED,
            args=(sample_date, Decimal("12.34"), sample_uuid),
            kwargs={
                "run_date": sample_date,
                "amount": Decimal("12.34"),
                "meta": {
                    "uuid": sample_uuid,
                    "items": [sample_date],
                },
            },
            started_at=now,
            finished_at=None,
            result=None,
            exception=None,
            traceback=None,
            runtime_seconds=None,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue="default",
            worker="worker1",
        )

        repository.save(record)

        model = TaskExecutionModel.objects.get(task_id="json-safe-123")
        assert model.args == [sample_date.isoformat(), "12.34", str(sample_uuid)]
        assert model.kwargs == {
            "run_date": sample_date.isoformat(),
            "amount": "12.34",
            "meta": {
                "uuid": str(sample_uuid),
                "items": [sample_date.isoformat()],
            },
        }

    def test_list_by_task_name(self, repository, db):
        """测试按任务名称列出记录"""
        # 创建多个记录
        now = timezone.now()
        for i in range(5):
            record = TaskExecutionRecord(
                task_id=f"test-id-{i}",
                task_name="test.task",
                status=TaskStatus.SUCCESS,
                args=(),
                kwargs={},
                started_at=now,
                finished_at=now + timedelta(seconds=10),
                result="OK",
                exception=None,
                traceback=None,
                runtime_seconds=10.0,
                retries=0,
                priority=TaskPriority.NORMAL,
                queue="default",
                worker="worker1",
            )
            repository.save(record)

        # 列出记录
        records = repository.list_by_task_name("test.task", limit=3)
        assert len(records) == 3

    def test_get_statistics(self, repository, db):
        """测试获取统计信息"""
        now = timezone.now()
        # 创建成功记录
        for _ in range(7):
            record = TaskExecutionRecord(
                task_id=f"success-{_}",
                task_name="test.task",
                status=TaskStatus.SUCCESS,
                args=(),
                kwargs={},
                started_at=now,
                finished_at=now + timedelta(seconds=10),
                result="OK",
                exception=None,
                traceback=None,
                runtime_seconds=10.0,
                retries=0,
                priority=TaskPriority.NORMAL,
                queue="default",
                worker="worker1",
            )
            repository.save(record)

        # 创建失败记录
        for _ in range(3):
            record = TaskExecutionRecord(
                task_id=f"failure-{_}",
                task_name="test.task",
                status=TaskStatus.FAILURE,
                args=(),
                kwargs={},
                started_at=now,
                finished_at=now + timedelta(seconds=10),
                result=None,
                exception="Error",
                traceback=None,
                runtime_seconds=5.0,
                retries=0,
                priority=TaskPriority.NORMAL,
                queue="default",
                worker="worker1",
            )
            repository.save(record)

        # 获取统计
        stats = repository.get_statistics("test.task", days=7)
        assert stats is not None
        assert stats.total_executions == 10
        assert stats.successful_executions == 7
        assert stats.failed_executions == 3
        assert stats.success_rate == 0.7

    def test_cleanup_old_records(self, repository, db):
        """测试清理旧记录"""
        # 直接修改数据库中的 created_at 时间来模拟旧记录
        old_model = TaskExecutionModel.objects.create(
            task_id="old-record",
            task_name="test.task",
            status="success",
            args=[],
            kwargs={},
            started_at=timezone.now() - timedelta(days=60),
            finished_at=timezone.now() - timedelta(days=60) + timedelta(seconds=10),
            result="OK",
            runtime_seconds=10.0,
        )
        # 手动设置为旧时间
        old_model.created_at = timezone.now() - timedelta(days=60)
        old_model.save()

        # 创建新记录
        new_record = TaskExecutionRecord(
            task_id="new-record",
            task_name="test.task",
            status=TaskStatus.SUCCESS,
            args=(),
            kwargs={},
            started_at=timezone.now(),
            finished_at=timezone.now() + timedelta(seconds=10),
            result="OK",
            exception=None,
            traceback=None,
            runtime_seconds=10.0,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue="default",
            worker="worker1",
        )
        repository.save(new_record)

        # 清理 30 天前的记录
        deleted_count = repository.cleanup_old_records(days_to_keep=30)
        assert deleted_count >= 1

        # 验证新记录仍在
        assert repository.get_by_task_id("new-record") is not None
        # 验证旧记录已删除
        assert repository.get_by_task_id("old-record") is None


class TestCeleryHealthChecker:
    """测试 CeleryHealthChecker"""

    def test_check_health_success(self):
        """测试健康检查成功"""
        # Mock Celery app
        mock_app = Mock()
        mock_connection = Mock()
        mock_app.connection_for_read.return_value = mock_connection

        mock_inspect = Mock()
        mock_inspect.active.return_value = {"worker1": []}
        mock_inspect.scheduled.return_value = {}
        mock_inspect.reserved.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect
        mock_app.backend = Mock()

        checker = CeleryHealthChecker(mock_app)
        result = checker.check_health()

        assert result.is_healthy is True
        assert result.broker_reachable is True
        assert result.backend_reachable is True
        assert "worker1" in result.active_workers

    def test_check_health_broker_failure(self):
        """测试 Broker 连接失败"""
        mock_app = Mock()
        mock_app.connection_for_read.side_effect = Exception("Connection failed")

        checker = CeleryHealthChecker(mock_app)
        result = checker.check_health()

        assert result.is_healthy is False
        assert result.broker_reachable is False


def test_backup_database_task_uses_backup_service(monkeypatch):
    class FakeBackupService:
        def backup_database(self, *, keep_days: int, compress: bool, output_dir: str | None):
            assert keep_days == 5
            assert compress is False
            assert output_dir == "D:/tmp/backups"
            return DatabaseBackupResult(
                backup_file="D:/tmp/backups/db_backup_20260430.sqlite3",
                removed_old_backups=2,
                keep_days=keep_days,
                compressed=compress,
                engine="django.db.backends.sqlite3",
            )

    monkeypatch.setattr(
        "apps.task_monitor.application.tasks.get_database_backup_service",
        lambda: FakeBackupService(),
    )

    result = backup_database_task.run(
        keep_days=5,
        compress=False,
        output_dir="D:/tmp/backups",
    )

    assert result["status"] == "success"
    assert result["backup_file"] == "D:/tmp/backups/db_backup_20260430.sqlite3"
    assert result["removed_old_backups"] == 2
    assert result["compressed"] is False


class TestGetTaskStatusUseCase:
    """测试 GetTaskStatusUseCase"""

    @pytest.fixture
    def repository(self, db):
        return DjangoTaskRecordRepository()

    def test_get_existing_task(self, repository):
        """测试获取存在的任务"""
        now = timezone.now()
        record = TaskExecutionRecord(
            task_id="test-id",
            task_name="test.task",
            status=TaskStatus.SUCCESS,
            args=(),
            kwargs={},
            started_at=now,
            finished_at=now + timedelta(seconds=10),
            result="OK",
            exception=None,
            traceback=None,
            runtime_seconds=10.0,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue="default",
            worker="worker1",
        )
        repository.save(record)

        use_case = GetTaskStatusUseCase(repository=repository)
        result = use_case.execute("test-id")

        assert result is not None
        assert result.task_id == "test-id"
        assert result.status == "success"
        assert result.is_success is True
        assert result.is_failure is False

    def test_get_nonexistent_task(self, repository):
        """测试获取不存在的任务"""
        use_case = GetTaskStatusUseCase(repository=repository)
        result = use_case.execute("nonexistent-id")
        assert result is None


class TestListTasksUseCase:
    """测试 ListTasksUseCase"""

    @pytest.fixture
    def repository(self, db):
        return DjangoTaskRecordRepository()

    def test_list_failures_only(self, repository):
        """测试只列出失败的任务"""
        now = timezone.now()
        # 创建成功记录
        success_record = TaskExecutionRecord(
            task_id="success-id",
            task_name="test.task",
            status=TaskStatus.SUCCESS,
            args=(),
            kwargs={},
            started_at=now,
            finished_at=now + timedelta(seconds=10),
            result="OK",
            exception=None,
            traceback=None,
            runtime_seconds=10.0,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue="default",
            worker="worker1",
        )
        repository.save(success_record)

        # 创建失败记录
        failure_record = TaskExecutionRecord(
            task_id="failure-id",
            task_name="test.task",
            status=TaskStatus.FAILURE,
            args=(),
            kwargs={},
            started_at=now,
            finished_at=now + timedelta(seconds=10),
            result=None,
            exception="Error",
            traceback=None,
            runtime_seconds=5.0,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue="default",
            worker="worker1",
        )
        repository.save(failure_record)

        use_case = ListTasksUseCase(repository=repository)
        result = use_case.execute(failures_only=True, limit=10)

        assert result.total == 1
        assert result.items[0].task_id == "failure-id"
        assert result.items[0].is_failure is True
