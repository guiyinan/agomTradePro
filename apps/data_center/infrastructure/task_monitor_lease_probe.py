"""Read-only Task Monitor lease probe for Data Center task contracts."""

from collections.abc import Mapping
from uuid import UUID

from django.core.cache import cache
from django.core.cache.backends.base import BaseCache
from django.utils import timezone

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityCheckpoint,
)
from apps.data_center.application.financial_refresh_lease import (
    FINANCIAL_REFRESH_LOCK_KEY,
)
from apps.data_center.application.full_market_refresh_lease import (
    FULL_MARKET_REFRESH_LOCK_KEY,
)
from apps.data_center.infrastructure.financial_capacity_checkpoint_repository import (
    DjangoFinancialCapacityCheckpointRepository,
)
from shared.domain.task_lease_evidence import (
    DomainTaskLeaseEvidence,
    DomainTaskLeaseProbeProtocol,
    DomainTaskLeaseState,
)

_FINANCIAL_REFRESH_TASK = "data_center.refresh_financial_publications_batch"
_FINANCIAL_CAPACITY_TASK = "data_center.refresh_financial_publication_capacity"
_FULL_MARKET_REFRESH_TASK = "data_center.refresh_full_market_publications"
_FINANCIAL_CAPACITY_ACTIONS = frozenset(
    {
        "qualification_start",
        "qualification_run",
        "capacity_rehearsal_start",
        "capacity_rehearsal_run",
        "formal_start",
        "formal_run",
    }
)


class DjangoDataCenterTaskLeaseProbe(DomainTaskLeaseProbeProtocol):
    """Inspect Data Center task leases and workflow claims without mutating them."""

    def __init__(self, cache_backend: BaseCache | None = None) -> None:
        self.cache_backend = cache_backend if cache_backend is not None else cache

    def supports_task_name(self, task_name: str) -> bool:
        """Identify Data Center task names that hold shared cache leases."""

        return task_name in {
            _FINANCIAL_REFRESH_TASK,
            _FINANCIAL_CAPACITY_TASK,
            _FULL_MARKET_REFRESH_TASK,
        }

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
        if task_name == _FINANCIAL_CAPACITY_TASK:
            return self._financial_capacity_lease_evidence(task_kwargs)
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

    def _financial_capacity_lease_evidence(
        self,
        task_kwargs: Mapping[str, object],
    ) -> DomainTaskLeaseEvidence:
        """Read the exact durable checkpoint and its in-flight slice claim."""

        action = task_kwargs.get("action")
        workflow_id = task_kwargs.get("workflow_id")
        if (
            not isinstance(action, str)
            or action not in _FINANCIAL_CAPACITY_ACTIONS
            or not isinstance(workflow_id, str)
            or not workflow_id
            or len(workflow_id) > 300
            or any(character.isspace() for character in workflow_id)
        ):
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="financial_capacity_workflow_identity_unavailable",
            )
        try:
            checkpoint = DjangoFinancialCapacityCheckpointRepository().get(workflow_id)
        except Exception:
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="financial_capacity_checkpoint_unavailable",
            )
        if checkpoint is None:
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="financial_capacity_checkpoint_missing",
            )
        if checkpoint.workflow_id != workflow_id:
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="financial_capacity_checkpoint_identity_mismatch",
            )

        claim_values = (
            checkpoint.in_flight_slice_index,
            checkpoint.in_flight_claim_token,
            checkpoint.in_flight_claim_expires_at,
        )
        if any(value is not None for value in claim_values):
            if self._has_valid_active_capacity_claim(checkpoint):
                return DomainTaskLeaseEvidence(
                    state=DomainTaskLeaseState.ACTIVE,
                    evidence_code="financial_capacity_inflight_claim_present",
                )
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.UNKNOWN,
                evidence_code="financial_capacity_inflight_outcome_indeterminate",
            )

        finished_at = checkpoint.finished_at
        has_indeterminate_outcome = (
            checkpoint.blocked_reason is not None
            and checkpoint.blocked_reason.endswith("_outcome_indeterminate")
        ) or any(
            error_code.endswith("_outcome_indeterminate") for error_code in checkpoint.error_codes
        )
        if (
            checkpoint.status in {"success", "partial", "failed", "blocked"}
            and finished_at is not None
            and finished_at.tzinfo is not None
            and finished_at.utcoffset() is not None
            and checkpoint.started_at.tzinfo is not None
            and checkpoint.started_at.utcoffset() is not None
            and finished_at >= checkpoint.started_at
            and self._is_uuid(checkpoint.run_id)
            and not has_indeterminate_outcome
        ):
            return DomainTaskLeaseEvidence(
                state=DomainTaskLeaseState.ABSENT,
                evidence_code="financial_capacity_checkpoint_terminal",
            )
        return DomainTaskLeaseEvidence(
            state=DomainTaskLeaseState.UNKNOWN,
            evidence_code="financial_capacity_checkpoint_not_terminal",
        )

    @staticmethod
    def _has_valid_active_capacity_claim(checkpoint: FinancialCapacityCheckpoint) -> bool:
        """Require the persisted claim to match a live running workflow slice."""

        index = checkpoint.in_flight_slice_index
        token = checkpoint.in_flight_claim_token
        expires_at = checkpoint.in_flight_claim_expires_at
        if (
            type(index) is not int
            or not 0 <= index < checkpoint.manifest_count
            or checkpoint.next_slice_index != index
            or not isinstance(token, str)
            or not DjangoDataCenterTaskLeaseProbe._is_uuid(token)
            or expires_at is None
            or expires_at.tzinfo is None
            or expires_at.utcoffset() is None
            or expires_at <= timezone.now()
            or checkpoint.status != "running"
            or checkpoint.finished_at is not None
            or checkpoint.started_at.tzinfo is None
            or checkpoint.started_at.utcoffset() is None
            or not DjangoDataCenterTaskLeaseProbe._is_uuid(checkpoint.run_id)
        ):
            return False
        return True

    @staticmethod
    def _is_uuid(value: object) -> bool:
        """Return whether a value is a canonical UUID string."""

        if not isinstance(value, str):
            return False
        try:
            return str(UUID(value)) == value
        except (ValueError, AttributeError):
            return False
