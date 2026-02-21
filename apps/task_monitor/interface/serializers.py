"""
Task Monitor Interface Serializers

DRF 序列化器定义。
"""

from rest_framework import serializers


class TaskStatusSerializer(serializers.Serializer):
    """任务状态序列化器"""
    task_id = serializers.CharField(read_only=True)
    task_name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    finished_at = serializers.DateTimeField(read_only=True, allow_null=True)
    runtime_seconds = serializers.FloatField(read_only=True, allow_null=True)
    retries = serializers.IntegerField(read_only=True)
    is_success = serializers.BooleanField(read_only=True)
    is_failure = serializers.BooleanField(read_only=True)


class TaskListSerializer(serializers.Serializer):
    """任务列表序列化器"""
    total = serializers.IntegerField(read_only=True)
    items = TaskStatusSerializer(many=True, read_only=True)


class HealthCheckSerializer(serializers.Serializer):
    """健康检查序列化器"""
    is_healthy = serializers.BooleanField(read_only=True)
    broker_reachable = serializers.BooleanField(read_only=True)
    backend_reachable = serializers.BooleanField(read_only=True)
    active_workers = serializers.ListField(
        child=serializers.CharField(),
        read_only=True
    )
    active_tasks_count = serializers.IntegerField(read_only=True)
    pending_tasks_count = serializers.IntegerField(read_only=True)
    scheduled_tasks_count = serializers.IntegerField(read_only=True)
    last_check = serializers.DateTimeField(read_only=True)


class TaskStatisticsSerializer(serializers.Serializer):
    """任务统计序列化器"""
    task_name = serializers.CharField(read_only=True)
    total_executions = serializers.IntegerField(read_only=True)
    successful_executions = serializers.IntegerField(read_only=True)
    failed_executions = serializers.IntegerField(read_only=True)
    average_runtime = serializers.FloatField(read_only=True)
    success_rate = serializers.FloatField(read_only=True)
    last_execution_status = serializers.CharField(read_only=True)
    last_execution_at = serializers.DateTimeField(read_only=True, allow_null=True)


class TaskStatusRequestSerializer(serializers.Serializer):
    """任务状态请求序列化器"""
    task_id = serializers.CharField(required=True)
