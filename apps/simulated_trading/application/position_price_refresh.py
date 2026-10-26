"""Bounded orchestration for account-scoped position price refreshes."""

import logging
from typing import Any, cast

from apps.data_center.application.price_service import UnifiedPriceService
from apps.simulated_trading.application.ports import (
    PositionPriceRefreshInput,
    PositionPriceRefreshRepositoryProtocol,
)
from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
    get_simulated_position_repository,
)
from apps.simulated_trading.application.task_contract_support import (
    _failed_task_result,
    _task_result,
    _validate_optional_id,
)
from apps.simulated_trading.application.use_cases import (
    PositionRepositoryProtocol,
    SimulatedAccountRepositoryProtocol,
)
from core.exceptions import DataFetchError

logger = logging.getLogger(__name__)


def refresh_position_prices_task_body(account_id: int | None = None) -> dict[str, Any]:
    """Refresh valuation fields with provider reads outside account transactions.

    The repository re-reads account and position state under account-first
    locks; this task never writes a previously read Account or Position entity
    back after the provider call. The Data Center observation clock is carried
    as-is in the typed refresh input. Cached fallbacks have no source clock and
    cannot upgrade an unknown valuation flag.
    """
    try:
        validated_account_id = _validate_optional_id(account_id, "account_id")
    except (TypeError, ValueError) as exc:
        return _failed_task_result(exc)

    logger.info("开始更新持仓价格: account_id=%s", validated_account_id)
    try:
        account_repo: SimulatedAccountRepositoryProtocol = get_simulated_account_repository()
        raw_position_repo = get_simulated_position_repository()
        position_repo = cast(PositionRepositoryProtocol, raw_position_repo)
        price_refresh_repo = cast(
            PositionPriceRefreshRepositoryProtocol,
            raw_position_repo,
        )
        price_provider = UnifiedPriceService()

        if validated_account_id is not None:
            account = account_repo.get_by_id(validated_account_id)
            if account is None:
                return _task_result(
                    outcome="failed",
                    requested=1,
                    succeeded=0,
                    failed=1,
                    stored=0,
                    error=f"账户不存在: {validated_account_id}",
                )
            accounts = [account]
        else:
            accounts = account_repo.get_active_accounts()

        updated_count = 0
        error_count = 0
        errors: list[dict[str, Any]] = []
        warning_count = 0
        warnings: list[dict[str, Any]] = []
        successful_account_count = 0
        stored_account_count = 0

        for account in accounts:
            positions = position_repo.get_by_account(account.account_id)
            account_has_errors = False
            price_by_code: dict[str, PositionPriceRefreshInput] = {}

            for position in positions:
                try:
                    price_result = price_provider.require_latest_price_result(
                        position.asset_code,
                        asset_type=position.asset_type,
                    )
                    price_by_code[position.asset_code] = PositionPriceRefreshInput(
                        asset_code=position.asset_code,
                        asset_type=position.asset_type,
                        price=price_result.price,
                        source=price_result.source,
                        freshness=price_result.freshness,
                        as_of=price_result.as_of,
                        observed_at=price_result.observed_at,
                    )
                except DataFetchError as exc:
                    if position.current_price > 0:
                        logger.warning(
                            "更新持仓 %s 失败，沿用库内价格: %s",
                            position.asset_code,
                            exc,
                        )
                        warning_count += 1
                        warnings.append(
                            {
                                "account_id": account.account_id,
                                "asset_code": position.asset_code,
                                "warning": str(exc),
                                "fallback": "cached_position_price",
                                "details": exc.details,
                            }
                        )
                        price_by_code[position.asset_code] = PositionPriceRefreshInput(
                            asset_code=position.asset_code,
                            asset_type=position.asset_type,
                            price=position.current_price,
                            source=None,
                            freshness="cached",
                            as_of=None,
                            observed_at=None,
                        )
                        continue
                    logger.error("更新持仓 %s 失败: %s", position.asset_code, exc)
                    account_has_errors = True
                    error_count += 1
                    errors.append(
                        {
                            "account_id": account.account_id,
                            "asset_code": position.asset_code,
                            "error": str(exc),
                            "details": exc.details,
                        }
                    )
                except Exception as exc:
                    logger.error("更新持仓 %s 失败: %s", position.asset_code, exc)
                    account_has_errors = True
                    error_count += 1
                    errors.append(
                        {
                            "account_id": account.account_id,
                            "asset_code": position.asset_code,
                            "error": str(exc),
                        }
                    )

            if account_has_errors:
                logger.error("账户 %s 存在持仓价格缺失，跳过本批估值写入", account.account_id)
                continue

            try:
                updated_count += price_refresh_repo.update_position_prices_for_account(
                    account.account_id,
                    price_by_code,
                )
            except Exception as exc:
                logger.error("账户 %s 持仓状态无法安全刷新: %s", account.account_id, exc)
                error_count += 1
                errors.append({"account_id": account.account_id, "error": str(exc)})
                continue

            successful_account_count += 1
            stored_account_count += 1

        logger.info("持仓价格更新完成: %s 个成功, %s 个失败", updated_count, error_count)
        failed_account_count = len(accounts) - successful_account_count
        if not accounts:
            outcome = "noop"
        elif failed_account_count and successful_account_count:
            outcome = "partial"
        elif failed_account_count:
            outcome = "failed"
        else:
            outcome = "success"
        return _task_result(
            outcome=outcome,
            requested=len(accounts),
            succeeded=successful_account_count,
            failed=failed_account_count,
            stored=updated_count + stored_account_count,
            updated_count=updated_count,
            warning_count=warning_count,
            warnings=warnings,
            error_count=error_count,
            errors=errors,
        )
    except Exception as exc:
        logger.exception("更新持仓价格任务失败: %s", exc)
        return _failed_task_result(exc)
