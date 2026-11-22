#!/usr/bin/env python3
"""Advance one disposable S6 market graph through the canonical full-market task."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from apps.data_center.infrastructure.rehearsal_http_capture import RehearsalHttpCapture

_SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT_RE = re.compile(r"[0-9a-f]{32}\Z")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DATABASE_RE = re.compile(r"agom_release_rehearsal_[a-f0-9]{32}\Z")
_NETWORK_RE = re.compile(r"agom-s6-network-[a-z0-9-]+\Z")
_POSTGRES_CONTAINER_RE = re.compile(r"agom-s6-postgres-[a-f0-9]{32}\Z")
_REDIS_CONTAINER_RE = re.compile(r"agom-s6-redis-[a-f0-9]{32}\Z")
_REPORT = Path("/candidate-output/current-market-graph-refresh.json")
_GRAPH_PLAN = Path("/graph-attempt-plan.json")
_CANDIDATE_SOURCE = Path("/candidate-src")
_ISOLATED_PROVIDER_SOURCE = "tushare"
_MAX_HTTP_DISPATCHES = 50
_MAX_HTTP_SECONDS = 3600.0
_KNOWN_FAILURE_CODES = frozenset(
    {
        "S6_GRAPH_REFRESH_ENVIRONMENT_INVALID",
        "S6_GRAPH_REFRESH_DATABASE_IDENTITY_INVALID",
        "S6_GRAPH_REFRESH_IDENTITY_INVALID",
        "S6_GRAPH_REFRESH_CANDIDATE_SOURCE_INVALID",
        "S6_GRAPH_REFRESH_TARGET_SESSION_UNAVAILABLE",
        "S6_GRAPH_REFRESH_HTTP_BUDGET_INVALID",
        "S6_GRAPH_SCOPE_INVALID",
        "S6_GRAPH_REFRESH_PLAN_MISMATCH",
        "S6_GRAPH_REFRESH_SESSION_MISMATCH",
        "S6_GRAPH_REFRESH_SCOPE_OUT_OF_BOUNDS",
        "S6_GRAPH_REFRESH_LATER_QUOTE",
        "S6_GRAPH_REFRESH_LATER_PRICE",
        "S6_GRAPH_REFRESH_LATER_VALUATION",
    }
)


def _blocked(error_code: str, *, capture: RehearsalHttpCapture | None = None) -> int:
    """Print one safe stable error code and return the standard blocked status."""

    details = ""
    if capture is not None and capture.started > 0:
        evidence = _http_capture_summary(capture)
        details = (
            f" dispatch_count={evidence['dispatch_count']}"
            f" rejected_dispatch_count={evidence['rejected_dispatch_count']}"
            f" max_dispatches={evidence['max_dispatches']}"
            f" guard_failure_code={evidence['guard_failure_code']}"
            f" elapsed_seconds={evidence['elapsed_seconds']}"
            f" max_seconds={evidence['max_seconds']}"
        )
        failures = [
            {
                "host_sha256": hashlib.sha256(receipt.host.encode()).hexdigest(),
                "path_sha256": receipt.path_sha256,
                "method": receipt.method,
                "status_code": receipt.status_code,
                "error_code": receipt.error_code,
            }
            for receipt in capture.receipts
            if receipt.error_code
        ]
        if failures:
            print(
                "S6_GRAPH_REFRESH_HTTP_FAILURES "
                + json.dumps(failures, sort_keys=True, separators=(",", ":")),
                file=sys.stderr,
                flush=True,
            )
    print(f"S6_GRAPH_REFRESH_BLOCKED code={error_code}{details}", file=sys.stderr, flush=True)
    return 2


def _validate_http_budget(max_dispatches: object, max_seconds: object) -> None:
    """Reject invalid or widened technical request bounds before any side effect."""
    if (
        type(max_dispatches) is not int
        or max_dispatches < 1
        or max_dispatches > _MAX_HTTP_DISPATCHES
        or isinstance(max_seconds, bool)
        or not isinstance(max_seconds, (int, float))
        or not math.isfinite(max_seconds)
        or max_seconds <= 0
        or max_seconds > _MAX_HTTP_SECONDS
    ):
        raise ValueError("S6_GRAPH_REFRESH_HTTP_BUDGET_INVALID")


def _http_capture_summary(capture: RehearsalHttpCapture) -> dict[str, object]:
    """Project only safe counts and bounds from the real transport observer."""
    observed = capture.to_dict()
    return {
        "count_unit": observed["count_unit"],
        "dispatch_count": observed["dispatch_count"],
        "rejected_dispatch_count": observed["rejected_dispatch_count"],
        "guard_failure_code": observed["guard_failure_code"],
        "max_dispatches": observed["max_dispatches"],
        "max_seconds": observed["max_seconds"],
        "elapsed_seconds": observed["elapsed_seconds"],
    }


def _capture_failure_code(capture: RehearsalHttpCapture) -> str | None:
    """Map a swallowed transport guard failure to a stable refresh diagnostic."""
    if capture.guard_failure_code is None:
        return None
    if capture.guard_failure_code == "REHEARSAL_HTTP_BUDGET_EXCEEDED":
        return "S6_GRAPH_REFRESH_HTTP_BUDGET_EXCEEDED"
    return "S6_GRAPH_REFRESH_HTTP_OBSERVATION_FAILED"


def _execute_captured_task(task: Callable[[], object], *, capture: RehearsalHttpCapture) -> object:
    """Run one task under the actual requests transport observer."""
    with capture:
        return task()


def _validate_runtime_identity(args: argparse.Namespace, environ: dict[str, str]) -> None:
    """Require an exact, isolated database/runtime identity before provider access."""

    _validate_http_budget(args.max_dispatches, args.max_seconds)
    if (
        environ.get("AGOM_RELEASE_REHEARSAL_DATABASE") != "1"
        or environ.get("S6_GRAPH_REFRESH_ENABLED") != "1"
        or environ.get("POSTGRES_DB") != args.database
        or environ.get("POSTGRES_HOST") != args.postgres_container
        or environ.get("REDIS_HOST") != args.redis_container
        or environ.get("REDIS_URL") != f"redis://{args.redis_container}:6379/0"
        or environ.get("CELERY_BROKER_URL") != f"redis://{args.redis_container}:6379/1"
    ):
        raise ValueError("S6_GRAPH_REFRESH_ENVIRONMENT_INVALID")
    parsed = urlparse(environ.get("DATABASE_URL", ""))
    if (
        parsed.scheme != "postgresql"
        or parsed.hostname != args.postgres_container
        or parsed.path != f"/{args.database}"
        or parsed.username != "agomtradepro_runtime"
        or not parsed.password
    ):
        raise ValueError("S6_GRAPH_REFRESH_DATABASE_IDENTITY_INVALID")
    for value, pattern in (
        (args.candidate_sha, _SHA1_RE),
        (args.attempt_plan_sha256, _SHA256_RE),
        (args.attempt_id, _ATTEMPT_RE),
        (args.database_container_id, _CONTAINER_ID_RE),
        (args.redis_container_id, _CONTAINER_ID_RE),
        (args.network_id, _CONTAINER_ID_RE),
        (args.execution_image_id.removeprefix("sha256:"), _SHA256_RE),
    ):
        if pattern.fullmatch(value) is None:
            raise ValueError("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    if (
        _DATABASE_RE.fullmatch(args.database) is None
        or _POSTGRES_CONTAINER_RE.fullmatch(args.postgres_container) is None
        or _REDIS_CONTAINER_RE.fullmatch(args.redis_container) is None
        or _NETWORK_RE.fullmatch(args.network) is None
        or _IMAGE_ID_RE.fullmatch(args.execution_image_id) is None
        or args.task_id != f"s6-market-refresh-{args.attempt_id}"
    ):
        raise ValueError("S6_GRAPH_REFRESH_IDENTITY_INVALID")


def _prepare_candidate_imports() -> None:
    """Load project code from the sealed candidate mount and dependencies from the image."""

    if _CANDIDATE_SOURCE.is_symlink() or not _CANDIDATE_SOURCE.is_dir():
        raise ValueError("S6_GRAPH_REFRESH_CANDIDATE_SOURCE_INVALID")
    os.chdir(_CANDIDATE_SOURCE)
    os.environ.pop("PYTHONPATH", None)
    sys.path[:] = [
        str(_CANDIDATE_SOURCE),
        *(
            item
            for item in sys.path
            if item
            and not _is_within(Path(item), _CANDIDATE_SOURCE)
            and not _is_within(Path(item), Path("/app"))
        ),
    ]


def _is_within(path: Path, root: Path) -> bool:
    """Return whether a path resolves inside a given runtime root."""

    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _require_isolated_target_session(
    now: datetime,
    *,
    resolver: Callable[[datetime], date | None],
) -> date:
    """Return the latest ready session or fail before the isolated task runs."""

    target_session = resolver(now)
    if target_session is None:
        raise ValueError("S6_GRAPH_REFRESH_TARGET_SESSION_UNAVAILABLE")
    return target_session


def _isolated_task_kwargs() -> dict[str, str]:
    """Use the full-session provider route that can reproduce the locked target date."""

    return {"source": _ISOLATED_PROVIDER_SOURCE}


def _check_restored_graph_scope(args: argparse.Namespace, now: datetime) -> date:
    """Check the restored scope against its frozen plan before provider calendar discovery."""

    from django.db.models import Q

    from apps.data_center.application.market_calendar import FULL_MARKET_PROVIDER_READY_AFTER
    from apps.data_center.domain.market_time import CN_MARKET_TIMEZONE, cn_market_date_start_utc
    from apps.data_center.infrastructure.models import (
        PriceBarModel,
        QuoteSnapshotModel,
        ValuationFactModel,
    )
    from apps.data_center.target_date_universe_composition import (
        build_target_date_a_share_universe_scope,
    )
    from scripts.plan_release_rehearsal_attempt import parse_graph_scope

    raw = _GRAPH_PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.attempt_plan_sha256:
        raise ValueError("S6_GRAPH_REFRESH_PLAN_MISMATCH")
    plan = json.loads(raw)
    if (
        not isinstance(plan, dict)
        or plan.get("schema") != "release.s6-attempt-plan.v4"
        or plan.get("advance_isolated_market_graph") is not True
        or plan.get("attempt_id") != args.attempt_id
        or plan.get("candidate_sha") != args.candidate_sha
        or plan.get("database") != args.database
        or plan.get("postgres_container") != args.postgres_container
        or plan.get("redis_container") != args.redis_container
        or plan.get("network") != args.network
    ):
        raise ValueError("S6_GRAPH_REFRESH_PLAN_MISMATCH")
    target, ceiling = parse_graph_scope(plan.get("graph_target_date"), plan.get("graph_max_assets"))
    local = now.astimezone(CN_MARKET_TIMEZONE)
    if target > local.date() or (
        target == local.date() and local.time() < FULL_MARKET_PROVIDER_READY_AFTER
    ):
        raise ValueError("S6_GRAPH_REFRESH_SESSION_MISMATCH")
    codes = build_target_date_a_share_universe_scope(target).requested_codes
    if not 0 < len(codes) <= ceiling:
        raise ValueError("S6_GRAPH_REFRESH_SCOPE_OUT_OF_BOUNDS")
    next_midnight = cn_market_date_start_utc(target + timedelta(days=1))
    if QuoteSnapshotModel.objects.filter(
        asset_code__in=codes, snapshot_at__gte=next_midnight
    ).exists():
        raise ValueError("S6_GRAPH_REFRESH_LATER_QUOTE")
    if PriceBarModel.objects.filter(
        asset_code__in=codes, freq="1d", adjustment="none", bar_date__gt=target
    ).exists():
        raise ValueError("S6_GRAPH_REFRESH_LATER_PRICE")
    if ValuationFactModel.objects.filter(
        Q(val_date__gt=target) | Q(observed_at__gte=next_midnight), asset_code__in=codes
    ).exists():
        raise ValueError("S6_GRAPH_REFRESH_LATER_VALUATION")
    return target


def _run(args: argparse.Namespace, environ: dict[str, str]) -> int:
    """Run the real Task Monitor task, then publish its verified graph receipt."""

    _validate_runtime_identity(args, environ)
    _prepare_candidate_imports()
    import django

    django.setup()

    from django.db import connection

    from apps.data_center.infrastructure.rehearsal_http_capture import RehearsalHttpCapture

    if (
        connection.settings_dict.get("NAME") != args.database
        or connection.settings_dict.get("HOST") != args.postgres_container
    ):
        return _blocked("S6_GRAPH_REFRESH_DATABASE_IDENTITY_INVALID")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), current_setting('transaction_read_only'), "
            "current_setting('default_transaction_read_only')"
        )
        row = cursor.fetchone()
    if not row or row[0] != args.database or row[1] != "off" or row[2] != "off":
        return _blocked("S6_GRAPH_REFRESH_DATABASE_IDENTITY_INVALID")

    from apps.data_center.application.market_calendar import (
        FULL_MARKET_PROVIDER_READY_AFTER,
        isolated_s6_full_market_provider_session,
        latest_cn_market_session_ready_after,
    )
    from apps.data_center.application.tasks import refresh_full_market_publications_task
    from scripts.s6_isolated_market_graph_receipt import (
        MarketGraphReceiptError,
        capture_current_market_graph,
        write_success_receipt,
    )

    task_module = sys.modules.get("apps.data_center.application.tasks")
    receipt_module = sys.modules.get("scripts.s6_isolated_market_graph_receipt")
    capture_module = sys.modules.get("apps.data_center.infrastructure.rehearsal_http_capture")
    task_module_file = getattr(task_module, "__file__", None)
    receipt_module_file = getattr(receipt_module, "__file__", None)
    capture_module_file = getattr(capture_module, "__file__", None)
    if (
        task_module is None
        or not isinstance(task_module_file, str)
        or not _is_within(Path(task_module_file), _CANDIDATE_SOURCE)
        or receipt_module is None
        or not isinstance(receipt_module_file, str)
        or not _is_within(Path(receipt_module_file), _CANDIDATE_SOURCE)
        or capture_module is None
        or not isinstance(capture_module_file, str)
        or not _is_within(Path(capture_module_file), _CANDIDATE_SOURCE)
    ):
        return _blocked("S6_GRAPH_REFRESH_CANDIDATE_IMPORT_INVALID")

    triggered_at = datetime.now(UTC)
    capture = RehearsalHttpCapture(
        max_dispatches=args.max_dispatches,
        max_seconds=args.max_seconds,
    )
    try:
        # Calendar discovery can dispatch provider HTTP too; share one budget
        # and deadline with the market refresh instead of opening a second scope.
        with capture:
            expected_session = _check_restored_graph_scope(args, triggered_at)
            target_session = _require_isolated_target_session(
                triggered_at,
                resolver=lambda now: latest_cn_market_session_ready_after(
                    now,
                    ready_after=FULL_MARKET_PROVIDER_READY_AFTER,
                ),
            )
            if target_session != expected_session:
                raise ValueError("S6_GRAPH_REFRESH_SESSION_MISMATCH")
            with isolated_s6_full_market_provider_session(
                target_session,
                triggered_at=triggered_at,
            ):
                result = refresh_full_market_publications_task.apply(
                    task_id=args.task_id,
                    kwargs=_isolated_task_kwargs(),
                    throw=False,
                )
    except ValueError as exc:
        guard_failure = _capture_failure_code(capture)
        failure = (
            str(exc)
            if str(exc) in _KNOWN_FAILURE_CODES
            else "S6_GRAPH_REFRESH_TASK_EXECUTION_FAILED"
        )
        return _blocked(guard_failure or failure, capture=capture)
    except Exception:
        guard_failure = _capture_failure_code(capture)
        return _blocked(
            guard_failure or "S6_GRAPH_REFRESH_TASK_EXECUTION_FAILED",
            capture=capture,
        )
    guard_failure = _capture_failure_code(capture)
    if guard_failure is not None:
        return _blocked(guard_failure, capture=capture)
    if getattr(result, "state", None) != "SUCCESS" or not isinstance(
        getattr(result, "result", None), dict
    ):
        return _blocked("S6_GRAPH_REFRESH_TASK_EXECUTION_FAILED", capture=capture)

    context = {
        "candidate_sha": args.candidate_sha,
        "attempt_id": args.attempt_id,
        "attempt_plan_sha256": args.attempt_plan_sha256,
        "database": args.database,
        "postgres_container": args.postgres_container,
        "redis_container": args.redis_container,
        "postgres_container_id": args.database_container_id,
        "redis_container_id": args.redis_container_id,
        "network": args.network,
        "network_id": args.network_id,
        "execution_image_id": args.execution_image_id,
    }
    try:
        payload = capture_current_market_graph(
            context=context,
            task_id=args.task_id,
            http_capture=_http_capture_summary(capture),
        )
        write_success_receipt(_REPORT, payload)
    except MarketGraphReceiptError as exc:
        return _blocked(exc.error_code, capture=capture)
    except Exception:
        return _blocked("S6_GRAPH_REFRESH_RUNTIME_FAILED", capture=capture)
    print(
        "S6_GRAPH_REFRESH_COMPLETE "
        f"target_trade_date={payload['target_trade_date']} "
        f"task_id={args.task_id} "
        f"dispatch_count={capture.dispatches} "
        f"max_dispatches={capture.max_dispatches} "
        f"receipt_sha256={payload['receipt_sha256']}",
        flush=True,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    """Build the fixed candidate refresh CLI contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--attempt-plan-sha256", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--postgres-container", required=True)
    parser.add_argument("--redis-container", required=True)
    parser.add_argument("--database-container-id", required=True)
    parser.add_argument("--redis-container-id", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--network-id", required=True)
    parser.add_argument("--execution-image-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--max-dispatches", type=int, default=_MAX_HTTP_DISPATCHES)
    parser.add_argument("--max-seconds", type=float, default=_MAX_HTTP_SECONDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one plan-bound current-market refresh in the isolated S6 runtime."""

    try:
        args = _parser().parse_args(argv)
        return _run(args, dict(os.environ))
    except ValueError as exc:
        error_code = str(exc)
        if error_code not in _KNOWN_FAILURE_CODES:
            error_code = "S6_GRAPH_REFRESH_RUNTIME_INVALID"
        return _blocked(error_code)
    except Exception:
        return _blocked("S6_GRAPH_REFRESH_RUNTIME_FAILED")


if __name__ == "__main__":
    raise SystemExit(main())
