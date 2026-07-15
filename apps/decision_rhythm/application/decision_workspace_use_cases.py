"""Decision workspace valuation, preview, and approval use cases."""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError

from apps.events.domain.entities import EventType, create_event

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)

RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


@dataclass
class CreateValuationSnapshotRequest:
    """
    创建估值快照请求

    Attributes:
        security_code: 证券代码
        valuation_method: 估值方法
        fair_value: 公允价值
        current_price: 当前价格
        input_parameters: 输入参数
        stop_loss_pct: 止损比例（可选）
        target_upside_pct: 目标收益比例（可选）
    """

    security_code: str
    valuation_method: str
    fair_value: float
    current_price: float
    input_parameters: dict[str, Any]
    stop_loss_pct: float | None = None
    target_upside_pct: float | None = None


@dataclass
class CreateValuationSnapshotResponse:
    """
    创建估值快照响应

    Attributes:
        success: 是否成功
        snapshot: 估值快照实体
        error: 错误信息
    """

    success: bool
    snapshot: Any | None = None  # ValuationSnapshot
    error: str | None = None


@dataclass
class GetAggregatedWorkspaceRequest:
    """
    获取聚合工作台请求

    Attributes:
        account_id: 账户 ID（可选，不传则获取全部）
        include_executed: 是否包含已执行的建议
    """

    account_id: str | None = None
    include_executed: bool = False


@dataclass
class GetAggregatedWorkspaceResponse:
    """
    获取聚合工作台响应

    Attributes:
        success: 是否成功
        aggregated_recommendations: 聚合后的建议列表
        regime_context: Regime 上下文
        error: 错误信息
    """

    success: bool
    aggregated_recommendations: list[dict[str, Any]] = field(default_factory=list)
    regime_context: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class PreviewExecutionRequest:
    """
    预览执行请求

    Attributes:
        recommendation_id: 投资建议 ID
        account_id: 账户 ID
        market_price: 当前市场价格
    """

    recommendation_id: str
    account_id: str
    market_price: float


@dataclass
class PreviewExecutionResponse:
    """
    预览执行响应

    Attributes:
        success: 是否成功
        preview: 执行预览详情
        risk_checks: 风控检查结果
        error: 错误信息
    """

    success: bool
    preview: dict[str, Any] | None = None
    risk_checks: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ApproveExecutionRequest:
    """
    批准执行请求

    Attributes:
        approval_request_id: 执行审批请求 ID
        reviewer_comments: 审批评论
        market_price: 当前市场价格
    """

    approval_request_id: str
    reviewer_comments: str
    market_price: float | None = None


@dataclass
class ApproveExecutionResponse:
    """
    批准执行响应

    Attributes:
        success: 是否成功
        approval_request: 更新后的执行审批请求
        error: 错误信息
    """

    success: bool
    approval_request: Any | None = None  # ExecutionApprovalRequest
    error: str | None = None


@dataclass
class RejectExecutionRequest:
    """
    拒绝执行请求

    Attributes:
        approval_request_id: 执行审批请求 ID
        reviewer_comments: 拒绝原因
    """

    approval_request_id: str
    reviewer_comments: str


@dataclass
class RejectExecutionResponse:
    """
    拒绝执行响应

    Attributes:
        success: 是否成功
        approval_request: 更新后的执行审批请求
        error: 错误信息
    """

    success: bool
    approval_request: Any | None = None  # ExecutionApprovalRequest
    error: str | None = None


class CreateValuationSnapshotUseCase:
    """
    创建估值快照用例

    为指定证券创建估值快照。

    Attributes:
        valuation_snapshot_repo: 估值快照仓储
        valuation_service: 估值快照服务

    Example:
        >>> use_case = CreateValuationSnapshotUseCase(repo, service)
        >>> response = use_case.execute(CreateValuationSnapshotRequest(
        ...     security_code="000001.SH",
        ...     valuation_method="COMPOSITE",
        ...     fair_value=12.50,
        ...     current_price=10.80,
        ...     input_parameters={"pe_percentile": 0.15},
        ... ))
    """

    def __init__(self, valuation_snapshot_repo, valuation_service=None):
        """
        初始化用例

        Args:
            valuation_snapshot_repo: 估值快照仓储
            valuation_service: 估值快照服务（可选）
        """
        self.valuation_snapshot_repo = valuation_snapshot_repo
        self.valuation_service = valuation_service

    def execute(self, request: CreateValuationSnapshotRequest) -> CreateValuationSnapshotResponse:
        """
        执行创建估值快照

        Args:
            request: 创建请求

        Returns:
            创建响应
        """
        try:
            from decimal import Decimal

            from ..domain.entities import create_valuation_snapshot

            # 创建估值快照
            snapshot = create_valuation_snapshot(
                security_code=request.security_code,
                valuation_method=request.valuation_method,
                fair_value=Decimal(str(request.fair_value)),
                entry_price_low=Decimal(str(request.fair_value * 0.95)),
                entry_price_high=Decimal(str(request.fair_value * 1.05)),
                target_price_low=Decimal(str(request.fair_value * 1.15)),
                target_price_high=Decimal(str(request.fair_value * 1.25)),
                stop_loss_price=Decimal(str(request.current_price * 0.90)),
                input_parameters=request.input_parameters,
            )

            # 保存到仓储
            self.valuation_snapshot_repo.save(snapshot)

            logger.info(
                f"Valuation snapshot created: {snapshot.snapshot_id} for {request.security_code}"
            )

            return CreateValuationSnapshotResponse(
                success=True,
                snapshot=snapshot,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to create valuation snapshot: {e}", exc_info=True)
            return CreateValuationSnapshotResponse(
                success=False,
                error=str(e),
            )


class GetAggregatedWorkspaceUseCase:
    """
    获取聚合工作台用例

    获取按账户+证券+方向聚合后的投资建议列表。

    Attributes:
        recommendation_repo: 投资建议仓储
        consolidation_service: 建议聚合服务
        regime_provider: Regime 提供器

    Example:
        >>> use_case = GetAggregatedWorkspaceUseCase(repo, service, regime_provider)
        >>> response = use_case.execute(GetAggregatedWorkspaceRequest(account_id="account_1"))
    """

    def __init__(
        self,
        recommendation_repo,
        consolidation_service=None,
        regime_provider=None,
    ):
        """
        初始化用例

        Args:
            recommendation_repo: 投资建议仓储
            consolidation_service: 建议聚合服务（可选）
            regime_provider: Regime 提供器（可选）
        """
        self.recommendation_repo = recommendation_repo
        self.consolidation_service = consolidation_service
        self.regime_provider = regime_provider

    def execute(self, request: GetAggregatedWorkspaceRequest) -> GetAggregatedWorkspaceResponse:
        """
        执行获取聚合工作台

        Args:
            request: 获取请求

        Returns:
            聚合工作台响应
        """
        try:
            from ..domain.services import RecommendationConsolidationService

            # 获取活跃建议
            if request.account_id:
                recommendations = self.recommendation_repo.get_active_by_account(
                    account_id=request.account_id,
                    include_executed=request.include_executed,
                )
            else:
                recommendations = self.recommendation_repo.get_all_active(
                    include_executed=request.include_executed,
                )

            # 聚合建议
            if self.consolidation_service:
                consolidation_service = self.consolidation_service
            else:
                consolidation_service = RecommendationConsolidationService()

            # 按账户分组聚合
            account_groups: dict[str, list[Any]] = {}
            for rec in recommendations:
                # 从 recommendation 中提取账户信息
                # 这里简化处理，实际应该从关联关系获取
                account_id = getattr(rec, "account_id", "default")
                if account_id not in account_groups:
                    account_groups[account_id] = []
                account_groups[account_id].append(rec)

            aggregated = []
            for account_id, recs in account_groups.items():
                consolidated_recs = consolidation_service.consolidate(recs, account_id)
                for rec in consolidated_recs:
                    aggregated.append(self._format_recommendation(rec, account_id))

            # 获取 Regime 上下文
            regime_context = None
            if self.regime_provider:
                try:
                    regime_context = {
                        "current_regime": self.regime_provider.get_current_regime(),
                        "confidence": self.regime_provider.get_regime_confidence(),
                        "source": getattr(self.regime_provider, "source", "UNKNOWN"),
                    }
                except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                    logger.warning(f"Failed to get regime context: {e}")

            return GetAggregatedWorkspaceResponse(
                success=True,
                aggregated_recommendations=aggregated,
                regime_context=regime_context,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to get aggregated workspace: {e}", exc_info=True)
            return GetAggregatedWorkspaceResponse(
                success=False,
                error=str(e),
            )

    def _format_recommendation(self, rec, account_id: str) -> dict[str, Any]:
        """格式化建议为 API 响应格式"""
        return {
            "aggregation_key": f"{account_id}:{rec.security_code}:{rec.side}",
            "security_code": rec.security_code,
            "security_name": getattr(rec, "security_name", rec.security_code),
            "side": rec.side,
            "confidence": rec.confidence,
            "valuation_snapshot_id": rec.valuation_snapshot_id,
            "price_range": {
                "entry_low": float(rec.entry_price_low),
                "entry_high": float(rec.entry_price_high),
                "target_low": float(rec.target_price_low),
                "target_high": float(rec.target_price_high),
                "stop_loss": float(rec.stop_loss_price),
            },
            "position_suggestion": {
                "suggested_pct": rec.position_size_pct,
                "suggested_quantity": rec.suggested_quantity,
                "max_capital": float(rec.max_capital),
            },
            "risk_checks": {},  # 将在 PreviewExecution 中填充
            "source_recommendation_ids": rec.source_recommendation_ids,
            "reason_codes": rec.reason_codes,
            "human_readable_rationale": rec.human_readable_rationale,
            "regime_source": getattr(rec, "regime_source", "UNKNOWN"),
        }


class PreviewExecutionUseCase:
    """
    预览执行用例

    在审批前预览执行详情，包括风控检查。

    Attributes:
        recommendation_repo: 投资建议仓储
        approval_repo: 执行审批仓储
        quota_repo: 配额仓储
        cooldown_repo: 冷却期仓储
        regime_provider: Regime 提供器

    Example:
        >>> use_case = PreviewExecutionUseCase(...)
        >>> response = use_case.execute(PreviewExecutionRequest(
        ...     recommendation_id="rec_001",
        ...     account_id="account_1",
        ...     market_price=10.80,
        ... ))
    """

    def __init__(
        self,
        recommendation_repo,
        approval_repo,
        quota_repo=None,
        cooldown_repo=None,
        regime_provider=None,
    ):
        """
        初始化用例

        Args:
            recommendation_repo: 投资建议仓储
            approval_repo: 执行审批仓储
            quota_repo: 配额仓储（可选）
            cooldown_repo: 冷却期仓储（可选）
            regime_provider: Regime 提供器（可选）
        """
        self.recommendation_repo = recommendation_repo
        self.approval_repo = approval_repo
        self.quota_repo = quota_repo
        self.cooldown_repo = cooldown_repo
        self.regime_provider = regime_provider

    def execute(self, request: PreviewExecutionRequest) -> PreviewExecutionResponse:
        """
        执行预览

        Args:
            request: 预览请求

        Returns:
            预览响应
        """
        try:
            from decimal import Decimal

            from ..domain.entities import create_execution_approval_request

            # 获取投资建议
            recommendation = self.recommendation_repo.get_by_id(request.recommendation_id)
            if recommendation is None:
                return PreviewExecutionResponse(
                    success=False,
                    error=f"投资建议不存在: {request.recommendation_id}",
                )

            # 执行风控检查
            risk_checks = self._run_risk_checks(
                recommendation=recommendation,
                market_price=Decimal(str(request.market_price)),
            )

            # 获取 Regime 来源
            regime_source = "UNKNOWN"
            if self.regime_provider:
                try:
                    regime_source = getattr(self.regime_provider, "source", "V2_CALCULATION")
                except (AttributeError, RuntimeError, TypeError):
                    regime_source = "UNKNOWN"

            # 创建预览审批请求（DRAFT 状态）
            approval_request = create_execution_approval_request(
                recommendation=recommendation,
                account_id=request.account_id,
                risk_check_results=risk_checks,
                regime_source=regime_source,
                market_price_at_review=Decimal(str(request.market_price)),
            )

            # 构建预览详情
            preview = {
                "recommendation_id": recommendation.recommendation_id,
                "security_code": recommendation.security_code,
                "side": recommendation.side,
                "confidence": recommendation.confidence,
                "suggested_quantity": approval_request.suggested_quantity,
                "market_price": request.market_price,
                "price_range": {
                    "entry_low": float(recommendation.entry_price_low),
                    "entry_high": float(recommendation.entry_price_high),
                    "target_low": float(recommendation.target_price_low),
                    "target_high": float(recommendation.target_price_high),
                    "stop_loss": float(recommendation.stop_loss_price),
                },
                "position_suggestion": {
                    "suggested_pct": recommendation.position_size_pct,
                    "suggested_quantity": recommendation.suggested_quantity,
                    "max_capital": float(recommendation.max_capital),
                },
                "regime_source": regime_source,
            }

            return PreviewExecutionResponse(
                success=True,
                preview=preview,
                risk_checks=risk_checks,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to preview execution: {e}", exc_info=True)
            return PreviewExecutionResponse(
                success=False,
                error=str(e),
            )

    def _run_risk_checks(
        self,
        recommendation,
        market_price,
    ) -> dict[str, Any]:
        """执行风控检查"""
        risk_checks = {}

        # 1. 价格验证
        if recommendation.is_buy:
            price_valid = market_price <= recommendation.entry_price_high
            risk_checks["price_validation"] = {
                "passed": price_valid,
                "reason": (
                    ""
                    if price_valid
                    else f"市场价格 {market_price} 高于入场上限 {recommendation.entry_price_high}"
                ),
            }
        else:
            price_valid = True  # SELL 不限制价格
            risk_checks["price_validation"] = {
                "passed": True,
                "reason": "",
            }

        # 2. 配额检查
        if self.quota_repo:
            try:
                from ..domain.entities import QuotaPeriod

                quota = self.quota_repo.get_quota(QuotaPeriod.WEEKLY)
                quota_ok = quota and not quota.is_quota_exceeded
                risk_checks["quota"] = {
                    "passed": quota_ok,
                    "remaining": quota.remaining_decisions if quota else 0,
                    "reason": "" if quota_ok else "配额已耗尽",
                }
            except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                risk_checks["quota"] = {"passed": True, "reason": f"检查失败（跳过）: {e}"}
        else:
            risk_checks["quota"] = {"passed": True, "reason": "未配置"}

        # 3. 冷却期检查
        if self.cooldown_repo:
            try:
                cooldown = self.cooldown_repo.get_active_cooldown(recommendation.security_code)
                cooldown_ok = not cooldown or cooldown.is_decision_ready
                risk_checks["cooldown"] = {
                    "passed": cooldown_ok,
                    "hours_remaining": cooldown.decision_ready_in_hours if cooldown else 0,
                    "reason": (
                        ""
                        if cooldown_ok
                        else f"冷却期内，剩余 {cooldown.decision_ready_in_hours:.1f} 小时"
                    ),
                }
            except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                risk_checks["cooldown"] = {"passed": True, "reason": f"检查失败（跳过）: {e}"}
        else:
            risk_checks["cooldown"] = {"passed": True, "reason": "未配置"}

        return risk_checks


class ApproveExecutionUseCase:
    """
    批准执行用例

    批准执行审批请求。

    Attributes:
        approval_repo: 执行审批仓储
        approval_service: 执行审批服务
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = ApproveExecutionUseCase(repo, service)
        >>> response = use_case.execute(ApproveExecutionRequest(
        ...     approval_request_id="apr_001",
        ...     reviewer_comments="审批通过",
        ...     market_price=10.80,
        ... ))
    """

    def __init__(self, approval_repo, approval_service=None, event_bus=None):
        """
        初始化用例

        Args:
            approval_repo: 执行审批仓储
            approval_service: 执行审批服务（可选）
            event_bus: 事件总线（可选）
        """
        self.approval_repo = approval_repo
        self.approval_service = approval_service
        self.event_bus = event_bus

    def execute(self, request: ApproveExecutionRequest) -> ApproveExecutionResponse:
        """
        执行批准

        Args:
            request: 批准请求

        Returns:
            批准响应
        """
        try:
            from decimal import Decimal

            from ..domain.services import ExecutionApprovalService

            # 获取审批请求
            approval_request = self.approval_repo.get_by_id(request.approval_request_id)
            if approval_request is None:
                return ApproveExecutionResponse(
                    success=False,
                    error=f"审批请求不存在: {request.approval_request_id}",
                )

            # 获取或创建审批服务
            if self.approval_service:
                approval_service = self.approval_service
            else:
                approval_service = ExecutionApprovalService()

            # 市场价格
            market_price = Decimal(str(request.market_price)) if request.market_price else None

            # 检查是否可以批准
            if market_price:
                can_approve, reason = approval_service.can_approve(approval_request, market_price)
                if not can_approve:
                    return ApproveExecutionResponse(
                        success=False,
                        error=f"无法批准: {reason}",
                    )

            # 执行批准
            updated_request = approval_service.approve(
                approval_request=approval_request,
                reviewer_comments=request.reviewer_comments,
                market_price=market_price,
            )

            # 保存更新
            self.approval_repo.save(updated_request)

            # 发布事件
            if self.event_bus:
                event = create_event(
                    event_type=EventType.DECISION_APPROVED,
                    payload={
                        "approval_request_id": updated_request.request_id,
                        "recommendation_id": updated_request.recommendation_id,
                        "security_code": updated_request.security_code,
                        "side": updated_request.side,
                        "reviewer_comments": request.reviewer_comments,
                    },
                )
                self.event_bus.publish(event)

            logger.info(f"Execution approved: {updated_request.request_id}")

            return ApproveExecutionResponse(
                success=True,
                approval_request=updated_request,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to approve execution: {e}", exc_info=True)
            return ApproveExecutionResponse(
                success=False,
                error=str(e),
            )


class RejectExecutionUseCase:
    """
    拒绝执行用例

    拒绝执行审批请求。

    Attributes:
        approval_repo: 执行审批仓储
        approval_service: 执行审批服务
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = RejectExecutionUseCase(repo, service)
        >>> response = use_case.execute(RejectExecutionRequest(
        ...     approval_request_id="apr_001",
        ...     reviewer_comments="风险过高",
        ... ))
    """

    def __init__(self, approval_repo, approval_service=None, event_bus=None):
        """
        初始化用例

        Args:
            approval_repo: 执行审批仓储
            approval_service: 执行审批服务（可选）
            event_bus: 事件总线（可选）
        """
        self.approval_repo = approval_repo
        self.approval_service = approval_service
        self.event_bus = event_bus

    def execute(self, request: RejectExecutionRequest) -> RejectExecutionResponse:
        """
        执行拒绝

        Args:
            request: 拒绝请求

        Returns:
            拒绝响应
        """
        try:
            from ..domain.services import ExecutionApprovalService

            # 获取审批请求
            approval_request = self.approval_repo.get_by_id(request.approval_request_id)
            if approval_request is None:
                return RejectExecutionResponse(
                    success=False,
                    error=f"审批请求不存在: {request.approval_request_id}",
                )

            # 获取或创建审批服务
            if self.approval_service:
                approval_service = self.approval_service
            else:
                approval_service = ExecutionApprovalService()

            # 执行拒绝
            updated_request = approval_service.reject(
                approval_request=approval_request,
                reviewer_comments=request.reviewer_comments,
            )

            # 保存更新
            self.approval_repo.save(updated_request)

            # 发布事件
            if self.event_bus:
                event = create_event(
                    event_type=EventType.DECISION_REJECTED,
                    payload={
                        "approval_request_id": updated_request.request_id,
                        "recommendation_id": updated_request.recommendation_id,
                        "security_code": updated_request.security_code,
                        "side": updated_request.side,
                        "rejection_reason": request.reviewer_comments,
                    },
                )
                self.event_bus.publish(event)

            logger.info(f"Execution rejected: {updated_request.request_id}")

            return RejectExecutionResponse(
                success=True,
                approval_request=updated_request,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to reject execution: {e}", exc_info=True)
            return RejectExecutionResponse(
                success=False,
                error=str(e),
            )


__all__ = [
    "CreateValuationSnapshotRequest",
    "CreateValuationSnapshotResponse",
    "GetAggregatedWorkspaceRequest",
    "GetAggregatedWorkspaceResponse",
    "PreviewExecutionRequest",
    "PreviewExecutionResponse",
    "ApproveExecutionRequest",
    "ApproveExecutionResponse",
    "RejectExecutionRequest",
    "RejectExecutionResponse",
    "CreateValuationSnapshotUseCase",
    "GetAggregatedWorkspaceUseCase",
    "PreviewExecutionUseCase",
    "ApproveExecutionUseCase",
    "RejectExecutionUseCase",
]
