"""Canonical ORM storage for immutable portfolio transition plans."""

import uuid
from typing import Any

from django.db import models
from django.utils import timezone

from core.integration.transition_plan_contracts import (
    CANONICAL_TRANSITION_PLAN_FAMILY,
    LEGACY_TRANSITION_PLAN_FAMILY,
)


class PortfolioTransitionPlanModel(models.Model):
    CONTRACT_FAMILY_LEGACY = LEGACY_TRANSITION_PLAN_FAMILY
    CONTRACT_FAMILY_CANONICAL = CANONICAL_TRANSITION_PLAN_FAMILY
    CONTRACT_FAMILY_CHOICES = [
        (CONTRACT_FAMILY_LEGACY, "Decision Rhythm legacy v1"),
        (CONTRACT_FAMILY_CANONICAL, "Portfolio canonical v1"),
    ]
    STATUS_CHOICES = [
        ("DRAFT", "草稿"),
        ("READY_FOR_APPROVAL", "可提交审批"),
        ("APPROVAL_PENDING", "审批中"),
        ("APPROVED", "已批准"),
        ("REJECTED", "已拒绝"),
        ("EXECUTED", "已执行"),
        ("FAILED", "执行失败"),
        ("CANCELLED", "已取消"),
    ]

    plan_id = models.CharField(
        max_length=64, unique=True, db_index=True, help_text="计划唯一标识符"
    )
    account_id = models.CharField(max_length=64, db_index=True, help_text="账户 ID")
    source_recommendation_ids = models.JSONField(default=list, help_text="来源推荐 ID 列表")
    current_positions_snapshot = models.JSONField(default=list, help_text="当前持仓快照")
    target_positions_snapshot = models.JSONField(default=list, help_text="目标持仓快照")
    orders = models.JSONField(default=list, help_text="调仓订单快照")
    risk_contract = models.JSONField(default=dict, help_text="计划级风控契约")
    summary = models.JSONField(default=dict, help_text="计划摘要")
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default="DRAFT",
        db_index=True,
        help_text="计划状态",
    )
    approval_request_id = models.CharField(
        max_length=64, blank=True, default="", help_text="关联审批请求 ID"
    )
    plan_contract_family = models.CharField(
        max_length=40,
        choices=CONTRACT_FAMILY_CHOICES,
        null=True,
        blank=True,
        db_index=True,
        help_text="Transition-plan payload contract family; NULL denotes unclassified legacy data",
    )
    idempotency_key = models.CharField(max_length=128, null=True, blank=True, unique=True)
    decision_snapshot_id = models.CharField(max_length=64, blank=True, db_index=True)
    portfolio_snapshot_id = models.CharField(max_length=64, blank=True)
    target_portfolio_id = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    immutable_payload_hash = models.CharField(max_length=64, blank=True)
    plan_version = models.PositiveIntegerField(default=1)
    approved_at = models.DateTimeField(null=True, blank=True)
    as_of = models.DateTimeField(db_index=True, help_text="计划快照时间")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")

    class Meta:
        db_table = "decision_portfolio_transition_plan"
        verbose_name = "账户级调仓计划"
        verbose_name_plural = "账户级调仓计划"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account_id", "-created_at"], name="idx_plan_acc_created"),
            models.Index(fields=["status", "-created_at"], name="idx_plan_status_created"),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.plan_id:
            self.plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        if not self.as_of:
            self.as_of = timezone.now()
        super().save(*args, **kwargs)
