"""
Events Infrastructure Models

事件存储和失败事件的 ORM 模型。

架构约束：
- ORM 模型属于 Infrastructure 层
- 通过 to_domain() 转换为 Domain 实体
"""

from django.db import models


class FailedEventModel(models.Model):
    """
    失败事件 ORM 模型

    存储处理失败的事件，支持后续重放。

    Attributes:
        event_id: 事件 ID
        event_type: 事件类型
        payload: 事件负载
        metadata: 事件元数据
        handler_id: 处理器 ID
        error_message: 错误信息
        error_traceback: 错误堆栈
        retry_count: 重试次数
        max_retries: 最大重试次数
        next_retry_at: 下次重试时间
        last_retry_at: 最后重试时间
        status: 状态（PENDING, RETRYING, SUCCESS, EXHAUSTED）
        created_at: 创建时间
        updated_at: 更新时间
    """

    # Status Choices
    PENDING = "PENDING"
    RETRYING = "RETRYING"
    SUCCESS = "SUCCESS"
    EXHAUSTED = "EXHAUSTED"
    STATUS_CHOICES = [
        (PENDING, "待重试"),
        (RETRYING, "重试中"),
        (SUCCESS, "已成功"),
        (EXHAUSTED, "已耗尽重试次数"),
    ]

    event_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="事件 ID"
    )

    event_type = models.CharField(
        max_length=64,
        db_index=True,
        help_text="事件类型"
    )

    payload = models.JSONField(
        help_text="事件负载"
    )

    metadata = models.JSONField(
        default=dict,
        help_text="事件元数据"
    )

    handler_id = models.CharField(
        max_length=128,
        db_index=True,
        help_text="处理器 ID"
    )

    error_message = models.TextField(
        help_text="错误信息"
    )

    error_traceback = models.TextField(
        blank=True,
        help_text="错误堆栈"
    )

    retry_count = models.IntegerField(
        default=0,
        help_text="重试次数"
    )

    max_retries = models.IntegerField(
        default=3,
        help_text="最大重试次数"
    )

    next_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="下次重试时间"
    )

    last_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最后重试时间"
    )

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=PENDING,
        db_index=True,
        help_text="状态"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="更新时间"
    )

    class Meta:
        db_table = "failed_event"
        verbose_name = "失败事件"
        verbose_name_plural = "失败事件"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_retry_at"], name="evt_fail_status_retry_idx"),
            models.Index(fields=["handler_id", "status"], name="evt_fail_handler_idx"),
        ]

    def __str__(self):
        return f"FailedEvent({self.event_id}, {self.event_type}, {self.status})"
