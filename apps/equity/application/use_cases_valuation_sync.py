"""
估值数据可信化 Application 用例

聚焦本地估值数据的同步、质量校验与新鲜度判断。
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from apps.equity.infrastructure.repositories import (
    build_quality_snapshot,
)
from apps.equity.infrastructure.valuation_source_gateways import (
    AKShareValuationGateway,
    TushareValuationGateway,
)
from shared.config.secrets import get_secrets

logger = logging.getLogger(__name__)


@dataclass
class ValidateEquityValuationQualityRequest:
    as_of_date: date | None = None
    primary_source: str = "akshare"


@dataclass
class SyncEquityValuationRequest:
    stock_codes: list[str] | None = None
    start_date: date | None = None
    end_date: date | None = None
    primary_source: str = "akshare"
    fallback_source: str = "tushare"
    days_back: int = 1


@dataclass
class SyncEquityValuationResponse:
    success: bool
    data: dict | None = None
    error: str | None = None


@dataclass
class BackfillEquityValuationRequest:
    years: int = 3
    batch_size: int = 100


@dataclass
class BackfillEquityValuationResponse:
    success: bool
    data: dict | None = None
    error: str | None = None


@dataclass
class ValidateEquityValuationQualityResponse:
    success: bool
    data: dict | None = None
    error: str | None = None


@dataclass
class GetEquityValuationFreshnessResponse:
    success: bool
    data: dict | None = None
    error: str | None = None


@dataclass
class GetLatestEquityValuationQualityResponse:
    success: bool
    data: dict | None = None
    error: str | None = None


class ValidateEquityValuationQualityUseCase:
    """对指定日期本地估值数据执行质量校验并持久化快照。"""

    def __init__(self, stock_repository, quality_repository):
        self.stock_repo = stock_repository
        self.quality_repo = quality_repository

    def execute(self, request: ValidateEquityValuationQualityRequest) -> ValidateEquityValuationQualityResponse:
        try:
            as_of_date = request.as_of_date or self.stock_repo.get_latest_valuation_date()
            if not as_of_date:
                raise ValueError("未找到估值数据")

            expected_stock_count = len(self.stock_repo.list_active_stock_codes())
            valuations = self.stock_repo.get_valuation_models_by_date(as_of_date)
            snapshot = build_quality_snapshot(
                as_of_date=as_of_date,
                expected_stock_count=expected_stock_count,
                valuations=valuations,
                primary_source=request.primary_source,
            )
            self.quality_repo.upsert_snapshot(snapshot)
            return ValidateEquityValuationQualityResponse(success=True, data=_snapshot_to_dict(snapshot))
        except Exception as exc:
            logger.exception("估值数据质量校验失败")
            return ValidateEquityValuationQualityResponse(success=False, error=str(exc))


class SyncEquityValuationUseCase:
    """从主备 provider 同步估值数据到本地估值表。"""

    def __init__(self, stock_repository):
        self.stock_repo = stock_repository
        self.akshare_gateway = AKShareValuationGateway()
        self.tushare_gateway = None

    def execute(self, request: SyncEquityValuationRequest) -> SyncEquityValuationResponse:
        try:
            end_date = request.end_date or date.today()
            start_date = request.start_date or (end_date - timedelta(days=request.days_back))
            stock_codes = request.stock_codes or self.stock_repo.list_active_stock_codes()
            if not stock_codes:
                raise ValueError("未找到可同步股票")

            if request.fallback_source == "tushare":
                try:
                    tushare_settings = get_secrets().data_sources
                    if tushare_settings.tushare_token:
                        self.tushare_gateway = TushareValuationGateway(
                            token=tushare_settings.tushare_token,
                            http_url=tushare_settings.tushare_http_url,
                        )
                except Exception:
                    self.tushare_gateway = None

            synced_count = 0
            fallback_used_count = 0
            skipped_count = 0
            error_count = 0
            errors = []

            for stock_code in stock_codes:
                try:
                    batch = self.akshare_gateway.fetch(stock_code, start_date, end_date)
                    source_used = "akshare"

                    if not batch.records and self.tushare_gateway:
                        batch = self.tushare_gateway.fetch(stock_code, start_date, end_date)
                        source_used = "tushare"

                    if not batch.records:
                        skipped_count += 1
                        errors.append(f"{stock_code}: no valuation records from providers")
                        continue

                    for record in batch.records:
                        self.stock_repo.save_valuation(record)

                    if source_used != request.primary_source:
                        fallback_used_count += 1
                    synced_count += len(batch.records)
                except Exception as exc:
                    error_count += 1
                    errors.append(f"{stock_code}: {exc}")
                    logger.warning("同步股票估值失败 %s: %s", stock_code, exc)

            return SyncEquityValuationResponse(
                success=True,
                data={
                    "requested_count": len(stock_codes),
                    "synced_count": synced_count,
                    "fallback_used_count": fallback_used_count,
                    "skipped_count": skipped_count,
                    "error_count": error_count,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "errors": errors[:50],
                },
            )
        except Exception as exc:
            logger.exception("估值数据同步失败")
            return SyncEquityValuationResponse(success=False, error=str(exc))


class BackfillEquityValuationUseCase:
    """按批次回填历史估值数据。"""

    def __init__(self, stock_repository):
        self.stock_repo = stock_repository
        self.sync_use_case = SyncEquityValuationUseCase(stock_repository)

    def execute(self, request: BackfillEquityValuationRequest) -> BackfillEquityValuationResponse:
        try:
            stock_codes = self.stock_repo.list_active_stock_codes()
            if not stock_codes:
                raise ValueError("未找到可回填股票")

            end_date = date.today()
            start_date = end_date - timedelta(days=request.years * 366)
            total_batches = (len(stock_codes) + request.batch_size - 1) // request.batch_size
            batch_results = []

            for batch_index in range(total_batches):
                batch_codes = stock_codes[
                    batch_index * request.batch_size:(batch_index + 1) * request.batch_size
                ]
                result = self.sync_use_case.execute(
                    SyncEquityValuationRequest(
                        stock_codes=batch_codes,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )
                batch_results.append({
                    "batch": batch_index + 1,
                    "success": result.success,
                    "synced_count": result.data["synced_count"] if result.success else 0,
                    "error": result.error,
                })

            return BackfillEquityValuationResponse(
                success=True,
                data={
                    "years": request.years,
                    "batch_size": request.batch_size,
                    "total_batches": total_batches,
                    "results": batch_results,
                },
            )
        except Exception as exc:
            logger.exception("估值数据回填失败")
            return BackfillEquityValuationResponse(success=False, error=str(exc))


class GetEquityValuationFreshnessUseCase:
    """计算本地估值数据新鲜度。"""

    def __init__(self, stock_repository, quality_repository):
        self.stock_repo = stock_repository
        self.quality_repo = quality_repository

    def execute(self) -> GetEquityValuationFreshnessResponse:
        try:
            latest_date = self.stock_repo.get_latest_valuation_date()
            latest_snapshot = self.quality_repo.get_latest_snapshot()
            if not latest_date:
                raise ValueError("未找到估值数据")

            lag_days = (date.today() - latest_date).days
            status = "fresh"
            if lag_days >= 3:
                status = "critical"
            elif lag_days >= 2:
                status = "warning"

            return GetEquityValuationFreshnessResponse(
                success=True,
                data={
                    "latest_trade_date": latest_date.isoformat(),
                    "lag_days": lag_days,
                    "freshness_status": status,
                    "coverage_ratio": getattr(latest_snapshot, "coverage_ratio", None),
                    "is_gate_passed": getattr(latest_snapshot, "is_gate_passed", None),
                },
            )
        except Exception as exc:
            logger.exception("估值数据新鲜度查询失败")
            return GetEquityValuationFreshnessResponse(success=False, error=str(exc))


class GetLatestEquityValuationQualityUseCase:
    """获取最近一次质量快照。"""

    def __init__(self, quality_repository):
        self.quality_repo = quality_repository

    def execute(self) -> GetLatestEquityValuationQualityResponse:
        try:
            snapshot = self.quality_repo.get_latest_snapshot()
            if not snapshot:
                raise ValueError("尚未生成估值质量快照")
            return GetLatestEquityValuationQualityResponse(
                success=True,
                data=_snapshot_to_dict(snapshot),
            )
        except Exception as exc:
            logger.exception("获取最近估值质量快照失败")
            return GetLatestEquityValuationQualityResponse(success=False, error=str(exc))


def _snapshot_to_dict(snapshot) -> dict:
    if isinstance(snapshot, dict):
        data = snapshot
    else:
        data = {
            "as_of_date": snapshot.as_of_date,
            "expected_stock_count": snapshot.expected_stock_count,
            "synced_stock_count": snapshot.synced_stock_count,
            "valid_stock_count": snapshot.valid_stock_count,
            "coverage_ratio": snapshot.coverage_ratio,
            "valid_ratio": snapshot.valid_ratio,
            "missing_pb_count": snapshot.missing_pb_count,
            "invalid_pb_count": snapshot.invalid_pb_count,
            "missing_pe_count": snapshot.missing_pe_count,
            "jump_alert_count": snapshot.jump_alert_count,
            "source_deviation_count": snapshot.source_deviation_count,
            "primary_source": snapshot.primary_source,
            "fallback_used_count": snapshot.fallback_used_count,
            "is_gate_passed": snapshot.is_gate_passed,
            "gate_reason": snapshot.gate_reason,
        }

    normalized = dict(data)
    if isinstance(normalized.get("as_of_date"), date):
        normalized["as_of_date"] = normalized["as_of_date"].isoformat()
    return normalized
