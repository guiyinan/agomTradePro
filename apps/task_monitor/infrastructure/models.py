"""
Task Monitor Infrastructure Models

Django ORM 模型定义。
"""

import json

from django.core.exceptions import ValidationError
from django.db import models


class TaskExecutionModel(models.Model):
    """任务执行记录模型"""

    # 任务基本信息
    task_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        verbose_name="任务ID"
    )
    task_name = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="任务名称"
    )

    # 任务状态
    STATUS_CHOICES = [
        ("pending", "等待中"),
        ("started", "已开始"),
        ("success", "成功"),
        ("failure", "失败"),
        ("retry", "重试中"),
        ("revoked", "已撤销"),
        ("timeout", "超时"),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        db_index=True,
        verbose_name="状态"
    )

    # 任务参数
    args = models.JSONField(default=list, verbose_name="位置参数")
    kwargs = models.JSONField(default=dict, verbose_name="关键字参数")

    # 时间信息
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="开始时间"
    )
    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="完成时间"
    )

    # 执行结果
    result = models.TextField(null=True, blank=True, verbose_name="执行结果")
    exception = models.TextField(null=True, blank=True, verbose_name="异常信息")
    traceback = models.TextField(null=True, blank=True, verbose_name="堆栈跟踪")

    # 性能指标
    runtime_seconds = models.FloatField(
        null=True,
        blank=True,
        verbose_name="运行时长(秒)"
    )

    # 重试信息
    retries = models.IntegerField(default=0, verbose_name="重试次数")

    # 任务配置
    PRIORITY_CHOICES = [
        ("low", "低"),
        ("normal", "普通"),
        ("high", "高"),
        ("critical", "紧急"),
    ]
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default="normal",
        verbose_name="优先级"
    )
    queue = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="队列名称"
    )

    # Worker 信息
    worker = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Worker 名称"
    )

    # 创建时间
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="创建时间"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        verbose_name = "任务执行记录"
        verbose_name_plural = "任务执行记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["task_name", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.task_name}[{self.task_id}] - {self.get_status_display()}"

    def clean(self) -> None:
        """验证数据"""
        if self.finished_at and self.started_at:
            if self.finished_at < self.started_at:
                raise ValidationError("完成时间不能早于开始时间")

            # 自动计算运行时长
            if not self.runtime_seconds:
                self.runtime_seconds = (
                    self.finished_at - self.started_at
                ).total_seconds()


class TaskAlertModel(models.Model):
    """任务告警记录模型"""

    # 告警级别
    LEVEL_CHOICES = [
        ("info", "信息"),
        ("warning", "警告"),
        ("critical", "严重"),
    ]
    level = models.CharField(
        max_length=20,
        choices=LEVEL_CHOICES,
        db_index=True,
        verbose_name="告警级别"
    )

    # 任务信息
    task_id = models.CharField(max_length=255, verbose_name="任务ID")
    task_name = models.CharField(max_length=255, verbose_name="任务名称")

    # 告警内容
    title = models.CharField(max_length=500, verbose_name="告警标题")
    message = models.TextField(verbose_name="告警消息")
    exception = models.TextField(null=True, blank=True, verbose_name="异常信息")
    traceback = models.TextField(null=True, blank=True, verbose_name="堆栈跟踪")

    # 告警状态
    is_sent = models.BooleanField(default=False, verbose_name="已发送")
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="发送时间")
    send_error = models.TextField(null=True, blank=True, verbose_name="发送错误")

    # 元数据
    metadata = models.JSONField(default=dict, verbose_name="元数据")

    # 时间信息
    triggered_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="触发时间"
    )

    class Meta:
        verbose_name = "任务告警记录"
        verbose_name_plural = "任务告警记录"
        ordering = ["-triggered_at"]
        indexes = [
            models.Index(fields=["level", "triggered_at"]),
            models.Index(fields=["task_name", "triggered_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.get_level_display()}] {self.title}"
