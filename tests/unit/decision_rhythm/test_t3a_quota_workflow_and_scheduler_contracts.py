"""T3A decision quota, state-machine, and scheduler boundary contracts."""

import argparse
from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.decision_rhythm.application.decision_quota_use_cases import (
    GetDecisionQueueUseCase,
    GetQuotaStatusRequest,
    GetQuotaStatusUseCase,
    GetRhythmSummaryRequest,
    GetRhythmSummaryUseCase,
    ResetQuotaRequest,
    ResetQuotaUseCase,
    SubmitBatchRequestRequest,
    SubmitBatchRequestUseCase,
    SubmitDecisionRequestRequest,
    SubmitDecisionRequestUseCase,
)
from apps.decision_rhythm.domain.entities import (
    ApprovalStatus,
    DecisionPriority,
    DecisionResponse,
    QuotaPeriod,
)
from apps.decision_rhythm.domain.workflow_services import (
    ApprovalStatusStateMachine,
    CandidateStatusStateMachine,
    ExecutionResult,
    ExecutionStatusStateMachine,
    PrecheckResult,
)
from apps.decision_rhythm.management.commands import setup_workspace_snapshot_refresh


def _submit_request(
    *,
    asset_code: str = "000001.SZ",
    priority: DecisionPriority = DecisionPriority.HIGH,
) -> SubmitDecisionRequestRequest:
    return SubmitDecisionRequestRequest(
        asset_code=asset_code,
        asset_class="equity",
        direction="BUY",
        priority=priority,
        trigger_id="trigger-1",
        candidate_id="candidate-1",
        reason="quality signal",
        expected_confidence=0.8,
        quantity=100,
        notional=1000.0,
        quota_period=QuotaPeriod.WEEKLY,
    )


class _EventBus:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


class _RhythmManager:
    def __init__(self, *, approved: bool = True, fail: bool = False) -> None:
        self.approved = approved
        self.fail = fail

    def submit_request(self, request: object, _period: QuotaPeriod) -> DecisionResponse:
        if self.fail:
            raise RuntimeError("rhythm unavailable")
        return DecisionResponse(
            request_id=request.request_id,  # type: ignore[attr-defined]
            approved=self.approved,
            approval_reason="quota available" if self.approved else "",
            rejection_reason=None if self.approved else "quota exhausted",
        )

    def submit_batch(
        self,
        requests: list[object],
        period: QuotaPeriod,
    ) -> list[DecisionResponse]:
        if self.fail:
            raise RuntimeError("batch unavailable")
        return [
            (
                self.submit_request(request, period)
                if index == 0
                else DecisionResponse(
                    request_id=request.request_id,  # type: ignore[attr-defined]
                    approved=False,
                    approval_reason="",
                    rejection_reason="cooldown",
                )
            )
            for index, request in enumerate(requests)
        ]

    def get_summary(self) -> dict[str, int]:
        if self.fail:
            raise RuntimeError("summary unavailable")
        return {"pending": 2}


@pytest.mark.parametrize("approved", [True, False])
def test_submit_decision_publishes_explicit_business_outcome(approved: bool) -> None:
    event_bus = _EventBus()
    result = SubmitDecisionRequestUseCase(
        _RhythmManager(approved=approved),
        event_bus,
    ).execute(_submit_request())

    assert result.success is True
    assert result.response is not None
    assert result.response.approved is approved
    assert result.decision_request is not None
    assert result.decision_request.candidate_id == "candidate-1"
    assert len(event_bus.events) == 1
    assert event_bus.events[0].payload["approved"] is approved  # type: ignore[attr-defined]


def test_submit_decision_dependency_failure_is_reported_without_event() -> None:
    event_bus = _EventBus()

    result = SubmitDecisionRequestUseCase(
        _RhythmManager(fail=True),
        event_bus,
    ).execute(_submit_request())

    assert result.success is False
    assert result.error == "rhythm unavailable"
    assert event_bus.events == []


def test_submit_decision_without_event_bus_keeps_success_local() -> None:
    result = SubmitDecisionRequestUseCase(_RhythmManager()).execute(_submit_request())

    assert result.success is True


def test_batch_submission_reports_partial_business_summary_and_event() -> None:
    event_bus = _EventBus()
    request = SubmitBatchRequestRequest(
        requests=[
            _submit_request(asset_code="000001.SZ", priority=DecisionPriority.CRITICAL),
            _submit_request(asset_code="600000.SH", priority=DecisionPriority.MEDIUM),
        ]
    )

    result = SubmitBatchRequestUseCase(_RhythmManager(), event_bus).execute(request)

    assert result.success is True
    assert len(result.decision_requests) == 2
    assert result.summary == {
        "total": 2,
        "approved": 1,
        "rejected": 1,
        "approval_rate": 0.5,
    }
    assert event_bus.events[0].payload["rejected"] == 1  # type: ignore[attr-defined]


def test_batch_submission_empty_and_failure_contracts() -> None:
    empty = SubmitBatchRequestUseCase(_RhythmManager()).execute(
        SubmitBatchRequestRequest(requests=[])
    )
    failed = SubmitBatchRequestUseCase(_RhythmManager(fail=True)).execute(
        SubmitBatchRequestRequest(requests=[_submit_request()])
    )

    assert empty.summary["approval_rate"] == 0
    assert failed.success is False
    assert failed.error == "batch unavailable"


class _QuotaManager:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.reset: list[QuotaPeriod | str] = []

    def get_quota_status(self, period: QuotaPeriod) -> dict[str, object]:
        if self.fail:
            raise RuntimeError("quota unavailable")
        return {"period": period.value, "remaining": 2}

    def reset_all_quotas(self) -> None:
        if self.fail:
            raise RuntimeError("reset unavailable")
        self.reset.append("all")

    def _reset_quota(self, period: QuotaPeriod) -> None:
        if self.fail:
            raise RuntimeError("reset unavailable")
        self.reset.append(period)


def test_quota_status_summary_queue_and_dependency_failures() -> None:
    success = GetQuotaStatusUseCase(_QuotaManager()).execute(
        GetQuotaStatusRequest(QuotaPeriod.DAILY)
    )
    failure = GetQuotaStatusUseCase(_QuotaManager(fail=True)).execute(GetQuotaStatusRequest())
    summary = GetRhythmSummaryUseCase(_RhythmManager()).execute(GetRhythmSummaryRequest())
    broken_summary = GetRhythmSummaryUseCase(_RhythmManager(fail=True)).execute(
        GetRhythmSummaryRequest()
    )
    queue = GetDecisionQueueUseCase(
        SimpleNamespace(get_queue_summary=lambda: {"queued": 3})
    ).execute()

    assert success.status == {"period": "daily", "remaining": 2}
    assert failure.error == "quota unavailable"
    assert summary.summary == {"pending": 2}
    assert broken_summary.error == "summary unavailable"
    assert queue == {"queued": 3}


@pytest.mark.parametrize("period", [None, QuotaPeriod.MONTHLY])
def test_reset_quota_publishes_scope(period: QuotaPeriod | None) -> None:
    manager = _QuotaManager()
    bus = _EventBus()

    result = ResetQuotaUseCase(manager, bus).execute(ResetQuotaRequest(period))

    assert result.success is True
    assert manager.reset == [period or "all"]
    assert bus.events[0].payload["period"] == (period.value if period else "all")  # type: ignore[attr-defined]


def test_reset_quota_failure_is_observable() -> None:
    result = ResetQuotaUseCase(_QuotaManager(fail=True)).execute(ResetQuotaRequest())

    assert result.success is False
    assert result.error == "reset unavailable"


@pytest.mark.parametrize(
    ("errors", "candidate_valid", "expected"),
    [([], True, True), (["quota"], True, False), ([], False, False)],
)
def test_precheck_requires_no_errors_and_valid_candidate(
    errors: list[str],
    candidate_valid: bool,
    expected: bool,
) -> None:
    assert (
        PrecheckResult(
            candidate_id="candidate-1",
            errors=errors,
            candidate_valid=candidate_valid,
        ).can_proceed
        is expected
    )


@pytest.mark.parametrize(
    ("from_status", "to_status", "expected"),
    [
        ("PENDING", "EXECUTED", True),
        ("PENDING", "FAILED", True),
        ("FAILED", "CANCELLED", True),
        ("EXECUTED", "PENDING", False),
        ("UNKNOWN", "FAILED", False),
        ("PENDING", "PENDING", True),
    ],
)
def test_execution_state_machine_covers_allowed_terminal_and_unknown_states(
    from_status: str,
    to_status: str,
    expected: bool,
) -> None:
    assert ExecutionStatusStateMachine.can_transition(from_status, to_status) is expected
    valid, reason = ExecutionStatusStateMachine.validate_transition(from_status, to_status)
    assert valid is expected
    assert (reason == "") is expected


@pytest.mark.parametrize(
    ("from_status", "to_status", "via_api", "expected"),
    [
        ("ACTIONABLE", "EXECUTED", True, True),
        ("ACTIONABLE", "EXECUTED", False, False),
        ("CANDIDATE", "EXECUTED", True, False),
        ("WATCH", "ACTIONABLE", False, True),
        ("EXECUTED", "CANCELLED", False, False),
    ],
)
def test_candidate_state_machine_requires_execution_api(
    from_status: str,
    to_status: str,
    via_api: bool,
    expected: bool,
) -> None:
    valid, reason = CandidateStatusStateMachine.validate_transition(
        from_status,
        to_status,
        via_api=via_api,
    )
    assert valid is expected
    assert CandidateStatusStateMachine.can_execute(from_status) is (from_status == "ACTIONABLE")
    assert (reason == "") is expected


def test_candidate_state_machine_allows_same_state_idempotently() -> None:
    assert CandidateStatusStateMachine.can_transition("WATCH", "WATCH") is True


@pytest.mark.parametrize(
    ("from_status", "to_status", "expected"),
    [
        (ApprovalStatus.DRAFT, ApprovalStatus.PENDING, True),
        (ApprovalStatus.PENDING, ApprovalStatus.APPROVED, True),
        (ApprovalStatus.FAILED, ApprovalStatus.PENDING, True),
        (ApprovalStatus.REJECTED, ApprovalStatus.APPROVED, False),
        (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED, True),
    ],
)
def test_approval_state_machine_covers_retry_and_terminal_states(
    from_status: ApprovalStatus,
    to_status: ApprovalStatus,
    expected: bool,
) -> None:
    valid, reason = ApprovalStatusStateMachine.validate_transition(
        from_status,
        to_status,
    )
    assert valid is expected
    assert (reason == "") is expected
    assert ApprovalStatusStateMachine.get_valid_next_statuses(from_status) == (
        ApprovalStatusStateMachine.ALLOWED_TRANSITIONS[from_status]
    )


def test_execution_result_success_is_explicit() -> None:
    assert ExecutionResult("request-1", "EXECUTED").is_success is True
    assert ExecutionResult("request-2", "FAILED", error="boom").is_success is False


def test_scheduler_command_validates_clock_and_persists_enabled_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_module = setup_workspace_snapshot_refresh
    crontab = object()
    get_or_create = Mock(return_value=(crontab, True))
    update_or_create = Mock()
    changed = Mock()
    monkeypatch.setattr(command_module.transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        command_module.CrontabSchedule,
        "objects",
        SimpleNamespace(get_or_create=get_or_create),
    )
    monkeypatch.setattr(
        command_module.PeriodicTask,
        "objects",
        SimpleNamespace(update_or_create=update_or_create),
    )
    monkeypatch.setattr(command_module.PeriodicTasks, "changed", changed)
    stdout = StringIO()
    stderr = StringIO()
    command = command_module.Command(stdout=stdout, stderr=stderr)

    command.handle(hour=22, minute=45, disable=False)

    defaults = update_or_create.call_args.kwargs["defaults"]
    assert defaults["enabled"] is True
    assert defaults["crontab"] is crontab
    assert '"use_pit": true' in defaults["kwargs"]
    changed.assert_called_once_with(command_module.PeriodicTask)
    assert "enabled @ 22:45" in stdout.getvalue()

    command.handle(hour=-1, minute=45, disable=False)
    command.handle(hour=22, minute=60, disable=False)
    assert "--hour must be between 0 and 23" in stderr.getvalue()
    assert "--minute must be between 0 and 59" in stderr.getvalue()


def test_scheduler_command_argument_defaults_are_explicit() -> None:
    parser = argparse.ArgumentParser()
    setup_workspace_snapshot_refresh.Command().add_arguments(parser)

    options = parser.parse_args([])

    assert options.hour == 22
    assert options.minute == 45
    assert options.disable is False
