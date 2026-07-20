"""Local runtime probes for personal readiness operations."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

PERSONAL_READINESS_REQUIRED_REGISTERED_TASKS = (
    "apps.operational_readiness.application.tasks.run_personal_readiness_daily_task",
    "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task",
    "dashboard.generate_auto_advisor_weekly_reports",
)


def collect_local_scheduler_runtime(
    *,
    required: bool,
    process_commands: list[dict[str, Any]] | None = None,
    worker_ping: list[dict[str, Any]] | None = None,
    worker_active_queues: dict[str, list[dict[str, Any]]] | None = None,
    worker_registered_tasks: dict[str, list[str]] | None = None,
    required_queues: tuple[str, ...] = ("celery", "qlib_infer"),
    required_registered_tasks: tuple[str, ...] = PERSONAL_READINESS_REQUIRED_REGISTERED_TASKS,
    worker_ping_timeout: float = 5.0,
) -> dict[str, Any]:
    """Return local Celery worker/beat process evidence for a readiness run."""

    if not required:
        return {
            "required": False,
            "status": "not_checked",
            "worker_process_count": None,
            "beat_process_count": None,
            "required_queues": [],
            "missing_queues": [],
            "required_registered_tasks": [],
            "missing_registered_tasks": [],
            "remediation_commands": [],
            "issues": [],
        }

    try:
        commands = process_commands if process_commands is not None else _list_process_commands()
    except RuntimeError as exc:
        issues = [
            {
                "code": "local_scheduler_process_scan_failed",
                "message": str(exc),
            }
        ]
        return {
            "required": True,
            "status": "warning",
            "worker_process_count": 0,
            "beat_process_count": 0,
            "required_queues": list(required_queues),
            "missing_queues": list(required_queues),
            "required_registered_tasks": list(required_registered_tasks),
            "missing_registered_tasks": list(required_registered_tasks),
            "remediation_commands": _build_remediation_commands(
                issues=issues,
                required_queues=required_queues,
            ),
            "issues": issues,
            "processes": [],
        }

    worker_processes = [
        item for item in commands if _classify_command_line(item.get("command_line")) == "worker"
    ]
    beat_processes = [
        item for item in commands if _classify_command_line(item.get("command_line")) == "beat"
    ]
    issues: list[dict[str, str]] = []
    if not beat_processes:
        issues.append(
            {
                "code": "local_celery_beat_not_running",
                "message": "Local Celery beat process is required for scheduled readiness evidence.",
            }
        )
    if not worker_processes:
        issues.append(
            {
                "code": "local_celery_worker_not_running",
                "message": "Local Celery worker process is required to execute scheduled readiness evidence.",
            }
        )
    ping_payload = (
        _normalize_worker_ping(worker_ping)
        if worker_ping is not None
        else _ping_celery_workers(timeout=worker_ping_timeout)
    )
    if worker_processes and ping_payload["responsive_worker_count"] <= 0:
        issues.append(
            {
                "code": "local_celery_worker_not_responsive",
                "message": "Local Celery worker process exists but did not respond to inspect ping.",
            }
        )
    queue_payload = (
        _normalize_worker_active_queues(worker_active_queues, required_queues=required_queues)
        if worker_active_queues is not None
        else _inspect_worker_active_queues(
            timeout=worker_ping_timeout,
            required_queues=required_queues,
        )
    )
    if worker_processes and queue_payload["status"] != "ok":
        issues.append(
            {
                "code": "local_celery_required_queue_uncovered",
                "message": (
                    "Local Celery workers are not listening to required queues: "
                    + ", ".join(queue_payload["missing_queues"])
                ),
            }
        )
    registered_payload = (
        _normalize_worker_registered_tasks(
            worker_registered_tasks,
            required_registered_tasks=required_registered_tasks,
        )
        if worker_registered_tasks is not None
        else _inspect_worker_registered_tasks(
            timeout=worker_ping_timeout,
            required_registered_tasks=required_registered_tasks,
        )
    )
    if worker_processes and registered_payload["status"] != "ok":
        issues.append(
            {
                "code": "local_celery_required_task_unregistered",
                "message": (
                    "Local Celery workers do not register required scheduled tasks: "
                    + ", ".join(registered_payload["missing_registered_tasks"])
                ),
            }
        )
    return {
        "required": True,
        "status": "warning" if issues else "ok",
        "worker_process_count": len(worker_processes),
        "beat_process_count": len(beat_processes),
        "responsive_worker_count": ping_payload["responsive_worker_count"],
        "worker_ping_status": ping_payload["status"],
        "worker_ping_error": ping_payload["error"],
        "active_queues_status": queue_payload["status"],
        "active_queues_error": queue_payload["error"],
        "required_queues": list(required_queues),
        "covered_queues": queue_payload["covered_queues"],
        "missing_queues": queue_payload["missing_queues"],
        "active_queue_worker_count": queue_payload["active_queue_worker_count"],
        "registered_tasks_status": registered_payload["status"],
        "registered_tasks_error": registered_payload["error"],
        "required_registered_tasks": list(required_registered_tasks),
        "missing_registered_tasks": registered_payload["missing_registered_tasks"],
        "registered_task_worker_count": registered_payload["registered_task_worker_count"],
        "remediation_commands": _build_remediation_commands(
            issues=issues,
            required_queues=required_queues,
        ),
        "issues": issues,
        "processes": [_redact_process(item) for item in [*beat_processes, *worker_processes]],
    }


def _build_remediation_commands(
    *,
    issues: list[dict[str, str]],
    required_queues: tuple[str, ...],
) -> list[str]:
    commands: list[str] = []
    issue_codes = {issue.get("code") for issue in issues}
    if "local_celery_beat_not_running" in issue_codes:
        commands.append("python manage.py celery_beat_windows --loglevel=info")
    if {
        "local_celery_worker_not_running",
        "local_celery_worker_not_responsive",
        "local_celery_required_queue_uncovered",
        "local_celery_required_task_unregistered",
    } & issue_codes:
        queue_arg = ",".join(required_queues)
        commands.append(
            "python manage.py celery_worker_windows "
            f"--queues={queue_arg} --hostname=readiness@%h"
        )
    if "local_scheduler_process_scan_failed" in issue_codes:
        commands.append(
            "python manage.py show_personal_readiness_status "
            "--json --strict-monitor --require-local-scheduler-runtime"
        )
    return list(dict.fromkeys(commands))


def _classify_command_line(command_line: Any) -> str | None:
    normalized = f" {str(command_line or '').lower()} "
    if " celery_beat_windows" in normalized:
        return "beat"
    if " celery_worker_windows" in normalized:
        return "worker"
    if (
        " celery " not in normalized
        and "/celery" not in normalized
        and "\\celery" not in normalized
    ):
        return None
    if " beat " in normalized:
        return "beat"
    if " worker " in normalized:
        return "worker"
    return None


def _redact_process(process: dict[str, Any]) -> dict[str, Any]:
    return {
        "pid": process.get("pid"),
        "role": _classify_command_line(process.get("command_line")),
        "command_line": str(process.get("command_line") or ""),
    }


def _ping_celery_workers(*, timeout: float) -> dict[str, Any]:
    try:
        from core.celery import app

        return _normalize_worker_ping(app.control.ping(timeout=max(float(timeout), 0.1)) or [])
    except Exception as exc:
        return {
            "status": "error",
            "responsive_worker_count": 0,
            "error": str(exc),
        }


def _inspect_worker_active_queues(
    *,
    timeout: float,
    required_queues: tuple[str, ...],
) -> dict[str, Any]:
    try:
        from core.celery import app

        inspect = app.control.inspect(timeout=max(float(timeout), 0.1))
        return _normalize_worker_active_queues(
            inspect.active_queues() or {},
            required_queues=required_queues,
        )
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "covered_queues": [],
            "missing_queues": list(required_queues),
            "active_queue_worker_count": 0,
        }


def _inspect_worker_registered_tasks(
    *,
    timeout: float,
    required_registered_tasks: tuple[str, ...],
) -> dict[str, Any]:
    if not required_registered_tasks:
        return _normalize_worker_registered_tasks(
            {},
            required_registered_tasks=required_registered_tasks,
        )
    try:
        from core.celery import app

        inspect = app.control.inspect(timeout=max(float(timeout), 0.1))
        return _normalize_worker_registered_tasks(
            inspect.registered() or {},
            required_registered_tasks=required_registered_tasks,
        )
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "required_registered_tasks": list(required_registered_tasks),
            "missing_registered_tasks": list(required_registered_tasks),
            "registered_task_worker_count": 0,
        }


def _normalize_worker_ping(payload: list[dict[str, Any]]) -> dict[str, Any]:
    responsive = [
        item
        for item in payload
        if isinstance(item, dict)
        and any(isinstance(value, dict) and value.get("ok") == "pong" for value in item.values())
    ]
    return {
        "status": "ok" if responsive else "unresponsive",
        "responsive_worker_count": len(responsive),
        "error": None,
    }


def _normalize_worker_active_queues(
    payload: dict[str, list[dict[str, Any]]] | None,
    *,
    required_queues: tuple[str, ...],
) -> dict[str, Any]:
    covered: set[str] = set()
    worker_count = 0
    for queues in (payload or {}).values():
        if not isinstance(queues, list):
            continue
        worker_count += 1
        for queue in queues:
            if not isinstance(queue, dict):
                continue
            name = str(queue.get("name") or "")
            if name:
                covered.add(name)
    missing = [queue for queue in required_queues if queue not in covered]
    return {
        "status": "ok" if not missing else "missing",
        "error": None,
        "covered_queues": sorted(covered),
        "missing_queues": missing,
        "active_queue_worker_count": worker_count,
    }


def _normalize_worker_registered_tasks(
    payload: dict[str, list[str]] | None,
    *,
    required_registered_tasks: tuple[str, ...],
) -> dict[str, Any]:
    if not required_registered_tasks:
        return {
            "status": "ok",
            "error": None,
            "required_registered_tasks": [],
            "missing_registered_tasks": [],
            "registered_task_worker_count": 0,
        }

    workers_by_task: dict[str, set[str]] = {task: set() for task in required_registered_tasks}
    for worker_name, tasks in (payload or {}).items():
        if not isinstance(tasks, list):
            continue
        registered = {str(task) for task in tasks}
        for task in required_registered_tasks:
            if task in registered:
                workers_by_task[task].add(str(worker_name))

    missing = [task for task, workers in workers_by_task.items() if not workers]
    registered_workers = {worker for workers in workers_by_task.values() for worker in workers}
    return {
        "status": "ok" if not missing else "missing",
        "error": None,
        "required_registered_tasks": list(required_registered_tasks),
        "missing_registered_tasks": missing,
        "registered_task_worker_count": len(registered_workers),
    }


def _list_process_commands() -> list[dict[str, Any]]:
    if sys.platform == "win32":
        return _list_windows_process_commands()
    return _list_posix_process_commands()


def _list_windows_process_commands() -> list[dict[str, Any]]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    errors: list[str] = []
    for executable in ("pwsh", "powershell"):
        try:
            completed = subprocess.run(
                [executable, "-NoProfile", "-Command", script],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"{executable}: {exc}")
            continue
        return _parse_windows_process_json(completed.stdout)
    raise RuntimeError("; ".join(errors) or "no PowerShell executable found")


def _parse_windows_process_json(payload: str) -> list[dict[str, Any]]:
    import json

    if not payload.strip():
        return []
    parsed = json.loads(payload)
    records = parsed if isinstance(parsed, list) else [parsed]
    return [
        {
            "pid": item.get("ProcessId"),
            "command_line": item.get("CommandLine") or "",
        }
        for item in records
        if isinstance(item, dict)
    ]


def _list_posix_process_commands() -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(str(exc)) from exc
    processes: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command_line = stripped.partition(" ")
        processes.append(
            {
                "pid": int(pid_text) if pid_text.isdigit() else pid_text,
                "command_line": command_line,
            }
        )
    return processes
