"""
板块分析模块 - 数据仓储实现

遵循项目架构约束：
- 实现 Domain 层定义的接口
- 封装 Django ORM 调用
- 返回 Domain 层实体
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from apps.data_center.application.public import get_sector_membership_repository_port
from shared.numeric import safe_float

from ..domain.entities import SectorIndex, SectorInfo, SectorRelativeStrength
from .models import (
    SectorIndexModel,
    SectorInfoModel,
    SectorPreferenceConfigModel,
    SectorRelativeStrengthModel,
)

logger = logging.getLogger(__name__)


class DjangoSectorRepository:
    """Django ORM 板块数据仓储

    职责：
    1. 板块基本信息 CRUD
    2. 板块指数数据 CRUD
    3. 板块成分股关系 CRUD
    4. 相对强弱指标 CRUD
    """

    def __init__(self) -> None:
        """Wire canonical sector-membership reads through Data Center."""

        self._dc_membership_repo = get_sector_membership_repository_port()

    # ===== 板块基本信息 =====

    def get_sector_info(self, sector_code: str) -> SectorInfo | None:
        """获取板块基本信息

        Args:
            sector_code: 板块代码

        Returns:
            SectorInfo 或 None
        """
        try:
            model = SectorInfoModel._default_manager.get(sector_code=sector_code, is_active=True)
            return SectorInfo(
                sector_code=model.sector_code,
                sector_name=model.sector_name,
                level=model.level,
                parent_code=model.parent_code,
            )
        except SectorInfoModel.DoesNotExist:
            return None

    def get_all_sectors(self, level: str | None = None) -> list[SectorInfo]:
        """获取所有板块信息

        Args:
            level: 板块级别过滤（SW1/SW2/SW3）

        Returns:
            SectorInfo 列表
        """
        queryset = SectorInfoModel._default_manager.filter(is_active=True)

        if level:
            queryset = queryset.filter(level=level)

        sectors = []
        for model in queryset:
            sectors.append(
                SectorInfo(
                    sector_code=model.sector_code,
                    sector_name=model.sector_name,
                    level=model.level,
                    parent_code=model.parent_code,
                )
            )

        return sectors

    def get_sector_weights_by_regime(self, regime: str) -> dict[str, float]:
        """Return configured sector weights for one regime."""

        configs = list(
            SectorPreferenceConfigModel._default_manager.filter(
                regime=regime,
                is_active=True,
            )
        )
        codes_by_name = dict(
            SectorInfoModel._default_manager.filter(
                sector_name__in=[config.sector_name for config in configs],
                is_active=True,
            ).values_list("sector_name", "sector_code")
        )
        return {
            codes_by_name[config.sector_name]: config.weight
            for config in configs
            if config.sector_name in codes_by_name
        }

    def save_sector_info(self, sector_info: SectorInfo) -> bool:
        """保存板块基本信息

        Args:
            sector_info: 板块信息实体

        Returns:
            是否成功
        """
        try:
            SectorInfoModel._default_manager.update_or_create(
                sector_code=sector_info.sector_code,
                defaults={
                    "sector_name": sector_info.sector_name,
                    "level": sector_info.level,
                    "parent_code": sector_info.parent_code,
                    "is_active": True,
                },
            )
            return True
        except Exception as exc:
            logger.error("保存板块信息失败 (error_type=%s)", type(exc).__name__)
            return False

    def get_stock_sector_name_map(self) -> dict[str, list[str]]:
        """Return current stock-to-sector-name mapping for policy influence checks."""

        canonical_rows = self._dc_membership_repo.list_current(as_of=date.today())
        canonical_mapping: dict[str, list[str]] = {}
        for canonical_row in canonical_rows:
            if not canonical_row.asset_code or not canonical_row.sector_name:
                continue
            canonical_mapping.setdefault(canonical_row.asset_code, [])
            if canonical_row.sector_name not in canonical_mapping[canonical_row.asset_code]:
                canonical_mapping[canonical_row.asset_code].append(canonical_row.sector_name)
        return canonical_mapping

    # ===== 板块指数数据 =====

    def get_sector_index(self, sector_code: str, trade_date: date) -> SectorIndex | None:
        """获取板块指数数据

        Args:
            sector_code: 板块代码
            trade_date: 交易日期

        Returns:
            SectorIndex 或 None
        """
        try:
            model = SectorIndexModel._default_manager.get(
                sector_code=sector_code, trade_date=trade_date
            )
            return SectorIndex(
                sector_code=model.sector_code,
                trade_date=model.trade_date,
                open_price=model.open_price,
                high=model.high,
                low=model.low,
                close=model.close,
                volume=model.volume,
                amount=model.amount,
                change_pct=model.change_pct,
                turnover_rate=model.turnover_rate,
            )
        except SectorIndexModel.DoesNotExist:
            return None

    def get_sector_index_range(
        self, sector_code: str, start_date: date, end_date: date
    ) -> list[SectorIndex]:
        """获取板块指数时间范围数据

        Args:
            sector_code: 板块代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            SectorIndex 列表
        """
        queryset = SectorIndexModel._default_manager.filter(
            sector_code=sector_code, trade_date__gte=start_date, trade_date__lte=end_date
        ).order_by("trade_date")

        indices = []
        for model in queryset:
            indices.append(
                SectorIndex(
                    sector_code=model.sector_code,
                    trade_date=model.trade_date,
                    open_price=model.open_price,
                    high=model.high,
                    low=model.low,
                    close=model.close,
                    volume=model.volume,
                    amount=model.amount,
                    change_pct=model.change_pct,
                    turnover_rate=model.turnover_rate,
                )
            )

        return indices

    def save_sector_index(self, sector_index: SectorIndex) -> bool:
        """保存板块指数数据

        Args:
            sector_index: 板块指数实体

        Returns:
            是否成功
        """
        try:
            SectorIndexModel._default_manager.update_or_create(
                sector_code=sector_index.sector_code,
                trade_date=sector_index.trade_date,
                defaults={
                    "open_price": sector_index.open_price,
                    "high": sector_index.high,
                    "low": sector_index.low,
                    "close": sector_index.close,
                    "volume": sector_index.volume,
                    "amount": sector_index.amount,
                    "change_pct": sector_index.change_pct,
                    "turnover_rate": sector_index.turnover_rate,
                },
            )
            return True
        except Exception as exc:
            logger.error("保存板块指数失败 (error_type=%s)", type(exc).__name__)
            return False

    def get_latest_sector_index(self, sector_code: str) -> SectorIndex | None:
        """获取板块最新指数数据

        Args:
            sector_code: 板块代码

        Returns:
            SectorIndex 或 None
        """
        try:
            model = (
                SectorIndexModel._default_manager.filter(sector_code=sector_code)
                .order_by("-trade_date")
                .first()
            )

            if model:
                return SectorIndex(
                    sector_code=model.sector_code,
                    trade_date=model.trade_date,
                    open_price=model.open_price,
                    high=model.high,
                    low=model.low,
                    close=model.close,
                    volume=model.volume,
                    amount=model.amount,
                    change_pct=model.change_pct,
                    turnover_rate=model.turnover_rate,
                )
            return None
        except Exception as exc:
            logger.error("获取板块最新指数失败 (error_type=%s)", type(exc).__name__)
            return None

    # ===== 相对强弱指标 =====

    def save_relative_strength(self, rs: SectorRelativeStrength) -> bool:
        """保存相对强弱指标

        Args:
            rs: 相对强弱实体

        Returns:
            是否成功
        """
        try:
            SectorRelativeStrengthModel._default_manager.update_or_create(
                sector_code=rs.sector_code,
                trade_date=rs.trade_date,
                defaults={
                    "relative_strength": rs.relative_strength,
                    "momentum": rs.momentum,
                    "beta": rs.beta,
                },
            )
            return True
        except Exception as exc:
            logger.error("保存相对强弱指标失败 (error_type=%s)", type(exc).__name__)
            return False

    def get_relative_strength(
        self, sector_code: str, trade_date: date
    ) -> SectorRelativeStrength | None:
        """获取相对强弱指标

        Args:
            sector_code: 板块代码
            trade_date: 交易日期

        Returns:
            SectorRelativeStrength 或 None
        """
        try:
            model = SectorRelativeStrengthModel._default_manager.get(
                sector_code=sector_code, trade_date=trade_date
            )
            return SectorRelativeStrength(
                sector_code=model.sector_code,
                trade_date=model.trade_date,
                relative_strength=model.relative_strength,
                momentum=model.momentum,
                beta=model.beta,
            )
        except SectorRelativeStrengthModel.DoesNotExist:
            return None

    # ===== 辅助方法 =====

    def batch_save_sector_indices(self, indices_df: Any) -> int:
        """批量保存板块指数数据

        Args:
            indices_df: Pandas DataFrame，包含板块指数数据

        Returns:
            成功保存的记录数
        """
        count = 0
        for _, row in indices_df.iterrows():
            try:
                sector_code = str(row.get("sector_code") or "").strip()
                trade_date = _plain_date(row.get("trade_date"))
                open_price = _required_decimal(row.get("open_price"), "open_price")
                high = _required_decimal(row.get("high"), "high")
                low = _required_decimal(row.get("low"), "low")
                close = _required_decimal(row.get("close"), "close")
                volume_value = safe_float(row.get("volume"))
                amount = _required_decimal(row.get("amount"), "amount")
                change_pct = _required_float(row.get("change_pct"), "change_pct")
                turnover_rate = safe_float(row.get("turnover_rate"))
                if (
                    not sector_code
                    or len(sector_code) > 10
                    or any(ord(character) < 32 for character in sector_code)
                ):
                    raise ValueError("sector_code_invalid")
                if volume_value is None or volume_value < 0 or not volume_value.is_integer():
                    raise ValueError("volume_invalid")
                SectorIndexModel._default_manager.update_or_create(
                    sector_code=sector_code,
                    trade_date=trade_date,
                    defaults={
                        "open_price": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": int(volume_value),
                        "amount": amount,
                        "change_pct": change_pct,
                        "turnover_rate": turnover_rate,
                    },
                )
                count += 1
            except Exception as exc:
                logger.warning("批量保存板块指数失败 (error_type=%s)", type(exc).__name__)
                continue

        return count


def _plain_date(value: object) -> date:
    """Normalize a dataframe date cell to a plain date."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    normalized = str(value or "").strip()
    if len(normalized) >= 10:
        return date.fromisoformat(normalized[:10])
    raise ValueError("trade_date_invalid")


def _required_float(value: object, field_name: str) -> float:
    """Return one finite dataframe numeric cell."""

    parsed = safe_float(value)
    if parsed is None:
        raise ValueError(f"{field_name}_invalid")
    return parsed


def _required_decimal(value: object, field_name: str) -> Decimal:
    """Return one finite dataframe decimal cell."""

    return Decimal(str(_required_float(value, field_name)))
