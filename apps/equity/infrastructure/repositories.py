"""Compatibility exports for equity infrastructure repositories.

Repository implementations live in focused owner modules. This module remains
the stable import and monkeypatch surface used by providers, tests, and
integrations; keep public symbol identities and legacy patch paths stable.
"""

from apps.data_center.application.interface_services import make_on_demand_data_center_service
from apps.equity.infrastructure.asset_repository import DjangoEquityAssetRepository
from apps.equity.infrastructure.config_repositories import (
    EquityBootstrapConfigRepository,
    ScoringWeightConfigRepository,
    ValuationRepairConfigRepository,
)
from apps.equity.infrastructure.stock_repository import (
    DjangoStockRepository as _DjangoStockRepository,
)
from apps.equity.infrastructure.valuation_repair_repositories import (
    DjangoValuationDataQualityRepository,
    DjangoValuationRepairRepository,
    build_quality_snapshot,
    compute_valuation_quality_flag,
)


class DjangoStockRepository(_DjangoStockRepository):
    """Compatibility subclass preserving the legacy monkeypatch surface.

    Tests patch ``apps.equity.infrastructure.repositories.DjangoStockRepository``
    methods and ``apps.equity.infrastructure.repositories
    .make_on_demand_data_center_service``; resolving the on-demand factory from
    this module namespace keeps both patch paths working.
    """

    def __init__(self) -> None:
        super().__init__(on_demand_service=make_on_demand_data_center_service())


__all__ = [
    "DjangoEquityAssetRepository",
    "DjangoStockRepository",
    "DjangoValuationDataQualityRepository",
    "DjangoValuationRepairRepository",
    "EquityBootstrapConfigRepository",
    "ScoringWeightConfigRepository",
    "ValuationRepairConfigRepository",
    "build_quality_snapshot",
    "compute_valuation_quality_flag",
    "make_on_demand_data_center_service",
]
