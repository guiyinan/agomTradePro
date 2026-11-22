"""Offline normal-entry regressions for the isolated graph preflight."""

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import refresh_s6_isolated_market_graph as launcher
from scripts.plan_release_rehearsal_attempt import build_attempt_plan


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("case", "expected_code", "calendar_calls", "task_calls"),
    [
        ("later_valuation", "LATER_VALUATION", 0, 0),
        ("later_observation", "LATER_VALUATION", 0, 0),
        ("later_quote", "LATER_QUOTE", 0, 0),
        ("later_price", "LATER_PRICE", 0, 0),
        ("empty", "SCOPE_OUT_OF_BOUNDS", 0, 0),
        ("oversize", "SCOPE_OUT_OF_BOUNDS", 0, 0),
        ("tampered", "PLAN_MISMATCH", 0, 0),
        ("too_early", "SESSION_MISMATCH", 0, 0),
        ("calendar_disagrees", "SESSION_MISMATCH", 1, 0),
        ("eligible", "TASK_EXECUTION_FAILED", 1, 1),
    ],
)
def test_normal_worker_checks_restored_facts_before_calendar_and_task(
    case: str,
    expected_code: str,
    calendar_calls: int,
    task_calls: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Run the worker against local ORM facts with an offline calendar and a terminal task stub."""
    import requests
    from django.db import connection

    from apps.data_center.application import market_calendar, tasks
    from apps.data_center.infrastructure.models import (
        AssetMasterModel,
        PriceBarModel,
        QuoteSnapshotModel,
        ValuationFactModel,
    )

    target = date(2026, 11, 20)
    code = "600519.SH"
    next_midnight = datetime(2026, 11, 20, 16, tzinfo=UTC)
    if case != "empty":
        AssetMasterModel.objects.create(code=code, name=code, asset_type="stock", exchange="SSE")
    if case == "oversize":
        AssetMasterModel.objects.create(
            code="000001.SZ", name="Second", asset_type="stock", exchange="SZSE"
        )
    # A verified later listing is outside this session's scope even with a newer fact.
    AssetMasterModel.objects.create(
        code="600000.SH",
        name="Later listing",
        asset_type="stock",
        exchange="SSE",
        list_date=date(2026, 11, 23),
        extra={"list_date_evidence_status": "verified", "list_date_source": "exchange"},
    )
    ValuationFactModel.objects.create(asset_code="600000.SH", val_date=date(2026, 11, 21))
    ValuationFactModel.objects.create(
        asset_code=code,
        val_date=target,
        observed_at=(
            next_midnight if case == "later_observation" else datetime(2026, 11, 20, 7, tzinfo=UTC)
        ),
        available_at=next_midnight,
        fetched_at=next_midnight,
        source="tushare",
    )
    if case == "later_valuation":
        ValuationFactModel.objects.create(
            asset_code=code, val_date=date(2026, 11, 21), source="akshare"
        )
    if case == "later_quote":
        QuoteSnapshotModel.objects.create(
            asset_code=code, snapshot_at=next_midnight, current_price=1, source="tushare"
        )
    PriceBarModel.objects.create(
        asset_code=code,
        bar_date=date(2026, 11, 21),
        adjustment="none" if case == "later_price" else "forward",
        source="tushare",
        open=1,
        close=1,
        high=1,
        low=1,
    )

    plan = build_attempt_plan(
        candidate_sha="a" * 40,
        attempt_id="b" * 32,
        attempts_dir=tmp_path,
        advance_isolated_market_graph=True,
        graph_target_date=target.isoformat(),
        graph_max_assets=1,
    )
    raw = (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path = tmp_path / "attempt-plan.json"
    path.write_bytes(raw + (b" " if case == "tampered" else b""))
    monkeypatch.setattr(launcher, "_GRAPH_PLAN", path)
    args = argparse.Namespace(
        candidate_sha=plan["candidate_sha"],
        attempt_id=plan["attempt_id"],
        attempt_plan_sha256=hashlib.sha256(raw).hexdigest(),
        database=plan["database"],
        postgres_container=plan["postgres_container"],
        redis_container=plan["redis_container"],
        network=plan["network"],
        max_dispatches=50,
        max_seconds=3600,
        task_id="test",
    )
    monkeypatch.setattr(launcher, "_validate_runtime_identity", lambda *args: None)
    monkeypatch.setattr(launcher, "_prepare_candidate_imports", lambda: None)
    monkeypatch.setattr(launcher, "_CANDIDATE_SOURCE", Path(launcher.__file__).resolve().parents[1])
    monkeypatch.setattr(
        launcher,
        "datetime",
        Mock(
            now=Mock(
                return_value=datetime(2026, 11, 20, 9, 4 if case == "too_early" else 5, tzinfo=UTC)
            )
        ),
    )
    monkeypatch.setitem(connection.settings_dict, "NAME", args.database)
    monkeypatch.setitem(connection.settings_dict, "HOST", args.postgres_container)
    resolver = Mock(return_value=date(2026, 11, 19) if case == "calendar_disagrees" else target)
    task = Mock(return_value=SimpleNamespace(state="FAILURE"))
    wire = Mock(side_effect=AssertionError("unexpected provider request"))
    monkeypatch.setattr(market_calendar, "latest_cn_market_session_ready_after", resolver)
    monkeypatch.setattr(tasks.refresh_full_market_publications_task, "apply", task)
    monkeypatch.setattr(requests.Session, "send", wire)

    def sqlite_identity(execute, sql, params, many, context):
        if sql.startswith("SELECT current_database()"):
            return execute("SELECT %s, 'off', 'off'", [args.database], many, context)
        assert sql.lstrip().upper().startswith("SELECT ")
        return execute(sql, params, many, context)

    with connection.execute_wrapper(sqlite_identity):
        assert launcher._run(args, {}) == 2
    err = capsys.readouterr().err
    assert f"code=S6_GRAPH_REFRESH_{expected_code} " in err and " dispatch_count=0 " in err
    assert resolver.call_count == calendar_calls and task.call_count == task_calls
    wire.assert_not_called()
