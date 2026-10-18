"""Errors exposed by the legacy position adoption application operation."""

from core.exceptions import BusinessLogicError


class LegacyPositionAdoptionConflict(BusinessLogicError):
    """A legacy balance cannot be attached to one exact unified position."""

    default_message = "旧持仓与统一账本关系不明确，需先完成核对"
    default_code = "LEGACY_POSITION_RECONCILIATION_REQUIRED"
    default_status_code = 409
