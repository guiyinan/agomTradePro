"""
持仓证伪检查服务

定期检查所有持仓的证伪条件是否满足，满足时标记并提示平仓。
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, TypedDict, cast

from django.utils import timezone

from apps.signal.domain.invalidation import (
    IndicatorValue,
    InvalidationCheckResult,
    InvalidationRule,
    evaluate_rule,
)
from apps.simulated_trading.application.repository_provider import (
    get_simulated_position_repository,
)
from apps.simulated_trading.domain.entities import Position

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MacroObservation:
    value: float
    unit: str
    observed_at: date


class _DataCenterMacroGateway:
    """Compatibility gateway that reads macro facts from data_center."""

    def __init__(self) -> None:
        from apps.data_center.composition import get_macro_fact_repository

        self._repo = get_macro_fact_repository()

    def get_latest_by_code(self, code: str) -> _MacroObservation | None:
        fact = self._repo.get_latest(code)
        if fact is None:
            return None
        return _MacroObservation(
            value=fact.value,
            unit=fact.unit,
            observed_at=fact.reporting_period,
        )

    def get_history_by_code(self, code: str, periods: int = 12) -> list[_MacroObservation]:
        facts = self._repo.get_series(code, limit=periods)
        return [
            _MacroObservation(
                value=fact.value,
                unit=fact.unit,
                observed_at=fact.reporting_period,
            )
            for fact in reversed(facts)
        ]


class MacroGatewayProtocol(Protocol):
    """Macro observations required to evaluate invalidation rules."""

    def get_latest_by_code(self, code: str) -> _MacroObservation | None:
        """Return the latest observation for one indicator."""
        ...

    def get_history_by_code(
        self,
        code: str,
        periods: int = 12,
    ) -> list[_MacroObservation]:
        """Return historical observations for one indicator."""
        ...


class PositionInvalidationRepositoryProtocol(Protocol):
    """Position persistence required by the invalidation checker."""

    def get_pending_invalidation_positions(self) -> list[Position]:
        """Return positions awaiting invalidation evaluation."""
        ...

    def get_position_by_id(self, position_id: int) -> Position | None:
        """Return one position by persistence identifier."""
        ...

    def mark_invalidation_checked(
        self,
        account_id: int,
        asset_code: str,
        checked_at: datetime,
    ) -> bool:
        """Persist an invalidation check timestamp."""
        ...

    def mark_invalidated(
        self,
        account_id: int,
        asset_code: str,
        reason: str,
        checked_at: datetime,
    ) -> bool:
        """Persist an invalidated position state."""
        ...

    def count_positions_with_invalidation_rules(self) -> int:
        """Count positions that have invalidation rules."""
        ...

    def get_invalidated_position_summaries(self) -> list[dict[str, object]]:
        """Return summaries for invalidated open positions."""
        ...


class InvalidatedPositionResult(TypedDict):
    """Summary of one position invalidated by a batch check."""

    position_id: int | None
    account_id: int
    asset_code: str
    asset_name: str
    reason: str


class PositionInvalidationBatchResult(TypedDict):
    """Result returned by the scheduled invalidation check."""

    checked: int
    invalidated: int
    positions: list[InvalidatedPositionResult]


class PositionInvalidationChecker:
    """持仓证伪检查器

    负责检查持仓的证伪条件是否满足。
    """

    def __init__(
        self,
        macro_repo: MacroGatewayProtocol | None = None,
        position_repo: PositionInvalidationRepositoryProtocol | None = None,
    ) -> None:
        """初始化检查器"""
        self.macro_repo = macro_repo if macro_repo is not None else _DataCenterMacroGateway()
        self.position_repo = (
            position_repo if position_repo is not None else get_simulated_position_repository()
        )

    def check_all_positions(self) -> list[InvalidatedPositionResult]:
        """
        检查所有有证伪规则的持仓

        Returns:
            List[Dict]: 被证伪的持仓列表
        """
        # 获取所有有证伪规则且未被证伪的持仓
        positions = self.position_repo.get_pending_invalidation_positions()

        invalidated: list[InvalidatedPositionResult] = []

        for position in positions:
            result = self._check_position(position)
            if result and result.is_invalidated:
                # 更新持仓的证伪状态
                if not self._mark_position_invalidated(position, result):
                    logger.error(
                        "持仓证伪状态写入失败: account=%s asset=%s",
                        position.account_id,
                        position.asset_code,
                    )
                    continue
                invalidated.append(
                    {
                        "position_id": None,
                        "account_id": position.account_id,
                        "asset_code": position.asset_code,
                        "asset_name": position.asset_name,
                        "reason": result.reason,
                    }
                )

        return invalidated

    def check_position(self, position_id: int) -> InvalidationCheckResult | None:
        """
        检查单个持仓的证伪状态

        Args:
            position_id: 持仓ID

        Returns:
            InvalidationCheckResult 或 None
        """
        position = self.position_repo.get_position_by_id(position_id)
        if not position or not position.invalidation_rule_json or position.is_invalidated:
            return None
        return self._check_position(position)

    def _check_position(self, position: Position) -> InvalidationCheckResult | None:
        """
        检查持仓的证伪状态

        Args:
            position: Position 实体

        Returns:
            InvalidationCheckResult 或 None
        """

        # 解析证伪规则
        try:
            raw_rule = position.invalidation_rule_json
            if not raw_rule:
                return None
            decoded_rule = json.loads(raw_rule)
            if not isinstance(decoded_rule, dict):
                raise TypeError("invalidation rule must be a JSON object")
            rule = InvalidationRule.from_dict(cast(dict[str, Any], decoded_rule))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            # 规则格式错误，无法检查
            logger.warning(
                "持仓证伪规则无效: account=%s asset=%s error=%s",
                position.account_id,
                position.asset_code,
                exc,
            )
            return None

        # 获取指标值
        indicator_values = self._fetch_indicator_values(rule)

        # 评估规则（Domain 层纯函数）
        result = evaluate_rule(rule, indicator_values)

        # 更新检查时间
        checked = self.position_repo.mark_invalidation_checked(
            account_id=position.account_id,
            asset_code=position.asset_code,
            checked_at=timezone.now(),
        )
        if not checked:
            logger.warning(
                "持仓证伪检查时间写入失败: account=%s asset=%s",
                position.account_id,
                position.asset_code,
            )

        return result

    def _fetch_indicator_values(self, rule: InvalidationRule) -> dict[str, IndicatorValue]:
        """
        获取规则中所有指标的当前值

        Args:
            rule: 证伪规则

        Returns:
            Dict[str, IndicatorValue]: 指标值字典
        """
        values: dict[str, IndicatorValue] = {}

        for condition in rule.conditions:
            code = condition.indicator_code

            # 避免重复获取
            if code in values:
                continue

            # 从数据库获取指标数据
            try:
                latest = self.macro_repo.get_latest_by_code(code)
                if latest:
                    history = self.macro_repo.get_history_by_code(code, periods=12)
                    values[code] = IndicatorValue(
                        code=code,
                        current_value=latest.value,
                        history_values=[d.value for d in history],
                        unit=latest.unit or "",
                        last_updated=latest.observed_at.isoformat() if latest.observed_at else None,
                    )
                else:
                    values[code] = IndicatorValue(
                        code=code,
                        current_value=None,
                        history_values=[],
                        unit="",
                        last_updated=None,
                    )
            except Exception as exc:
                # 获取失败，使用空值
                logger.warning("证伪指标读取失败: code=%s error=%s", code, exc)
                values[code] = IndicatorValue(
                    code=code,
                    current_value=None,
                    history_values=[],
                    unit="",
                    last_updated=None,
                )

        return values

    def _mark_position_invalidated(
        self,
        position: Position,
        result: InvalidationCheckResult,
    ) -> bool:
        """
        标记持仓为已证伪

        Args:
            position: 持仓模型
            result: 证伪检查结果
        """
        updated = self.position_repo.mark_invalidated(
            account_id=position.account_id,
            asset_code=position.asset_code,
            reason=result.reason,
            checked_at=timezone.now(),
        )

        if updated:
            logger.warning(
                "持仓证伪: %s - %s - %s",
                position.account_id,
                position.asset_code,
                result.reason,
            )
        return updated

    def get_positions_to_close(self) -> list[dict[str, object]]:
        """
        获取所有应该平仓的持仓（已证伪）

        Returns:
            List[dict]: 应该平仓的持仓摘要列表
        """
        return self.position_repo.get_invalidated_position_summaries()


# ==================== 导出函数，供 Celery 任务使用 ====================


def check_and_invalidate_positions() -> PositionInvalidationBatchResult:
    """
    检查并证伪满足条件的持仓

    这是一个导出函数，供 Celery 任务调用。

    Returns:
        Dict: 包含统计信息
    """
    checker = PositionInvalidationChecker()
    invalidated = checker.check_all_positions()

    return {
        "checked": checker.position_repo.count_positions_with_invalidation_rules(),
        "invalidated": len(invalidated),
        "positions": invalidated,
    }


def get_invalidated_positions_summary() -> list[dict[str, object]]:
    """
    获取已证伪持仓的摘要

    Returns:
        List[Dict]: 已证伪持仓的摘要列表
    """
    checker = PositionInvalidationChecker()
    positions = checker.get_positions_to_close()

    return positions
