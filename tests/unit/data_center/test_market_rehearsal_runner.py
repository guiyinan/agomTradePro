"""Rehearsal artifacts must stay source-bound, read-only and safely blocked."""

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.infrastructure import market_rehearsal_runner as runner
from apps.data_center.infrastructure.rehearsal_http_capture import RehearsalHttpCapture


def test_probe_without_real_response_receipt_cannot_pass() -> None:
    now = datetime.now(UTC)
    fact = QuoteSnapshot("600000.SH", now - timedelta(minutes=1), 12.5, "test", fetched_at=now)
    with RehearsalHttpCapture(max_dispatches=1, max_seconds=5) as capture:
        result = runner._probe(
            dataset="equity.quote.snapshot",
            fetch=lambda: [fact],
            sample=(fact.asset_code,),
            target_date=now.date(),
            capture=capture,
        )
    assert result["outcome"] == "blocked"
    assert result["transport_error_code"] == "REHEARSAL_REAL_RESPONSE_MISSING"


def test_provider_exception_never_leaks_credential_text() -> None:
    def fail():
        raise RuntimeError("https://provider.invalid?token=secret-rehearsal-test")

    with RehearsalHttpCapture(max_dispatches=1, max_seconds=5) as capture:
        result = runner._probe(
            dataset="equity.quote.snapshot",
            fetch=fail,
            sample=("600000.SH",),
            target_date=date(2026, 9, 24),
            capture=capture,
        )
    assert result["outcome"] != "success"
    assert "secret-rehearsal-test" not in json.dumps(result)


def test_source_digest_binds_actual_files_and_rejects_missing_tree(tmp_path) -> None:
    with pytest.raises(ValueError):
        runner.market_rehearsal_source_digest(tmp_path)
    for name in ("apps", "core", "shared"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "source.py").write_text("x = 1\n")
    for name in ("pyproject.toml", "requirements-prod.txt"):
        (tmp_path / name).write_text("test\n")
    digest = runner.market_rehearsal_source_digest(tmp_path)
    assert digest == runner.market_rehearsal_source_digest(tmp_path)
    (tmp_path / "apps/source.py").write_text("x = 2\n")
    assert digest != runner.market_rehearsal_source_digest(tmp_path)


def test_invalid_candidate_sha_is_rejected_before_database_or_provider(tmp_path) -> None:
    with pytest.raises(ValueError, match="commit SHA"):
        runner.run_market_provider_rehearsal(
            quote_provider_id=1, valuation_provider_id=2, candidate_sha="HEAD", source_root=tmp_path
        )


def test_calendar_resolution_runs_inside_total_transport_budget(tmp_path, monkeypatch) -> None:
    """Calendar transport is observed by the same wall-clock/request budget as probes."""

    state = {"capture_active": False}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

    class Capture:
        def __init__(self, *, max_dispatches, max_seconds):
            self.max_dispatches = max_dispatches
            self.max_seconds = max_seconds
            self.started = 1.0

        def __enter__(self):
            state["capture_active"] = True
            return self

        def __exit__(self, *_args):
            state["capture_active"] = False

        def to_dict(self):
            return {"dispatch_count": 1, "receipts": [{"stage": "calendar"}]}

    @contextmanager
    def atomic():
        yield

    def resolve_calendar(_started):
        assert state["capture_active"] is True
        return None

    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(vendor="postgresql", in_atomic_block=False, cursor=lambda: Cursor()),
    )
    monkeypatch.setattr(runner.transaction, "atomic", atomic)
    monkeypatch.setattr(runner, "RehearsalHttpCapture", Capture)
    monkeypatch.setattr(runner, "latest_completed_cn_market_session", resolve_calendar)
    monkeypatch.setattr(runner, "list_active_stock_codes_for_backfill", lambda: ["600000.SH"])
    monkeypatch.setattr(runner, "market_rehearsal_source_digest", lambda _root: "d" * 64)
    monkeypatch.setattr(runner.time, "monotonic", lambda: 1.0)

    report = runner.run_market_provider_rehearsal(
        quote_provider_id=1,
        valuation_provider_id=2,
        candidate_sha="a" * 40,
        source_root=tmp_path,
        sample_size=1,
        max_dispatches=3,
        max_seconds=5,
    )

    assert report["outcome"] == "blocked"
    assert report["stage_error_code"] == "REHEARSAL_SESSION_UNAVAILABLE"
    assert report["transport"] == {
        "dispatch_count": 1,
        "receipts": [{"stage": "calendar"}],
    }


def _command_args(destination):
    return [
        "--candidate-sha",
        "a" * 40,
        "--quote-provider-id",
        "1",
        "--valuation-provider-id",
        "2",
        "--output",
        str(destination),
    ]


def test_command_does_not_overwrite_evidence_or_call_provider(tmp_path, monkeypatch) -> None:
    from apps.data_center.management.commands import rehearse_market_providers as command

    destination = tmp_path / "evidence.json"
    destination.write_text("retained")
    monkeypatch.setattr(
        command, "run_market_provider_rehearsal", lambda **kwargs: pytest.fail("must not call")
    )
    with pytest.raises(CommandError, match="overwrite"):
        call_command("rehearse_market_providers", *_command_args(destination), stdout=StringIO())
    assert destination.read_text() == "retained"


@pytest.mark.parametrize("raises", [False, True])
def test_command_writes_safe_blocked_artifact_and_fails_exit(tmp_path, monkeypatch, raises) -> None:
    from apps.data_center.management.commands import rehearse_market_providers as command

    def blocked(**kwargs):
        assert kwargs["candidate_sha"] == "a" * 40
        if raises:
            raise ValueError("token=secret-rehearsal-test")
        return {"outcome": "blocked", "release_ready": False, "stored": 0}

    monkeypatch.setattr(command, "run_market_provider_rehearsal", blocked)
    destination = tmp_path / "blocked.json"
    with pytest.raises(CommandError, match="blocked"):
        call_command("rehearse_market_providers", *_command_args(destination), stdout=StringIO())
    report = json.loads(destination.read_text())
    assert report["outcome"] == "blocked"
    assert report["release_ready"] is False
    assert report["stored"] == 0
    assert "secret-rehearsal-test" not in destination.read_text()
