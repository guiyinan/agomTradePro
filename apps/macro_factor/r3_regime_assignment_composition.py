"""Using-only composition for the canonical Regime R3 assignment read adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from apps.macro_factor.infrastructure.regime_historical_assignment_adapter import (
    ExactHistoricalRegimeAssignmentReceiptReader,
    RegimeHistoricalAssignmentReportAdapter,
)
from apps.macro_factor.infrastructure.run_ledger_repository import (
    DjangoMacroFactorRunLedgerReadRepository,
)
from core.integration.r3_owner_evidence import (
    build_r3_regime_assignment_reader,
)


@dataclass(frozen=True, slots=True)
class MacroFactorR3RegimeAssignmentReadRuntime:
    """Narrow report reader without mutation, current, decision, or execution ports."""

    report_provider: RegimeHistoricalAssignmentReportAdapter


def build_macro_factor_r3_regime_assignment_read_runtime(
    *,
    using: str = "default",
) -> MacroFactorR3RegimeAssignmentReadRuntime:
    """Compose public Regime and Macro Factor exact readers on one database alias."""

    return MacroFactorR3RegimeAssignmentReadRuntime(
        report_provider=RegimeHistoricalAssignmentReportAdapter(
            assignment_reader=cast(
                ExactHistoricalRegimeAssignmentReceiptReader,
                build_r3_regime_assignment_reader(using=using),
            ),
            ledger=DjangoMacroFactorRunLedgerReadRepository(using=using),
        )
    )


__all__ = [
    "MacroFactorR3RegimeAssignmentReadRuntime",
    "build_macro_factor_r3_regime_assignment_read_runtime",
]
