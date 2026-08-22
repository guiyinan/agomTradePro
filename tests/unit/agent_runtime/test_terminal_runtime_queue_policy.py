"""Pure TAR-01 bounded queue and migration policy contract tests."""

from __future__ import annotations

import ast
from dataclasses import MISSING, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_queue_policy import (
    LEGACY_INLINE_CONCURRENCY_CAP,
    LEGACY_INLINE_TIMEOUT_CAP_SECONDS,
    TERMINAL_AGENT_QUEUE_NAME,
    TERMINAL_AGENT_STREAM_NAMESPACE,
    TerminalAdmissionLimits,
    TerminalAdmissionReason,
    TerminalFallbackMode,
    TerminalRunDeadlines,
    TerminalRuntimeFeatureFlags,
    TerminalRuntimeQueuePolicy,
    TerminalRuntimeQueuePolicyError,
    TerminalWorkerQueueLimits,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import TerminalRuntimeMode

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def _worker_limits(**overrides: int | str) -> TerminalWorkerQueueLimits:
    values: dict[str, int | str] = {
        "queue_name": TERMINAL_AGENT_QUEUE_NAME,
        "stream_namespace": TERMINAL_AGENT_STREAM_NAMESPACE,
        "worker_concurrency": 4,
        "broker_prefetch_count": 1,
        "queue_max_depth": 40,
        "stream_max_length": 200,
        "stream_ttl_seconds": 3600,
        "max_tasks_per_child": 100,
    }
    values.update(overrides)
    return TerminalWorkerQueueLimits(**values)


def _admission_limits(**overrides: int) -> TerminalAdmissionLimits:
    values = {
        "per_user_active": 1,
        "per_user_queued": 4,
        "global_active": 4,
        "global_queued": 40,
    }
    values.update(overrides)
    return TerminalAdmissionLimits(**values)


def _deadlines(**overrides: int) -> TerminalRunDeadlines:
    values = {
        "max_queue_wait_seconds": 300,
        "soft_timeout_seconds": 45,
        "hard_timeout_seconds": 60,
        "cancel_grace_seconds": 10,
        "heartbeat_interval_seconds": 5,
        "orphan_after_seconds": 30,
    }
    values.update(overrides)
    return TerminalRunDeadlines(**values)


def _flags(**overrides: bool | int | TerminalFallbackMode) -> TerminalRuntimeFeatureFlags:
    values: dict[str, bool | int | TerminalFallbackMode] = {
        "queued_intake_enabled": True,
        "queued_worker_enabled": True,
        "legacy_inline_enabled": True,
        "fallback_mode": TerminalFallbackMode.PAUSE,
        "emergency_stop": False,
        "legacy_inline_concurrency": LEGACY_INLINE_CONCURRENCY_CAP,
        "legacy_inline_timeout_seconds": LEGACY_INLINE_TIMEOUT_CAP_SECONDS,
    }
    values.update(overrides)
    return TerminalRuntimeFeatureFlags(**values)


def test_policy_requires_explicit_config_and_composes_bounded_limits() -> None:
    policy = TerminalRuntimeQueuePolicy(
        worker_limits=_worker_limits(),
        admission_limits=_admission_limits(),
        deadlines=_deadlines(),
        feature_flags=_flags(),
    )

    assert policy.worker_limits.queue_max_depth == policy.admission_limits.global_queued
    assert policy.worker_limits.worker_concurrency == policy.admission_limits.global_active
    assert all(field.default is MISSING for field in fields(TerminalRuntimeQueuePolicy))


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("worker_concurrency", 0),
        ("broker_prefetch_count", 0),
        ("queue_max_depth", 0),
        ("stream_max_length", 0),
        ("stream_ttl_seconds", 0),
        ("max_tasks_per_child", 0),
        ("worker_concurrency", True),
    ],
)
def test_worker_limits_reject_unbounded_or_bool_values(field_name: str, value: object) -> None:
    with pytest.raises(TerminalRuntimeQueuePolicyError):
        _worker_limits(**{field_name: value})


def test_worker_and_stream_names_are_canonical() -> None:
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="queue_name"):
        _worker_limits(queue_name="celery")
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="stream_namespace"):
        _worker_limits(stream_namespace="events")


def test_admission_caps_are_user_bounded_and_fit_worker_capacity() -> None:
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="per_user_active"):
        _admission_limits(per_user_active=2, global_active=1)
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="per_user_queued"):
        _admission_limits(per_user_queued=5, global_queued=4)
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="worker_concurrency"):
        TerminalRuntimeQueuePolicy(
            worker_limits=_worker_limits(worker_concurrency=3),
            admission_limits=_admission_limits(global_active=4),
            deadlines=_deadlines(),
            feature_flags=_flags(),
        )
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="queue_max_depth"):
        TerminalRuntimeQueuePolicy(
            worker_limits=_worker_limits(queue_max_depth=39),
            admission_limits=_admission_limits(global_queued=40),
            deadlines=_deadlines(),
            feature_flags=_flags(),
        )


def test_deadlines_are_ordered_and_derive_aware_absolute_cutoffs() -> None:
    deadlines = _deadlines()

    assert deadlines.run_deadline_at(NOW) == NOW.replace(second=0) + timedelta(seconds=360)
    assert deadlines.cancel_deadline_at(NOW) == NOW.replace(second=0) + timedelta(seconds=10)
    assert deadlines.orphan_deadline_at(NOW) == NOW.replace(second=0) + timedelta(seconds=30)

    with pytest.raises(TerminalRuntimeQueuePolicyError, match="soft_timeout"):
        _deadlines(soft_timeout_seconds=60)
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="cancel_grace"):
        _deadlines(cancel_grace_seconds=61)
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="heartbeat"):
        _deadlines(heartbeat_interval_seconds=30)
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="timezone-aware"):
        deadlines.run_deadline_at(NOW.replace(tzinfo=None))


def test_flags_require_worker_for_intake_and_keep_inline_cap_fail_closed() -> None:
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="queued intake"):
        _flags(queued_worker_enabled=False)
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="fallback"):
        _flags(
            fallback_mode=TerminalFallbackMode.RESTRICTED_INLINE,
            legacy_inline_enabled=False,
        )
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="capped at 1"):
        _flags(legacy_inline_concurrency=2)
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="60 seconds"):
        _flags(legacy_inline_timeout_seconds=61)
    with pytest.raises(TerminalRuntimeQueuePolicyError, match="emergency stop"):
        _flags(emergency_stop=True, queued_intake_enabled=True)


def test_migration_defaults_keep_queued_mode_closed_and_inline_bounded() -> None:
    flags = TerminalRuntimeFeatureFlags.migration_defaults()

    assert flags.queued_intake_enabled is False
    assert flags.queued_worker_enabled is False
    assert flags.legacy_inline_enabled is True
    assert flags.fallback_mode is TerminalFallbackMode.PAUSE
    assert flags.emergency_stop is False
    assert flags.legacy_inline_concurrency == LEGACY_INLINE_CONCURRENCY_CAP
    assert flags.legacy_inline_timeout_seconds == LEGACY_INLINE_TIMEOUT_CAP_SECONDS
    assert flags.resolve_mode(
        TerminalRuntimeMode.WEB_QUEUED,
        worker_ready=False,
    ) == (None, TerminalAdmissionReason.QUEUED_UNAVAILABLE)


def test_mode_resolution_never_implicitly_falls_back_to_inline() -> None:
    flags = _flags()
    assert flags.resolve_mode(
        TerminalRuntimeMode.WEB_QUEUED,
        worker_ready=True,
    ) == (TerminalRuntimeMode.WEB_QUEUED, TerminalAdmissionReason.ACCEPTED_QUEUED)
    assert flags.resolve_mode(
        TerminalRuntimeMode.WEB_QUEUED,
        worker_ready=False,
    ) == (None, TerminalAdmissionReason.QUEUED_UNAVAILABLE)

    fallback_flags = _flags(fallback_mode=TerminalFallbackMode.RESTRICTED_INLINE)
    assert fallback_flags.resolve_mode(
        TerminalRuntimeMode.WEB_QUEUED,
        worker_ready=False,
    ) == (
        TerminalRuntimeMode.LEGACY_INLINE,
        TerminalAdmissionReason.ACCEPTED_RESTRICTED_INLINE,
    )
    paused_flags = _flags(
        queued_intake_enabled=False,
        queued_worker_enabled=False,
        legacy_inline_enabled=False,
        emergency_stop=True,
    )
    assert paused_flags.resolve_mode(
        TerminalRuntimeMode.WEB_QUEUED,
        worker_ready=False,
    ) == (None, TerminalAdmissionReason.SUBMISSIONS_PAUSED)


def test_local_cli_is_disabled_and_must_use_server_owned_queued_mode() -> None:
    flags = _flags(
        queued_intake_enabled=False,
        queued_worker_enabled=False,
        legacy_inline_enabled=False,
    )
    assert flags.resolve_mode(
        TerminalRuntimeMode.LOCAL_CLI,
        worker_ready=False,
    ) == (None, TerminalAdmissionReason.LOCAL_CLI_DISABLED)


def test_policy_module_is_pure_and_has_no_runtime_adapter_dependency() -> None:
    source_path = Path("apps/agent_runtime/application/terminal_runtime_queue_policy.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert all(not name.startswith("django") for name in imported_names)
    assert all("infrastructure" not in name for name in imported_names)
    assert "celery" not in imported_names
    assert "OpenAIAgentsTerminalService" not in source
    assert ".objects" not in source
