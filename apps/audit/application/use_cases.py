"""
Use Cases for Audit Operations.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import date
import logging

from apps.audit.domain.services import (
    AttributionAnalyzer,
    analyze_attribution,
    AttributionConfig,
    AttributionResult,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository

logger = logging.getLogger(__name__)


@dataclass
class GenerateAttributionReportRequest:
    """生成归因报告请求"""
    backtest_id: int


@dataclass
class GenerateAttributionReportResponse:
    """生成归因报告响应"""
    success: bool
    report_id: Optional[int] = None
    error: Optional[str] = None


class GenerateAttributionReportUseCase:
    """生成归因分析报告的用例"""

    def __init__(
        self,
        audit_repository: DjangoAuditRepository,
        backtest_repository: DjangoBacktestRepository,
    ):
        self.audit_repo = audit_repository
        self.backtest_repo = backtest_repository

    def execute(
        self,
        request: GenerateAttributionReportRequest
    ) -> GenerateAttributionReportResponse:
        """执行归因分析"""
        try:
            # 1. 获取回测结果
            backtest_model = self.backtest_repo.get_backtest_by_id(request.backtest_id)
            if not backtest_model:
                return GenerateAttributionReportResponse(
                    success=False,
                    error=f"回测 {request.backtest_id} 不存在"
                )

            # 2. 将 ORM 对象转换为字典
            backtest_dict = self._backtest_model_to_dict(backtest_model)

            # 3. 解析 Regime 历史（从 JSON 字符串）
            import json
            regime_history = []
            if backtest_dict.get('regime_history'):
                try:
                    regime_history = json.loads(backtest_dict['regime_history'])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Regime 历史解析失败，使用空列表")

            # 4. 进行归因分析（Domain 层）
            # 构建 asset_returns（简化版本，实际需要从数据库获取）
            asset_returns = self._build_asset_returns(backtest_dict)

            config = AttributionConfig()

            # 使用 Domain 层的 analyze_attribution 函数
            # 需要构造 backtest_result 对象
            from dataclasses import dataclass, field

            @dataclass
            class SimpleBacktestResult:
                equity_curve: List[tuple]
                trades: List
                total_return: float

            simple_result = SimpleBacktestResult(
                equity_curve=[(d, v) for d, v in backtest_dict.get('equity_curve', [])],
                trades=[],  # 简化：不使用 trades（避免 Domain 层依赖 Trade 对象）
                total_return=backtest_dict.get('total_return', 0.0)
            )

            attribution = analyze_attribution(
                backtest_result=simple_result,
                regime_history=regime_history,
                asset_returns=asset_returns,
                config=config
            )

            # 5. 分析 Regime 准确性（简化版本）
            analyzer = AttributionAnalyzer(config)
            # TODO: 需要实际的市场数据来验证准确率
            regime_accuracy = 0.75  # 默认值
            dominant_regime = regime_history[-1].get('dominant_regime', 'UNKNOWN') if regime_history else 'UNKNOWN'

            # 6. 保存归因报告
            report_id = self.audit_repo.save_attribution_report(
                backtest_id=request.backtest_id,
                period_start=backtest_dict['start_date'],
                period_end=backtest_dict['end_date'],
                regime_timing_pnl=attribution.regime_timing_pnl,
                asset_selection_pnl=attribution.asset_selection_pnl,
                interaction_pnl=attribution.interaction_pnl,
                total_pnl=attribution.total_return,
                regime_accuracy=regime_accuracy,
                regime_predicted=dominant_regime,
                regime_actual=None,  # TODO: 需要实际数据
            )

            # 6. 保存损失分析
            if attribution.loss_amount < 0:
                self.audit_repo.save_loss_analysis(
                    report_id=report_id,
                    loss_source=attribution.loss_source.value,
                    impact=attribution.loss_amount,
                    impact_percentage=abs(attribution.loss_amount / attribution.total_return * 100) if attribution.total_return != 0 else 0,
                    description=f"损失来源: {attribution.loss_source.value}",
                    improvement_suggestion="; ".join(attribution.improvement_suggestions[:3]),
                )

            # 7. 保存经验总结
            self.audit_repo.save_experience_summary(
                report_id=report_id,
                lesson=attribution.lesson_learned,
                recommendation="; ".join(attribution.improvement_suggestions),
                priority='HIGH' if attribution.loss_amount < -0.05 else 'MEDIUM',
            )

            logger.info(f"归因报告生成成功: report_id={report_id}")

            return GenerateAttributionReportResponse(
                success=True,
                report_id=report_id
            )

        except Exception as e:
            logger.error(f"归因分析失败: {e}", exc_info=True)
            return GenerateAttributionReportResponse(
                success=False,
                error=str(e)
            )

    def _build_asset_returns(self, backtest: dict) -> dict:
        """
        构建资产收益数据（简化版本）

        实际应从数据库获取各资产的历史收益
        """
        # 简化版本：基于回测结果推算
        from datetime import timedelta

        start_date = backtest['start_date']
        end_date = backtest['end_date']

        # 生成每日收益（模拟数据）
        days = (end_date - start_date).days
        dates = [start_date + timedelta(days=i) for i in range(days + 1)]

        # 简化：为每个资产类别生成模拟收益
        asset_classes = ['bond', 'equity', 'commodity', 'cash']
        asset_returns = {}

        for asset in asset_classes:
            # 生成随机收益（实际应从数据库获取）
            import random
            random.seed(42)  # 固定种子确保可重复

            returns = []
            for i in range(1, len(dates)):
                daily_return = random.gauss(0.0005, 0.01)  # 日收益均值0.05%，标准差1%
                returns.append((dates[i], daily_return))

            asset_returns[asset] = returns

        return asset_returns

    def _backtest_model_to_dict(self, model) -> dict:
        """
        将 BacktestResultModel 转换为字典

        Args:
            model: BacktestResultModel ORM 对象

        Returns:
            dict: 回测数据字典
        """
        import json

        # 解析 JSON 字段
        equity_curve = []
        regime_history = []

        if model.equity_curve:
            try:
                equity_curve = json.loads(model.equity_curve)
            except (json.JSONDecodeError, TypeError):
                pass

        if model.regime_history:
            try:
                regime_history = json.loads(model.regime_history)
            except (json.JSONDecodeError, TypeError):
                pass

        # trades 字段是 JSONField，直接是列表
        trades = model.trades if model.trades else []

        return {
            'id': model.id,
            'name': model.name,
            'start_date': model.start_date,
            'end_date': model.end_date,
            'initial_capital': float(model.initial_capital),
            'total_return': model.total_return or 0.0,
            'sharpe_ratio': model.sharpe_ratio or 0.0,
            'max_drawdown': model.max_drawdown or 0.0,
            'annualized_return': model.annualized_return or 0.0,
            'equity_curve': equity_curve,
            'trades': trades,
            'regime_history': regime_history if regime_history else [],
            'status': model.status,
        }


@dataclass
class GetAuditSummaryRequest:
    """获取审计摘要请求"""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    backtest_id: Optional[int] = None


@dataclass
class GetAuditSummaryResponse:
    """获取审计摘要响应"""
    success: bool
    reports: List[dict] = None
    error: Optional[str] = None


class GetAuditSummaryUseCase:
    """获取审计摘要的用例"""

    def __init__(self, audit_repository: DjangoAuditRepository):
        self.audit_repo = audit_repository

    def execute(
        self,
        request: GetAuditSummaryRequest
    ) -> GetAuditSummaryResponse:
        """获取审计摘要"""
        try:
            if request.backtest_id:
                reports = self.audit_repo.get_reports_by_backtest(
                    request.backtest_id
                )
            elif request.start_date and request.end_date:
                reports = self.audit_repo.get_reports_by_date_range(
                    request.start_date,
                    request.end_date
                )
            else:
                return GetAuditSummaryResponse(
                    success=False,
                    error="必须提供 backtest_id 或 start_date + end_date"
                )

            # 补充损失分析和经验总结
            for report in reports:
                report['loss_analyses'] = self.audit_repo.get_loss_analyses(
                    report['id']
                )
                report['experience_summaries'] = self.audit_repo.get_experience_summaries(
                    report['id']
                )

            return GetAuditSummaryResponse(
                success=True,
                reports=reports
            )

        except Exception as e:
            logger.error(f"获取审计摘要失败: {e}", exc_info=True)
            return GetAuditSummaryResponse(
                success=False,
                error=str(e)
            )
