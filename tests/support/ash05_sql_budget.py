"""Optional assigned-QA query timing without SQL values, bodies, or credentials."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any

from django.db import connection

_SEQUENCE = itertools.count(1)
_TABLE = re.compile(r'(?:FROM|JOIN|UPDATE|INTO)\s+"?([a-zA-Z0-9_]+)', re.IGNORECASE)


def record_ash05_blocked_origin(error: BaseException) -> None:
    """Retain bounded error classes and frame locations without messages, SQL or local values."""
    output = os.environ.get("ASH05_SQL_BUDGET_DIR")
    if not output:
        return
    chain: list[dict[str, object]] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(
            {
                "exception_type": type(current).__name__,
                "frames": [
                    {
                        "file": Path(frame.filename).name,
                        "line": frame.lineno,
                        "function": frame.name,
                    }
                    for frame in traceback.extract_tb(current.__traceback__)[-12:]
                ],
            }
        )
        current = current.__cause__
    directory = Path(output) / "blocked-origins"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{next(_SEQUENCE):03d}.json"
    path.write_text(json.dumps({"chain": chain}, indent=2) + "\n", encoding="utf-8")


@contextmanager
def record_ash05_sql_budget(*, label: str) -> Iterator[None]:
    """Record table names, counts and elapsed time only when Root enables QA profiling."""
    output = os.environ.get("ASH05_SQL_BUDGET_DIR")
    if not output:
        yield
        return
    bins: dict[str, tuple[int, float]] = {}
    metadata_bins: dict[str, tuple[int, float]] = {}

    def measure(
        execute: Callable[..., Any],
        sql: object,
        params: object,
        many: bool,
        context: dict[str, Any],
    ) -> Any:
        started = perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            elapsed = perf_counter() - started
            key = (
                ",".join(sorted(set(_TABLE.findall(sql) if isinstance(sql, str) else ())))
                or "transaction_or_metadata"
            )
            count, total = bins.get(key, (0, 0.0))
            bins[key] = count + 1, total + elapsed
            if key == "transaction_or_metadata":
                # Retain command families and code locations, never SQL or parameters.
                command = (
                    str(sql).lstrip().split(None, 1)[0].upper()
                    if isinstance(sql, str) and sql.strip()
                    else "OTHER"
                )
                if command not in {
                    "SELECT",
                    "SHOW",
                    "SAVEPOINT",
                    "RELEASE",
                    "ROLLBACK",
                    "LOCK",
                    "SET",
                }:
                    command = "OTHER"
                frames = traceback.extract_stack(limit=30)
                site = next(
                    (
                        f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
                        for frame in reversed(frames[:-1])
                        if "agomTradePro" in frame.filename
                        and "site-packages" not in frame.filename
                        and Path(frame.filename).name != "ash05_sql_budget.py"
                    ),
                    "framework",
                )
                metadata_key = f"{command} {site}"
                meta_count, meta_total = metadata_bins.get(metadata_key, (0, 0.0))
                metadata_bins[metadata_key] = meta_count + 1, meta_total + elapsed

    started = perf_counter()
    try:
        with connection.execute_wrapper(measure):
            yield
    finally:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{next(_SEQUENCE):03d}-{hashlib.sha256(label.encode()).hexdigest()[:12]}.json"
        report = {
            "label": label,
            "wall_seconds": perf_counter() - started,
            "query_count": sum(value[0] for value in bins.values()),
            "query_seconds": sum(value[1] for value in bins.values()),
            "tables": sorted(
                (
                    {"tables": key, "count": value[0], "seconds": value[1]}
                    for key, value in bins.items()
                ),
                key=lambda value: value["seconds"],
                reverse=True,
            ),
            "sql_values_retained": False,
            "metadata_origins": sorted(
                (
                    {"origin": key, "count": value[0], "seconds": value[1]}
                    for key, value in metadata_bins.items()
                ),
                key=lambda value: value["seconds"],
                reverse=True,
            ),
        }
        (directory / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
