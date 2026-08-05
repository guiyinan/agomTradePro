# ruff: noqa: F821

ALLOCATION_MATRIX = {
    Regime.RECOVERY: {
        Risk.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.70, fixed_income=0.15, commodity=0.05, cash=0.10)
        ),
        Risk.MODERATE: AllocationTarget(
            allocation=AssetAllocation(equity=0.55, fixed_income=0.25, commodity=0.05, cash=0.15)
        ),
        Risk.CONSERVATIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.40, fixed_income=0.35, commodity=0.05, cash=0.20)
        ),
        Risk.DEFENSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.25, fixed_income=0.45, commodity=0.05, cash=0.25)
        ),
    },
    Regime.OVERHEAT: {
        Risk.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.50, fixed_income=0.20, commodity=0.15, cash=0.15)
        ),
        Risk.MODERATE: AllocationTarget(
            allocation=AssetAllocation(equity=0.40, fixed_income=0.30, commodity=0.10, cash=0.20)
        ),
        Risk.CONSERVATIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.25, fixed_income=0.40, commodity=0.10, cash=0.25)
        ),
        Risk.DEFENSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.15, fixed_income=0.45, commodity=0.10, cash=0.30)
        ),
    },
    Regime.STAGFLATION: {
        Risk.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.30, fixed_income=0.25, commodity=0.20, cash=0.25)
        ),
        Risk.MODERATE: AllocationTarget(
            allocation=AssetAllocation(equity=0.20, fixed_income=0.35, commodity=0.15, cash=0.30)
        ),
        Risk.CONSERVATIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.10, fixed_income=0.45, commodity=0.15, cash=0.30)
        ),
        Risk.DEFENSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.05, fixed_income=0.40, commodity=0.15, cash=0.40)
        ),
    },
    Regime.DEFLATION: {
        Risk.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.40, fixed_income=0.35, commodity=0.05, cash=0.20)
        ),
        Risk.MODERATE: AllocationTarget(
            allocation=AssetAllocation(equity=0.25, fixed_income=0.45, commodity=0.05, cash=0.25)
        ),
        Risk.CONSERVATIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.15, fixed_income=0.55, commodity=0.05, cash=0.25)
        ),
        Risk.DEFENSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.10, fixed_income=0.50, commodity=0.05, cash=0.35)
        ),
    },
}
