#!/usr/bin/env python3
"""Advance one disposable S6 market graph through the canonical full-market task."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

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
_CANDIDATE_SOURCE = Path("/candidate-src")
_KNOWN_FAILURE_CODES = frozenset(
    {
        "S6_GRAPH_REFRESH_ENVIRONMENT_INVALID",
        "S6_GRAPH_REFRESH_DATABASE_IDENTITY_INVALID",
        "S6_GRAPH_REFRESH_IDENTITY_INVALID",
        "S6_GRAPH_REFRESH_CANDIDATE_SOURCE_INVALID",
    }
)


def _blocked(error_code: str) -> int:
    """Print one safe stable error code and return the standard blocked status."""

    print(f"S6_GRAPH_REFRESH_BLOCKED code={error_code}", file=sys.stderr, flush=True)
    return 2


def _validate_runtime_identity(args: argparse.Namespace, environ: dict[str, str]) -> None:
    """Require an exact, isolated database/runtime identity before provider access."""

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


def _run(args: argparse.Namespace, environ: dict[str, str]) -> int:
    """Run the real Task Monitor task, then publish its verified graph receipt."""

    _validate_runtime_identity(args, environ)
    _prepare_candidate_imports()
    import django

    django.setup()

    from django.db import connection

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

    from apps.data_center.application.tasks import refresh_full_market_publications_task
    from scripts.s6_isolated_market_graph_receipt import (
        MarketGraphReceiptError,
        capture_current_market_graph,
        write_success_receipt,
    )

    task_module = sys.modules.get("apps.data_center.application.tasks")
    receipt_module = sys.modules.get("scripts.s6_isolated_market_graph_receipt")
    task_module_file = getattr(task_module, "__file__", None)
    receipt_module_file = getattr(receipt_module, "__file__", None)
    if (
        task_module is None
        or not isinstance(task_module_file, str)
        or not _is_within(Path(task_module_file), _CANDIDATE_SOURCE)
        or receipt_module is None
        or not isinstance(receipt_module_file, str)
        or not _is_within(Path(receipt_module_file), _CANDIDATE_SOURCE)
    ):
        return _blocked("S6_GRAPH_REFRESH_CANDIDATE_IMPORT_INVALID")

    try:
        result = refresh_full_market_publications_task.apply(
            task_id=args.task_id,
            throw=False,
        )
    except Exception:
        return _blocked("S6_GRAPH_REFRESH_TASK_EXECUTION_FAILED")
    if result.state != "SUCCESS" or not isinstance(result.result, dict):
        return _blocked("S6_GRAPH_REFRESH_TASK_EXECUTION_FAILED")

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
        payload = capture_current_market_graph(context=context, task_id=args.task_id)
        write_success_receipt(_REPORT, payload)
    except MarketGraphReceiptError as exc:
        return _blocked(exc.error_code)
    print(
        "S6_GRAPH_REFRESH_COMPLETE "
        f"target_trade_date={payload['target_trade_date']} "
        f"task_id={args.task_id} receipt_sha256={payload['receipt_sha256']}",
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
