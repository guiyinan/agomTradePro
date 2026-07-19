"""Valuation-repair tracking and valuation data-quality repositories.

Owns `DjangoValuationRepairRepository`, `DjangoValuationDataQualityRepository`,
and the valuation quality-flag/snapshot builders. The compatibility facade in
`repositories.py` remains the stable import surface; do not import it here.
"""

from datetime import date

from .models import ValuationDataQualitySnapshotModel, ValuationModel


class DjangoValuationRepairRepository:
    """Django ORM 估值修复仓储"""

    def upsert_snapshot(self, status, source_universe: str = "all_active") -> None:
        """
        保存或更新估值修复快照

        Args:
            status: ValuationRepairStatus 实体
            source_universe: 来源股票池
        """
        from .models import ValuationRepairTrackingModel

        ValuationRepairTrackingModel._default_manager.update_or_create(
            stock_code=status.stock_code,
            source_universe=source_universe,
            defaults={
                "stock_name": status.stock_name,
                "as_of_date": status.as_of_date,
                "repair_start_date": status.repair_start_date,
                "repair_start_percentile": status.repair_start_percentile,
                "current_phase": status.phase,
                "signal": status.signal,
                "composite_percentile": status.composite_percentile,
                "pe_percentile": status.pe_percentile,
                "pb_percentile": status.pb_percentile,
                "repair_progress": status.repair_progress,
                "repair_speed_per_30d": status.repair_speed_per_30d,
                "estimated_days_to_target": status.estimated_days_to_target,
                "is_stalled": status.is_stalled,
                "stall_start_date": status.stall_start_date,
                "stall_duration_trading_days": status.stall_duration_trading_days,
                "repair_duration_trading_days": status.repair_duration_trading_days,
                "lowest_percentile": status.lowest_percentile,
                "lowest_percentile_date": status.lowest_percentile_date,
                "target_percentile": status.target_percentile,
                "composite_method": status.composite_method,
                "confidence": status.confidence,
                "is_active": True,
            },
        )

    def deactivate_snapshot(self, stock_code: str, source_universe: str = "all_active") -> None:
        """
        停用估值修复快照

        Args:
            stock_code: 股票代码
            source_universe: 来源股票池
        """
        from .models import ValuationRepairTrackingModel

        ValuationRepairTrackingModel._default_manager.filter(
            stock_code=stock_code, source_universe=source_universe
        ).update(is_active=False)

    def list_active_snapshots(
        self, source_universe: str = "all_active", phase: str | None = None, limit: int = 50
    ) -> list:
        """
        列出活跃的估值修复快照

        Args:
            source_universe: 来源股票池
            phase: 阶段过滤（可选）
            limit: 数量限制

        Returns:
            ORM Model 列表
        """
        from .models import ValuationRepairTrackingModel

        queryset = ValuationRepairTrackingModel._default_manager.filter(
            source_universe=source_universe, is_active=True
        )

        if phase:
            queryset = queryset.filter(current_phase=phase)

        return list(queryset.order_by("-composite_percentile")[:limit])

    def get_snapshot(self, stock_code: str, source_universe: str = "all_active") -> object | None:
        """
        获取单只股票的估值修复快照

        Args:
            stock_code: 股票代码
            source_universe: 来源股票池

        Returns:
            ORM Model 或 None
        """
        from .models import ValuationRepairTrackingModel

        try:
            return ValuationRepairTrackingModel._default_manager.get(
                stock_code=stock_code, source_universe=source_universe, is_active=True
            )
        except ValuationRepairTrackingModel.DoesNotExist:
            return None

    def get_snapshot_map(self, stock_codes: list[str]) -> dict[str, dict]:
        """批量获取估值修复快照映射。"""
        normalized_codes = [str(code).upper() for code in stock_codes if code]
        if not normalized_codes:
            return {}

        from .models import ValuationRepairTrackingModel

        rows = ValuationRepairTrackingModel._default_manager.filter(
            stock_code__in=normalized_codes,
            is_active=True,
        ).values(
            "stock_code",
            "current_phase",
            "signal",
            "composite_percentile",
            "repair_progress",
            "repair_speed_per_30d",
            "estimated_days_to_target",
            "confidence",
            "as_of_date",
            "is_stalled",
        )
        return {
            str(row["stock_code"]).upper(): {
                "phase": row.get("current_phase"),
                "signal": row.get("signal"),
                "composite_percentile": row.get("composite_percentile"),
                "repair_progress": row.get("repair_progress"),
                "repair_speed_per_30d": row.get("repair_speed_per_30d"),
                "estimated_days_to_target": row.get("estimated_days_to_target"),
                "confidence": row.get("confidence"),
                "is_stalled": row.get("is_stalled"),
                "as_of_date": row["as_of_date"].isoformat() if row.get("as_of_date") else None,
            }
            for row in rows
        }


class DjangoValuationDataQualityRepository:
    """估值数据质量快照仓储"""

    def upsert_snapshot(self, snapshot: dict) -> None:
        ValuationDataQualitySnapshotModel._default_manager.update_or_create(
            as_of_date=snapshot["as_of_date"],
            defaults=snapshot,
        )

    def get_snapshot(self, as_of_date: date) -> ValuationDataQualitySnapshotModel | None:
        try:
            return ValuationDataQualitySnapshotModel._default_manager.get(as_of_date=as_of_date)
        except ValuationDataQualitySnapshotModel.DoesNotExist:
            return None

    def get_latest_snapshot(self) -> ValuationDataQualitySnapshotModel | None:
        return ValuationDataQualitySnapshotModel._default_manager.order_by("-as_of_date").first()

    def get_latest_gate_passed_snapshot(self) -> ValuationDataQualitySnapshotModel | None:
        return (
            ValuationDataQualitySnapshotModel._default_manager.filter(is_gate_passed=True)
            .order_by("-as_of_date")
            .first()
        )


def compute_valuation_quality_flag(
    pb: float | None,
    pe: float | None,
    previous_pb: float | None = None,
    previous_pe: float | None = None,
) -> tuple[bool, str, str]:
    """根据估值字段计算基础质量标记。"""
    if pb is None:
        return False, "missing_pb", "PB is missing"
    if pb <= 0:
        return False, "invalid_pb", "PB must be greater than 0"
    if pe is None:
        return True, "missing_pe", "PE is missing"

    if previous_pb and previous_pb > 0:
        pb_jump = abs(pb - previous_pb) / previous_pb
        if pb_jump > 0.60:
            return True, "jump_alert", f"PB jump={pb_jump:.2f}"

    if previous_pe and previous_pe > 0:
        pe_jump = abs(pe - previous_pe) / previous_pe
        if pe_jump > 0.80:
            return True, "jump_alert", f"PE jump={pe_jump:.2f}"

    return True, "ok", ""


def build_quality_snapshot(
    as_of_date: date,
    expected_stock_count: int,
    valuations: list[ValuationModel],
    primary_source: str = "akshare",
) -> dict:
    """根据指定日期估值记录构建质量快照。"""
    synced_stock_count = len(valuations)
    valid_stock_count = sum(1 for item in valuations if item.is_valid)
    missing_pb_count = sum(1 for item in valuations if item.quality_flag == "missing_pb")
    invalid_pb_count = sum(1 for item in valuations if item.quality_flag == "invalid_pb")
    missing_pe_count = sum(1 for item in valuations if item.quality_flag == "missing_pe")
    jump_alert_count = sum(1 for item in valuations if item.quality_flag == "jump_alert")
    source_deviation_count = sum(
        1 for item in valuations if item.quality_flag == "source_deviation"
    )
    fallback_used_count = sum(1 for item in valuations if item.source_provider != primary_source)

    coverage_ratio = (synced_stock_count / expected_stock_count) if expected_stock_count else 0.0
    valid_ratio = (valid_stock_count / synced_stock_count) if synced_stock_count else 0.0

    gate_reasons = []
    if coverage_ratio < 0.95:
        gate_reasons.append("coverage<0.95")
    if valid_ratio < 0.90:
        gate_reasons.append("valid<0.90")
    if invalid_pb_count > 0:
        gate_reasons.append("invalid_pb")
    if synced_stock_count:
        if jump_alert_count / synced_stock_count > 0.03:
            gate_reasons.append("jump_alert_ratio>0.03")
        if source_deviation_count / synced_stock_count > 0.05:
            gate_reasons.append("source_deviation_ratio>0.05")

    return {
        "as_of_date": as_of_date,
        "expected_stock_count": expected_stock_count,
        "synced_stock_count": synced_stock_count,
        "valid_stock_count": valid_stock_count,
        "coverage_ratio": round(coverage_ratio, 4),
        "valid_ratio": round(valid_ratio, 4),
        "missing_pb_count": missing_pb_count,
        "invalid_pb_count": invalid_pb_count,
        "missing_pe_count": missing_pe_count,
        "jump_alert_count": jump_alert_count,
        "source_deviation_count": source_deviation_count,
        "primary_source": primary_source,
        "fallback_used_count": fallback_used_count,
        "is_gate_passed": not gate_reasons,
        "gate_reason": ", ".join(gate_reasons),
    }


__all__ = [
    "DjangoValuationDataQualityRepository",
    "DjangoValuationRepairRepository",
    "build_quality_snapshot",
    "compute_valuation_quality_flag",
]
