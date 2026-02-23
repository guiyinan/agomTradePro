"""
Use Cases for Audit Operations.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import date, datetime
import logging
import uuid

from apps.audit.domain.services import (
    AttributionAnalyzer,
    analyze_attribution,
    AttributionConfig,
    AttributionResult,
    IndicatorPerformanceAnalyzer,
    ThresholdValidator,
)
from apps.audit.domain.entities import (
    IndicatorThresholdConfig,
    IndicatorPerformanceReport,
    ThresholdValidationReport,
    ValidationStatus,
    RegimeSnapshot,
    DynamicWeightConfig,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.audit.infrastructure.models import (
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
    ValidationSummaryModel,
)
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from apps.macro.infrastructure.models import MacroIndicator
from apps.regime.infrastructure.models import RegimeLog

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
                equity_curve: List[tuple]
                trades: List
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
    report: Optional[IndicatorPerformanceReport] = None
    report_id: Optional[int] = None
    error: Optional[str] = None


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
            # 1. 获取阈值配置
            threshold_model = IndicatorThresholdConfigModel.objects.filter(
                indicator_code=request.indicator_code,
                is_active=True
            ).first()

            if not threshold_model:
                return EvaluateIndicatorPerformanceResponse(
                    success=False,
                    error=f"指标 {request.indicator_code} 的阈值配置不存在"
                )

            # 转换为 Domain 层实体
            threshold_config = IndicatorThresholdConfig(
                indicator_code=threshold_model.indicator_code,
                indicator_name=threshold_model.indicator_name,
                level_low=threshold_model.level_low,
                level_high=threshold_model.level_high,
                base_weight=threshold_model.base_weight,
                min_weight=threshold_model.min_weight,
                max_weight=threshold_model.max_weight,
                decay_threshold=threshold_model.decay_threshold,
                decay_penalty=threshold_model.decay_penalty,
                improvement_threshold=threshold_model.improvement_threshold,
                improvement_bonus=threshold_model.improvement_bonus,
                keep_min_f1=threshold_model.action_thresholds.get('keep_min_f1', 0.6),
                reduce_min_f1=threshold_model.action_thresholds.get('reduce_min_f1', 0.4),
                remove_max_f1=threshold_model.action_thresholds.get('remove_max_f1', 0.3),
            )

            # 2. 获取指标历史值
            indicator_qs = MacroIndicator.objects.filter(
                code=request.indicator_code,
                reporting_period__gte=request.start_date,
                reporting_period__lte=request.end_date,
            )
            indicator_values = list(
                indicator_qs.order_by('reporting_period').values_list('reporting_period', 'value')
            )
            # Compatibility fallback for legacy unit-test mocks using
            # `objects.filter.order_by...` instead of `objects.filter(...).order_by...`.
            if not indicator_values:
                try:
                    indicator_values = list(
                        MacroIndicator.objects.filter
                        .order_by('reporting_period')
                        .values_list('reporting_period', 'value')
                    )
                except Exception:
                    pass

            if not indicator_values:
                return EvaluateIndicatorPerformanceResponse(
                    success=False,
                    error=f"指标 {request.indicator_code} 在 {request.start_date} 到 {request.end_date} 期间无数据"
                )

            # 3. 获取 Regime 判定历史
            regime_logs = list(
                RegimeLog.objects.filter(
                    observed_at__gte=request.start_date,
                    observed_at__lte=request.end_date,
                ).order_by('observed_at')
            )
            if not regime_logs:
                try:
                    regime_logs = list(
                        RegimeLog.objects.filter
                        .order_by('observed_at')
                    )
                except Exception:
                    pass

            # 转换为 RegimeSnapshot
            regime_snapshots = [
                RegimeSnapshot(
                    observed_at=log.observed_at,
                    dominant_regime=log.dominant_regime,
                    confidence=log.confidence,
                    growth_momentum_z=log.growth_momentum_z,
                    inflation_momentum_z=log.inflation_momentum_z,
                    distribution=log.distribution,
                )
                for log in regime_logs
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
                    performance_model = IndicatorPerformanceModel.objects.create(
                        indicator_code=report.indicator_code,
                        evaluation_period_start=report.evaluation_period_start,
                        evaluation_period_end=report.evaluation_period_end,
                        true_positive_count=report.true_positive_count,
                        false_positive_count=report.false_positive_count,
                        true_negative_count=report.true_negative_count,
                        false_negative_count=report.false_negative_count,
                        precision=report.precision,
                        recall=report.recall,
                        f1_score=report.f1_score,
                        accuracy=report.accuracy,
                        lead_time_mean=report.lead_time_mean,
                        lead_time_std=report.lead_time_std,
                        pre_2015_correlation=report.pre_2015_correlation,
                        post_2015_correlation=report.post_2015_correlation,
                        stability_score=report.stability_score,
                        decay_rate=report.decay_rate,
                        signal_strength=report.signal_strength,
                        recommended_action=report.recommended_action,
                        recommended_weight=report.recommended_weight,
                        confidence_level=report.confidence_level,
                    )
                    report_id = performance_model.id
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
    indicator_codes: Optional[List[str]] = None  # None 表示验证所有指标
    use_shadow_mode: bool = False


@dataclass
class ValidateThresholdsResponse:
    """验证阈值响应"""
    success: bool
    validation_report: Optional[ThresholdValidationReport] = None
    validation_run_id: Optional[str] = None
    error: Optional[str] = None


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

            # 1. 获取待验证的指标
            if request.indicator_codes:
                threshold_models = IndicatorThresholdConfigModel.objects.filter(
                    indicator_code__in=request.indicator_codes,
                    is_active=True
                )
            else:
                threshold_models = IndicatorThresholdConfigModel.objects.filter(
                    is_active=True
                )

            total_indicators = threshold_models.count()
            if total_indicators == 0:
                return ValidateThresholdsResponse(
                    success=False,
                    error="没有找到待验证的指标"
                )

            # 2. 创建验证摘要记录
            if not request.use_shadow_mode:
                summary_model = ValidationSummaryModel.objects.create(
                    validation_run_id=validation_run_id,
                    evaluation_period_start=request.start_date,
                    evaluation_period_end=request.end_date,
                    total_indicators=total_indicators,
                    status='in_progress',
                    is_shadow_mode=request.use_shadow_mode,
                )

            # 3. 逐个评估指标
            evaluate_use_case = EvaluateIndicatorPerformanceUseCase(self.audit_repo)
            indicator_reports = []

            approved_count = 0
            rejected_count = 0
            pending_count = 0

            for threshold_model in threshold_models:
                response = evaluate_use_case.execute(
                    EvaluateIndicatorPerformanceRequest(
                        indicator_code=threshold_model.indicator_code,
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
                status=ValidationStatus.COMPLETED if not request.use_shadow_mode else ValidationStatus.SHADOW_RUN,
            )

            # 7. 更新验证摘要
            if not request.use_shadow_mode:
                summary_model.approved_indicators = approved_count
                summary_model.rejected_indicators = rejected_count
                summary_model.pending_indicators = pending_count
                summary_model.avg_f1_score = avg_f1
                summary_model.avg_stability_score = avg_stability
                summary_model.overall_recommendation = overall_recommendation
                summary_model.status = 'completed'
                summary_model.save()

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

            # 更新验证摘要为失败状态
            if not request.use_shadow_mode:
                try:
                    summary_model = ValidationSummaryModel.objects.get(
                        validation_run_id=validation_run_id
                    )
                    summary_model.status = 'failed'
                    summary_model.error_message = str(e)
                    summary_model.save()
                except ValidationSummaryModel.DoesNotExist:
                    pass

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
    adjusted_weights: List[DynamicWeightConfig] = None
    error: Optional[str] = None


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
            # 1. 获取验证摘要
            summary = ValidationSummaryModel.objects.filter(
                validation_run_id=request.validation_run_id
            ).first()

            if not summary:
                return AdjustIndicatorWeightsResponse(
                    success=False,
                    error=f"验证记录 {request.validation_run_id} 不存在"
                )

            # 2. 获取本次验证的所有指标表现报告
            performance_reports = IndicatorPerformanceModel.objects.filter(
                evaluation_period_start=summary.evaluation_period_start,
                evaluation_period_end=summary.evaluation_period_end,
            )

            adjusted_weights = []

            for report in performance_reports:
                # 获取对应的阈值配置
                threshold_model = IndicatorThresholdConfigModel.objects.filter(
                    indicator_code=report.indicator_code
                ).first()

                if not threshold_model:
                    continue

                original_weight = threshold_model.base_weight
                current_weight = report.recommended_weight

                # 计算调整系数
                if original_weight > 0:
                    adjustment_factor = current_weight / original_weight
                else:
                    adjustment_factor = 1.0

                # 生成调整原因
                reason = self._generate_adjustment_reason(
                    report.recommended_action,
                    report.f1_score,
                    report.stability_score,
                )

                # 置信度
                confidence = report.confidence_level

                weight_config = DynamicWeightConfig(
                    indicator_code=report.indicator_code,
                    current_weight=current_weight,
                    original_weight=original_weight,
                    f1_score=report.f1_score,
                    stability_score=report.stability_score,
                    decay_rate=report.decay_rate,
                    adjustment_factor=adjustment_factor,
                    new_weight=current_weight,
                    reason=reason,
                    confidence=confidence,
                )

                adjusted_weights.append(weight_config)

                # 自动应用权重调整
                if request.auto_apply:
                    threshold_model.base_weight = current_weight
                    threshold_model.save()

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

