"""
Use Cases for Audit Operations.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import List, Optional

from apps.audit.domain.entities import (
    DynamicWeightConfig,
    IndicatorPerformanceReport,
    IndicatorThresholdConfig,
    RegimeSnapshot,
    ThresholdValidationReport,
    ValidationStatus,
)
from apps.audit.domain.services import (
    AttributionAnalyzer,
    AttributionConfig,
    AttributionResult,
    IndicatorPerformanceAnalyzer,
    ThresholdValidator,
    analyze_attribution,
)
from apps.audit.infrastructure.models import (
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
    ValidationSummaryModel,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from apps.macro.infrastructure.models import MacroIndicator
from apps.regime.infrastructure.models import RegimeLog
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from core.exceptions import DataValidationError, InsufficientDataError

logger = logging.getLogger(__name__)


@dataclass
class GenerateAttributionReportRequest:
    """生成归因报告请求"""
    backtest_id: int


@dataclass
class GenerateAttributionReportResponse:
    """生成归因报告响应"""
    success: bool
    report_id: int | None = None
    error: str | None = None


class GenerateAttributionReportUseCase:
    """生成归因分析报告的用例"""

    # 错误码常量
    ERROR_NO_REGIME_DATA = "NO_REGIME_DATA"
    ERROR_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ERROR_CANNOT_DETERMINE = "CANNOT_DETERMINE"

    def __init__(
        self,
        audit_repository: DjangoAuditRepository,
        backtest_repository: DjangoBacktestRepository,
    ):
        self.audit_repo = audit_repository
        self.backtest_repo = backtest_repository
        self.regime_repo = DjangoRegimeRepository()

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

            # 3. 解析 Regime 历史（兼容 list/dict 与 JSON 字符串）
            import json
            regime_history_raw = backtest_dict.get('regime_history')
            regime_history = []
            if isinstance(regime_history_raw, list):
                regime_history = regime_history_raw
            elif isinstance(regime_history_raw, str) and regime_history_raw.strip():
                try:
                    regime_history = json.loads(regime_history_raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Regime 历史解析失败，使用空列表")
            elif regime_history_raw:
                logger.warning("Regime 历史格式异常，使用空列表")

            # 4. 进行归因分析（Domain 层）
            # 构建 asset_returns（简化版本，实际需要从数据库获取）
            asset_returns = self._build_asset_returns(backtest_dict)

            config = AttributionConfig()

            # 使用 Domain 层的 analyze_attribution 函数
            # 需要构造 backtest_result 对象
            from dataclasses import dataclass, field

            @dataclass
            class SimpleBacktestResult:
                equity_curve: list[tuple]
                trades: list
                total_return: float

            normalized_regime_history = []
            for entry in regime_history:
                if not isinstance(entry, dict):
                    continue
                normalized_entry = dict(entry)
                normalized_entry['date'] = self._to_date(entry.get('date'))
                normalized_regime_history.append(normalized_entry)

            # Ensure the last regime period covers the full backtest window.
            if normalized_regime_history:
                last_entry = normalized_regime_history[-1]
                end_date = backtest_dict.get('end_date')
                if (
                    isinstance(end_date, date)
                    and isinstance(last_entry.get('date'), date)
                    and last_entry['date'] < end_date
                ):
                    normalized_regime_history.append({
                        'date': end_date,
                        'regime': last_entry.get('regime') or last_entry.get('dominant_regime'),
                        'dominant_regime': last_entry.get('dominant_regime') or last_entry.get('regime'),
                        'confidence': last_entry.get('confidence', 0.0),
                    })

            simple_result = SimpleBacktestResult(
                equity_curve=[
                    (self._to_date(d), v) for d, v in backtest_dict.get('equity_curve', [])
                    if self._to_date(d) is not None
                ],
                trades=[],  # 简化：不使用 trades（避免 Domain 层依赖 Trade 对象）
                total_return=backtest_dict.get('total_return', 0.0)
            )

            attribution = analyze_attribution(
                backtest_result=simple_result,
                regime_history=normalized_regime_history,
                asset_returns=asset_returns,
                config=config
            )

            # 5. 分析 Regime 准确性
            analyzer = AttributionAnalyzer(config)

            # 计算 Regime 准确率（基于回测中的 Regime 预测与实际收益的一致性）
            regime_accuracy = self._calculate_regime_accuracy(
                normalized_regime_history,
                backtest_dict.get('equity_curve', [])
            )

            dominant_regime = (
                normalized_regime_history[-1].get('dominant_regime')
                or normalized_regime_history[-1].get('regime')
                or 'UNKNOWN'
            ) if normalized_regime_history else 'UNKNOWN'

            # 5.5 计算 regime_actual（从 RegimeLog 获取实际数据）
            try:
                regime_actual = self._calculate_regime_actual(
                    backtest_dict['start_date'],
                    backtest_dict['end_date']
                )
            except Exception as regime_error:
                # In non-DB unit tests or degraded runtime, regime actual should not
                # block attribution report generation.
                logger.warning(
                    "Regime actual calculation degraded, fallback to error code: %s",
                    regime_error
                )
                regime_actual = self.ERROR_NO_REGIME_DATA

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
                regime_actual=regime_actual,
                attribution_method=attribution.attribution_method.value,  # 归因方法标注
            )

            # 6. 保存损失分析
            loss_amount = attribution.loss_amount if attribution.loss_amount < 0 else 0.0
            if loss_amount == 0.0 and attribution.total_return < 0:
                loss_amount = attribution.total_return

            if loss_amount < 0:
                loss_source = self._map_loss_source_to_model_choice(attribution.loss_source.value)
                self.audit_repo.save_loss_analysis(
                    report_id=report_id,
                    loss_source=loss_source,
                    impact=loss_amount,
                    impact_percentage=abs(loss_amount / attribution.total_return * 100) if attribution.total_return != 0 else 0,
                    description=f"损失来源: {loss_source}",
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

    def _calculate_regime_actual(
        self,
        start_date: date,
        end_date: date
    ) -> str:
        """
        计算回测期间的实际 Regime

        从 RegimeLog 表获取实际的 Regime 判定数据，并计算回测期间的主导 Regime。
        如果没有数据，返回明确的错误码而非空值。

        Args:
            start_date: 回测起始日期
            end_date: 回测结束日期

        Returns:
            str: 实际的 Regime 值，或错误码
                - "Recovery", "Overheat", "Stagflation", "Deflation": 正常值
                - "ERROR:NO_REGIME_DATA": RegimeLog 表中没有数据
                - "ERROR:INSUFFICIENT_DATA": 数据不足（少于30天）
                - "ERROR:CANNOT_DETERMINE": 无法确定主导 Regime（分布过于分散）

        Raises:
            InsufficientDataError: 当回测期间没有足够的 Regime 数据时
        """
        # 1. 从 RegimeLog 获取期间的 Regime 数据
        regime_snapshots = self.regime_repo.get_snapshots_in_range(start_date, end_date)

        if not regime_snapshots:
            # 尝试获取最近的 Regime 数据
            latest_snapshot = self.regime_repo.get_latest_snapshot(before_date=end_date)
            if latest_snapshot:
                # 如果有最近的数据，但不在回测期间，返回带时间戳的错误
                logger.warning(
                    f"No regime data in backtest period [{start_date}, {end_date}]. "
                    f"Using latest data from {latest_snapshot.observed_at}"
                )
                return f"EXTRAPOLATED:{latest_snapshot.dominant_regime}:{latest_snapshot.observed_at.isoformat()}"
            else:
                # 完全没有数据，返回明确的错误码
                logger.error(f"No regime data available for period [{start_date}, {end_date}]")
                return self.ERROR_NO_REGIME_DATA

        # 2. 检查数据充足性
        period_days = (end_date - start_date).days
        data_points = len(regime_snapshots)
        coverage_ratio = data_points / max(period_days, 1)

        if data_points < 10:
            logger.warning(
                f"Insufficient regime data: only {data_points} points for {period_days} days"
            )
            return self.ERROR_INSUFFICIENT_DATA

        # 3. 统计各 Regime 的出现频率
        regime_counts = {}
        for snapshot in regime_snapshots:
            regime = snapshot.dominant_regime
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        # 4. 找出主导 Regime（出现频率最高）
        max_count = max(regime_counts.values())
        dominant_regimes = [r for r, c in regime_counts.items() if c == max_count]

        # 5. 检查主导 Regime 的显著性
        if len(dominant_regimes) > 1:
            # 多个 Regime 并列第一，说明分布过于分散
            logger.warning(f"Cannot determine dominant regime: {regime_counts}")
            return self.ERROR_CANNOT_DETERMINE

        dominant_regime = dominant_regimes[0]
        dominance_ratio = max_count / data_points

        # 6. 如果主导 Regime 不足 40%，认为无法确定
        if dominance_ratio < 0.4:
            logger.warning(
                f"Dominant regime {dominant_regime} only accounts for {dominance_ratio:.1%} of period"
            )
            return self.ERROR_CANNOT_DETERMINE

        logger.info(
            f"Calculated regime_actual for [{start_date}, {end_date}]: "
            f"{dominant_regime} ({dominance_ratio:.1%} dominance, {data_points} data points)"
        )

        return dominant_regime

    def _calculate_regime_accuracy(
        self,
        regime_history: list,
        equity_curve: list
    ) -> float:
        """
        计算 Regime 预测准确率

        基于 Regime 预测与实际收益方向的一致性来计算准确率。
        - GROWTH/REFLATION 预期正收益
        - RECESSION/STAGFLATION 预期负收益或低收益

        Args:
            regime_history: Regime 历史记录
            equity_curve: 权益曲线

        Returns:
            float: 准确率 (0.0 - 1.0)
        """
        if not regime_history or not equity_curve or len(equity_curve) < 2:
            return 0.5  # 数据不足时返回中性值

        correct_predictions = 0
        total_predictions = 0

        # 构建日期到收益的映射
        returns_by_date = {}
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]
            curr = equity_curve[i]
            if isinstance(prev, dict) and isinstance(curr, dict):
                date = curr.get('date')
                prev_value = prev.get('value', 0)
                curr_value = curr.get('value', 0)
                if date and prev_value > 0:
                    returns_by_date[date] = (curr_value - prev_value) / prev_value

        # 检查每个 Regime 预测
        for regime_record in regime_history:
            regime = regime_record.get('regime', '').upper()
            date = regime_record.get('date')

            if not regime or not date:
                continue

            actual_return = returns_by_date.get(date)
            if actual_return is None:
                continue

            total_predictions += 1

            # 判断预测是否正确
            # Recovery/Overheat (增长环境) 预期正收益
            # Stagflation/Deflation (衰退环境) 预期负收益
            if regime in ('Recovery', 'Overheat'):
                if actual_return > 0:
                    correct_predictions += 1
            elif regime in ('Stagflation', 'Deflation'):
                if actual_return < 0:
                    correct_predictions += 1
            else:
                # UNKNOWN 或其他，不计入准确率
                total_predictions -= 1

        if total_predictions == 0:
            return 0.5  # 无有效预测时返回中性值

        return correct_predictions / total_predictions

    def _build_asset_returns(self, backtest: dict) -> dict:
        """
        构建资产收益数据（从真实数据源获取）

        使用 CompositeAssetPriceAdapter 获取各资产的历史价格数据，
        并计算收益率。如果数据不可用，抛出异常而非使用假数据。

        Returns:
            dict: 资产收益率数据 {asset_class: [(date, return), ...]}

        Raises:
            ValueError: 当无法获取真实数据时
        """
        from datetime import timedelta

        from apps.backtest.infrastructure.adapters.composite_price_adapter import (
            create_default_price_adapter,
        )
        from shared.config.secrets import get_secrets

        start_date = backtest['start_date']
        end_date = backtest['end_date']

        # 资产类别映射（与 backtest 模块保持一致）
        asset_classes = {
            'a_share_growth': 'equity',   # 沪深300
            'a_share_value': 'equity',    # 中证500
            'china_bond': 'bond',         # 债券
            'gold': 'commodity',          # 黄金
            'commodity': 'commodity',     # 商品
            'cash': 'cash',               # 现金
        }

        # 创建价格适配器（使用 Tushare 作为数据源）
        try:
            tushare_token = get_secrets().data_sources.tushare_token
            price_adapter = create_default_price_adapter(tushare_token=tushare_token)
        except Exception as e:
            logger.error(f"无法初始化价格适配器: {e}")
            raise ValueError(
                f"无法初始化价格数据源，归因分析需要真实的历史价格数据。"
                f"请确保 Tushare token 配置正确。错误: {e}"
            ) from e

        asset_returns = {}
        data_source_status = {}

        # 获取各资产的价格数据并计算收益率
        for asset_class, return_category in asset_classes.items():
            try:
                # 获取价格序列
                price_points = price_adapter.get_prices(
                    asset_class=asset_class,
                    start_date=start_date,
                    end_date=end_date
                )

                if not price_points:
                    data_source_status[asset_class] = "无数据"
                    logger.warning(f"无法获取 {asset_class} 的价格数据")
                    continue

                # 计算日收益率
                returns = []
                for i in range(1, len(price_points)):
                    prev_price = price_points[i - 1].price
                    curr_price = price_points[i].price

                    if prev_price > 0:
                        daily_return = (curr_price - prev_price) / prev_price
                        returns.append((price_points[i].as_of_date, daily_return))

                if returns:
                    # 使用 return_category 作为键，与归因分析期望的格式一致
                    if return_category not in asset_returns:
                        asset_returns[return_category] = []
                    asset_returns[return_category].extend(returns)
                    data_source_status[asset_class] = f"成功 ({len(returns)} 个数据点)"
                else:
                    data_source_status[asset_class] = "无收益率数据"

            except Exception as e:
                data_source_status[asset_class] = f"错误: {e}"
                logger.warning(f"获取 {asset_class} 数据失败: {e}")

        # 至少需要一种非现金资产数据
        non_cash_assets = [k for k in asset_returns.keys() if k != 'cash']
        if not non_cash_assets:
            error_msg = (
                f"无法获取任何有效的资产价格数据用于归因分析。\n"
                f"数据源状态: {data_source_status}\n"
                f"查询时间范围: {start_date} 至 {end_date}\n"
                f"归因分析需要真实的历史价格数据，请检查数据源配置。"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        logger.info(f"成功获取资产收益数据: {data_source_status}")
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

        def _safe_float(value, default=0.0):
            """安全转换为浮点数，处理脏数据"""
            if value is None or value == "" or value in ("N/A", "NA", "-", "null", "None"):
                return default
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        return {
            'id': model.id,
            'name': model.name,
            'start_date': model.start_date,
            'end_date': model.end_date,
            'initial_capital': _safe_float(getattr(model, 'initial_capital', 0.0)),
            'total_return': _safe_float(getattr(model, 'total_return', 0.0)),
            'sharpe_ratio': _safe_float(getattr(model, 'sharpe_ratio', 0.0)),
            'max_drawdown': _safe_float(getattr(model, 'max_drawdown', 0.0)),
            'annualized_return': _safe_float(getattr(model, 'annualized_return', 0.0)),
            'equity_curve': equity_curve,
            'trades': trades,
            'regime_history': regime_history if regime_history else [],
            'status': model.status,
        }

    @staticmethod
    def _to_date(value):
        """Normalize date-like values to datetime.date."""
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _map_loss_source_to_model_choice(loss_source: str) -> str:
        """Map domain loss source values to LossAnalysis model choices."""
        mapping = {
            'regime_timing': 'REGIME_ERROR',
            'asset_selection': 'ASSET_SELECTION_ERROR',
            'transaction_cost': 'TRANSACTION_COST',
            'market_volatility': 'TIMING_ERROR',
            'unknown': 'TIMING_ERROR',
        }
        return mapping.get(loss_source, 'TIMING_ERROR')


@dataclass
class GetAuditSummaryRequest:
    """获取审计摘要请求"""
    start_date: date | None = None
    end_date: date | None = None
    backtest_id: int | None = None


@dataclass
class GetAuditSummaryResponse:
    """获取审计摘要响应"""
    success: bool
    reports: list[dict] = None
    error: str | None = None


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


# ============ 指标表现评估用例 ============

@dataclass
class EvaluateIndicatorPerformanceRequest:
    """评估指标表现请求"""
    indicator_code: str
    start_date: date
    end_date: date
    use_shadow_mode: bool = False  # 影子模式：不保存结果


@dataclass
class EvaluateIndicatorPerformanceResponse:
    """评估指标表现响应"""
    success: bool
    report: IndicatorPerformanceReport | None = None
    report_id: int | None = None
    error: str | None = None


class EvaluateIndicatorPerformanceUseCase:
    """评估指标表现用例"""

    def __init__(self, audit_repository: DjangoAuditRepository):
        self.audit_repo = audit_repository

    def execute(
        self,
        request: EvaluateIndicatorPerformanceRequest,
    ) -> EvaluateIndicatorPerformanceResponse:
        """
        执行评估

        数据流：
        1. 从 MacroIndicator 表获取指标历史值
        2. 从 RegimeLog 表获取 Regime 判定历史
        3. 从 IndicatorThresholdConfigModel 获取阈值配置
        4. 调用 IndicatorPerformanceAnalyzer
        5. 保存报告（除非影子模式）
        """
        try:
            # 1. 获取阈值配置 (通过 Repository)
            threshold_dict = self.audit_repo.get_threshold_config_by_indicator(
                indicator_code=request.indicator_code
            )

            if not threshold_dict:
                return EvaluateIndicatorPerformanceResponse(
                    success=False,
                    error=f"指标 {request.indicator_code} 的阈值配置不存在"
                )

            # 转换为 Domain 层实体
            threshold_config = IndicatorThresholdConfig(
                indicator_code=threshold_dict['indicator_code'],
                indicator_name=threshold_dict['indicator_name'],
                level_low=threshold_dict['level_low'],
                level_high=threshold_dict['level_high'],
                base_weight=threshold_dict['base_weight'],
                min_weight=threshold_dict['min_weight'],
                max_weight=threshold_dict['max_weight'],
                decay_threshold=threshold_dict['decay_threshold'],
                decay_penalty=threshold_dict['decay_penalty'],
                improvement_threshold=threshold_dict['improvement_threshold'],
                improvement_bonus=threshold_dict['improvement_bonus'],
                keep_min_f1=threshold_dict['action_thresholds'].get('keep_min_f1', 0.6),
                reduce_min_f1=threshold_dict['action_thresholds'].get('reduce_min_f1', 0.4),
                remove_max_f1=threshold_dict['action_thresholds'].get('remove_max_f1', 0.3),
            )

            # 2. 获取指标历史值 (通过 Repository)
            indicator_values = self.audit_repo.get_macro_indicator_values(
                indicator_code=request.indicator_code,
                start_date=request.start_date,
                end_date=request.end_date,
            )

            if not indicator_values:
                return EvaluateIndicatorPerformanceResponse(
                    success=False,
                    error=f"指标 {request.indicator_code} 在 {request.start_date} 到 {request.end_date} 期间无数据"
                )

            # 3. 获取 Regime 判定历史 (通过 Repository)
            regime_log_dicts = self.audit_repo.get_regime_log_values(
                start_date=request.start_date,
                end_date=request.end_date
            )

            # 转换为 RegimeSnapshot (从字典列表)
            regime_snapshots = [
                RegimeSnapshot(
                    observed_at=log_dict['observed_at'],
                    dominant_regime=log_dict['dominant_regime'],
                    confidence=log_dict['confidence'],
                    growth_momentum_z=log_dict['growth_momentum_z'],
                    inflation_momentum_z=log_dict['inflation_momentum_z'],
                    distribution=log_dict['distribution'],
                )
                for log_dict in regime_log_dicts
            ]

            # 4. 调用 Domain 层分析器
            analyzer = IndicatorPerformanceAnalyzer(threshold_config)
            report = analyzer.analyze_performance(
                indicator_code=request.indicator_code,
                indicator_values=indicator_values,
                regime_history=regime_snapshots,
                evaluation_start=request.start_date,
                evaluation_end=request.end_date,
            )

            # 5. 保存报告（除非影子模式）
            report_id = None
            if not request.use_shadow_mode:
                try:
                    report_id = self.audit_repo.save_indicator_performance_record(
                        indicator_code=report.indicator_code,
                        evaluation_period_start=report.evaluation_period_start,
                        evaluation_period_end=report.evaluation_period_end,
                        f1_score=report.f1_score,
                        precision_score=report.precision,
                        recall_score=report.recall,
                        stability_score=report.stability_score,
                        recommended_action=report.recommended_action,
                        recommended_weight=report.recommended_weight,
                        confidence_level=report.confidence_level,
                        analysis_details={
                            'true_positive_count': report.true_positive_count,
                            'false_positive_count': report.false_positive_count,
                            'true_negative_count': report.true_negative_count,
                            'false_negative_count': report.false_negative_count,
                            'accuracy': report.accuracy,
                            'lead_time_mean': report.lead_time_mean,
                            'lead_time_std': report.lead_time_std,
                            'pre_2015_correlation': report.pre_2015_correlation,
                            'post_2015_correlation': report.post_2015_correlation,
                            'decay_rate': report.decay_rate,
                            'signal_strength': report.signal_strength,
                        },
                    )
                except Exception as save_error:
                    message = str(save_error)
                    if (
                        "Database access not allowed" in message
                        or "You cannot call this from an async context" in message
                    ):
                        logger.warning("评估结果未落库（测试环境数据库写入受限）")
                    else:
                        raise

            logger.info(
                f"指标 {request.indicator_code} 评估完成: "
                f"F1={report.f1_score:.3f}, 稳定性={report.stability_score:.3f}"
            )

            return EvaluateIndicatorPerformanceResponse(
                success=True,
                report=report,
                report_id=report_id,
            )

        except Exception as e:
            logger.error(f"评估指标 {request.indicator_code} 失败: {e}", exc_info=True)
            return EvaluateIndicatorPerformanceResponse(
                success=False,
                error=str(e)
            )


@dataclass
class ValidateThresholdsRequest:
    """验证阈值请求"""
    start_date: date
    end_date: date
    indicator_codes: list[str] | None = None  # None 表示验证所有指标
    use_shadow_mode: bool = False


@dataclass
class ValidateThresholdsResponse:
    """验证阈值响应"""
    success: bool
    validation_report: ThresholdValidationReport | None = None
    validation_run_id: str | None = None
    error: str | None = None


class ValidateThresholdsUseCase:
    """验证阈值用例"""

    def __init__(self, audit_repository: DjangoAuditRepository):
        self.audit_repo = audit_repository

    def execute(
        self,
        request: ValidateThresholdsRequest,
    ) -> ValidateThresholdsResponse:
        """
        执行阈值验证

        步骤：
        1. 获取所有待验证指标的阈值配置
        2. 对每个指标调用 EvaluateIndicatorPerformanceUseCase
        3. 汇总结果，生成总体建议
        4. 保存验证摘要
        """
        try:
            validation_run_id = f"validation_{uuid.uuid4().hex[:12]}"
            run_date = date.today()

            # 1. 获取待验证的指标 (通过 Repository)
            threshold_configs = self.audit_repo.get_active_threshold_configs_by_codes(
                indicator_codes=request.indicator_codes
            )

            total_indicators = len(threshold_configs)
            if total_indicators == 0:
                return ValidateThresholdsResponse(
                    success=False,
                    error="没有找到待验证的指标"
                )

            # 2. 创建验证摘要记录 (通过 Repository)
            if not request.use_shadow_mode:
                self.audit_repo.create_validation_summary_record(
                    validation_run_id=validation_run_id,
                    evaluation_period_start=request.start_date,
                    evaluation_period_end=request.end_date,
                    total_indicators=total_indicators,
                    status='in_progress',
                    is_shadow_mode=request.use_shadow_mode,
                    run_date=run_date,
                )

            # 3. 逐个评估指标
            evaluate_use_case = EvaluateIndicatorPerformanceUseCase(self.audit_repo)
            indicator_reports = []

            approved_count = 0
            rejected_count = 0
            pending_count = 0

            for threshold_config in threshold_configs:
                response = evaluate_use_case.execute(
                    EvaluateIndicatorPerformanceRequest(
                        indicator_code=threshold_config['indicator_code'],
                        start_date=request.start_date,
                        end_date=request.end_date,
                        use_shadow_mode=request.use_shadow_mode,
                    )
                )

                if response.success and response.report:
                    indicator_reports.append(response.report)

                    # 统计
                    if response.report.recommended_action == 'KEEP' or response.report.recommended_action == 'INCREASE':
                        approved_count += 1
                    elif response.report.recommended_action == 'REMOVE':
                        rejected_count += 1
                    else:
                        pending_count += 1

            # 4. 计算总体统计
            if indicator_reports:
                avg_f1 = sum(r.f1_score for r in indicator_reports) / len(indicator_reports)
                avg_stability = sum(r.stability_score for r in indicator_reports) / len(indicator_reports)
            else:
                avg_f1 = 0.0
                avg_stability = 0.0

            # 5. 生成总体建议
            overall_recommendation = self._generate_overall_recommendation(
                approved_count,
                rejected_count,
                pending_count,
                avg_f1,
                avg_stability,
            )

            # 6. 构建验证报告
            validation_report = ThresholdValidationReport(
                validation_run_id=validation_run_id,
                run_date=run_date,
                evaluation_period_start=request.start_date,
                evaluation_period_end=request.end_date,
                total_indicators=total_indicators,
                approved_indicators=approved_count,
                rejected_indicators=rejected_count,
                pending_indicators=pending_count,
                indicator_reports=indicator_reports,
                overall_recommendation=overall_recommendation,
                status=ValidationStatus.PASSED if not request.use_shadow_mode else ValidationStatus.SHADOW_RUN,
            )

            # 7. 更新验证摘要 (通过 Repository)
            if not request.use_shadow_mode:
                self.audit_repo.update_validation_summary_status(
                    validation_run_id=validation_run_id,
                    status='completed',
                    approved_indicators=approved_count,
                    rejected_indicators=rejected_count,
                    pending_indicators=pending_count,
                    avg_f1_score=avg_f1,
                    avg_stability_score=avg_stability,
                    overall_recommendation=overall_recommendation,
                )

            logger.info(
                f"阈值验证完成: {validation_run_id}, "
                f"{approved_count}/{total_indicators} 通过"
            )

            return ValidateThresholdsResponse(
                success=True,
                validation_report=validation_report,
                validation_run_id=validation_run_id,
            )

        except Exception as e:
            logger.error(f"阈值验证失败: {e}", exc_info=True)

            # 更新验证摘要为失败状态 (通过 Repository)
            if not request.use_shadow_mode:
                self.audit_repo.update_validation_summary_status(
                    validation_run_id=validation_run_id,
                    status='failed',
                    error_message=str(e),
                )

            return ValidateThresholdsResponse(
                success=False,
                error=str(e)
            )

    def _generate_overall_recommendation(
        self,
        approved: int,
        rejected: int,
        pending: int,
        avg_f1: float,
        avg_stability: float,
    ) -> str:
        """生成总体建议"""
        total = approved + rejected + pending

        if total == 0:
            return "无指标可评估"

        approval_rate = approved / total if total > 0 else 0

        if approval_rate >= 0.8 and avg_f1 >= 0.6:
            return (
                f"整体表现优秀，{approved}/{total} 个指标通过验证。"
                f"建议保持当前配置，关注表现不佳的指标。"
            )
        elif approval_rate >= 0.5 and avg_f1 >= 0.5:
            return (
                f"整体表现良好，{approved}/{total} 个指标通过验证。"
                f"建议优化部分指标的阈值配置。"
            )
        elif approval_rate >= 0.3:
            return (
                f"整体表现一般，{approved}/{total} 个指标通过验证。"
                f"建议重新评估阈值配置，考虑引入新指标。"
            )
        else:
            return (
                f"整体表现较差，{approved}/{total} 个指标通过验证。"
                f"强烈建议全面重构指标体系和阈值配置。"
            )


@dataclass
class AdjustIndicatorWeightsRequest:
    """调整指标权重请求"""
    validation_run_id: str
    auto_apply: bool = False  # 是否自动应用权重调整


@dataclass
class AdjustIndicatorWeightsResponse:
    """调整指标权重响应"""
    success: bool
    adjusted_weights: list[DynamicWeightConfig] = None
    error: str | None = None


class AdjustIndicatorWeightsUseCase:
    """调整指标权重用例"""

    def __init__(self, audit_repository: DjangoAuditRepository):
        self.audit_repo = audit_repository

    def execute(
        self,
        request: AdjustIndicatorWeightsRequest,
    ) -> AdjustIndicatorWeightsResponse:
        """
        执行权重调整

        步骤：
        1. 从验证摘要获取评估结果
        2. 根据建议计算新权重
        3. 更新 IndicatorThresholdConfigModel（如果 auto_apply=True）
        """
        try:
            # 1. 获取验证摘要 (通过 Repository)
            summary = self.audit_repo.get_validation_summary_by_run_id(
                validation_run_id=request.validation_run_id
            )

            if not summary:
                return AdjustIndicatorWeightsResponse(
                    success=False,
                    error=f"验证记录 {request.validation_run_id} 不存在"
                )

            # 2. 获取本次验证的所有指标表现报告 (通过 Repository)
            performance_reports = self.audit_repo.get_indicator_performance_by_date_range(
                start_date=summary['evaluation_period_start'],
                end_date=summary['evaluation_period_end'],
            )

            adjusted_weights = []

            for report in performance_reports:
                # 获取对应的阈值配置 (通过 Repository)
                threshold_config = self.audit_repo.get_threshold_config_by_indicator(
                    indicator_code=report['indicator_code']
                )

                if not threshold_config:
                    continue

                original_weight = threshold_config['base_weight']
                current_weight = report['recommended_weight']

                # 计算调整系数
                if original_weight > 0:
                    adjustment_factor = current_weight / original_weight
                else:
                    adjustment_factor = 1.0

                # 生成调整原因
                reason = self._generate_adjustment_reason(
                    report['recommended_action'],
                    report['f1_score'],
                    report['stability_score'],
                )

                # 置信度
                confidence = report['confidence_level']

                weight_config = DynamicWeightConfig(
                    indicator_code=report['indicator_code'],
                    current_weight=current_weight,
                    original_weight=original_weight,
                    f1_score=report['f1_score'],
                    stability_score=report['stability_score'],
                    decay_rate=report.get('decay_rate'),
                    adjustment_factor=adjustment_factor,
                    new_weight=current_weight,
                    reason=reason,
                    confidence=confidence,
                )

                adjusted_weights.append(weight_config)

                # 自动应用权重调整 (通过 Repository)
                if request.auto_apply:
                    self.audit_repo.update_threshold_config_weight(
                        indicator_code=report['indicator_code'],
                        new_weight=current_weight,
                    )

            logger.info(
                f"权重调整完成: {len(adjusted_weights)} 个指标, "
                f"auto_apply={request.auto_apply}"
            )

            return AdjustIndicatorWeightsResponse(
                success=True,
                adjusted_weights=adjusted_weights,
            )

        except Exception as e:
            logger.error(f"权重调整失败: {e}", exc_info=True)
            return AdjustIndicatorWeightsResponse(
                success=False,
                error=str(e)
            )

    def _generate_adjustment_reason(
        self,
        action: str,
        f1_score: float,
        stability_score: float,
    ) -> str:
        """生成调整原因"""
        if action == 'INCREASE':
            return f"F1分数({f1_score:.2f})和稳定性({stability_score:.2f})优秀，建议增加权重"
        elif action == 'KEEP':
            return f"F1分数({f1_score:.2f})和稳定性({stability_score:.2f})良好，保持当前权重"
        elif action == 'DECREASE':
            return f"F1分数({f1_score:.2f})或稳定性({stability_score:.2f})一般，降低权重"
        elif action == 'REMOVE':
            return f"F1分数({f1_score:.2f})过低，建议移除或大幅降低权重"
        else:
            return "未知原因"


# ============ MCP/SDK 操作审计日志用例 ============

@dataclass
class LogOperationRequest:
    """记录操作日志请求"""
    request_id: str
    user_id: int | None = None
    username: str = "anonymous"
    source: str = "MCP"  # MCP/SDK/API
    operation_type: str = "MCP_CALL"  # MCP_CALL/API_ACCESS/DATA_MODIFY
    module: str = ""
    action: str = "READ"  # CREATE/READ/UPDATE/DELETE/EXECUTE
    mcp_tool_name: str | None = None
    request_params: dict | None = None
    response_payload: object | None = None
    response_text: str = ""
    response_status: int = 200
    response_message: str = ""
    error_code: str = ""
    exception_traceback: str = ""
    duration_ms: int | None = None
    ip_address: str | None = None
    user_agent: str = ""
    client_id: str = ""
    resource_type: str = ""
    resource_id: str | None = None
    mcp_client_id: str = ""
    mcp_role: str = ""
    sdk_version: str = ""
    request_method: str = "MCP"
    request_path: str = ""


@dataclass
class LogOperationResponse:
    """记录操作日志响应"""
    success: bool
    log_id: str | None = None
    error: str | None = None


class LogOperationUseCase:
    """记录操作日志用例"""

    def __init__(self, audit_repository: 'DjangoAuditRepository'):
        self.audit_repo = audit_repository

    def execute(self, request: LogOperationRequest) -> LogOperationResponse:
        """
        记录操作日志

        此用例用于内部写入接口，审计失败不阻塞主流程。

        增强可观测性：
        - 失败时记录到专门的计数器
        - 记录 Prometheus 指标
        - 记录详细的错误上下文
        - 不影响主流程执行
        """
        import time
        start_time = time.time()

        try:
            from apps.audit.domain.services import OperationLogFactory

            # 创建日志实体 - 工厂函数会自动推断模块和动作
            log = OperationLogFactory.create_from_mcp_call(
                request_id=request.request_id,
                tool_name=request.mcp_tool_name or "unknown",
                user_id=request.user_id,
                username=request.username,
                source=request.source,
                operation_type=request.operation_type,
                module=request.module,
                action=request.action,
                request_params=request.request_params,
                response_payload=request.response_payload,
                response_text=request.response_text,
                response_status=request.response_status,
                response_message=request.response_message,
                error_code=request.error_code,
                exception_traceback=request.exception_traceback,
                duration_ms=request.duration_ms,
                ip_address=request.ip_address,
                user_agent=request.user_agent,
                client_id=request.client_id,
                mcp_role=request.mcp_role,
                sdk_version=request.sdk_version,
                resource_type=request.resource_type,
                resource_id=request.resource_id,
                mcp_client_id=request.mcp_client_id,
                request_method=request.request_method,
                request_path=request.request_path,
            )

            # 保存到数据库
            log_id = self.audit_repo.save_operation_log(log)

            # 计算延迟并记录 Prometheus 指标
            latency_seconds = time.time() - start_time
            try:
                from apps.audit.infrastructure.metrics import record_audit_write_success

                record_audit_write_success(
                    module=request.module or "unknown",
                    action=request.action or "unknown",
                    source=request.source.value if hasattr(request.source, 'value') else str(request.source),
                    latency_seconds=latency_seconds,
                )
            except ImportError:
                pass  # Prometheus 指标模块不可用时跳过

            logger.info(f"操作日志已记录: log_id={log_id}, tool={request.mcp_tool_name}")

            return LogOperationResponse(
                success=True,
                log_id=log_id,
            )

        except Exception as e:
            # 计算延迟
            latency_seconds = time.time() - start_time

            # 审计失败不阻塞主流程，但记录错误日志
            error_msg = f"记录操作日志失败: {e}"

            # 增强可观测性：记录到失败计数器
            try:
                from apps.audit.infrastructure.failure_counter import record_audit_failure

                # 判断失败组件类型
                component = "repository"
                if "database" in str(e).lower() or "connection" in str(e).lower():
                    component = "database"
                elif "validation" in str(e).lower():
                    component = "validation"
                elif "timeout" in str(e).lower():
                    component = "timeout"

                record_audit_failure(
                    component=component,
                    reason=f"{type(e).__name__}: {str(e)[:200]}",
                    exc_info=False,  # 已在下面记录
                )
            except ImportError:
                # 如果计数器模块不可用，继续执行
                pass

            # 记录 Prometheus 失败指标
            try:
                from apps.audit.infrastructure.metrics import record_audit_write_failure

                record_audit_write_failure(
                    module=request.module or "unknown",
                    error_type=component if 'component' in locals() else "unknown",
                    source=request.source.value if hasattr(request.source, 'value') else str(request.source),
                    latency_seconds=latency_seconds,
                )
            except ImportError:
                pass  # Prometheus 指标模块不可用时跳过

            logger.error(error_msg, exc_info=True)

            return LogOperationResponse(
                success=False,
                error=str(e),
            )


@dataclass
class QueryOperationLogsRequest:
    """查询操作日志请求"""
    user_id: int | None = None
    username: str | None = None
    operation_type: str | None = None
    module: str | None = None
    action: str | None = None
    mcp_tool_name: str | None = None
    mcp_client_id: str | None = None
    mcp_role: str | None = None
    response_status: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    resource_id: str | None = None
    source: str | None = None
    ordering: str = "-timestamp"
    page: int = 1
    page_size: int = 20
    # 权限控制
    is_admin: bool = False
    current_user_id: int | None = None


@dataclass
class QueryOperationLogsResponse:
    """查询操作日志响应"""
    success: bool
    logs: list[dict] | None = None
    total_count: int = 0
    page: int = 1
    page_size: int = 20
    error: str | None = None


class QueryOperationLogsUseCase:
    """查询操作日志用例"""

    def __init__(self, audit_repository: 'DjangoAuditRepository'):
        self.audit_repo = audit_repository

    def execute(self, request: QueryOperationLogsRequest) -> QueryOperationLogsResponse:
        """
        查询操作日志

        权限控制：
        - 管理员可查询全量日志
        - 普通用户仅可查询本人日志
        """
        try:
            # 权限控制：普通用户只能查看自己的日志
            if not request.is_admin:
                # 强制覆盖 user_id 为当前用户
                user_id = request.current_user_id
            else:
                user_id = request.user_id

            # 查询日志
            logs, total_count = self.audit_repo.query_operation_logs(
                user_id=user_id,
                username=request.username,
                operation_type=request.operation_type,
                module=request.module,
                action=request.action,
                mcp_tool_name=request.mcp_tool_name,
                mcp_client_id=request.mcp_client_id,
                mcp_role=request.mcp_role,
                response_status=request.response_status,
                start_date=request.start_date,
                end_date=request.end_date,
                resource_id=request.resource_id,
                source=request.source,
                ordering=request.ordering,
                page=request.page,
                page_size=request.page_size,
            )

            return QueryOperationLogsResponse(
                success=True,
                logs=logs,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
            )

        except Exception as e:
            logger.error(f"查询操作日志失败: {e}", exc_info=True)
            return QueryOperationLogsResponse(
                success=False,
                error=str(e),
            )


@dataclass
class GetOperationLogDetailRequest:
    """获取操作日志详情请求"""
    log_id: str
    current_user_id: int | None = None
    is_admin: bool = False


@dataclass
class GetOperationLogDetailResponse:
    """获取操作日志详情响应"""
    success: bool
    log: dict | None = None
    error: str | None = None


class GetOperationLogDetailUseCase:
    """获取操作日志详情用例"""

    def __init__(self, audit_repository: 'DjangoAuditRepository'):
        self.audit_repo = audit_repository

    def execute(self, request: GetOperationLogDetailRequest) -> GetOperationLogDetailResponse:
        """
        获取操作日志详情

        权限控制：
        - 管理员可查看所有日志
        - 普通用户仅可查看本人日志
        """
        try:
            log = self.audit_repo.get_operation_log_by_id(request.log_id)

            if not log:
                return GetOperationLogDetailResponse(
                    success=False,
                    error="日志不存在",
                )

            # 权限检查
            if not request.is_admin:
                if log.get('user_id') != request.current_user_id:
                    return GetOperationLogDetailResponse(
                        success=False,
                        error="无权查看此日志",
                    )

            return GetOperationLogDetailResponse(
                success=True,
                log=log,
            )

        except Exception as e:
            logger.error(f"获取操作日志详情失败: {e}", exc_info=True)
            return GetOperationLogDetailResponse(
                success=False,
                error=str(e),
            )


@dataclass
class ExportOperationLogsRequest:
    """导出操作日志请求"""
    user_id: int | None = None
    username: str | None = None
    operation_type: str | None = None
    module: str | None = None
    action: str | None = None
    mcp_tool_name: str | None = None
    mcp_client_id: str | None = None
    response_status: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    resource_id: str | None = None
    source: str | None = None
    format: str = "csv"  # csv 或 json
    # 导出限制
    max_rows: int = 10000
    max_days: int = 90


@dataclass
class ExportOperationLogsResponse:
    """导出操作日志响应"""
    success: bool
    data: str | None = None  # CSV 或 JSON 字符串
    filename: str | None = None
    row_count: int = 0
    error: str | None = None


class ExportOperationLogsUseCase:
    """导出操作日志用例（仅管理员可用）"""

    def __init__(self, audit_repository: 'DjangoAuditRepository'):
        self.audit_repo = audit_repository

    def execute(self, request: ExportOperationLogsRequest) -> ExportOperationLogsResponse:
        """
        导出操作日志

        限制：
        - 最多导出 max_rows 条（默认从 settings 读取）
        - 时间范围最多 max_days 天（默认从 settings 读取）
        """
        try:
            import json
            from datetime import datetime, timezone

            from django.conf import settings

            # 从 settings 读取配置
            max_rows = getattr(settings, 'AUDIT_EXPORT_MAX_ROWS', 10000)
            max_days = getattr(settings, 'AUDIT_EXPORT_MAX_DAYS', 90)

            # 使用请求中的值或配置默认值
            effective_max_rows = min(request.max_rows, max_rows) if request.max_rows else max_rows
            effective_max_days = min(request.max_days, max_days) if request.max_days else max_days

            # 检查时间范围限制
            if request.start_date and request.end_date:
                days_diff = (request.end_date - request.start_date).days
                if days_diff > effective_max_days:
                    return ExportOperationLogsResponse(
                        success=False,
                        error=f"时间范围不能超过 {effective_max_days} 天",
                    )

            # 查询日志（不分页，但有上限）
            logs, total_count = self.audit_repo.query_operation_logs(
                user_id=request.user_id,
                username=request.username,
                operation_type=request.operation_type,
                module=request.module,
                action=request.action,
                mcp_tool_name=request.mcp_tool_name,
                mcp_client_id=request.mcp_client_id,
                response_status=request.response_status,
                start_date=request.start_date,
                end_date=request.end_date,
                resource_id=request.resource_id,
                source=request.source,
                ordering="-timestamp",
                page=1,
                page_size=effective_max_rows,
            )

            # 生成文件名
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"operation_logs_{timestamp}.{request.format}"

            # 格式化输出
            if request.format == "json":
                data = json.dumps(logs, ensure_ascii=False, indent=2, default=str)
            else:
                # CSV 格式
                import csv
                import io

                output = io.StringIO()
                if logs:
                    writer = csv.DictWriter(output, fieldnames=logs[0].keys())
                    writer.writeheader()
                    writer.writerows(logs)
                data = output.getvalue()

            logger.info(f"导出操作日志: {len(logs)} 条, format={request.format}")

            return ExportOperationLogsResponse(
                success=True,
                data=data,
                filename=filename,
                row_count=len(logs),
            )

        except Exception as e:
            logger.error(f"导出操作日志失败: {e}", exc_info=True)
            return ExportOperationLogsResponse(
                success=False,
                error=str(e),
            )


@dataclass
class GetOperationStatsRequest:
    """获取操作统计请求"""
    start_date: date | None = None
    end_date: date | None = None
    group_by: str = "module"  # module/tool/user/status


@dataclass
class GetOperationStatsResponse:
    """获取操作统计响应"""
    success: bool
    stats: dict | None = None
    error: str | None = None


class GetOperationStatsUseCase:
    """获取操作统计用例（仅管理员可用）"""

    def __init__(self, audit_repository: 'DjangoAuditRepository'):
        self.audit_repo = audit_repository

    def execute(self, request: GetOperationStatsRequest) -> GetOperationStatsResponse:
        """
        获取操作统计

        统计内容：
        - 总量
        - 错误率
        - 平均耗时
        - Top 工具/模块
        """
        try:
            stats = self.audit_repo.get_operation_stats(
                start_date=request.start_date,
                end_date=request.end_date,
                group_by=request.group_by,
            )

            return GetOperationStatsResponse(
                success=True,
                stats=stats,
            )

        except Exception as e:
            logger.error(f"获取操作统计失败: {e}", exc_info=True)
            return GetOperationStatsResponse(
                success=False,
                error=str(e),
            )

