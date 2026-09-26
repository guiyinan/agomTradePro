"""Rehearsal artifacts must stay source-bound, read-only and safely blocked."""

import json
import subprocess
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.entities import QuoteSnapshot, ValuationFact
from apps.data_center.infrastructure import market_rehearsal_runner as runner
from apps.data_center.infrastructure.rehearsal_http_capture import RehearsalHttpCapture
from apps.data_center.infrastructure.rehearsal_identity import RehearsalProviderIdentity


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


def test_image_candidate_requires_release_manifest_and_runtime_image(tmp_path, monkeypatch) -> None:
    candidate = "a" * 40
    image_id = f"sha256:{'b' * 64}"
    (tmp_path / ".agom-build-identity.json").write_text(
        json.dumps({"source_commit": candidate}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="UNATTESTED"):
        runner.verify_candidate_source(tmp_path, candidate)

    manifest = tmp_path / ".agom-release-manifest.json"
    manifest.write_text(
        json.dumps({"source_commit": candidate, "image_id": image_id}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGOM_RELEASE_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("AGOM_CANDIDATE_IMAGE_ID", image_id)
    assert runner.verify_candidate_source(tmp_path, candidate) == "image_release_manifest"

    monkeypatch.setenv("AGOM_CANDIDATE_IMAGE_ID", f"sha256:{'c' * 64}")
    with pytest.raises(ValueError, match="MISMATCH"):
        runner.verify_candidate_source(tmp_path, candidate)


def test_git_candidate_rejects_untracked_source(tmp_path) -> None:
    for name in ("apps", "core", "shared"):
        (tmp_path / name).mkdir()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "rehearsal@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Rehearsal"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=tmp_path, check=True)
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "apps" / "untracked.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="DIRTY"):
        runner.verify_candidate_source(tmp_path, candidate)


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
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", f"sha256:{'b' * 64}"),
    )
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


def test_probe_blocks_partial_valuation_scope_without_proving_asset_status(
    tmp_path, monkeypatch
) -> None:
    target = date(2026, 9, 24)
    registered = ("000001.SZ", "600000.SH", "600001.SH")
    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    contexts = []
    provider_calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

    @contextmanager
    def atomic():
        yield

    class Capture:
        active = None

        def __init__(self, **_kwargs):
            self.receipts = []
            self.started = runner.time.monotonic()
            self.context = None

        def __enter__(self):
            Capture.active = self
            return self

        def __exit__(self, *_args):
            Capture.active = None

        @contextmanager
        def provider_probe(self, context):
            previous = self.context
            self.context = context
            if context is not None:
                contexts.append(context)
            try:
                yield
            finally:
                self.context = previous

        def add_receipt(self, body_hash):
            self.receipts.append(
                SimpleNamespace(
                    status_code=200,
                    body_bytes=10,
                    error_code="",
                    body_sha256=body_hash,
                    response_artifact={"retained": True},
                )
            )

        def to_dict(self):
            return {"dispatch_count": len(self.receipts), "receipts": []}

    class Provider:
        def provider_source(self):
            return "tushare"

        def fetch_current_valuations(self, asset_codes, as_of_date):
            provider_calls.append("valuation")
            assert tuple(asset_codes) == registered
            assert as_of_date == target
            body_hash = "a" * 64
            Capture.active.add_receipt(body_hash)
            now = datetime.now(UTC)
            return [
                ValuationFact(
                    asset_code=code,
                    val_date=target,
                    source="tushare",
                    observed_at=observed,
                    available_at=now,
                    fetched_at=now,
                    source_record_id=f"scope:{code}",
                    raw_payload_hash=body_hash,
                )
                for code in registered[:2]
            ]

        def fetch_quote_snapshots_for_session(self, asset_codes, target_trade_date):
            provider_calls.append("quote")
            assert tuple(asset_codes) == registered[:2]
            assert target_trade_date == target
            Capture.active.add_receipt("b" * 64)
            now = datetime.now(UTC)
            return [
                QuoteSnapshot(
                    asset_code=code,
                    snapshot_at=observed,
                    current_price=10.0,
                    source="tushare",
                    fetched_at=now,
                    volume=100.0,
                    amount=1000.0,
                )
                for code in asset_codes
            ]

    policy = PublicationPolicy(
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
        minimum_coverage_ratio=0.5,
        allow_partial=True,
        conflict_action="block",
        required_evidence=("source",),
        retention_days=30,
        policy_version="fixture",
    )
    from apps.data_center.infrastructure import publication_policy_repository

    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(vendor="postgresql", in_atomic_block=False, cursor=lambda: Cursor()),
    )
    monkeypatch.setattr(runner.transaction, "atomic", atomic)
    monkeypatch.setattr(runner, "RehearsalHttpCapture", Capture)
    monkeypatch.setattr(runner, "latest_completed_cn_market_session", lambda _now: target)
    monkeypatch.setattr(runner, "list_active_stock_codes_for_backfill", lambda: list(registered))
    monkeypatch.setattr(
        runner,
        "get_provider_registry",
        lambda: SimpleNamespace(get_by_id=lambda _provider_id: Provider()),
    )
    monkeypatch.setattr(runner, "market_rehearsal_source_digest", lambda _root: "d" * 64)
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", f"sha256:{'b' * 64}"),
    )
    monkeypatch.setattr(
        publication_policy_repository,
        "PublicationPolicyRepository",
        lambda: SimpleNamespace(get_active=lambda _dataset: policy),
    )
    identities = (
        RehearsalProviderIdentity(
            role="quote", provider_id=1, source="tushare", version="v1", endpoint_id="relay"
        ),
        RehearsalProviderIdentity(
            role="valuation",
            provider_id=2,
            source="tushare",
            version="v1",
            endpoint_id="relay",
        ),
    )
    identity_checks = []

    def verify_identities(supplied):
        identity_checks.append(supplied)
        return supplied

    monkeypatch.setattr(runner, "verify_configured_rehearsal_identities", verify_identities)
    response_root = tmp_path / "responses"
    response_root.mkdir()

    report = runner.run_market_provider_rehearsal(
        quote_provider_id=1,
        valuation_provider_id=2,
        candidate_sha="c" * 40,
        source_root=tmp_path,
        sample_size=2,
        response_evidence_root=response_root,
        provider_identities=identities,
    )

    assert report["outcome"] == "blocked"
    assert report["stage_error_code"] == "REHEARSAL_VALUATION_SCOPE_INCOMPLETE"
    assert report["asset_codes"] == list(registered)
    assert report["eligible_asset_codes"] == []
    assert report["excluded_asset_codes"] == []
    assert report["valuation_missing_target_session_codes"] == [registered[2]]
    assert report["probes"] == []
    assert contexts[0].sample_codes == registered
    assert len(contexts) == 1
    assert provider_calls == ["valuation"]
    assert identity_checks == [identities, identities]


def _command_args(destination):
    return [
        "--candidate-sha",
        "a" * 40,
        "--target-trade-date",
        "2026-09-24",
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


@pytest.mark.parametrize(
    "code",
    ["REHEARSAL_PROVIDER_IDENTITY_MISMATCH", "REHEARSAL_PROVIDER_IDENTITY_UNAVAILABLE"],
)
def test_command_preserves_allowlisted_identity_failure_code(
    tmp_path, monkeypatch, code: str
) -> None:
    from apps.data_center.management.commands import rehearse_market_providers as command

    def blocked(**_kwargs):
        raise ValueError(code)

    monkeypatch.setattr(command, "run_market_provider_rehearsal", blocked)
    destination = tmp_path / "blocked.json"
    with pytest.raises(CommandError, match="blocked"):
        call_command("rehearse_market_providers", *_command_args(destination), stdout=StringIO())

    assert json.loads(destination.read_text())["error_code"] == code
