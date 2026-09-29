"""Runtime contracts for Celery broker visibility and task time limits."""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings

_TASK_DECORATOR_NAMES = {"shared_task", "typed_shared_task", "_typed_shared_task"}


def _literal_int(node: ast.expr) -> int | None:
    """Return one positive integer literal or a literal ``getattr`` default."""

    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 3
        and isinstance(node.args[2], ast.Constant)
        and isinstance(node.args[2].value, int)
    ):
        return node.args[2].value
    return None


def _decorator_name(node: ast.expr) -> str | None:
    """Return the final name of a task decorator expression."""

    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _repository_hard_limits() -> list[int]:
    """Collect explicit hard limits from every application task source file."""

    limits: list[int] = []
    for source_path in Path("apps").glob("*/application/**/*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if _decorator_name(decorator) not in _TASK_DECORATOR_NAMES:
                    continue
                if not isinstance(decorator, ast.Call):
                    continue
                for keyword in decorator.keywords:
                    if keyword.arg == "time_limit":
                        value = _literal_int(keyword.value)
                        if value is None:
                            raise AssertionError(
                                f"{source_path}:{node.lineno} task time_limit must expose "
                                "a governed literal or getattr default"
                            )
                        limits.append(value)
    return limits


def test_redis_visibility_timeout_exceeds_every_repository_task_hard_limit() -> None:
    """Redis must not redeliver an acknowledged-late task before its hard limit."""

    transport_options = settings.CELERY_BROKER_TRANSPORT_OPTIONS
    visibility_timeout = transport_options["visibility_timeout"]
    hard_limits = [settings.CELERY_TASK_TIME_LIMIT, *_repository_hard_limits()]

    assert visibility_timeout == settings.CELERY_BROKER_VISIBILITY_TIMEOUT
    assert max(hard_limits) == settings.CELERY_REPOSITORY_TASK_HARD_LIMIT
    assert max(hard_limits) <= settings.CELERY_TASK_MAX_HARD_LIMIT
    assert visibility_timeout > max(hard_limits)


def test_full_market_task_limits_leave_strict_authority_finalization_headroom() -> None:
    """The full-market task and authority window move together as one contract."""

    from apps.data_center.application import tasks

    task = tasks.refresh_full_market_publications_task
    authority_seconds = tasks._FULL_MARKET_AUTHORITY_WINDOW.total_seconds()
    finalization_seconds = tasks._AUTHORITY_FINALIZATION_WINDOW.total_seconds()

    assert task.soft_time_limit == 5400
    assert task.time_limit == 5700
    assert authority_seconds > task.time_limit + finalization_seconds
