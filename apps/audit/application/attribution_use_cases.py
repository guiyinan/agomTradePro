"""Attribution report and audit summary use cases."""

import json
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol, TypedDict

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError

from apps.audit.application.repository_provider import DjangoAuditRepository
from apps.audit.domain.services import (
    AttributionAnalyzer,
    AttributionConfig,
    analyze_attribution,
)
from apps.backtest.application.repository_provider import (
    create_default_price_adapter,
)
from apps.backtest.domain.entities import Trade
from apps.regime.application.repository_provider import get_regime_repository
from core.exceptions import DataValidationError, InsufficientDataError
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    ConnectionError,
    DataValidationError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    InsufficientDataError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)

__all__ = [
    "GenerateAttributionReportRequest",
    "GenerateAttributionReportResponse",
    "GenerateAttributionReportUseCase",
    "GetAuditSummaryRequest",
    "GetAuditSummaryResponse",
    "GetAuditSummaryUseCase",
    "RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS",
]


class BacktestRepositoryProtocol(Protocol):
    """Dynamic ORM lookup required by attribution."""

    def get_backtest_by_id(self, backtest_id: int) -> Any | None: ...


class RegimeHistoryRecord(TypedDict):
    """Normalized regime evidence used by attribution."""

    date: date
    regime: str
    dominant_regime: str
    confidence: float


class BacktestAttributionData(TypedDict):
    """Validated persisted backtest data."""

    id: int
    name: str
    start_date: date
    end_date: date
    initial_capital: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    annualized_return: float
    equity_curve: list[tuple[date, float]]
    trades: list[object]
    regime_history: list[RegimeHistoryRecord]
    status: str


@dataclass(frozen=True)
class SimpleBacktestResult:
    """Minimal backtest result surface accepted by Audit Domain."""

    equity_curve: list[tuple[date, float]]
    trades: list[Trade]
    total_return: float


@dataclass(frozen=True)
class GenerateAttributionReportRequest:
    """生成归因报告请求"""

    backtest_id: int


@dataclass(frozen=True)
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
        backtest_repository: BacktestRepositoryProtocol,
    ) -> None:
        self.audit_repo = audit_repository
        self.backtest_repo = backtest_repository
        self.regime_repo = get_regime_repository()

    def execute(
        self, request: GenerateAttributionReportRequest
    ) -> GenerateAttributionReportResponse:
        """执行归因分析"""
        try:
            # 1. 获取回测结果
            backtest_model = self.backtest_repo.get_backtest_by_id(request.backtest_id)
            if not backtest_model:
                return GenerateAttributionReportResponse(
                    success=False, error=f"回测 {request.backtest_id} 不存在"
                )

            # 2. 将 ORM 对象转换为字典
            backtest_dict = self._backtest_model_to_dict(backtest_model)

            # 3. 进行归因分析（Domain 层）
            asset_returns = self._build_asset_returns(backtest_dict)
            config = AttributionConfig()
            normalized_regime_history = list(backtest_dict["regime_history"])

            # Ensure the last regime period covers the full backtest window.
            if normalized_regime_history:
                last_entry = normalized_regime_history[-1]
                end_date = backtest_dict["end_date"]
                if last_entry["date"] < end_date:
                    normalized_regime_history.append(
                        {
                            "date": end_date,
                            "regime": last_entry["regime"],
                            "dominant_regime": last_entry["dominant_regime"],
                            "confidence": last_entry["confidence"],
                        }
                    )

            simple_result = SimpleBacktestResult(
                equity_curve=backtest_dict["equity_curve"],
                trades=[],  # 简化：不使用 trades（避免 Domain 层依赖 Trade 对象）
                total_return=backtest_dict["total_return"],
            )

            attribution = analyze_attribution(
                backtest_result=simple_result,
                regime_history=[dict(entry) for entry in normalized_regime_history],
                asset_returns=asset_returns,
                config=config,
            )

            # 5. 分析 Regime 准确性
            AttributionAnalyzer(config)

            # 计算 Regime 准确率（基于回测中的 Regime 预测与实际收益的一致性）
            regime_accuracy = self._calculate_regime_accuracy(
                normalized_regime_history, backtest_dict["equity_curve"]
            )

            dominant_regime = (
                normalized_regime_history[-1]["dominant_regime"]
                if normalized_regime_history
                else "UNKNOWN"
            )

            # 5.5 计算 regime_actual（从 RegimeLog 获取实际数据）
            try:
                regime_actual = self._calculate_regime_actual(
                    backtest_dict["start_date"], backtest_dict["end_date"]
                )
            except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as regime_error:
                # In non-DB unit tests or degraded runtime, regime actual should not
                # block attribution report generation.
                logger.warning(
                    "Regime actual calculation degraded, fallback to error code: %s", regime_error
                )
                regime_actual = self.ERROR_NO_REGIME_DATA

            # 6. 保存归因报告
            report_id = self.audit_repo.save_attribution_report(
                backtest_id=request.backtest_id,
                period_start=backtest_dict["start_date"],
                period_end=backtest_dict["end_date"],
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
                    impact_percentage=(
                        abs(loss_amount / attribution.total_return * 100)
                        if attribution.total_return != 0
                        else 0
                    ),
                    description=f"损失来源: {loss_source}",
                    improvement_suggestion="; ".join(attribution.improvement_suggestions[:3]),
                )

            # 7. 保存经验总结
            self.audit_repo.save_experience_summary(
                report_id=report_id,
                lesson=attribution.lesson_learned,
                recommendation="; ".join(attribution.improvement_suggestions),
                priority="HIGH" if attribution.loss_amount < -0.05 else "MEDIUM",
            )

            logger.info(f"归因报告生成成功: report_id={report_id}")

            return GenerateAttributionReportResponse(success=True, report_id=report_id)

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
            logger.error("归因分析失败: %s", type(exc).__name__, exc_info=True)
            return GenerateAttributionReportResponse(
                success=False,
                error="归因分析失败，请检查回测数据与行情数据源",
            )

    def _calculate_regime_actual(self, start_date: date, end_date: date) -> str:
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

        if data_points < 10:
            logger.warning(
                f"Insufficient regime data: only {data_points} points for {period_days} days"
            )
            return self.ERROR_INSUFFICIENT_DATA

        # 3. 统计各 Regime 的出现频率
        regime_counts: dict[str, int] = {}
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
        regime_history: Sequence[RegimeHistoryRecord],
        equity_curve: Sequence[tuple[date, float]],
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
        returns_by_date: dict[date, float] = {}
        for i in range(1, len(equity_curve)):
            prev_value = equity_curve[i - 1][1]
            current_date, current_value = equity_curve[i]
            if prev_value > 0:
                returns_by_date[current_date] = (current_value - prev_value) / prev_value

        # 检查每个 Regime 预测
        for regime_record in regime_history:
            regime = regime_record["regime"].upper()
            regime_date = regime_record["date"]

            actual_return = returns_by_date.get(regime_date)
            if actual_return is None:
                continue

            total_predictions += 1

            # 判断预测是否正确
            # Recovery/Overheat (增长环境) 预期正收益
            # Stagflation/Deflation (衰退环境) 预期负收益
            if regime in ("RECOVERY", "OVERHEAT"):
                if actual_return > 0:
                    correct_predictions += 1
            elif regime in ("STAGFLATION", "DEFLATION"):
                if actual_return < 0:
                    correct_predictions += 1
            else:
                # UNKNOWN 或其他，不计入准确率
                total_predictions -= 1

        if total_predictions == 0:
            return 0.5  # 无有效预测时返回中性值

        return correct_predictions / total_predictions

    def _build_asset_returns(
        self,
        backtest: BacktestAttributionData,
    ) -> dict[str, list[tuple[date, float]]]:
        """
        构建资产收益数据（从真实数据源获取）

        使用 CompositeAssetPriceAdapter 获取各资产的历史价格数据，
        并计算收益率。如果数据不可用，抛出异常而非使用假数据。

        Returns:
            dict: 资产收益率数据 {asset_class: [(date, return), ...]}

        Raises:
            ValueError: 当无法获取真实数据时
        """

        from shared.config.secrets import get_secrets

        start_date = backtest["start_date"]
        end_date = backtest["end_date"]

        # 资产类别映射（与 backtest 模块保持一致）
        asset_classes: dict[str, str] = {
            "a_share_growth": "equity",  # 沪深300
            "a_share_value": "equity",  # 中证500
            "china_bond": "bond",  # 债券
            "gold": "commodity",  # 黄金
            "commodity": "commodity",  # 商品
            "cash": "cash",  # 现金
        }

        # 创建价格适配器（使用 Tushare 作为数据源）
        try:
            tushare_settings = get_secrets().data_sources
            price_adapter = create_default_price_adapter(
                tushare_token=tushare_settings.tushare_token,
                tushare_http_url=tushare_settings.tushare_http_url,
            )
        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
            logger.error("无法初始化价格适配器: %s", type(exc).__name__)
            raise ValueError(
                "无法初始化价格数据源，归因分析需要真实的历史价格数据。请检查行情数据源配置。"
            ) from exc

        asset_returns: dict[str, list[tuple[date, float]]] = {}
        data_source_status: dict[str, str] = {}

        # 获取各资产的价格数据并计算收益率
        for asset_class, return_category in asset_classes.items():
            try:
                # 获取价格序列
                price_points = price_adapter.get_prices(
                    asset_class=asset_class, start_date=start_date, end_date=end_date
                )

                if not price_points:
                    data_source_status[asset_class] = "无数据"
                    logger.warning(f"无法获取 {asset_class} 的价格数据")
                    continue

                # 计算日收益率
                returns: list[tuple[date, float]] = []
                for i in range(1, len(price_points)):
                    prev_price = safe_float(price_points[i - 1].price)
                    curr_price = safe_float(price_points[i].price)
                    as_of_date = price_points[i].as_of_date

                    if (
                        prev_price is not None
                        and curr_price is not None
                        and prev_price > 0
                        and isinstance(as_of_date, date)
                    ):
                        daily_return = (curr_price - prev_price) / prev_price
                        if math.isfinite(daily_return):
                            returns.append((as_of_date, daily_return))

                if returns:
                    # 使用 return_category 作为键，与归因分析期望的格式一致
                    if return_category not in asset_returns:
                        asset_returns[return_category] = []
                    asset_returns[return_category].extend(returns)
                    data_source_status[asset_class] = f"成功 ({len(returns)} 个数据点)"
                else:
                    data_source_status[asset_class] = "无收益率数据"

            except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
                data_source_status[asset_class] = f"错误: {type(exc).__name__}"
                logger.warning(
                    "获取 %s 数据失败: %s",
                    asset_class,
                    type(exc).__name__,
                )

        # 至少需要一种非现金资产数据
        non_cash_assets = [k for k in asset_returns.keys() if k != "cash"]
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

    def _backtest_model_to_dict(
        self,
        model: Any,
    ) -> BacktestAttributionData:
        """
        将 BacktestResultModel 转换为字典

        Args:
            model: BacktestResultModel ORM 对象

        Returns:
            dict: 回测数据字典
        """
        equity_curve = self._normalize_equity_curve(model.equity_curve)
        regime_history = self._normalize_regime_history(model.regime_history)
        trades = model.trades if isinstance(model.trades, list) else []

        def _model_float(field: str) -> float:
            return safe_float(getattr(model, field, 0.0), default=0.0)

        return {
            "id": model.id,
            "name": model.name,
            "start_date": model.start_date,
            "end_date": model.end_date,
            "initial_capital": _model_float("initial_capital"),
            "total_return": _model_float("total_return"),
            "sharpe_ratio": _model_float("sharpe_ratio"),
            "max_drawdown": _model_float("max_drawdown"),
            "annualized_return": _model_float("annualized_return"),
            "equity_curve": equity_curve,
            "trades": trades,
            "regime_history": regime_history,
            "status": model.status,
        }

    @staticmethod
    def _decode_json_value(value: object) -> object:
        """Decode legacy JSON text while preserving native JSONField values."""

        if not isinstance(value, str):
            return value
        if not value.strip():
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []

    @classmethod
    def _normalize_equity_curve(cls, value: object) -> list[tuple[date, float]]:
        """Normalize native or legacy equity points into finite dated values."""

        decoded = cls._decode_json_value(value)
        if not isinstance(decoded, list):
            return []

        normalized: list[tuple[date, float]] = []
        for item in decoded:
            raw_date: object
            raw_value: object
            if isinstance(item, Mapping):
                raw_date = item.get("date")
                raw_value = item.get("value")
            elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                if len(item) < 2:
                    continue
                raw_date, raw_value = item[0], item[1]
            else:
                continue

            point_date = cls._to_date(raw_date)
            point_value = safe_float(raw_value)
            if point_date is not None and point_value is not None:
                normalized.append((point_date, point_value))

        normalized.sort(key=lambda point: point[0])
        return normalized

    @classmethod
    def _normalize_regime_history(cls, value: object) -> list[RegimeHistoryRecord]:
        """Normalize persisted regime evidence and reject malformed records."""

        decoded = cls._decode_json_value(value)
        if not isinstance(decoded, list):
            return []

        normalized: list[RegimeHistoryRecord] = []
        for item in decoded:
            if not isinstance(item, Mapping):
                continue
            observed_date = cls._to_date(item.get("date"))
            raw_regime = item.get("regime") or item.get("dominant_regime")
            if observed_date is None or not isinstance(raw_regime, str):
                continue
            regime = raw_regime.strip()
            if not regime:
                continue
            raw_dominant = item.get("dominant_regime")
            dominant_regime = (
                raw_dominant.strip()
                if isinstance(raw_dominant, str) and raw_dominant.strip()
                else regime
            )
            confidence = safe_float(item.get("confidence"), default=0.0)
            normalized.append(
                {
                    "date": observed_date,
                    "regime": regime,
                    "dominant_regime": dominant_regime,
                    "confidence": confidence,
                }
            )

        normalized.sort(key=lambda item: item["date"])
        return normalized

    @staticmethod
    def _to_date(value: object) -> date | None:
        """Normalize date-like values to datetime.date."""

        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        if isinstance(value, bool):
            return None
        timestamp = safe_float(value)
        if timestamp is not None:
            if abs(timestamp) >= 100_000_000_000:
                timestamp /= 1000
            try:
                return datetime.fromtimestamp(timestamp, tz=UTC).date()
            except (OverflowError, OSError, ValueError):
                return None
        return None

    @staticmethod
    def _map_loss_source_to_model_choice(loss_source: str) -> str:
        """Map domain loss source values to LossAnalysis model choices."""
        mapping = {
            "regime_timing": "REGIME_ERROR",
            "asset_selection": "ASSET_SELECTION_ERROR",
            "transaction_cost": "TRANSACTION_COST",
            "market_volatility": "TIMING_ERROR",
            "unknown": "TIMING_ERROR",
        }
        return mapping.get(loss_source, "TIMING_ERROR")


@dataclass(frozen=True)
class GetAuditSummaryRequest:
    """获取审计摘要请求"""

    start_date: date | None = None
    end_date: date | None = None
    backtest_id: int | None = None


@dataclass(frozen=True)
class GetAuditSummaryResponse:
    """获取审计摘要响应"""

    success: bool
    reports: list[dict[str, object]] = field(default_factory=list)
    error: str | None = None


class GetAuditSummaryUseCase:
    """获取审计摘要的用例"""

    def __init__(self, audit_repository: DjangoAuditRepository) -> None:
        self.audit_repo = audit_repository

    def execute(self, request: GetAuditSummaryRequest) -> GetAuditSummaryResponse:
        """获取审计摘要"""
        try:
            if request.backtest_id:
                reports = self.audit_repo.get_reports_by_backtest(request.backtest_id)
            elif request.start_date and request.end_date:
                reports = self.audit_repo.get_reports_by_date_range(
                    request.start_date, request.end_date
                )
            else:
                return GetAuditSummaryResponse(
                    success=False, error="必须提供 backtest_id 或 start_date + end_date"
                )

            # 补充损失分析和经验总结，不修改 Repository 的精确投影。
            enriched_reports: list[dict[str, object]] = []
            for report in reports:
                enriched_report: dict[str, object] = dict(report)
                enriched_report["loss_analyses"] = self.audit_repo.get_loss_analyses(report["id"])
                enriched_report["experience_summaries"] = self.audit_repo.get_experience_summaries(
                    report["id"]
                )
                enriched_reports.append(enriched_report)

            return GetAuditSummaryResponse(success=True, reports=enriched_reports)

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
            logger.error("获取审计摘要失败: %s", type(exc).__name__, exc_info=True)
            return GetAuditSummaryResponse(
                success=False,
                error="获取审计摘要失败，请稍后重试",
            )
