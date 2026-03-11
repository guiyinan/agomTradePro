from celery import shared_task
from django.conf import settings

from apps.equity.application.use_cases_valuation_repair import (
    ScanValuationRepairsRequest,
    ScanValuationRepairsUseCase,
)
from apps.equity.application.use_cases_valuation_sync import (
    SyncEquityValuationRequest,
    SyncEquityValuationUseCase,
    ValidateEquityValuationQualityRequest,
    ValidateEquityValuationQualityUseCase,
)
from apps.equity.infrastructure.adapters import StockPoolRepositoryAdapter
from apps.equity.infrastructure.repositories import (
    DjangoStockRepository,
    DjangoValuationDataQualityRepository,
    DjangoValuationRepairRepository,
)


@shared_task(
    time_limit=getattr(settings, 'EQUITY_VALUATION_SYNC_TASK_TIMEOUT', 1800),
    soft_time_limit=getattr(settings, 'EQUITY_VALUATION_SYNC_TASK_SOFT_TIMEOUT', 1700)
)
def sync_equity_valuation_task(days_back: int = 1, primary_source: str = "akshare", fallback_source: str = "tushare") -> dict:
    use_case = SyncEquityValuationUseCase(stock_repository=DjangoStockRepository())
    response = use_case.execute(
        SyncEquityValuationRequest(
            days_back=days_back,
            primary_source=primary_source,
            fallback_source=fallback_source,
        )
    )
    return response.data if response.success else {"success": False, "error": response.error}


@shared_task(
    time_limit=getattr(settings, 'EQUITY_VALUATION_VALIDATE_TASK_TIMEOUT', 600),
    soft_time_limit=getattr(settings, 'EQUITY_VALUATION_VALIDATE_TASK_SOFT_TIMEOUT', 570)
)
def validate_equity_valuation_quality_task(primary_source: str = "akshare") -> dict:
    use_case = ValidateEquityValuationQualityUseCase(
        stock_repository=DjangoStockRepository(),
        quality_repository=DjangoValuationDataQualityRepository(),
    )
    response = use_case.execute(
        ValidateEquityValuationQualityRequest(primary_source=primary_source)
    )
    return response.data if response.success else {"success": False, "error": response.error}


@shared_task(
    time_limit=getattr(settings, 'EQUITY_VALUATION_SCAN_TASK_TIMEOUT', 2400),
    soft_time_limit=getattr(settings, 'EQUITY_VALUATION_SCAN_TASK_SOFT_TIMEOUT', 2300)
)
def sync_validate_scan_equity_valuation_task(
    days_back: int = 1,
    primary_source: str = "akshare",
    fallback_source: str = "tushare",
    universe: str = "all_active",
    lookback_days: int | None = None,
) -> dict:
    """日常编排任务：同步 -> 质量校验 -> gate通过才scan。"""
    stock_repo = DjangoStockRepository()
    quality_repo = DjangoValuationDataQualityRepository()

    # 从 settings 获取默认值
    if lookback_days is None:
        lookback_days = getattr(settings, 'EQUITY_VALUATION_DEFAULT_LOOKBACK_DAYS', 756)

    sync_response = SyncEquityValuationUseCase(stock_repository=stock_repo).execute(
        SyncEquityValuationRequest(
            days_back=days_back,
            primary_source=primary_source,
            fallback_source=fallback_source,
        )
    )
    if not sync_response.success:
        return {
            "success": False,
            "stage": "sync",
            "error": sync_response.error,
        }

    validate_response = ValidateEquityValuationQualityUseCase(
        stock_repository=stock_repo,
        quality_repository=quality_repo,
    ).execute(
        ValidateEquityValuationQualityRequest(primary_source=primary_source)
    )
    if not validate_response.success:
        return {
            "success": False,
            "stage": "validate",
            "sync": sync_response.data,
            "error": validate_response.error,
        }

    if not validate_response.data.get("is_gate_passed"):
        return {
            "success": True,
            "stage": "gate_blocked",
            "sync": sync_response.data,
            "validate": validate_response.data,
            "scan_skipped": True,
        }

    scan_response = ScanValuationRepairsUseCase(
        stock_repository=stock_repo,
        valuation_repair_repository=DjangoValuationRepairRepository(),
        stock_pool_adapter=StockPoolRepositoryAdapter(),
        valuation_quality_repository=quality_repo,
    ).execute(
        ScanValuationRepairsRequest(
            universe=universe,
            lookback_days=lookback_days,
        )
    )
    return {
        "success": scan_response.success,
        "stage": "scan",
        "sync": sync_response.data,
        "validate": validate_response.data,
        "scan": {
            "universe": scan_response.universe,
            "as_of_date": scan_response.as_of_date.isoformat(),
            "scanned_count": scan_response.scanned_count,
            "saved_count": scan_response.saved_count,
            "failed_count": scan_response.failed_count,
            "phase_counts": scan_response.phase_counts,
            "error": scan_response.error,
        },
    }
