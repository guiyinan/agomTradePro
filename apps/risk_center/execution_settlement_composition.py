"""Risk-owned composition for source-backed A-share settlement rule reads."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.risk_center.application.execution_settlement_v3 import (
    ReadEffectiveExecutionSettlementV3UseCase,
)
from apps.risk_center.infrastructure.ashare_execution_rule_repository import (
    DjangoAShareExecutionRuleRepository,
)


def build_execution_settlement_v3_rule_reader() -> ReadEffectiveExecutionSettlementV3UseCase:
    """Compose the Risk-owned current rule reader on the default database alias."""

    repository = DjangoAShareExecutionRuleRepository(using=DEFAULT_DB_ALIAS)
    return ReadEffectiveExecutionSettlementV3UseCase(repository=repository)


__all__: tuple[str, ...] = ("build_execution_settlement_v3_rule_reader",)
