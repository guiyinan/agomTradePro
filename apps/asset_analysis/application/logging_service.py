"""
资产分析模块 - 日志记录服务

本模块负责记录评分日志和告警。
"""

import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.utils import timezone

from apps.asset_analysis.application.repository_provider import (
    get_asset_analysis_log_repository,
)
from apps.asset_analysis.domain.entities import AssetScore
from apps.asset_analysis.domain.value_objects import ScoreContext, WeightConfig

logger = logging.getLogger(__name__)


@dataclass
class ScoringLogEntry:
    """评分日志条目"""
    asset_type: str
    request_source: str
    user_id: int | None = None
    regime: str = ""
    policy_level: str = ""
    sentiment_index: float = 0.0
    active_signals_count: int = 0
    weight_config_name: str = ""
    regime_weight: float = 0.0
    policy_weight: float = 0.0
    sentiment_weight: float = 0.0
    signal_weight: float = 0.0
    filters: dict[str, Any] = field(default_factory=dict)
    total_assets: int = 0
    scored_assets: int = 0
    filtered_assets: int = 0
    execution_time_ms: int | None = None
    cache_hit: bool = False
    status: str = "success"
    error_message: str | None = None


class ScoringLogger:
    """
    评分日志记录器

    负责记录每次评分操作的详细信息。
    """

    def __init__(self, repository=None):
        """初始化日志记录器"""
        self.logger = logging.getLogger(__name__)
        self.repository = repository or get_asset_analysis_log_repository()

    def log_scoring(
        self,
        entry: ScoringLogEntry,
    ) -> int | None:
        """
        记录评分日志

        Args:
            entry: 评分日志条目

        Returns:
            日志记录ID，如果记录失败则返回 None
        """
        try:
            log_id = self.repository.create_scoring_log(
                {
                    "asset_type": entry.asset_type,
                    "request_source": entry.request_source,
                    "user_id": entry.user_id,
                    "regime": entry.regime,
                    "policy_level": entry.policy_level,
                    "sentiment_index": entry.sentiment_index,
                    "active_signals_count": entry.active_signals_count,
                    "weight_config_name": entry.weight_config_name,
                    "regime_weight": entry.regime_weight,
                    "policy_weight": entry.policy_weight,
                    "sentiment_weight": entry.sentiment_weight,
                    "signal_weight": entry.signal_weight,
                    "filters": entry.filters,
                    "total_assets": entry.total_assets,
                    "scored_assets": entry.scored_assets,
                    "filtered_assets": entry.filtered_assets,
                    "execution_time_ms": entry.execution_time_ms,
                    "cache_hit": entry.cache_hit,
                    "status": entry.status,
                    "error_message": entry.error_message,
                }
            )

            self.logger.info(
                f"评分日志已记录: {entry.asset_type} - {entry.status} - "
                f"筛选 {entry.filtered_assets}/{entry.total_assets} 资产"
            )
            return log_id

        except Exception as e:
            self.logger.error(f"记录评分日志失败: {str(e)}")
            return None

    def log_scoring_from_context(
        self,
        asset_type: str,
        request_source: str,
        context: ScoreContext,
        weights: WeightConfig,
        filters: dict[str, Any],
        total_assets: int,
        filtered_assets: int,
        execution_time_ms: int | None = None,
        user_id: int | None = None,
        status: str = "success",
        error_message: str | None = None,
    ) -> int | None:
        """
        从评分上下文记录日志

        Args:
            asset_type: 资产类型
            request_source: 请求来源
            context: 评分上下文
            weights: 权重配置
            filters: 筛选条件
            total_assets: 总资产数
            filtered_assets: 筛选后资产数
            execution_time_ms: 执行时间（毫秒）
            user_id: 用户ID
            status: 状态
            error_message: 错误信息

        Returns:
            日志记录ID，如果记录失败则返回 None
        """
        entry = ScoringLogEntry(
            asset_type=asset_type,
            request_source=request_source,
            user_id=user_id,
            regime=context.current_regime,
            policy_level=context.policy_level,
            sentiment_index=context.sentiment_index,
            active_signals_count=len(context.active_signals),
            weight_config_name=weights.__class__.__name__,
            regime_weight=weights.regime_weight,
            policy_weight=weights.policy_weight,
            sentiment_weight=weights.sentiment_weight,
            signal_weight=weights.signal_weight,
            filters=filters,
            total_assets=total_assets,
            scored_assets=total_assets,  # 假设所有资产都进行了评分
            filtered_assets=filtered_assets,
            execution_time_ms=execution_time_ms,
            status=status,
            error_message=error_message,
        )

        return self.log_scoring(entry)


class AlertService:
    """
    告警服务

    负责创建和管理告警。
    """

    def __init__(self, repository=None):
        """初始化告警服务"""
        self.logger = logging.getLogger(__name__)
        self.repository = repository or get_asset_analysis_log_repository()

    def create_alert(
        self,
        severity: str,
        alert_type: str,
        title: str,
        message: str,
        asset_type: str | None = None,
        asset_code: str | None = None,
        context: dict[str, Any] | None = None,
        stack_trace: str | None = None,
    ) -> int | None:
        """
        创建告警

        Args:
            severity: 严重程度 (info/warning/error/critical)
            alert_type: 告警类型
            title: 告警标题
            message: 告警消息
            asset_type: 相关资产类型
            asset_code: 相关资产代码
            context: 上下文信息
            stack_trace: 堆栈跟踪

        Returns:
            告警ID，如果创建失败则返回 None
        """
        try:
            alert_id = self.repository.create_alert(
                {
                    "severity": severity,
                    "alert_type": alert_type,
                    "title": title,
                    "message": message,
                    "asset_type": asset_type,
                    "asset_code": asset_code,
                    "context": context or {},
                    "stack_trace": stack_trace,
                }
            )

            self.logger.warning(
                f"告警已创建: [{severity.upper()}] {title}"
            )

            return alert_id

        except Exception as e:
            self.logger.error(f"创建告警失败: {str(e)}")
            return None

    def create_scoring_error_alert(
        self,
        asset_type: str,
        error_message: str,
        context: dict[str, Any] | None = None,
        stack_trace: str | None = None,
    ) -> int | None:
        """
        创建评分错误告警

        Args:
            asset_type: 资产类型
            error_message: 错误消息
            context: 上下文信息
            stack_trace: 堆栈跟踪

        Returns:
            告警ID
        """
        return self.create_alert(
            severity="error",
            alert_type="scoring_error",
            title=f"资产评分错误: {asset_type}",
            message=error_message,
            asset_type=asset_type,
            context=context,
            stack_trace=stack_trace,
        )

    def create_weight_config_error_alert(
        self,
        asset_type: str,
        error_message: str,
        context: dict[str, Any] | None = None,
    ) -> int | None:
        """
        创建权重配置错误告警

        Args:
            asset_type: 资产类型
            error_message: 错误消息
            context: 上下文信息

        Returns:
            告警ID
        """
        return self.create_alert(
            severity="critical",
            alert_type="weight_config_error",
            title=f"权重配置错误: {asset_type}",
            message=error_message,
            asset_type=asset_type,
            context=context,
        )

    def create_performance_alert(
        self,
        asset_type: str,
        execution_time_ms: int,
        threshold_ms: int = 5000,
        context: dict[str, Any] | None = None,
    ) -> int | None:
        """
        创建性能告警

        Args:
            asset_type: 资产类型
            execution_time_ms: 实际执行时间（毫秒）
            threshold_ms: 阈值（毫秒）
            context: 上下文信息

        Returns:
            告警ID
        """
        if execution_time_ms < threshold_ms:
            return None

        return self.create_alert(
            severity="warning",
            alert_type="performance_issue",
            title=f"性能问题: {asset_type} 评分耗时 {execution_time_ms}ms",
            message=f"{asset_type} 资产评分耗时 {execution_time_ms}ms，超过阈值 {threshold_ms}ms",
            asset_type=asset_type,
            context={
                **(context or {}),
                "execution_time_ms": execution_time_ms,
                "threshold_ms": threshold_ms,
            },
        )

    def create_data_quality_alert(
        self,
        asset_type: str,
        issue_description: str,
        asset_code: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> int | None:
        """
        创建数据质量问题告警

        Args:
            asset_type: 资产类型
            issue_description: 问题描述
            asset_code: 资产代码
            context: 上下文信息

        Returns:
            告警ID
        """
        return self.create_alert(
            severity="warning",
            alert_type="data_quality_issue",
            title=f"数据质量问题: {asset_type}",
            message=issue_description,
            asset_type=asset_type,
            asset_code=asset_code,
            context=context,
        )

    def create_api_failure_alert(
        self,
        api_name: str,
        error_message: str,
        context: dict[str, Any] | None = None,
        stack_trace: str | None = None,
    ) -> int | None:
        """
        创建 API 调用失败告警

        Args:
            api_name: API 名称
            error_message: 错误消息
            context: 上下文信息
            stack_trace: 堆栈跟踪

        Returns:
            告警ID
        """
        return self.create_alert(
            severity="error",
            alert_type="api_failure",
            title=f"API 调用失败: {api_name}",
            message=error_message,
            context=context,
            stack_trace=stack_trace,
        )

    def get_unresolved_alerts(
        self,
        severity: str | None = None,
        alert_type: str | None = None,
        limit: int = 100,
    ) -> list:
        """
        获取未解决的告警

        Args:
            severity: 严重程度过滤
            alert_type: 告警类型过滤
            limit: 返回数量限制

        Returns:
            告警列表
        """
        return self.repository.list_unresolved_alerts(
            severity=severity,
            alert_type=alert_type,
            limit=limit,
        )

    def resolve_alert(
        self,
        alert_id: int,
        resolved_by: int,
        resolution_notes: str | None = None,
    ) -> bool:
        """
        解决告警

        Args:
            alert_id: 告警ID
            resolved_by: 解决人ID
            resolution_notes: 解决备注

        Returns:
            是否成功解决
        """
        try:
            success = self.repository.resolve_alert(
                alert_id=alert_id,
                resolved_by=resolved_by,
                resolved_at=timezone.now(),
                resolution_notes=resolution_notes,
            )
            if not success:
                self.logger.error(f"告警不存在: {alert_id}")
                return False

            self.logger.info(f"告警已解决: {alert_id}")
            return True

        except Exception as e:
            self.logger.error(f"解决告警失败: {str(e)}")
            return False

