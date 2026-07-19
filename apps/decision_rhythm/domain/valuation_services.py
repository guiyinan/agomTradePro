"""
Valuation pricing and execution approval domain services for Decision Rhythm.

估值快照创建、投资建议聚合与执行审批业务逻辑。

仅使用 Python 标准库。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from .entities import (
    ApprovalStatus,
    ExecutionApprovalRequest,
    InvestmentRecommendation,
    ValuationSnapshot,
    create_valuation_snapshot,
)
from .workflow_services import ApprovalStatusStateMachine


class ValuationSnapshotService:
    """
    估值快照服务

    提供估值快照的创建和管理功能。

    Example:
        >>> service = ValuationSnapshotService()
        >>> snapshot = service.create_from_comprehensive_valuation(
        ...     stock_code="000001.SH",
        ...     valuation_result=comprehensive_result,
        ...     current_price=Decimal("10.80"),
        ... )
    """

    # 止损比例（入场价下方）
    DEFAULT_STOP_LOSS_PCT = 0.10  # 10%

    # 目标收益比例（入场价上方）
    DEFAULT_TARGET_UPSIDE_PCT = 0.20  # 20%

    # 入场价格容差
    ENTRY_PRICE_TOLERANCE = 0.05  # 5%

    def create_snapshot(
        self,
        security_code: str,
        valuation_method: str,
        fair_value: Decimal,
        current_price: Decimal,
        input_parameters: dict[str, Any],
        stop_loss_pct: float | None = None,
        target_upside_pct: float | None = None,
    ) -> ValuationSnapshot:
        """
        创建估值快照

        Args:
            security_code: 证券代码
            valuation_method: 估值方法
            fair_value: 公允价值
            current_price: 当前价格
            input_parameters: 输入参数
            stop_loss_pct: 止损比例（默认 10%）
            target_upside_pct: 目标收益比例（默认 20%）

        Returns:
            ValuationSnapshot 实例
        """
        stop_loss_pct = stop_loss_pct or self.DEFAULT_STOP_LOSS_PCT
        target_upside_pct = target_upside_pct or self.DEFAULT_TARGET_UPSIDE_PCT

        # 计算入场价格区间（基于公允价值和容差）
        entry_price_low = fair_value * Decimal(str(1 - self.ENTRY_PRICE_TOLERANCE))
        entry_price_high = fair_value * Decimal(str(1 + self.ENTRY_PRICE_TOLERANCE))

        # 如果当前价格低于公允价值，扩大入场区间
        if current_price < fair_value:
            entry_price_high = max(entry_price_high, current_price * Decimal("1.02"))
            entry_price_low = min(entry_price_low, current_price * Decimal("0.98"))

        # 计算目标价格区间
        target_price_low = fair_value * Decimal(str(1 + target_upside_pct * 0.8))
        target_price_high = fair_value * Decimal(str(1 + target_upside_pct * 1.2))

        # 计算止损价格
        stop_loss_price = entry_price_low * Decimal(str(1 - stop_loss_pct))

        return create_valuation_snapshot(
            security_code=security_code,
            valuation_method=valuation_method,
            fair_value=fair_value,
            entry_price_low=entry_price_low,
            entry_price_high=entry_price_high,
            target_price_low=target_price_low,
            target_price_high=target_price_high,
            stop_loss_price=stop_loss_price,
            input_parameters=input_parameters,
        )

    def create_from_comprehensive_valuation(
        self,
        stock_code: str,
        valuation_result,  # ComprehensiveValuationResult
        current_price: Decimal,
    ) -> ValuationSnapshot:
        """
        从综合估值结果创建快照

        Args:
            stock_code: 股票代码
            valuation_result: 综合估值结果
            current_price: 当前价格

        Returns:
            ValuationSnapshot 实例
        """
        # 将综合评分转换为公允价值
        # 评分越高，公允价值相对当前价格的溢价越高
        score = valuation_result.overall_score
        if score >= 80:
            # 强烈低估：公允价值 = 当前价格 * 1.3
            fair_value_multiplier = 1.3
        elif score >= 60:
            # 中度低估：公允价值 = 当前价格 * 1.15
            fair_value_multiplier = 1.15
        elif score >= 40:
            # 合理：公允价值 = 当前价格
            fair_value_multiplier = 1.0
        else:
            # 高估：公允价值 = 当前价格 * 0.9
            fair_value_multiplier = 0.9

        fair_value = current_price * Decimal(str(fair_value_multiplier))

        # 提取输入参数
        input_parameters = {
            "overall_score": score,
            "overall_signal": valuation_result.overall_signal,
            "confidence": valuation_result.confidence,
            "scores": [
                {"method": s.method, "score": s.score, "signal": s.signal}
                for s in valuation_result.scores
            ],
        }

        return self.create_snapshot(
            security_code=stock_code,
            valuation_method="COMPOSITE",
            fair_value=fair_value,
            current_price=current_price,
            input_parameters=input_parameters,
        )

    def create_legacy_snapshot(
        self,
        security_code: str,
        estimated_fair_value: Decimal,
        current_price: Decimal,
    ) -> ValuationSnapshot:
        """
        创建历史数据的估值快照

        用于数据迁移，为历史建议创建缺失的估值快照。

        Args:
            security_code: 证券代码
            estimated_fair_value: 估算的公允价值
            current_price: 当前价格

        Returns:
            ValuationSnapshot 实例（标记为 legacy）
        """
        # 历史数据使用保守的参数
        snapshot = self.create_snapshot(
            security_code=security_code,
            valuation_method="LEGACY",
            fair_value=estimated_fair_value or current_price,
            current_price=current_price,
            input_parameters={"source": "legacy_migration"},
        )
        return replace(snapshot, is_legacy=True)

    def create_current_price_fallback_snapshot(
        self,
        security_code: str,
        current_price: Decimal,
        *,
        source: str = "current_price",
    ) -> ValuationSnapshot:
        """
        Create a conservative valuation snapshot from the latest observable price.

        This is only a fallback for recommendation contracts when no formal
        valuation is available; it must stay explicitly marked as FALLBACK.
        """
        return create_valuation_snapshot(
            security_code=security_code,
            valuation_method="FALLBACK",
            fair_value=current_price,
            entry_price_low=current_price * Decimal("0.95"),
            entry_price_high=current_price * Decimal("1.02"),
            target_price_low=current_price * Decimal("1.15"),
            target_price_high=current_price * Decimal("1.25"),
            stop_loss_price=current_price * Decimal("0.90"),
            input_parameters={
                "source": source,
                "fallback_type": "current_price_based",
                "fair_value_formula": "current_price",
                "entry_band": "current_price * 0.95..1.02",
                "target_band": "current_price * 1.15..1.25",
                "stop_loss": "current_price * 0.90",
            },
        )


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
        fair_value = (
            sum(rec.fair_value * rec.position_size_pct for rec in recommendations) / total_weight
            if total_weight > 0
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

    def __init__(self):
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
