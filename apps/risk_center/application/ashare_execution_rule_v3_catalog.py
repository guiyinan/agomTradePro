"""Application ports and import use case for v3 settlement rule bundles."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleImportResult,
    ExecutionRuleInputError,
)
from apps.risk_center.application.execution_settlement_v3 import (
    ExecutionSettlementV3ReadRecord,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3


class AShareExecutionSettlementRuleV3Catalog(Protocol):
    """Persistence boundary for exact v3 settlement rule bundles."""

    def import_settlement_bundles(
        self, *, bundles: tuple[ExecutionSettlementBundleV3, ...]
    ) -> ExecutionRuleImportResult:
        """Atomically append v3 bundles or report exact idempotent replays."""

    def get_effective_settlement_bundle(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSettlementV3ReadRecord | None:
        """Read one v3 bundle and retain its local database knowledge timestamp."""


class ImportAShareExecutionSettlementRulesV3UseCase:
    """Validate and persist one operator-supplied v3 bundle batch."""

    def __init__(self, repository: AShareExecutionSettlementRuleV3Catalog) -> None:
        """Require the Risk-owned shared rule-table port explicitly."""

        self._repository = repository

    def execute(
        self, *, bundles: tuple[ExecutionSettlementBundleV3, ...]
    ) -> ExecutionRuleImportResult:
        """Import exact sealed bundles, preserving their V3 hash and identity."""

        if type(bundles) is not tuple or not bundles:
            raise ExecutionRuleInputError(
                "v3 settlement import requires a nonempty immutable tuple"
            )
        for bundle in bundles:
            if type(bundle) is not ExecutionSettlementBundleV3:
                raise ExecutionRuleInputError(
                    "v3 settlement import requires exact typed domain bundles"
                )
            try:
                ExecutionSettlementBundleV3.__post_init__(bundle)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise ExecutionRuleInputError(
                    "v3 settlement import contains invalid content"
                ) from error
        return self._repository.import_settlement_bundles(bundles=bundles)


__all__: tuple[str, ...] = (
    "AShareExecutionSettlementRuleV3Catalog",
    "ImportAShareExecutionSettlementRulesV3UseCase",
)
