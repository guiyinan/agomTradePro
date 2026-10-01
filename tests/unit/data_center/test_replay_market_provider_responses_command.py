"""Stable diagnostics for the offline provider-response replay command."""

from apps.data_center.management.commands.replay_market_provider_responses import (
    _stable_failure_code,
)


def test_replay_command_preserves_stable_business_error_code() -> None:
    assert (
        _stable_failure_code(ValueError("REHEARSAL_REPLAY_CONTEXT_MISMATCH"))
        == "REHEARSAL_REPLAY_CONTEXT_MISMATCH"
    )


def test_replay_command_hides_unclassified_exception_detail() -> None:
    assert (
        _stable_failure_code(OSError("private provider response path"))
        == "REHEARSAL_OFFLINE_REPLAY_FAILED"
    )
