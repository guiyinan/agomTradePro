"""Producer-bound invocation identity for the registered daily auto-trading task."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from celery.app.task import Context, Task

from apps.simulated_trading.application import tasks
from core.celery import app as celery_app

_TASK_PATH = "apps.simulated_trading.application.tasks.daily_auto_trading_task"


def _registered_task() -> Task:
    """Resolve the task through Celery's real application registry."""
    task = celery_app.tasks.get(_TASK_PATH)
    assert task is not None
    assert task.name == _TASK_PATH
    return task


def _capture_base_apply_async(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    """Capture the registered Task's final publish call without a broker."""
    calls: list[dict[str, object]] = []

    def capture(
        task: Task,
        args: tuple[object, ...] | list[object] | None = None,
        kwargs: Mapping[str, object] | None = None,
        task_id: str | None = None,
        producer: object | None = None,
        link: object | None = None,
        link_error: object | None = None,
        shadow: str | None = None,
        **options: object,
    ) -> SimpleNamespace:
        del task, producer, link, link_error, shadow
        calls.append(
            {
                "args": args,
                "kwargs": None if kwargs is None else dict(kwargs),
                "task_id": task_id,
                "options": dict(options),
            }
        )
        return SimpleNamespace(id=task_id or "captured-celery-task-id")

    monkeypatch.setattr(Task, "apply_async", capture)
    return calls


def _published_kwargs(call: Mapping[str, object]) -> dict[str, object]:
    """Read the captured Celery message kwargs with a test-local type guard."""
    value = call["kwargs"]
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_registered_beat_style_publish_generates_key_and_preserves_call_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered task adds one run key while preserving its input publish data."""
    calls = _capture_base_apply_async(monkeypatch)
    task = _registered_task()
    original_kwargs: dict[str, object] = {"account_ids": [17, 22]}
    expected_kwargs = {"account_ids": [17, 22]}
    headers = {"caller": "unit-test"}
    options: dict[str, object] = {
        "queue": "simulated-trading",
        "countdown": 23,
        "headers": headers,
        "task_id": "celery-transport-task-id",
    }
    args = ("2026-10-19",)

    task.apply_async(args=args, kwargs=original_kwargs, **options)

    assert len(calls) == 1
    call = calls[0]
    assert call["args"] == args
    assert call["task_id"] == "celery-transport-task-id"
    published_kwargs = _published_kwargs(call)
    key = published_kwargs.get("invocation_key")
    assert isinstance(key, str) and key
    assert key != call["task_id"]
    assert published_kwargs["account_ids"] == [17, 22]
    expected_options = {key: value for key, value in options.items() if key != "task_id"}
    assert call["options"] == expected_options
    assert original_kwargs == expected_kwargs
    assert "invocation_key" not in original_kwargs


def test_registered_publish_preserves_an_explicit_invocation_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly supplied business key is passed through exactly as given."""
    calls = _capture_base_apply_async(monkeypatch)
    task = _registered_task()
    explicit_key = "caller-owned-run-001"
    original_kwargs: dict[str, object] = {
        "trade_date": "2026-10-19",
        "invocation_key": explicit_key,
    }

    task.apply_async(kwargs=original_kwargs)

    assert len(calls) == 1
    assert _published_kwargs(calls[0])["invocation_key"] == explicit_key
    assert original_kwargs["invocation_key"] == explicit_key


def test_each_independent_publish_gets_a_distinct_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only retries/redeliveries reuse a key; fresh publishes get new identities."""
    calls = _capture_base_apply_async(monkeypatch)
    task = _registered_task()

    task.apply_async(kwargs={})
    task.apply_async(kwargs={})

    assert len(calls) == 2
    keys = [_published_kwargs(call).get("invocation_key") for call in calls]
    assert all(isinstance(key, str) and key for key in keys)
    assert keys[0] != keys[1]


def test_real_signature_from_request_reuses_the_message_invocation_key() -> None:
    """Celery's retry-signature source keeps business identity separate from task id."""
    task = _registered_task()
    invocation_key = "first-publish-business-key"
    request = Context(
        args=("2026-10-19",),
        kwargs={"account_ids": [17], "invocation_key": invocation_key},
        delivery_info={"exchange": "", "routing_key": "simulated-trading"},
        id="celery-transport-task-id",
        root_id="celery-transport-root-id",
        retries=1,
        called_directly=False,
    )

    retry_signature = task.signature_from_request(request=request)

    assert retry_signature.kwargs["invocation_key"] == invocation_key
    assert retry_signature.args == request.args
    assert retry_signature.options["task_id"] == "celery-transport-task-id"


def test_legacy_direct_run_without_a_key_fails_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old task parameters still bind, but direct execution without a run key is blocked."""
    account_repository_factory = Mock(
        side_effect=AssertionError("missing invocation key must fail before repositories")
    )
    monkeypatch.setattr(tasks, "get_simulated_account_repository", account_repository_factory)

    result = _registered_task().run(trade_date="2026-10-19", account_ids=[17])

    account_repository_factory.assert_not_called()
    assert result["outcome"] == "failed"
    assert result["success"] is False
    assert result["stored"] == 0


@pytest.mark.parametrize("invocation_key", ["", "contains whitespace"])
def test_direct_run_with_an_invalid_key_fails_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
    invocation_key: str,
) -> None:
    """Invalid explicit values are rejected, never replaced with a fresh identity."""
    account_repository_factory = Mock(
        side_effect=AssertionError("invalid invocation key must fail before repositories")
    )
    monkeypatch.setattr(tasks, "get_simulated_account_repository", account_repository_factory)

    result = _registered_task().run(
        trade_date="2026-10-19",
        account_ids=[17],
        invocation_key=invocation_key,
    )

    account_repository_factory.assert_not_called()
    assert result["outcome"] == "failed"
    assert result["success"] is False
    assert result["stored"] == 0


def test_invocation_key_is_not_a_new_positional_legacy_argument() -> None:
    """Legacy date/scope positions stay supported; the new key is keyword-only."""
    task = _registered_task()

    with pytest.raises(TypeError):
        task.run("2026-10-19", [17], "positional-key")
