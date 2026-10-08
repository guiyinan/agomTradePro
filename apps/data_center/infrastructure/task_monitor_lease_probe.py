"""Read-only Task Monitor lease probe for Data Center task contracts."""

from collections.abc import Mapping

from django.core.cache import cache
from django.core.cache.backends.base import BaseCache

from apps.data_center.application.financial_refresh_lease import (
    FINANCIAL_REFRESH_LOCK_KEY,
)
from apps.data_center.application.full_market_refresh_lease import (
    FULL_MARKET_REFRESH_LOCK_KEY,
)
from shared.domain.task_lease_evidence import (
    DomainTaskLeaseEvidence,
    DomainTaskLeaseProbeProtocol,
    DomainTaskLeaseState,
)

_FINANCIAL_REFRESH_TASK = "data_center.refresh_financial_publications_batch"
_FULL_MARKET_REFRESH_TASK = "data_center.refresh_full_market_publications"


class DjangoDataCenterTaskLeaseProbe(DomainTaskLeaseProbeProtocol):
    """Inspect Data Center's two shared task locks without mutating either one."""

    def __init__(self, cache_backend: BaseCache | None = None) -> None:
        self.cache_backend = cache_backend if cache_backend is not None else cache

    def supports_task_name(self, task_name: str) -> bool:
        """Identify Data Center task names that hold shared cache leases."""

        return task_name in {_FINANCIAL_REFRESH_TASK, _FULL_MARKET_REFRESH_TASK}

    def get_lease_evidence(
        self,
        *,
        task_name: str,
        task_kwargs: Mapping[str, object],
    ) -> DomainTaskLeaseEvidence:
        """Return the exact lease state for a Data Center task attempt."""

        if task_name == _FULL_MARKET_REFRESH_TASK:
            return self._full_market_lease_evidence()
        if task_name == _FINANCIAL_REFRESH_TASK:
            return self._financial_lease_evidence(task_kwargs)
        return DomainTaskLeaseEvidence(
            state=DomainTaskLeaseState.UNKNOWN,
            evidence_code="data_center_lease_task_unrecognized",
        )

    def _full_market_lease_evidence(self) -> DomainTaskLeaseEvidence:
        """A missing task-wide key proves no full-market refresh holds its lease."""

        try:
            owner: object = self.cache_backend.get(FULL_MARKET_REFRESH_LOCK_KEY)
        except Exception:
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="full_market_refresh_lease_unavailable",
            )
        if owner is None:
            state = DomainTaskLeaseState.ABSENT
            code = "full_market_refresh_lease_absent"
        elif isinstance(owner, str) and owner:
            state = DomainTaskLeaseState.ACTIVE
            code = "full_market_refresh_lease_present"
        else:
            state = DomainTaskLeaseState.UNKNOWN
            code = "full_market_refresh_lease_invalid"
        return DomainTaskLeaseEvidence(state=state, evidence_code=code)

    def _financial_lease_evidence(
        self,
        task_kwargs: Mapping[str, object],
    ) -> DomainTaskLeaseEvidence:
        """Check the persisted lease against the exact workflow owner in kwargs."""

        workflow_id = task_kwargs.get("workflow_id")
        if (
            not isinstance(workflow_id, str)
            or not workflow_id
            or len(workflow_id) > 64
            or any(character.isspace() for character in workflow_id)
        ):
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="financial_refresh_workflow_id_unavailable",
            )
        try:
            owner: object = self.cache_backend.get(FINANCIAL_REFRESH_LOCK_KEY)
        except Exception:
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="financial_refresh_lease_unavailable",
            )
        if owner is not None and not isinstance(owner, str):
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="financial_refresh_lease_invalid",
            )
        active = owner == workflow_id
        return DomainTaskLeaseEvidence(
            state=(DomainTaskLeaseState.ACTIVE if active else DomainTaskLeaseState.ABSENT),
            evidence_code=(
                "financial_refresh_workflow_lease_present"
                if active
                else "financial_refresh_workflow_lease_absent"
            ),
        )
