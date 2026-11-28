"""Fast S6 diagnostics must fail early without creating release evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from apps.data_center.domain.entities import QuoteSnapshot, ValuationFact
from scripts import run_s6_prepare_preflight as preflight

TARGET = date(2026, 10, 14)
CLOSE = datetime(2026, 10, 14, 7, tzinfo=UTC)
CODES = ("000001.SZ", "600000.SH")


def _provider() -> Mock:
    provider = Mock()
    provider.fetch_quote_snapshots_for_session.return_value = [
        QuoteSnapshot(code, CLOSE, 10.0, "tushare") for code in CODES
    ]
    provider.fetch_current_valuations.return_value = [
        ValuationFact(code, TARGET, market_cap=100.0, source="tushare", observed_at=CLOSE)
        for code in CODES
    ]
    return provider


def test_sample_is_bounded_deterministic_and_spans_universe() -> None:
    codes = tuple(f"{i:06}.SZ" for i in range(100))
    sample = preflight.select_sample(tuple(reversed(codes)), 10)
    assert sample == preflight.select_sample(codes, 10)
    assert len(set(sample)) == 10
    assert sample[0] == codes[0]
    assert sample[-1] == codes[-1]


@pytest.mark.parametrize("size", [0, -1, 51, True])
def test_sample_rejects_unbounded_or_invalid_requests(size: int) -> None:
    with pytest.raises(ValueError):
        preflight.select_sample(CODES, size)


def test_empty_universe_is_blocked() -> None:
    with pytest.raises(ValueError, match="S6_PREFLIGHT_UNIVERSE_EMPTY"):
        preflight.select_sample((), 10)


def test_fresh_worker_reaches_the_postgres_guard_without_provider_access() -> None:
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_s6_prepare_preflight",
            "--worker",
            "--target-date",
            TARGET.isoformat(),
            "--max-quote-gaps",
            "11",
        ],
        cwd=preflight.ROOT,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "core.settings.development_sqlite"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 2, run.stderr
    assert (
        json.loads(run.stdout.splitlines()[-1])["error_code"]
        == "S6_PREFLIGHT_READ_ONLY_POSTGRES_REQUIRED"
    )


def test_daily_rejection_records_business_code_before_suspension_lookup() -> None:
    from core.exceptions import TushareError

    provider = _provider()
    provider.fetch_quote_snapshots_for_session.side_effect = TushareError(
        "private daily response", code="TUSHARE_PROVIDER_REJECTED", details={"provider_code": 40203}
    )
    report = preflight.probe_quote_gaps(provider, CODES, TARGET, 11)
    assert report["outcome"] == "blocked" and report["provider_code"] == 40203
    assert report["error_code"] == "TUSHARE_PROVIDER_REJECTED" and report["universe_count"] == 2
    assert "private daily response" not in str(report)
    provider.model_market_source.assert_not_called()


def test_gap_preflight_calls_the_prepare_source_once_for_the_actual_missing_set():
    import pandas as pd

    from apps.data_center.infrastructure.tushare_model_market_source import TushareModelMarketSource
    from core.exceptions import TushareError

    provider = _provider()
    extra = ("600001.SH", "600002.SH")
    universe = CODES + extra
    client = Mock()
    provider.model_market_source.return_value = TushareModelMarketSource(client)
    frame = pd.DataFrame(
        [[extra[0], "20261014", "S", None], [extra[1], "20261014", "R", None]],
        columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"],
    )
    client.suspend_d.return_value = frame
    result = preflight.probe_quote_gaps(provider, universe, TARGET, max_gaps=1)
    assert result["outcome"] == "blocked"
    client.suspend_d.assert_not_called()
    result = preflight.probe_quote_gaps(provider, universe, TARGET, max_gaps=2)
    assert result["verified_codes"] == [extra[0]]
    assert result["unverified_codes"] == [extra[1]]
    assert result["outcome"] == "blocked"
    client.suspend_d.assert_called_once_with(
        ts_code=",".join(extra),
        start_date="20261014",
        end_date="20261014",
        fields="ts_code,trade_date,suspend_type,suspend_timing",
    )
    frame.loc[1, "suspend_type"] = "S"
    assert preflight.probe_quote_gaps(provider, universe, TARGET, 2)["outcome"] == "success"
    client.suspend_d.side_effect = TushareError(
        "private text", code="TUSHARE_PROVIDER_REJECTED", details={"provider_code": 40203}
    )
    result = preflight.probe_quote_gaps(provider, universe, TARGET, 2)
    assert result["provider_code"] == 40203
    assert result["unverified_codes"] == list(extra)
    assert "private text" not in str(result)
    assert client.suspend_d.call_count == 3


def test_live_probe_uses_explicit_session_batches_without_writers() -> None:
    provider = _provider()
    result = preflight.probe_sample(provider, CODES, TARGET)
    assert result["outcome"] == "success"
    assert result["release_approval"] is False
    assert result["must_not_use_for_decision"] is True
    assert result["stored"] == 0
    assert provider.method_calls == [
        ("fetch_current_valuations", (list(CODES), TARGET), {}),
        ("fetch_quote_snapshots_for_session", (list(CODES), TARGET), {}),
    ]


@pytest.mark.parametrize("failure", ["missing", "wrong_date", "duplicate", "no_clock", "intraday"])
def test_valuation_failure_stops_before_quote(failure: str) -> None:
    provider = _provider()
    rows = provider.fetch_current_valuations.return_value
    if failure == "missing":
        rows.pop()
    elif failure == "wrong_date":
        rows[0] = replace(rows[0], val_date=date(2026, 10, 13))
    elif failure == "duplicate":
        rows.append(rows[0])
    elif failure == "no_clock":
        rows[0] = replace(rows[0], observed_at=None)
    else:
        rows[0] = replace(rows[0], observed_at=CLOSE.replace(hour=6))
    result = preflight.probe_sample(provider, CODES, TARGET)
    assert result["outcome"] == "blocked"
    assert result["error_code"] == "S6_PREFLIGHT_VALUATION_SAMPLE_INCOMPLETE"
    provider.fetch_quote_snapshots_for_session.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["missing", "wrong_date", "duplicate", "unexpected", "intraday"]
)
def test_quote_failure_never_becomes_sample_success(failure: str) -> None:
    provider = _provider()
    rows = provider.fetch_quote_snapshots_for_session.return_value
    if failure == "missing":
        rows.pop()
    elif failure == "wrong_date":
        rows[0] = replace(rows[0], snapshot_at=CLOSE.replace(day=13))
    elif failure == "duplicate":
        rows.append(rows[0])
    elif failure == "unexpected":
        rows.append(replace(rows[0], asset_code="999999.SZ"))
    else:
        rows[0] = replace(rows[0], snapshot_at=CLOSE.replace(hour=6))
    result = preflight.probe_sample(provider, CODES, TARGET)
    assert result["outcome"] == "blocked"
    assert result["error_code"] == "S6_PREFLIGHT_QUOTE_SAMPLE_INCOMPLETE"


def test_failed_focused_tests_prevent_provider_process(monkeypatch, capsys) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], 1, "test failure", ""))
    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight.main(["--live", "--target-date", TARGET.isoformat()]) == 2
    assert run.call_count == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "S6_PREFLIGHT_TESTS_FAILED"


def test_tests_only_does_not_contact_provider(monkeypatch, capsys, tmp_path) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "passed", ""))
    monkeypatch.setattr(preflight, "ROOT", tmp_path)
    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight.main([]) == 0
    assert run.call_count == 1
    assert run.call_args.kwargs["timeout"] == 600
    base_arg = next(arg for arg in run.call_args.args[0] if arg.startswith("--basetemp="))
    base = tmp_path / base_arg.removeprefix("--basetemp=")
    assert base.parent.is_dir()
    assert not base.exists()
    assert (
        run.call_args.kwargs["env"]["DJANGO_SETTINGS_MODULE"] == "core.settings.development_sqlite"
    )
    assert json.loads(capsys.readouterr().out)["provider_probe"] == "not_requested"


def test_provider_timeout_is_bounded_and_does_not_leak_output(monkeypatch, capsys) -> None:
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, "passed", ""),
            subprocess.TimeoutExpired("provider", 60, output="secret", stderr="secret"),
        ]
    )
    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight.main(["--live", "--target-date", TARGET.isoformat(), "--timeout", "60"]) == 2
    assert run.call_args.kwargs["timeout"] == 60
    captured = capsys.readouterr()
    assert "secret" not in captured.out + captured.err
    assert json.loads(captured.out)["error_code"] == "S6_PREFLIGHT_PROVIDER_TIMEOUT"


def test_live_requires_target_date_before_tests_or_provider(monkeypatch) -> None:
    run = Mock()
    monkeypatch.setattr(preflight.subprocess, "run", run)
    with pytest.raises(SystemExit):
        preflight.main(["--live"])
    run.assert_not_called()


@pytest.fixture
def live_runtime(monkeypatch):
    """Replace external I/O while preserving the live composition call sequence."""

    import django.db

    from apps.data_center import composition, target_date_universe_composition
    from apps.data_center.application import market_calendar, public

    connection = MagicMock(vendor="postgresql", in_atomic_block=False)
    monkeypatch.setattr(django.db, "connection", connection)
    monkeypatch.setattr(django.db.transaction, "atomic", MagicMock())
    resolver = Mock(return_value=TARGET)
    monkeypatch.setattr(market_calendar, "latest_cn_market_session_ready_after", resolver)
    selection = Mock(return_value=7)
    monkeypatch.setattr(public, "get_active_provider_id_by_source", selection)
    provider = _provider()
    live_provider = SimpleNamespace(
        fetch_current_valuations=provider.fetch_current_valuations,
        fetch_quote_snapshots_for_session=provider.fetch_quote_snapshots_for_session,
        method_calls=provider.method_calls,
    )
    registry = Mock()
    registry.get_by_id.return_value = live_provider
    monkeypatch.setattr(composition, "get_provider_registry", lambda: registry)
    scope = Mock(return_value=SimpleNamespace(requested_codes=CODES))
    monkeypatch.setattr(
        target_date_universe_composition, "build_target_date_a_share_universe_scope", scope
    )
    return connection, resolver, selection, live_provider, scope


def test_live_sets_postgres_read_only_before_calendar_and_provider(live_runtime) -> None:
    connection, resolver, selection, provider, scope = live_runtime
    execute = connection.cursor.return_value.__enter__.return_value.execute

    def resolve(*args, **kwargs):
        execute.assert_called_once_with("SET TRANSACTION READ ONLY")
        provider.fetch_current_valuations.assert_not_called()
        return TARGET

    resolver.side_effect = resolve
    result = preflight._live_probe(TARGET, 10)
    assert result["outcome"] == "success"
    assert result["coverage_scope"] == "sample_only"
    assert result["universe_count"] == 2
    selection.assert_called_once_with("tushare")
    scope.assert_called_once_with(TARGET)


@pytest.mark.parametrize("vendor,in_atomic", [("sqlite", False), ("postgresql", True)])
def test_live_rejects_unsafe_transaction_before_calendar(live_runtime, vendor, in_atomic) -> None:
    connection, resolver, selection, provider, scope = live_runtime
    connection.vendor = vendor
    connection.in_atomic_block = in_atomic
    result = preflight._live_probe(TARGET, 10)
    assert result["error_code"] == "S6_PREFLIGHT_READ_ONLY_POSTGRES_REQUIRED"
    resolver.assert_not_called()
    selection.assert_not_called()
    scope.assert_not_called()
    assert not provider.method_calls


def test_full_quote_gap_probe_closes_scope_transaction_before_audited_transport(live_runtime):
    from django.db import transaction

    connection, resolver, _, provider, scope = live_runtime
    rows = provider.fetch_quote_snapshots_for_session.return_value

    def calendar(*args, **kwargs):
        connection.cursor.assert_not_called()
        provider.fetch_quote_snapshots_for_session.assert_not_called()
        return TARGET

    resolver.side_effect = calendar

    def quote(codes, target):
        scope.assert_called_once_with(TARGET)
        transaction.atomic.return_value.__exit__.assert_called_once()
        assert codes == list(CODES) and target == TARGET
        return rows

    provider.fetch_quote_snapshots_for_session.side_effect = quote
    result = preflight._live_probe(TARGET, 10, max_quote_gaps=2)
    assert result["outcome"] == "success" and result["coverage_scope"] == "full_target_quote_gaps"
    resolver.assert_called_once()
    provider.fetch_current_valuations.assert_not_called()


def test_target_mismatch_stops_before_provider_and_universe(live_runtime) -> None:
    connection, resolver, selection, provider, scope = live_runtime
    resolver.return_value = date(2026, 10, 13)
    assert preflight._live_probe(TARGET, 10)["error_code"] == "S6_PREFLIGHT_TARGET_SESSION_MISMATCH"
    selection.assert_not_called()
    scope.assert_not_called()
    assert not provider.method_calls


def test_missing_batch_capability_never_falls_back_to_per_asset_calls(live_runtime) -> None:
    connection, resolver, selection, provider, scope = live_runtime
    del provider.fetch_quote_snapshots_for_session
    result = preflight._live_probe(TARGET, 10)
    assert result["error_code"] == "S6_PREFLIGHT_SESSION_BATCH_UNAVAILABLE"
    scope.assert_not_called()
    assert not provider.method_calls


def test_worker_suppresses_provider_exception_secrets(monkeypatch) -> None:
    from core.exceptions import DataFetchError

    monkeypatch.setattr(
        preflight, "_live_probe", Mock(side_effect=DataFetchError("secret URL and token"))
    )
    result = preflight._worker(
        SimpleNamespace(target_date=TARGET, sample_size=10, max_quote_gaps=None)
    )
    assert result["error_code"] == "S6_PREFLIGHT_PROVIDER_FAILED"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "stdout,code",
    [
        ("bad", 0),
        ("{}", 0),
        ('{"outcome":"success"}', 0),
        (json.dumps({"schema": "release.s6-prepare-diagnostic.v1", "release_approval": False}), 0),
        (json.dumps(preflight._report("success")), 2),
    ],
)
def test_invalid_worker_output_cannot_pass(monkeypatch, capsys, stdout, code) -> None:
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, "passed", ""),
            subprocess.CompletedProcess([], code, stdout, "secret"),
        ]
    )
    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight.main(["--live", "--target-date", TARGET.isoformat()]) == 2
    assert "secret" not in capsys.readouterr().out


def test_public_live_entrypoint_returns_sample_diagnostic(monkeypatch, capsys) -> None:
    report = preflight.probe_sample(_provider(), CODES, TARGET)
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, "passed", ""),
            subprocess.CompletedProcess([], 0, json.dumps(report), ""),
        ]
    )
    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight.main(["--live", "--target-date", TARGET.isoformat()]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["focused_tests"] == "passed"
    assert result["valuation"]["source_observed_at"] == [CLOSE.isoformat()]
    assert result["quote"]["source_observed_at"] == [CLOSE.isoformat()]
    assert result["release_approval"] is False
