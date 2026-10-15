#!/usr/bin/env python3
"""Run focused contracts, then optionally probe S6 prepare routes without writes.

This diagnostic creates no attempt, database, receipt or release approval.
Invoke as ``python -m scripts.run_s6_prepare_preflight`` from the checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from apps.data_center.domain.entities import QuoteSnapshot, ValuationFact
from apps.data_center.domain.market_time import cn_market_session_close_utc

ROOT = Path(__file__).resolve().parents[1]
FOCUSED_TESTS = (
    "tests/unit/test_refresh_s6_isolated_market_graph.py",
    "tests/unit/data_center/test_market_calendar.py",
    "tests/unit/data_center/test_phase3_provider_adapters.py"
    "::test_tushare_current_valuations_use_one_session_batch",
    "tests/unit/data_center/test_egress_tushare_transport.py",
)


class SampleProvider(Protocol):
    """Only the two read capabilities needed by the prepare diagnostic."""

    def fetch_current_valuations(
        self, asset_codes: list[str], as_of_date: date
    ) -> list[ValuationFact]:
        """Read the explicit target-session valuation batch."""

    def fetch_quote_snapshots_for_session(
        self, asset_codes: list[str], target_trade_date: date
    ) -> list[QuoteSnapshot]:
        """Read the explicit target-session quote batch."""


def select_sample(codes: tuple[str, ...], size: int) -> tuple[str, ...]:
    """Select a deterministic, evenly spread sample of at most fifty assets."""

    if type(size) is not int or not 1 <= size <= 50:
        raise ValueError("S6_PREFLIGHT_SAMPLE_SIZE_INVALID")
    universe = tuple(sorted(set(codes)))
    if not universe:
        raise ValueError("S6_PREFLIGHT_UNIVERSE_EMPTY")
    count = min(size, len(universe))
    if count == 1:
        return universe[:1]
    return tuple(universe[i * (len(universe) - 1) // (count - 1)] for i in range(count))


def _report(outcome: str, **fields: object) -> dict[str, object]:
    """Keep all diagnostics explicitly outside the release evidence contract."""

    return {
        "schema": "release.s6-prepare-diagnostic.v1",
        "outcome": outcome,
        "release_approval": False,
        "must_not_use_for_decision": True,
        "decision_blocked_reason": "diagnostic_sample_not_release_evidence",
        "stored": 0,
        **fields,
    }


def _coverage(codes: tuple[str, ...], returned: list[str], valid: list[str]) -> dict[str, object]:
    """Count unique exact-session rows; duplicates never inflate coverage."""

    counts = Counter(returned)
    succeeded = set(valid).intersection(codes)
    return {
        "requested": len(codes),
        "succeeded": len(succeeded),
        "failed": len(codes) - len(succeeded),
        "stored": 0,
        "coverage_ratio": len(succeeded) / len(codes),
        "missing_asset_codes": sorted(set(codes) - succeeded),
        "unexpected_asset_codes": sorted(set(returned) - set(codes)),
        "duplicate_asset_codes": sorted(code for code, count in counts.items() if count > 1),
    }


def _complete(coverage: dict[str, object]) -> bool:
    """Require a complete sample without changing production coverage policy."""

    return (
        coverage["failed"] == 0
        and not coverage["unexpected_asset_codes"]
        and not coverage["duplicate_asset_codes"]
    )


def probe_sample(
    provider: SampleProvider, codes: tuple[str, ...], target: date
) -> dict[str, object]:
    """Read at most two batches, stopping after an incomplete valuation sample."""

    # Validate before either provider call, including direct Python callers.
    if not codes or len(codes) > 50 or len(set(codes)) != len(codes):
        raise ValueError("S6_PREFLIGHT_SAMPLE_INVALID")
    close = cn_market_session_close_utc(target)
    valuations = provider.fetch_current_valuations(list(codes), target)
    valuation = _coverage(
        codes,
        [row.asset_code for row in valuations],
        [
            row.asset_code
            for row in valuations
            if row.val_date == target and row.observed_at == close and row.source.strip()
        ],
    )
    valuation["source_observed_at"] = sorted(
        {row.observed_at.isoformat() for row in valuations if row.observed_at is not None}
    )
    fields: dict[str, object] = {
        "target_trade_date": target.isoformat(),
        "sample_asset_codes": list(codes),
        "valuation": valuation,
    }
    if not _complete(valuation):
        return _report("blocked", error_code="S6_PREFLIGHT_VALUATION_SAMPLE_INCOMPLETE", **fields)
    quotes = provider.fetch_quote_snapshots_for_session(list(codes), target)
    quote = _coverage(
        codes,
        [row.asset_code for row in quotes],
        [row.asset_code for row in quotes if row.snapshot_at == close and row.source.strip()],
    )
    quote["source_observed_at"] = sorted({row.snapshot_at.isoformat() for row in quotes})
    fields["quote"] = quote
    if not _complete(quote):
        return _report("blocked", error_code="S6_PREFLIGHT_QUOTE_SAMPLE_INCOMPLETE", **fields)
    return _report("success", **fields)


def _live_probe(target: date, sample_size: int) -> dict[str, object]:
    """Probe canonical configured routes inside a PostgreSQL read-only transaction."""

    from django.db import connection, transaction

    from apps.data_center.application.market_calendar import (
        FULL_MARKET_PROVIDER_READY_AFTER,
        latest_cn_market_session_ready_after,
    )
    from apps.data_center.application.public import get_active_provider_id_by_source
    from apps.data_center.composition import get_provider_registry
    from apps.data_center.domain.protocols import (
        CurrentValuationBatchProviderProtocol,
        SessionQuoteBatchProviderProtocol,
    )
    from apps.data_center.target_date_universe_composition import (
        build_target_date_a_share_universe_scope,
    )
    from scripts.refresh_s6_isolated_market_graph import _isolated_task_kwargs

    if connection.vendor != "postgresql" or connection.in_atomic_block:
        return _report("blocked", error_code="S6_PREFLIGHT_READ_ONLY_POSTGRES_REQUIRED")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        resolved = latest_cn_market_session_ready_after(
            datetime.now(UTC), ready_after=FULL_MARKET_PROVIDER_READY_AFTER
        )
        if resolved != target:
            return _report("blocked", error_code="S6_PREFLIGHT_TARGET_SESSION_MISMATCH")
        provider_id = get_active_provider_id_by_source(_isolated_task_kwargs()["source"])
        if provider_id is None:
            return _report("blocked", error_code="S6_PREFLIGHT_PROVIDER_UNAVAILABLE")
        provider = get_provider_registry().get_by_id(provider_id)
        if not isinstance(provider, CurrentValuationBatchProviderProtocol) or not isinstance(
            provider, SessionQuoteBatchProviderProtocol
        ):
            return _report("blocked", error_code="S6_PREFLIGHT_SESSION_BATCH_UNAVAILABLE")
        scope = build_target_date_a_share_universe_scope(target)
        sample = select_sample(scope.requested_codes, sample_size)
        result = probe_sample(provider, sample, target)
        result["provider_id"] = provider_id
        result["source"] = _isolated_task_kwargs()["source"]
        result["universe_count"] = len(scope.requested_codes)
        result["coverage_scope"] = "sample_only"
        return result


def _worker(args: argparse.Namespace) -> dict[str, object]:
    """Emit safe errors without reflecting credentials or provider exception text."""

    import django
    from django.core.exceptions import ImproperlyConfigured
    from django.db import DatabaseError

    try:
        django.setup()
    except (ImproperlyConfigured, OSError, RuntimeError, ValueError):
        return _report("blocked", error_code="S6_PREFLIGHT_CONFIGURATION_INVALID")

    from core.exceptions import AgomTradeProException

    try:
        return _live_probe(args.target_date, args.sample_size)
    except (
        AgomTradeProException,
        DatabaseError,
        ImproperlyConfigured,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return _report("blocked", error_code="S6_PREFLIGHT_PROVIDER_FAILED")


def _emit(result: dict[str, object]) -> int:
    """Print one JSON diagnostic and return a fail-closed exit status."""

    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["outcome"] == "success" else 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run focused tests first; live access requires explicit opt-in and target date."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Probe configured provider after tests")
    parser.add_argument("--target-date", type=date.fromisoformat)
    parser.add_argument("--sample-size", type=int, choices=range(1, 51), default=10)
    parser.add_argument(
        "--timeout", type=int, default=120, help="Provider process budget in seconds"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (args.live or args.worker) and args.target_date is None:
        parser.error("--target-date is required for provider access")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds")
    if args.worker:
        return _emit(_worker(args))
    try:
        tests = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *FOCUSED_TESTS,
                "-q",
                "--no-cov",
                f"--basetemp=.tmp/s6-prepare-preflight/{uuid4().hex}",
            ],
            cwd=ROOT,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "core.settings.development_sqlite"},
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _emit(_report("blocked", error_code="S6_PREFLIGHT_TESTS_UNAVAILABLE"))
    print(tests.stdout, file=sys.stderr, end="")
    print(tests.stderr, file=sys.stderr, end="")
    if tests.returncode != 0:
        return _emit(_report("blocked", error_code="S6_PREFLIGHT_TESTS_FAILED"))
    if not args.live:
        return _emit(_report("success", focused_tests="passed", provider_probe="not_requested"))
    try:
        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.run_s6_prepare_preflight",
                "--worker",
                "--target-date",
                args.target_date.isoformat(),
                "--sample-size",
                str(args.sample_size),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _emit(_report("blocked", error_code="S6_PREFLIGHT_PROVIDER_TIMEOUT"))
    except OSError:
        return _emit(_report("blocked", error_code="S6_PREFLIGHT_PROVIDER_UNAVAILABLE"))
    try:
        payload = json.loads(worker.stdout.splitlines()[-1])
    except (ValueError, IndexError):
        return _emit(_report("blocked", error_code="S6_PREFLIGHT_PROVIDER_FAILED"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "release.s6-prepare-diagnostic.v1"
        or payload.get("release_approval") is not False
        or payload.get("must_not_use_for_decision") is not True
        or payload.get("outcome") not in ("success", "blocked")
        or (worker.returncode != 0 and payload.get("outcome") == "success")
    ):
        return _emit(_report("blocked", error_code="S6_PREFLIGHT_PROVIDER_FAILED"))
    payload["focused_tests"] = "passed"
    return _emit(payload)


if __name__ == "__main__":
    raise SystemExit(main())
