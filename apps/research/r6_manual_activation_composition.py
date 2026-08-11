"""Using-only production composition for the R6 manual-activation preflight."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.r6_manual_activation_adapters import (
    R6ActivationScopeExactAdapter,
    R6ActivationStateExactAdapter,
    R6LatestActiveQualificationExactAdapter,
    R6LatestActiveQualificationRefSource,
    R6LatestCompleteMonitoringExactAdapter,
)
from apps.research.application.r6_manual_activation_preflight import (
    EvaluateR6ManualActivationPreflight,
)
from apps.research.domain.state_model_activation import R6ActivationScope
from apps.research.infrastructure.r6_manual_activation_queries import (
    DjangoR6ActiveQualificationExactQuery,
)
from apps.research.infrastructure.state_model_activation_repository import (
    DjangoR6ActivationRepository,
)
from apps.research.infrastructure.state_model_monitoring_repository import (
    DjangoR6MonitoringRepository,
)


class _UnavailableCanonicalScopeOwner(R6LatestActiveQualificationRefSource):
    """Explicit gap: no existing ledger canonically owns R6 activation scopes."""

    __slots__ = ("_unit_of_work_key",)

    def __init__(self, *, using: str) -> None:
        if type(using) is not str or not using.strip():
            raise ValueError("R6 manual activation database alias is invalid")
        self._unit_of_work_key = f"django:{using}"

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact(self, *, scope_id: str, as_of: datetime) -> None:
        """Return absence without fixtures, defaults, or assessment backfilling."""

        del scope_id, as_of
        return None

    def get_latest_active_ref(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> None:
        """Return no inferred scope-to-qualification binding."""

        del scope, as_of
        return None


@dataclass(frozen=True, slots=True)
class DjangoR6ManualActivationRuntime:
    """Read-only runtime with no mutation, current, consumer, or execution port."""

    preflight: EvaluateR6ManualActivationPreflight


def build_django_r6_manual_activation_runtime(
    *,
    using: str = "default",
) -> DjangoR6ManualActivationRuntime:
    """Build exact ledger adapters and block on the missing scope owner."""

    scope_owner = _UnavailableCanonicalScopeOwner(using=using)
    monitoring_repository = DjangoR6MonitoringRepository(using=using)
    activation_repository = DjangoR6ActivationRepository(using=using)
    qualification_query = DjangoR6ActiveQualificationExactQuery(using=using)
    return DjangoR6ManualActivationRuntime(
        preflight=EvaluateR6ManualActivationPreflight(
            scope_provider=R6ActivationScopeExactAdapter(scope_owner),
            qualification_provider=R6LatestActiveQualificationExactAdapter(
                ref_source=scope_owner,
                exact_query=qualification_query,
            ),
            monitoring_provider=R6LatestCompleteMonitoringExactAdapter(monitoring_repository),
            activation_state_provider=R6ActivationStateExactAdapter(activation_repository),
            unit_of_work=monitoring_repository,
        )
    )


__all__ = [
    "DjangoR6ManualActivationRuntime",
    "build_django_r6_manual_activation_runtime",
]
