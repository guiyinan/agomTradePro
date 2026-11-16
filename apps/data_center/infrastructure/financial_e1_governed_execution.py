"""Existing DATA02 actor, simulated-account owner, and Run adapters for finite E1."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from django.db import DatabaseError
from django.utils import timezone

from apps.data_center.application.control_plane import StartSyncRunUseCase
from apps.data_center.application.data02_task_authority import (
    Data02AuthorityLatch,
    preflight_data02_task_authority,
)
from apps.data_center.application.financial_e1_discovery_runner import (
    FinancialE1DiscoveryRunResult,
    FinancialE1ExecutionAuthorityPort,
)
from apps.data_center.domain.control_plane import SyncRun, SyncRunStatus
from apps.data_center.domain.financial_e1_execution_plan import (
    FinancialE1PinnedExecutionPlan,
)
from apps.data_center.infrastructure.control_plane_repositories import SyncRunRepository
from core.exceptions import DataValidationError
from core.integration.data_center_audit import SystemAuditReaderContext
from core.integration.financial_e1_simulated_account_owner import (
    FinancialE1SimulatedAccountBindingObservation,
    resolve_financial_e1_simulated_account_binding,
)


class DjangoFinancialE1ActorSimulatedAccountGuard(FinancialE1ExecutionAuthorityPort):
    """Recheck DATA02 authority and the actual simulated-account owner per boundary."""

    def __init__(
        self,
        authority: SystemAuditReaderContext,
        *,
        simulated_account_id: int,
        authority_latch: Data02AuthorityLatch | None = None,
    ) -> None:
        """Bind only an issued authority context and the pinned simulated-account id."""

        if type(authority) is not SystemAuditReaderContext:
            raise TypeError("E1 requires the issued SystemAudit reader context")
        if type(simulated_account_id) is not int or simulated_account_id <= 0:
            raise ValueError("E1 simulated_account_id must be a positive persisted identifier")
        if (
            authority.actor_id != f"django-user:{authority.user_id}"
            or not authority.is_authenticated
            or not authority.is_staff
        ):
            raise DataValidationError(
                "The current DATA02 authority is not bound to an authenticated staff actor.",
                code="FINANCIAL_E1_TASK_AUTHORITY_BLOCKED",
            )
        self._authority = authority
        self._simulated_account_id = simulated_account_id
        self._latch = authority_latch or Data02AuthorityLatch(authority)
        self._assert_simulated_account_owner()

    def assert_current(self) -> None:
        """Revalidate DATA02 and the current simulated-account binding per boundary."""

        now = timezone.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise DataValidationError(
                "The E1 authority clock is not timezone-aware.",
                code="FINANCIAL_E1_TASK_AUTHORITY_BLOCKED",
            )
        if not self._latch.allows_next_write(as_of=now):
            raise DataValidationError(
                "The DATA02 task authority is no longer current.",
                code="FINANCIAL_E1_TASK_AUTHORITY_BLOCKED",
            )
        self._assert_simulated_account_owner()

    def _assert_simulated_account_owner(self) -> None:
        """Require the exact active simulated account belongs to the task actor."""

        try:
            observation: FinancialE1SimulatedAccountBindingObservation | None = (
                resolve_financial_e1_simulated_account_binding(
                    user_id=self._authority.user_id,
                    account_id=self._simulated_account_id,
                )
            )
        except (DatabaseError, LookupError, PermissionError, TypeError, ValueError) as error:
            raise DataValidationError(
                "The pinned simulated account cannot be resolved for the DATA02 actor.",
                code="FINANCIAL_E1_SIMULATED_ACCOUNT_OWNER_BLOCKED",
            ) from error
        if (
            observation is None
            or type(observation) is not FinancialE1SimulatedAccountBindingObservation
            or observation.is_simulated is not True
            or observation.is_active is not True
            or observation.account_id != self._simulated_account_id
            or observation.owner_user_id != self._authority.user_id
        ):
            raise DataValidationError(
                "The pinned active simulated account is not owned by the current DATA02 actor.",
                code="FINANCIAL_E1_SIMULATED_ACCOUNT_OWNER_BLOCKED",
            )


def preflight_django_financial_e1_actor_simulated_account(
    *,
    expected_actor: str,
    simulated_account_id: int,
) -> DjangoFinancialE1ActorSimulatedAccountGuard:
    """Use existing DATA02 preflight and the simulated-account binding query."""

    if (
        type(expected_actor) is not str
        or not expected_actor
        or expected_actor != expected_actor.strip()
        or len(expected_actor) > 192
        or any(marker in expected_actor for marker in ("\r", "\n"))
    ):
        raise ValueError("operator must be the exact current server actor identity")
    now = timezone.now()
    authority, failure = preflight_data02_task_authority(
        as_of=now,
        minimum_window=timedelta(seconds=300),
        expected_actor=expected_actor,
    )
    if failure is not None or authority is None:
        reason = (failure or {}).get("blocked_reason")
        raise DataValidationError(
            f"The current DATA02 task authority is unavailable ({reason or 'unknown'}).",
            code="FINANCIAL_E1_TASK_AUTHORITY_BLOCKED",
        )
    guard = DjangoFinancialE1ActorSimulatedAccountGuard(
        authority,
        simulated_account_id=simulated_account_id,
    )
    guard.assert_current()
    return guard


def start_django_financial_e1_sync_run(
    pinned_plan: FinancialE1PinnedExecutionPlan,
    *,
    authority_guard: FinancialE1ExecutionAuthorityPort,
) -> SyncRun:
    """Persist one real SyncRun before any provider request is attempted."""

    if type(pinned_plan) is not FinancialE1PinnedExecutionPlan:
        raise TypeError("E1 run start requires the externally pinned typed plan")
    authority_guard.assert_current()
    plan = pinned_plan.discovery_plan
    run = StartSyncRunUseCase(SyncRunRepository()).execute(
        dataset_key=plan.main_request.dataset_key,
        trigger="financial_e1_discovery",
        requested=len(plan.qualification_identities),
        provider_name=plan.provider_name,
        contract_version="financial-e1-discovery.v2",
        config_snapshot_hash=pinned_plan.plan_file_sha256,
    )
    if (
        type(run) is not SyncRun
        or run.dataset_key != plan.main_request.dataset_key
        or run.provider_name != plan.provider_name
        or run.requested != len(plan.qualification_identities)
        or run.config_snapshot_hash != pinned_plan.plan_file_sha256
        or run.status is not SyncRunStatus.REQUESTED
    ):
        raise DataValidationError(
            "The persisted E1 SyncRun does not match the pinned plan.",
            code="FINANCIAL_E1_RUN_IDENTITY_INVALID",
        )
    authority_guard.assert_current()
    fetching = replace(run, status=SyncRunStatus.FETCHING)
    persisted = SyncRunRepository().save(fetching)
    if persisted != fetching:
        raise DataValidationError(
            "The E1 SyncRun could not enter its fetch state exactly.",
            code="FINANCIAL_E1_RUN_IDENTITY_INVALID",
        )
    return persisted


def finish_django_financial_e1_non_success_run(
    run: SyncRun,
    result: FinancialE1DiscoveryRunResult,
    *,
    authority_guard: FinancialE1ExecutionAuthorityPort,
) -> SyncRun:
    """Persist terminal blocked/failed/partial outcome through SyncRunRepository."""

    if type(run) is not SyncRun or type(result) is not FinancialE1DiscoveryRunResult:
        raise TypeError("E1 run finalization requires typed run and result values")
    if result.outcome == "stored":
        raise ValueError("successful E1 runs are finalized inside their fact/audit UOW")
    authority_guard.assert_current()
    status = SyncRunStatus.BLOCKED if result.outcome == "blocked" else SyncRunStatus.FAILED
    outcome = "partial" if result.outcome == "partial" else result.outcome
    finished = replace(
        run,
        status=status,
        outcome=outcome,
        fetched=result.physical_attempts,
        validated=result.succeeded,
        succeeded=result.succeeded,
        failed=result.failed,
        stored=result.stored,
        finished_at=timezone.now(),
        error_code=result.failure_code or "FINANCIAL_E1_EXECUTION_FAILED",
    )
    persisted = SyncRunRepository().save(finished)
    if persisted != finished:
        raise DataValidationError(
            "The terminal E1 SyncRun did not persist exactly.",
            code="FINANCIAL_E1_RUN_FINALIZATION_INVALID",
        )
    return persisted


__all__ = [
    "DjangoFinancialE1ActorSimulatedAccountGuard",
    "finish_django_financial_e1_non_success_run",
    "preflight_django_financial_e1_actor_simulated_account",
    "start_django_financial_e1_sync_run",
]
