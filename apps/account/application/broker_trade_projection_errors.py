"""Stable projection error imported after application registration."""

from __future__ import annotations

from core.exceptions import BusinessLogicError


class BrokerTradeProjectionConflict(BusinessLogicError):
    """Signal a projection CAS/provenance conflict and carry its stable reason."""

    default_message = "券商成交无法安全投影到统一持仓"
    default_code = "BROKER_FACT_PROJECTION_CONFLICT"

    def __init__(self, reason_code: str) -> None:
        """Carry one stable blocker through the transaction rollback boundary."""

        super().__init__(
            message=self.default_message,
            code=self.default_code,
            details={"reason_code": reason_code},
        )
        self.reason_code = reason_code
