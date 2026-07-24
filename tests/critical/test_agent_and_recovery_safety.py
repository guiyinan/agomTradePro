"""Agent uncertainty, recovery, reconciliation, and Fake Agent contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.component.broker_execution.test_risk_and_reconciliation import (
    test_escalated_reconciliation_remains_a_resume_blocker as _assert_resume_blocker,
)
from tests.component.broker_execution.test_risk_and_reconciliation import (
    test_four_dimension_reconciliation_is_idempotent_and_auto_stops_on_p0 as _assert_p0_auto_stop,
)
from tests.integration.broker_execution.test_fake_agent_flow import (
    test_fake_agent_approval_lease_submit_fill_flow_is_idempotent as _assert_fake_agent_flow,
)
from tests.unit.broker_execution.test_agent import (
    test_agent_records_submitting_before_broker_and_does_not_duplicate as _assert_local_idempotency,
)
from tests.unit.broker_execution.test_agent import (
    test_unknown_broker_outcome_requires_reconciliation as _assert_unknown_outcome,
)


def test_unknown_submission_result_is_not_blindly_retried(tmp_path: Path) -> None:
    """Unknown broker outcomes enter reconciliation-required state."""

    _assert_unknown_outcome(tmp_path)


def test_local_agent_submission_is_idempotent(tmp_path: Path) -> None:
    """The Agent records SUBMITTING before broker I/O and rejects replay."""

    _assert_local_idempotency(tmp_path)


@pytest.mark.django_db
def test_p0_reconciliation_difference_auto_stops_account() -> None:
    """P0 cash/order/fill/position differences activate the kill switch once."""

    _assert_p0_auto_stop()


@pytest.mark.django_db
def test_unresolved_p0_reconciliation_blocks_resume() -> None:
    """Escalation is not equivalent to resolving a P0 difference."""

    _assert_resume_blocker()


@pytest.mark.django_db(transaction=True)
def test_fake_agent_full_fill_and_event_replay_persist_once() -> None:
    """Approval through fill remains idempotent without QMT or external services."""

    _assert_fake_agent_flow()
