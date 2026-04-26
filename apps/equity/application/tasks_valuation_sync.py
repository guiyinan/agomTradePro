from django.conf import settings
from celery import shared_task
from apps.data_center.application.dtos import SyncFinancialRequest
from apps.data_center.application.interface_services import (
    get_active_provider_id_by_source,
    make_sync_financial_use_case,
)
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
from apps.equity.infrastructure.providers import (
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


@shared_task(
    time_limit=getattr(settings, 'EQUITY_FINANCIAL_SYNC_TASK_TIMEOUT', 3600),
    soft_time_limit=getattr(settings, 'EQUITY_FINANCIAL_SYNC_TASK_SOFT_TIMEOUT', 3500)
)
def sync_financial_data_task(
    source: str = "akshare",
    periods: int = 8,
    stock_codes: list | None = None,
) -> dict:
    """
    同步财务数据
    
    Args:
        source: 数据源（akshare 或 tushare）
        periods: 获取最近几个报告期
        stock_codes: 指定股票代码列表（None 表示全部活跃股票）
    """
    stock_repo = DjangoStockRepository()

    # 获取要同步的股票列表
    if stock_codes:
        active_stock_codes = []
        for stock_code in stock_codes:
            normalized = str(stock_code).strip().upper()
            if normalized and normalized not in active_stock_codes:
                active_stock_codes.append(normalized)
    else:
        active_stock_codes = stock_repo.list_active_stock_codes()

    if not active_stock_codes:
        return {"success": False, "error": "没有找到活跃股票"}

    provider_id = get_active_provider_id_by_source(source)
    if provider_id is None:
        return {"success": False, "error": f"未找到启用的数据源: {source}"}

    sync_use_case = make_sync_financial_use_case()
    synced_count = 0
    error_count = 0
    errors = []

    for stock_code in active_stock_codes:
        try:
            result = sync_use_case.execute(
                SyncFinancialRequest(
                    provider_id=provider_id,
                    asset_code=stock_code,
                    periods=periods,
                )
            )
            synced_count += result.stored_count
        except Exception as e:
            error_count += 1
            if len(errors) < 10:  # 只记录前 10 个错误
                errors.append(f"{stock_code}: {str(e)}")

    return {
        "success": True,
        "synced_count": synced_count,
        "error_count": error_count,
        "total_stocks": len(active_stock_codes),
        "errors": errors,
    }
