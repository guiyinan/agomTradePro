"""
Domain Entities for Investment Signals.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional
from shared.domain.asset_eligibility import Eligibility


class SignalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


@dataclass
class InvestmentSignal:
    """投资信号实体"""
    id: Optional[str]
    asset_code: str
    asset_class: str
    direction: str  # LONG, SHORT, NEUTRAL
    logic_desc: str
    invalidation_logic: str  # 必填
    invalidation_threshold: Optional[float]
    target_regime: str
    created_at: date
    status: SignalStatus = SignalStatus.PENDING
    rejection_reason: Optional[str] = None
