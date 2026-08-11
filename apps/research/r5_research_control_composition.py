"""Fail-closed production composition for the R5 research-control preflight."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.fixed_income.relative_value_composition import (
    build_django_r5_relative_value_owner_record_query,
)
from apps.research.application.r5_research_control_adapters import (
    R5FixedIncomeOwnerRecordQuery,
    R5FixedIncomeOwnerSealExactAdapter,
    R5LatestCompleteMonitoringExactAdapter,
    R5LatestCompleteMonitoringRepository,
)
from apps.research.application.r5_research_control_preflight import (
    EvaluateR5ResearchControlPreflight,
    R5ResearchControlActiveLifecycleProvider,
    R5ResearchControlUnitOfWork,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
)
from apps.research.infrastructure.r5_relative_value_monitoring_repository import (
    DjangoR5MonitoringRepository,
)


class _UnavailableCanonicalActiveLifecycleProvider:
    """Explicit gap until Portfolio exposes its canonical raw-source provider."""

    __slots__ = ("_unit_of_work_key",)

    def __init__(self, *, using: str) -> None:
        if type(using) is not str or not using.strip():
            raise ValueError("R5 research-control database alias is invalid")
        self._unit_of_work_key = f"django:{using}"

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R5MonitoringActiveLifecycle | None:
        """Return absence without consulting fixtures or minting owner evidence."""

        del scope_id, as_of
        return None


@dataclass(frozen=True, slots=True)
class DjangoR5ResearchControlRuntime:
    """Read-only runtime with no writer, consumer, current, or execution port."""

    preflight: EvaluateR5ResearchControlPreflight


def _compose_r5_research_control_runtime(
    *,
    active_lifecycle_provider: R5ResearchControlActiveLifecycleProvider,
    monitoring_repository: R5LatestCompleteMonitoringRepository,
    fixed_income_query: R5FixedIncomeOwnerRecordQuery,
    unit_of_work: R5ResearchControlUnitOfWork,
) -> DjangoR5ResearchControlRuntime:
    return DjangoR5ResearchControlRuntime(
        preflight=EvaluateR5ResearchControlPreflight(
            active_lifecycle_provider=active_lifecycle_provider,
            monitoring_provider=R5LatestCompleteMonitoringExactAdapter(monitoring_repository),
            fixed_income_provider=R5FixedIncomeOwnerSealExactAdapter(fixed_income_query),
            unit_of_work=unit_of_work,
        )
    )


def build_django_r5_research_control_runtime(
    *,
    using: str = "default",
) -> DjangoR5ResearchControlRuntime:
    """Build canonical exact readers and block on the missing Portfolio owner."""

    monitoring_repository = DjangoR5MonitoringRepository(using=using)
    return _compose_r5_research_control_runtime(
        active_lifecycle_provider=_UnavailableCanonicalActiveLifecycleProvider(using=using),
        monitoring_repository=monitoring_repository,
        fixed_income_query=build_django_r5_relative_value_owner_record_query(using=using),
        unit_of_work=monitoring_repository,
    )


def _build_django_r5_research_control_test_runtime(
    *,
    active_lifecycle_provider: R5ResearchControlActiveLifecycleProvider,
    fixed_income_query: R5FixedIncomeOwnerRecordQuery,
    using: str = "default",
) -> DjangoR5ResearchControlRuntime:
    """Privately prove exact canonical owners without exporting mutation authority."""

    monitoring_repository = DjangoR5MonitoringRepository(using=using)
    return _compose_r5_research_control_runtime(
        active_lifecycle_provider=active_lifecycle_provider,
        monitoring_repository=monitoring_repository,
        fixed_income_query=fixed_income_query,
        unit_of_work=monitoring_repository,
    )


__all__ = [
    "DjangoR5ResearchControlRuntime",
    "build_django_r5_research_control_runtime",
]
