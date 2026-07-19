"""Portfolio-transition ORM models."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone

from ..domain.entities import (
    PortfolioTransitionPlan,
    TransitionOrder,
    TransitionPlanStatus,
)


class PortfolioTransitionPlanModel(models.Model):
    """账户级调仓计划 ORM 模型。"""

    STATUS_CHOICES = [
        (TransitionPlanStatus.DRAFT.value, "草稿"),
        (TransitionPlanStatus.READY_FOR_APPROVAL.value, "可提交审批"),
        (TransitionPlanStatus.APPROVAL_PENDING.value, "审批中"),
        (TransitionPlanStatus.APPROVED.value, "已批准"),
        (TransitionPlanStatus.REJECTED.value, "已拒绝"),
        (TransitionPlanStatus.EXECUTED.value, "已执行"),
        (TransitionPlanStatus.FAILED.value, "执行失败"),
        (TransitionPlanStatus.CANCELLED.value, "已取消"),
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
        default=TransitionPlanStatus.DRAFT.value,
        db_index=True,
        help_text="计划状态",
    )
    approval_request_id = models.CharField(
        max_length=64, blank=True, default="", help_text="关联审批请求 ID"
    )
    as_of = models.DateTimeField(db_index=True, help_text="计划快照时间")
    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")
    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_portfolio_transition_plan"
        verbose_name = "账户级调仓计划"
        verbose_name_plural = "账户级调仓计划"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account_id", "-created_at"], name="idx_plan_acc_created"),
            models.Index(fields=["status", "-created_at"], name="idx_plan_status_created"),
        ]

    def __str__(self):
        return f"PortfolioTransitionPlan({self.plan_id}, {self.account_id}, {self.status})"

    def save(self, *args, **kwargs):
        if not self.plan_id:
            self.plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        if not self.as_of:
            self.as_of = timezone.now()
        super().save(*args, **kwargs)

    def to_domain(self) -> PortfolioTransitionPlan:
        orders = [
            TransitionOrder(
                security_code=str(item.get("security_code") or ""),
                action=str(item.get("action") or "HOLD"),
                current_qty=int(item.get("current_qty") or 0),
                target_qty=int(item.get("target_qty") or 0),
                delta_qty=int(item.get("delta_qty") or 0),
                current_weight=float(item.get("current_weight") or 0.0),
                target_weight=float(item.get("target_weight") or 0.0),
                price_band_low=Decimal(str(item.get("price_band_low") or "0")),
                price_band_high=Decimal(str(item.get("price_band_high") or "0")),
                max_capital=Decimal(str(item.get("max_capital") or "0")),
                stop_loss_price=(
                    Decimal(str(item.get("stop_loss_price")))
                    if item.get("stop_loss_price") not in [None, ""]
                    else None
                ),
                invalidation_rule=item.get("invalidation_rule") or {},
                execution_price=(
                    Decimal(str(item.get("execution_price")))
                    if item.get("execution_price") not in [None, ""]
                    else None
                ),
                price_source=str(item.get("price_source") or ""),
                take_profit_price=(
                    Decimal(str(item.get("take_profit_price")))
                    if item.get("take_profit_price") not in [None, ""]
                    else None
                ),
                take_profit_source=str(item.get("take_profit_source") or ""),
                stop_loss_source=str(item.get("stop_loss_source") or ""),
                thesis=str(item.get("thesis") or ""),
                risk_summary=str(item.get("risk_summary") or ""),
                reward_risk=dict(item.get("reward_risk") or {}),
                data_asof=str(item.get("data_asof") or ""),
                invalidation_description=str(item.get("invalidation_description") or ""),
                requires_user_confirmation=bool(item.get("requires_user_confirmation", False)),
                review_by=item.get("review_by"),
                time_horizon=str(item.get("time_horizon") or "swing"),
                source_recommendation_id=str(item.get("source_recommendation_id") or ""),
                notes=list(item.get("notes") or []),
            )
            for item in (self.orders or [])
        ]
        return PortfolioTransitionPlan(
            plan_id=self.plan_id,
            account_id=self.account_id,
            as_of=self.as_of,
            source_recommendation_ids=list(self.source_recommendation_ids or []),
            current_positions_snapshot=list(self.current_positions_snapshot or []),
            target_positions_snapshot=list(self.target_positions_snapshot or []),
            orders=orders,
            risk_contract=dict(self.risk_contract or {}),
            summary=dict(self.summary or {}),
            status=TransitionPlanStatus(self.status),
            approval_request_id=self.approval_request_id or None,
        )

    @classmethod
    def from_domain(cls, plan: PortfolioTransitionPlan) -> PortfolioTransitionPlanModel:
        return cls(
            plan_id=plan.plan_id,
            account_id=plan.account_id,
            source_recommendation_ids=plan.source_recommendation_ids,
            current_positions_snapshot=plan.current_positions_snapshot,
            target_positions_snapshot=plan.target_positions_snapshot,
            orders=[order.to_dict() for order in plan.orders],
            risk_contract=plan.risk_contract,
            summary=plan.summary,
            status=plan.status.value,
            approval_request_id=plan.approval_request_id or "",
            as_of=plan.as_of,
        )


__all__ = ["PortfolioTransitionPlanModel"]
