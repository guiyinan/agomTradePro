"""
Valuation pricing and execution approval domain services for Decision Rhythm.

估值快照创建、投资建议聚合与执行审批业务逻辑。

仅使用 Python 标准库。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from apps.valuation.domain.services import ValuationSnapshotService

from .entities import (
    ApprovalStatus,
    ExecutionApprovalRequest,
    InvestmentRecommendation,
)
from .workflow_services import ApprovalStatusStateMachine


class RecommendationConsolidationService:
    """
    建议聚合服务

    按账户+证券代码+方向聚合多个投资建议。

    聚合规则：
    1. 相同 (account_id, security_code, side) 的建议归并为一条
    2. 置信度取加权平均（按 position_size_pct 加权）
    3. 价格区间取并集（扩大范围）
    4. reason_codes 取并集
    5. source_recommendation_ids 保留所有来源

    Example:
        >>> service = RecommendationConsolidationService()
        >>> aggregated = service.consolidate(recommendations, account_id="account_1")
    """

    def consolidate(
        self,
        recommendations: list[InvestmentRecommendation],
        account_id: str,
    ) -> list[InvestmentRecommendation]:
        """
        聚合投资建议

        Args:
            recommendations: 投资建议列表
            account_id: 账户 ID

        Returns:
            聚合后的建议列表
        """
        if not recommendations:
            return []

        # 按 (security_code, side) 分组
        groups: dict[str, list[InvestmentRecommendation]] = {}
        for rec in recommendations:
            key = f"{rec.security_code}:{rec.side}"
            if key not in groups:
                groups[key] = []
            groups[key].append(rec)

        # 对每个分组进行聚合
        consolidated = []
        for _key, group in groups.items():
            if len(group) == 1:
                consolidated.append(group[0])
            else:
                merged = self._merge_recommendations(group, account_id)
                consolidated.append(merged)

        return consolidated

    def _merge_recommendations(
        self,
        recommendations: list[InvestmentRecommendation],
        account_id: str,
    ) -> InvestmentRecommendation:
        """
        合并多条建议

        Args:
            recommendations: 建议列表（同一 security_code 和 side）
            account_id: 账户 ID

        Returns:
            合并后的建议
        """
        first = recommendations[0]

        # 加权平均置信度
        total_weight = sum(rec.position_size_pct for rec in recommendations)
        if total_weight > 0:
            weighted_confidence = (
                sum(rec.confidence * rec.position_size_pct for rec in recommendations)
                / total_weight
            )
        else:
            weighted_confidence = sum(rec.confidence for rec in recommendations) / len(
                recommendations
            )

        # 价格区间取并集（扩大范围）
        entry_price_low = min(rec.entry_price_low for rec in recommendations)
        entry_price_high = max(rec.entry_price_high for rec in recommendations)
        target_price_low = min(rec.target_price_low for rec in recommendations)
        target_price_high = max(rec.target_price_high for rec in recommendations)
        stop_loss_price = max(
            rec.stop_loss_price for rec in recommendations
        )  # 止损价取最高（最保守）

        # 公允价值取加权平均
        decimal_weight = sum(
            (Decimal(str(rec.position_size_pct)) for rec in recommendations),
            Decimal("0"),
        )
        fair_value = (
            sum(
                (rec.fair_value * Decimal(str(rec.position_size_pct)) for rec in recommendations),
                Decimal("0"),
            )
            / decimal_weight
            if decimal_weight > 0
            else first.fair_value
        )

        # 仓位比例累加（但有上限）
        total_position_pct = min(
            sum(rec.position_size_pct for rec in recommendations),
            20.0,  # 单只股票最大 20% 仓位
        )

        # 最大资金取最大值
        max_capital = max(rec.max_capital for rec in recommendations)

        # reason_codes 取并集
        all_reason_codes = []
        for rec in recommendations:
            for code in rec.reason_codes:
                if code not in all_reason_codes:
                    all_reason_codes.append(code)

        # source_recommendation_ids 收集所有
        all_source_ids = []
        for rec in recommendations:
            all_source_ids.append(rec.recommendation_id)
            all_source_ids.extend(rec.source_recommendation_ids)

        # 合并人类可读理由
        rationales = [
            rec.human_readable_rationale for rec in recommendations if rec.human_readable_rationale
        ]
        merged_rationale = " | ".join(rationales[:3])  # 最多取 3 条
        if len(rationales) > 3:
            merged_rationale += f" ... (共 {len(rationales)} 条理由)"

        return InvestmentRecommendation(
            recommendation_id=f"rec_merged_{uuid4().hex[:8]}",
            security_code=first.security_code,
            side=first.side,
            confidence=round(weighted_confidence, 3),
            valuation_method="CONSOLIDATED",
            fair_value=fair_value,
            entry_price_low=entry_price_low,
            entry_price_high=entry_price_high,
            target_price_low=target_price_low,
            target_price_high=target_price_high,
            stop_loss_price=stop_loss_price,
            position_size_pct=total_position_pct,
            max_capital=max_capital,
            reason_codes=all_reason_codes,
            human_readable_rationale=merged_rationale,
            account_id=account_id,
            valuation_snapshot_id=first.valuation_snapshot_id,  # 使用第一条的快照
            source_recommendation_ids=all_source_ids,
            created_at=datetime.now(UTC),
            status="CONSOLIDATED",
        )


class ExecutionApprovalService:
    """
    执行审批服务

    处理执行审批的业务逻辑。

    Example:
        >>> service = ExecutionApprovalService()
        >>> result = service.approve(approval_request, reviewer_comments="审批通过")
    """

    def __init__(self) -> None:
        self.state_machine = ApprovalStatusStateMachine()

    def can_approve(
        self,
        approval_request: ExecutionApprovalRequest,
        market_price: Decimal,
    ) -> tuple[bool, str]:
        """
        检查是否可以批准执行

        Args:
            approval_request: 执行审批请求
            market_price: 当前市场价格

        Returns:
            (是否可以批准, 原因)
        """
        # 检查状态
        if not approval_request.is_pending:
            return (
                False,
                f"审批状态不是 PENDING，当前状态: {approval_request.approval_status.value}",
            )

        # 检查价格
        price_valid, price_reason = approval_request.validate_price_for_approval(market_price)
        if not price_valid:
            return False, price_reason

        # 检查风控
        risk_checks = approval_request.risk_check_results
        for check_name, check_result in risk_checks.items():
            if isinstance(check_result, dict) and not check_result.get("passed", True):
                return False, f"风控检查未通过: {check_name} - {check_result.get('reason', '')}"

        return True, "可以批准"

    def approve(
        self,
        approval_request: ExecutionApprovalRequest,
        reviewer_comments: str,
        market_price: Decimal | None = None,
    ) -> ExecutionApprovalRequest:
        """
        批准执行

        Args:
            approval_request: 执行审批请求
            reviewer_comments: 审批评论
            market_price: 当前市场价格（可选）

        Returns:
            更新后的 ExecutionApprovalRequest
        """
        # 验证状态迁移
        can_transition, reason = self.state_machine.validate_transition(
            approval_request.approval_status, ApprovalStatus.APPROVED
        )
        if not can_transition:
            raise ValueError(reason)

        return ExecutionApprovalRequest(
            request_id=approval_request.request_id,
            recommendation_id=approval_request.recommendation_id,
            plan_id=approval_request.plan_id,
            account_id=approval_request.account_id,
            security_code=approval_request.security_code,
            side=approval_request.side,
            approval_status=ApprovalStatus.APPROVED,
            suggested_quantity=approval_request.suggested_quantity,
            market_price_at_review=market_price or approval_request.market_price_at_review,
            price_range_low=approval_request.price_range_low,
            price_range_high=approval_request.price_range_high,
            stop_loss_price=approval_request.stop_loss_price,
            risk_check_results=approval_request.risk_check_results,
            reviewer_comments=reviewer_comments,
            regime_source=approval_request.regime_source,
            created_at=approval_request.created_at,
            reviewed_at=datetime.now(UTC),
            executed_at=None,
        )

    def reject(
        self,
        approval_request: ExecutionApprovalRequest,
        reviewer_comments: str,
    ) -> ExecutionApprovalRequest:
        """
        拒绝执行

        Args:
            approval_request: 执行审批请求
            reviewer_comments: 拒绝原因

        Returns:
            更新后的 ExecutionApprovalRequest
        """
        # 验证状态迁移
        can_transition, reason = self.state_machine.validate_transition(
            approval_request.approval_status, ApprovalStatus.REJECTED
        )
        if not can_transition:
            raise ValueError(reason)

        return ExecutionApprovalRequest(
            request_id=approval_request.request_id,
            recommendation_id=approval_request.recommendation_id,
            plan_id=approval_request.plan_id,
            account_id=approval_request.account_id,
            security_code=approval_request.security_code,
            side=approval_request.side,
            approval_status=ApprovalStatus.REJECTED,
            suggested_quantity=approval_request.suggested_quantity,
            market_price_at_review=approval_request.market_price_at_review,
            price_range_low=approval_request.price_range_low,
            price_range_high=approval_request.price_range_high,
            stop_loss_price=approval_request.stop_loss_price,
            risk_check_results=approval_request.risk_check_results,
            reviewer_comments=reviewer_comments,
            regime_source=approval_request.regime_source,
            created_at=approval_request.created_at,
            reviewed_at=datetime.now(UTC),
            executed_at=None,
        )

    def mark_executed(
        self,
        approval_request: ExecutionApprovalRequest,
    ) -> ExecutionApprovalRequest:
        """
        标记为已执行

        Args:
            approval_request: 执行审批请求

        Returns:
            更新后的 ExecutionApprovalRequest
        """
        # 验证状态迁移
        can_transition, reason = self.state_machine.validate_transition(
            approval_request.approval_status, ApprovalStatus.EXECUTED
        )
        if not can_transition:
            raise ValueError(reason)

        return ExecutionApprovalRequest(
            request_id=approval_request.request_id,
            recommendation_id=approval_request.recommendation_id,
            plan_id=approval_request.plan_id,
            account_id=approval_request.account_id,
            security_code=approval_request.security_code,
            side=approval_request.side,
            approval_status=ApprovalStatus.EXECUTED,
            suggested_quantity=approval_request.suggested_quantity,
            market_price_at_review=approval_request.market_price_at_review,
            price_range_low=approval_request.price_range_low,
            price_range_high=approval_request.price_range_high,
            stop_loss_price=approval_request.stop_loss_price,
            risk_check_results=approval_request.risk_check_results,
            reviewer_comments=approval_request.reviewer_comments,
            regime_source=approval_request.regime_source,
            created_at=approval_request.created_at,
            reviewed_at=approval_request.reviewed_at,
            executed_at=datetime.now(UTC),
        )

    def mark_failed(
        self,
        approval_request: ExecutionApprovalRequest,
        error_message: str,
    ) -> ExecutionApprovalRequest:
        """
        标记为执行失败

        Args:
            approval_request: 执行审批请求
            error_message: 错误信息

        Returns:
            更新后的 ExecutionApprovalRequest
        """
        # 验证状态迁移
        can_transition, reason = self.state_machine.validate_transition(
            approval_request.approval_status, ApprovalStatus.FAILED
        )
        if not can_transition:
            raise ValueError(reason)

        # 更新风控结果记录错误
        updated_risk_checks = dict(approval_request.risk_check_results)
        updated_risk_checks["execution_error"] = {
            "passed": False,
            "reason": error_message,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return ExecutionApprovalRequest(
            request_id=approval_request.request_id,
            recommendation_id=approval_request.recommendation_id,
            plan_id=approval_request.plan_id,
            account_id=approval_request.account_id,
            security_code=approval_request.security_code,
            side=approval_request.side,
            approval_status=ApprovalStatus.FAILED,
            suggested_quantity=approval_request.suggested_quantity,
            market_price_at_review=approval_request.market_price_at_review,
            price_range_low=approval_request.price_range_low,
            price_range_high=approval_request.price_range_high,
            stop_loss_price=approval_request.stop_loss_price,
            risk_check_results=updated_risk_checks,
            reviewer_comments=approval_request.reviewer_comments,
            regime_source=approval_request.regime_source,
            created_at=approval_request.created_at,
            reviewed_at=approval_request.reviewed_at,
            executed_at=None,
        )


__all__ = [
    "ExecutionApprovalService",
    "RecommendationConsolidationService",
    "ValuationSnapshotService",
]
