"""Decision model-parameter configuration and audit ORM models."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from ..domain.entities import ModelParamAuditLog, ModelParamConfig


class DecisionModelParamConfigModel(models.Model):
    """
    决策模型参数配置 ORM 模型

    保存推荐模型参数（按环境/版本）。

    Attributes:
        config_id: 配置唯一标识
        param_key: 参数键
        param_value: 参数值
        param_type: 参数类型 (float/int/str/bool)
        env: 环境 (dev/test/prod)
        version: 版本号
        is_active: 是否激活
        description: 参数描述
        updated_by: 最后修改人
        updated_reason: 变更说明
    """

    # Param Type Choices
    PARAM_TYPE_CHOICES = [
        ("float", "浮点数"),
        ("int", "整数"),
        ("str", "字符串"),
        ("bool", "布尔值"),
    ]

    # Environment Choices
    ENV_CHOICES = [
        ("dev", "开发环境"),
        ("test", "测试环境"),
        ("prod", "生产环境"),
    ]

    config_id = models.CharField(
        max_length=64, unique=True, db_index=True, help_text="配置唯一标识符"
    )

    param_key = models.CharField(max_length=128, db_index=True, help_text="参数键")

    param_value = models.TextField(help_text="参数值")

    param_type = models.CharField(
        max_length=16, choices=PARAM_TYPE_CHOICES, default="float", help_text="参数类型"
    )

    env = models.CharField(
        max_length=16, choices=ENV_CHOICES, default="dev", db_index=True, help_text="环境"
    )

    version = models.IntegerField(default=1, help_text="版本号")

    is_active = models.BooleanField(default=True, db_index=True, help_text="是否激活")

    description = models.TextField(blank=True, help_text="参数描述")

    updated_by = models.CharField(max_length=128, default="", help_text="最后修改人")

    updated_reason = models.TextField(blank=True, help_text="变更说明")

    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")

    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_model_param_config"
        verbose_name = "决策模型参数配置"
        verbose_name_plural = "决策模型参数配置"
        ordering = ["env", "param_key"]
        indexes = [
            models.Index(fields=["env", "param_key", "is_active"], name="idx_param_env_key_active"),
            models.Index(fields=["param_key", "env", "-version"], name="idx_param_key_env_version"),
        ]

    def __str__(self):
        return f"ModelParamConfig({self.param_key}={self.param_value}, env={self.env})"

    def save(self, *args, **kwargs):
        if not self.config_id:
            self.config_id = f"mpc_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def to_domain(self) -> ModelParamConfig:
        """转换为 Domain 层实体"""
        return ModelParamConfig(
            config_id=self.config_id,
            param_key=self.param_key,
            param_value=self.param_value,
            param_type=self.param_type,
            env=self.env,
            version=self.version,
            is_active=self.is_active,
            description=self.description,
            updated_by=self.updated_by,
            updated_reason=self.updated_reason,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, config: ModelParamConfig) -> DecisionModelParamConfigModel:
        """从 Domain 层实体创建"""
        return cls(
            config_id=config.config_id,
            param_key=config.param_key,
            param_value=config.param_value,
            param_type=config.param_type,
            env=config.env,
            version=config.version,
            is_active=config.is_active,
            description=config.description,
            updated_by=config.updated_by,
            updated_reason=config.updated_reason,
        )


class DecisionModelParamAuditLogModel(models.Model):
    """
    决策模型参数审计日志 ORM 模型

    保存参数变更审计日志（前后值、操作者、时间、备注）。

    Attributes:
        log_id: 日志唯一标识
        param_key: 参数键
        old_value: 旧值
        new_value: 新值
        env: 环境
        changed_by: 变更人
        change_reason: 变更原因
        changed_at: 变更时间
    """

    # Environment Choices
    ENV_CHOICES = [
        ("dev", "开发环境"),
        ("test", "测试环境"),
        ("prod", "生产环境"),
    ]

    log_id = models.CharField(max_length=64, unique=True, db_index=True, help_text="日志唯一标识符")

    param_key = models.CharField(max_length=128, db_index=True, help_text="参数键")

    old_value = models.TextField(help_text="旧值")

    new_value = models.TextField(help_text="新值")

    env = models.CharField(
        max_length=16, choices=ENV_CHOICES, default="dev", db_index=True, help_text="环境"
    )

    changed_by = models.CharField(max_length=128, default="", help_text="变更人")

    change_reason = models.TextField(blank=True, help_text="变更原因")

    changed_at = models.DateTimeField(db_index=True, help_text="变更时间")

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_model_param_audit_log"
        verbose_name = "决策模型参数审计日志"
        verbose_name_plural = "决策模型参数审计日志"
        ordering = ["-changed_at"]
        indexes = [
            models.Index(fields=["param_key", "-changed_at"], name="idx_audit_key_time"),
            models.Index(fields=["env", "-changed_at"], name="idx_audit_env_time"),
        ]

    def __str__(self):
        return f"ModelParamAuditLog({self.param_key}, {self.old_value} -> {self.new_value})"

    def save(self, *args, **kwargs):
        if not self.log_id:
            self.log_id = f"mpal_{uuid.uuid4().hex[:12]}"
        if not self.changed_at:
            self.changed_at = timezone.now()
        super().save(*args, **kwargs)

    def to_domain(self) -> ModelParamAuditLog:
        """转换为 Domain 层实体"""
        return ModelParamAuditLog(
            log_id=self.log_id,
            param_key=self.param_key,
            old_value=self.old_value,
            new_value=self.new_value,
            env=self.env,
            changed_by=self.changed_by,
            change_reason=self.change_reason,
            changed_at=self.changed_at,
        )

    @classmethod
    def from_domain(cls, log: ModelParamAuditLog) -> DecisionModelParamAuditLogModel:
        """从 Domain 层实体创建"""
        return cls(
            log_id=log.log_id,
            param_key=log.param_key,
            old_value=log.old_value,
            new_value=log.new_value,
            env=log.env,
            changed_by=log.changed_by,
            change_reason=log.change_reason,
            changed_at=log.changed_at,
        )


__all__ = [
    "DecisionModelParamAuditLogModel",
    "DecisionModelParamConfigModel",
]
