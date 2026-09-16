"""Read the current News head through the pinned EVID-09 target image only.

This source is streamed to an ephemeral, read-only, portless target container.
The libpq default transaction policy must already be READ ONLY before Django
setup; the explicit PostgreSQL snapshot is rolled back after the read.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

EXPECTED_NEWS_ID = "5713bdc5-0810-54ea-a043-119e724d773d"
EXPECTED_NEWS_HASH = "aed230f1d3c4e6b322e9533f594421badabe1f52fa513580ef217d2089725375"
EXPECTED_MEMBER_COUNT = 12
STRICT_DATASETS = (
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.financial.fact",
    "equity.valuation.fact",
)


class RuntimePreflightError(ValueError):
    """A stable, secret-free diagnostic stop reason."""


def _safe_excepthook(
    exception_type: type[BaseException],
    exception: BaseException,
    traceback: TracebackType | None,
) -> None:
    del exception, traceback
    print(f"DENY: {exception_type.__name__}", file=sys.stderr)


sys.excepthook = _safe_excepthook


def main() -> int:
    """Verify policy and News public ports in a rollback-only DB snapshot."""

    stage = "startup_guard"
    try:
        if "default_transaction_read_only=on" not in os.environ.get("PGOPTIONS", ""):
            raise RuntimePreflightError("PGOPTIONS_MISSING")
        import django
        from django.db import connection, transaction

        stage = "django_setup"
        django.setup()
        stage = "db_default_policy"
        with connection.cursor() as cursor:
            cursor.execute("SHOW default_transaction_read_only")
            default_read_only = cursor.fetchone()[0]
        if default_read_only != "on":
            raise RuntimePreflightError("DB_DEFAULT_READ_ONLY_OFF")

        from apps.data_center.application.public import (
            get_active_publication_policy,
            get_current_publication,
            get_published_market_news,
        )

        with transaction.atomic():
            stage = "db_snapshot_policy"
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SHOW transaction_read_only")
                read_only = cursor.fetchone()[0]
                cursor.execute("SHOW transaction_isolation")
                isolation = cursor.fetchone()[0]
            if read_only != "on" or isolation != "repeatable read":
                raise RuntimePreflightError("DB_SNAPSHOT_POLICY_MISMATCH")

            stage = "strict_policy_reader"
            policies_present = all(
                get_active_publication_policy(dataset_key) is not None
                for dataset_key in STRICT_DATASETS
            )
            stage = "news_current_reader"
            current = get_current_publication("market.news", "current")
            stage = "news_published_reader"
            published = get_published_market_news(limit=50)
            stage = "report"
            rows = published.get("rows")
            selected_rows = len(rows) if isinstance(rows, list) else None
            coverage = current.get("coverage") if current is not None else None
            selected_count = coverage.get("selected_count") if isinstance(coverage, dict) else None
            publication_identity_match = (
                current is not None
                and current.get("publication_id") == EXPECTED_NEWS_ID
                and current.get("publication_hash") == EXPECTED_NEWS_HASH
                and selected_count == EXPECTED_MEMBER_COUNT
            )
            blocked = bool(published.get("must_not_use_for_decision"))
            selected_rows_match = selected_rows == EXPECTED_MEMBER_COUNT if not blocked else True
            report = {
                "schema": "evid09.target-current-db-readonly-runtime.v1",
                "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "target_source_commit": "6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b",
                "transaction": "REPEATABLE READ READ ONLY; rollback",
                "four_strict_policies_present": policies_present,
                "news_publication_identity_match": publication_identity_match,
                "news_current_publication_id": current.get("publication_id") if current else None,
                "news_current_publication_hash": (
                    current.get("publication_hash") if current else None
                ),
                "news_current_selected_count": selected_count,
                "published_query_selected_rows": selected_rows,
                "published_query_must_not_use_for_decision": blocked,
                "published_query_blocked_reason": published.get("blocked_reason"),
                "published_query_freshness_status": published.get("freshness_status"),
                "selected_rows_match_when_usable": selected_rows_match,
                "business_dml_performed": False,
                "decision": (
                    "PASS_READ_ONLY"
                    if policies_present and publication_identity_match and selected_rows_match
                    else "DENY_RUNTIME_OR_DRIFT"
                ),
            }
            transaction.set_rollback(True)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0 if report["decision"] == "PASS_READ_ONLY" else 1
    except RuntimePreflightError as exc:
        print(f"DENY_CODE: {exc} STAGE={stage}", file=sys.stderr)
        return 1
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        print(f"DENY: {type(exc).__name__} STAGE={stage}", file=sys.stderr)
        frames = [
            (Path(frame.filename).name, frame.name, frame.lineno)
            for frame in traceback.extract_tb(exc.__traceback__)[-6:]
        ]
        print(f"DENY_FRAMES: {json.dumps(frames, separators=(',', ':'))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
