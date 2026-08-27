"""RED contracts for recording publication-bound decision-read outcomes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.audit.application.data_decision_read_audit import DataDecisionReadAuditObservation
from apps.audit.application.data_freshness_audit import DataFreshnessAuditObservation
from apps.audit.domain.system_audit_event import AuditOutcome
from apps.data_center.application.decision_read_audit import (
    DecisionReadAuditUnavailable,
    RecordPublicationDecisionReadCommand,
    RecordPublicationDecisionReadUseCase,
)
from apps.data_center.application.dtos import SyncResult

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _result(
    *,
    status: str = "success",
    run_id: str | None = "run-1",
    ingested_run_id: str | None = "ingested-1",
    publication_id: str | None = "publication-1",
    publication_version: str | None = "1.0:1.0",
    publication_hash: str | None = "b" * 64,
    error_message: str = "",
) -> SyncResult:
    """Build one result carrying the intended canonical chain identity."""

    return SyncResult(
        domain="equity.price.bar",
        provider_name="provider-main",
        stored_count=1 if status == "success" else 0,
        status=status,
        error_message=error_message,
        run_id=run_id,
        ingested_run_id=ingested_run_id,
        publication_id=publication_id,
        publication_version=publication_version,
        publication_hash=publication_hash,
    )


def _command(
    result: SyncResult,
    *,
    freshness_status: str = "fresh",
    must_not_use_for_decision: bool = False,
    blocked_reason: str | None = None,
) -> RecordPublicationDecisionReadCommand:
    """Build one publication decision-read command."""

    return RecordPublicationDecisionReadCommand(
        sync_result=result,
        dataset_key="equity.price.bar",
        publication_key="current",
        decision_key="portfolio-readiness",
        freshness_status=freshness_status,
        must_not_use_for_decision=must_not_use_for_decision,
        blocked_reason=blocked_reason,
    )


class _Clock:
    def now(self) -> datetime:
        return NOW


class _NaiveClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 27, 12, 0)


class _Writer:
    def __init__(self) -> None:
        self.observations: list[DataDecisionReadAuditObservation] = []
        self.error: Exception | None = None

    def write(self, observation: DataDecisionReadAuditObservation) -> object:
        if self.error is not None:
            raise self.error
        self.observations.append(observation)
        return object()


class _FreshnessWriter:
    def __init__(self) -> None:
        self.observations: list[DataFreshnessAuditObservation] = []
        self.error: Exception | None = None

    def write(self, observation: DataFreshnessAuditObservation) -> object:
        if self.error is not None:
            raise self.error
        self.observations.append(observation)
        return object()


def _recorder(
    writer: _Writer | None = None,
    clock: _Clock | _NaiveClock | None = None,
    freshness_writer: _FreshnessWriter | None = None,
) -> RecordPublicationDecisionReadUseCase:
    """Build the recorder with both required audit writers."""

    return RecordPublicationDecisionReadUseCase(
        writer or _Writer(),
        clock or _Clock(),
        freshness_writer=freshness_writer or _FreshnessWriter(),
    )


def test_success_writes_recovered_observation_with_exact_result_identity() -> None:
    writer = _Writer()
    freshness_writer = _FreshnessWriter()
    result = _result()

    returned = _recorder(writer, freshness_writer=freshness_writer).execute(_command(result))

    assert returned is not None
    observation = writer.observations[0]
    assert observation.outcome is AuditOutcome.RECOVERED
    assert observation.run_id == result.run_id
    assert observation.ingested_run_id == result.ingested_run_id
    assert observation.publication_id == result.publication_id
    assert observation.publication_version == result.publication_version
    assert observation.publication_hash == result.publication_hash
    assert observation.provider_key == result.provider_name
    assert observation.occurred_at == NOW
    assert observation.recorded_at == NOW
    assert observation.blocked_reason is None
    freshness = freshness_writer.observations[0]
    assert freshness.freshness_status == "fresh"
    assert freshness.must_not_use_for_decision is False
    assert freshness.publication_id == result.publication_id
    assert freshness.publication_hash == result.publication_hash


def test_blocked_result_writes_stable_blocked_observation_without_error_text() -> None:
    writer = _Writer()
    freshness_writer = _FreshnessWriter()
    result = _result(status="blocked", error_message="secret response token")

    _recorder(writer, freshness_writer=freshness_writer).execute(
        _command(
            result,
            freshness_status="stale",
            must_not_use_for_decision=True,
            blocked_reason="publication_stale",
        )
    )

    observation = writer.observations[0]
    assert observation.outcome is AuditOutcome.BLOCKED
    assert observation.blocked_reason == "publication_stale"
    assert "secret response token" not in str(observation)
    assert "error_message" not in str(observation)
    assert freshness_writer.observations[0].must_not_use_for_decision is True
    assert freshness_writer.observations[0].blocked_reason == "publication_stale"


def test_noop_without_publication_returns_none_without_writing() -> None:
    writer = _Writer()
    freshness_writer = _FreshnessWriter()

    returned = _recorder(writer, freshness_writer=freshness_writer).execute(
        _command(
            _result(
                status="noop",
                run_id="run-noop",
                ingested_run_id="ingested-noop",
                publication_id=None,
                publication_version=None,
                publication_hash=None,
            )
        )
    )

    assert returned is None
    assert writer.observations == []
    assert freshness_writer.observations == []


@pytest.mark.parametrize(
    "result,kwargs",
    [
        (_result(run_id=None), {}),
        (_result(ingested_run_id=None), {}),
        (_result(publication_id=None), {}),
        (_result(publication_version=None), {}),
        (_result(publication_hash=None), {}),
        (_result(status="blocked"), {"must_not_use_for_decision": True}),
        (_result(), {"freshness_status": "stale", "must_not_use_for_decision": True}),
        (_result(), {"blocked_reason": "bad reason", "must_not_use_for_decision": True}),
    ],
)
def test_success_or_blocked_identity_and_reason_requirements_fail_closed(
    result: SyncResult,
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(DecisionReadAuditUnavailable):
        _recorder().execute(_command(result, **kwargs))


def test_naive_clock_and_writer_failures_are_not_hidden() -> None:
    with pytest.raises(DecisionReadAuditUnavailable):
        _recorder(clock=_NaiveClock()).execute(_command(_result()))

    writer = _Writer()
    writer.error = RuntimeError("writer failure")
    with pytest.raises(RuntimeError, match="writer failure"):
        _recorder(writer).execute(_command(_result()))

    freshness_writer = _FreshnessWriter()
    freshness_writer.error = RuntimeError("freshness writer failure")
    decision_writer = _Writer()
    with pytest.raises(RuntimeError, match="freshness writer failure"):
        _recorder(decision_writer, freshness_writer=freshness_writer).execute(_command(_result()))
    assert decision_writer.observations == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_key", ""),
        ("publication_key", " current"),
        ("decision_key", "decision key"),
        ("freshness_status", ""),
    ],
)
def test_invalid_decision_read_tokens_fail_closed(field: str, value: str) -> None:
    command_values: dict[str, object] = {
        "sync_result": _result(),
        "dataset_key": "equity.price.bar",
        "publication_key": "current",
        "decision_key": "portfolio-readiness",
        "freshness_status": "fresh",
        "must_not_use_for_decision": False,
        "blocked_reason": None,
    }
    command_values[field] = value

    with pytest.raises((DecisionReadAuditUnavailable, TypeError, ValueError)):
        RecordPublicationDecisionReadCommand(**command_values)
