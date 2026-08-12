"""Fail-closed production composition for the R4 research-control preflight."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringEvaluationEvidence,
)
from apps.research.application.r4_research_control_adapters import (
    R4ActivePromotionExactAdapter,
    R4ActivePromotionQuery,
    R4LatestCompleteMonitoringExactAdapter,
    R4LatestCompleteMonitoringRepository,
)
from apps.research.application.r4_research_control_preflight import (
    EvaluateR4ResearchControlPreflight,
    R4ResearchControlActivePromotionProvider,
    R4ResearchControlOwnerGraphProvider,
    R4ResearchControlUnitOfWork,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.infrastructure.r4_research_control_repository import (
    DjangoR4ResearchControlMonitoringRepository,
)


class _UnavailableCanonicalActivePromotionProvider:
    """Explicit gap until every active-promotion owner is constructible by alias."""

    __slots__ = ("_unit_of_work_key",)

    def __init__(self, *, using: str) -> None:
        self._unit_of_work_key = _django_uow_key(using)

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R4PromotionDecisionIdentity | None:
        """Return absence without consulting fixtures or minting owner evidence."""

        del scope_id, as_of
        return None


class _UnavailableCanonicalOwnerGraphProvider:
    """Never mint monitoring owners when canonical active sources are absent."""

    __slots__ = ("_unit_of_work_key",)

    def __init__(self, *, using: str) -> None:
        self._unit_of_work_key = _django_uow_key(using)

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def execute_evidence(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringEvaluationEvidence:
        """Fail if invoked; the unavailable active provider must short-circuit first."""

        del command
        raise RuntimeError("canonical R4 monitoring owner graph is unavailable")


@dataclass(frozen=True, slots=True)
class DjangoR4ResearchControlRuntime:
    """Read-only runtime with no writer, consumer, current, or execution port."""

    preflight: EvaluateR4ResearchControlPreflight


def _compose_r4_research_control_runtime(
    *,
    active_promotion_provider: R4ResearchControlActivePromotionProvider,
    monitoring_repository: R4LatestCompleteMonitoringRepository,
    owner_graph_provider: R4ResearchControlOwnerGraphProvider,
    unit_of_work: R4ResearchControlUnitOfWork,
) -> DjangoR4ResearchControlRuntime:
    return DjangoR4ResearchControlRuntime(
        preflight=EvaluateR4ResearchControlPreflight(
            active_promotion_provider=active_promotion_provider,
            monitoring_provider=R4LatestCompleteMonitoringExactAdapter(monitoring_repository),
            owner_graph_provider=owner_graph_provider,
            unit_of_work=unit_of_work,
        )
    )


def build_django_r4_research_control_runtime(
    *,
    using: str = "default",
) -> DjangoR4ResearchControlRuntime:
    """Build canonical reads and block while upstream exact owners are unavailable."""

    _django_uow_key(using)
    monitoring_repository = DjangoR4ResearchControlMonitoringRepository(using=using)
    return _compose_r4_research_control_runtime(
        active_promotion_provider=_UnavailableCanonicalActivePromotionProvider(using=using),
        monitoring_repository=monitoring_repository,
        owner_graph_provider=_UnavailableCanonicalOwnerGraphProvider(using=using),
        unit_of_work=monitoring_repository,
    )


def _build_django_r4_research_control_test_runtime(
    *,
    active_promotion_query: R4ActivePromotionQuery,
    owner_graph_provider: R4ResearchControlOwnerGraphProvider,
    using: str = "default",
) -> DjangoR4ResearchControlRuntime:
    """Privately prove exact canonical owners without exporting mutation authority."""

    key = _django_uow_key(using)
    monitoring_repository = DjangoR4ResearchControlMonitoringRepository(using=using)
    return _compose_r4_research_control_runtime(
        active_promotion_provider=R4ActivePromotionExactAdapter(
            active_promotion_query,
            unit_of_work_key=key,
        ),
        monitoring_repository=monitoring_repository,
        owner_graph_provider=owner_graph_provider,
        unit_of_work=monitoring_repository,
    )


def _django_uow_key(using: object) -> str:
    if type(using) is not str or not using.strip():
        raise ValueError("R4 research-control database alias is invalid")
    return f"django:{using}"


__all__ = [
    "DjangoR4ResearchControlRuntime",
    "build_django_r4_research_control_runtime",
]
