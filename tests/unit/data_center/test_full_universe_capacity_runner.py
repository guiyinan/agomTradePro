"""Full-universe capacity collection uses measured, candidate-bound runtime evidence."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.entities import QuoteSnapshot, ValuationFact
from apps.data_center.domain.target_date_universe import (
    NotYetListedAsset,
    TargetDateAssetUniverseScope,
)
from apps.data_center.infrastructure import full_universe_capacity_runner as runner
from apps.data_center.infrastructure.rehearsal_http_capture import RehearsalHttpReceipt
from apps.data_center.infrastructure.rehearsal_identity import RehearsalProviderIdentity
from core.exceptions import DataFetchError
from scripts.validate_release_rehearsal import _validate_capacity


@pytest.fixture(autouse=True)
def _use_unknown_listing_scope_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep test candidates requested when no listing-date evidence is supplied."""

    def resolve(target_date: date) -> TargetDateAssetUniverseScope:
        codes = tuple(sorted(runner.list_active_stock_codes_for_backfill()))
        return TargetDateAssetUniverseScope(
            target_date=target_date,
            candidate_codes=codes,
            requested_codes=codes,
            excluded_not_yet_listed=(),
            unknown_listing_date_codes=codes,
        )

    monkeypatch.setattr(runner, "build_target_date_a_share_universe_scope", resolve)


def _identity(role: str) -> RehearsalProviderIdentity:
    return RehearsalProviderIdentity(
        role=role,
        provider_id=7,
        source="tushare",
        version="fixture-v1",
        endpoint_id="primary",
    )


def _prepare_capacity_scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    policy_available: bool = True,
    policy_coverage: float = 0.95,
    policy_allow_partial: bool = False,
    policy_version: str = "fixture",
    margin_floor: float = 0.15,
    valuation_codes: tuple[str, ...] | None = None,
    quote_codes: tuple[str, ...] | None = None,
    suspended_codes: tuple[str, ...] = (),
    receipt_count: int = 1,
    monitor_error_code: str = "",
    source_digests: tuple[str, ...] = ("d" * 64,),
) -> tuple[Path, Path, list[str]]:
    """Wire a fake read-only runtime while keeping the collector's decisions real."""
    source_root = tmp_path / "candidate"
    for name in ("apps", "core", "shared"):
        (source_root / name).mkdir(parents=True)
        (source_root / name / "source.py").write_text("x = 1\n", encoding="utf-8")
    (source_root / "governance").mkdir()
    (source_root / "governance" / "release_rehearsal_policy.json").write_text(
        json.dumps(
            {
                "schema": "release.rehearsal-policy.v1",
                "minimum_capacity_margin_ratio": margin_floor,
            }
        ),
        encoding="utf-8",
    )
    (source_root / ".agom-build-identity.json").write_text(
        json.dumps({"schema_version": 1, "source_commit": "c" * 40}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGOM_CANDIDATE_IMAGE_ID", "sha256:" + "f" * 64)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

        def fetchone(self):
            return (321,)

    @contextmanager
    def atomic():
        yield

    provider_calls: list[str] = []
    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)

    class Provider:
        def provider_source(self) -> str:
            return "tushare"

        def fetch_current_valuations(
            self, asset_codes: list[str], as_of_date: date
        ) -> list[ValuationFact]:
            provider_calls.append("valuation")
            codes = valuation_codes if valuation_codes is not None else tuple(asset_codes)
            return [
                ValuationFact(
                    asset_code=code,
                    val_date=as_of_date,
                    source="tushare",
                    observed_at=observed,
                    fetched_at=observed,
                )
                for code in codes
            ]

        def fetch_quote_snapshots_for_session(
            self, asset_codes: list[str], target_trade_date: date
        ) -> list[QuoteSnapshot]:
            provider_calls.append("quote")
            codes = quote_codes if quote_codes is not None else tuple(asset_codes)
            return [
                QuoteSnapshot(
                    asset_code=code,
                    snapshot_at=observed,
                    current_price=10.0,
                    source="tushare",
                    fetched_at=observed,
                )
                for code in codes
            ]

        def model_market_source(self, *, tolerance: float):
            assert tolerance == pytest.approx(0.01)

            class SuspensionSource:
                def suspended_days(
                    self,
                    asset_code: str,
                    start_date: date,
                    end_date: date,
                ) -> tuple[date, ...]:
                    assert start_date == end_date == date(2026, 9, 24)
                    return (start_date,) if asset_code in suspended_codes else ()

            return SuspensionSource()

    class Monitor:
        database_peak_connections = 2
        database_connection_limit = 100
        max_lock_wait_seconds = 0.0
        peak_memory_bytes = 100_000_000
        interval_seconds = 0.05

        def __init__(self, *, backend_pid: int) -> None:
            assert backend_pid == 321
            self.error_code = monitor_error_code

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    captured_at = datetime.now(UTC).isoformat()
    receipts = [
        RehearsalHttpReceipt(
            host="relay.test",
            path_sha256="a" * 64,
            method="POST",
            started_at=captured_at,
            finished_at=captured_at,
            status_code=200,
            body_sha256=f"{index:064x}",
            body_bytes=10,
            error_code="",
        )
        for index in range(1, receipt_count + 1)
    ]

    class Capture:
        def __init__(self, **_kwargs: object) -> None:
            self.receipts = receipts

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    default_policy = PublicationPolicy(
        dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
        minimum_coverage_ratio=policy_coverage,
        allow_partial=policy_allow_partial,
        conflict_action="block",
        required_evidence=("source",),
        retention_days=30,
        policy_version=policy_version,
    )
    policy = default_policy if policy_available else None
    digest_values = iter(source_digests)
    last_digest = source_digests[-1]
    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(vendor="postgresql", in_atomic_block=False, cursor=lambda: Cursor()),
    )
    monkeypatch.setattr(runner.transaction, "atomic", atomic)
    monkeypatch.setattr(runner, "_RuntimeMonitor", Monitor)
    monkeypatch.setattr(runner, "RehearsalHttpCapture", Capture)
    monkeypatch.setattr(
        runner,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "600000.SH"],
    )
    monkeypatch.setattr(
        runner, "get_provider_registry", lambda: SimpleNamespace(get_by_id=lambda _id: Provider())
    )
    monkeypatch.setattr(runner, "_memory_limit_bytes", lambda: 1_000_000_000)
    monkeypatch.setattr(
        runner,
        "PublicationPolicyRepository",
        lambda: SimpleNamespace(get_active=lambda _dataset_key: policy),
    )
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )
    monkeypatch.setattr(
        runner,
        "market_rehearsal_source_digest",
        lambda _root: next(digest_values, last_digest),
    )
    monkeypatch.setattr(
        runner,
        "verify_configured_rehearsal_identities",
        lambda supplied: supplied,
    )
    return source_root, tmp_path / "evidence", provider_calls


def _collect_capacity(
    source_root: Path, output_dir: Path, *, request_limit: int = 100
) -> dict[str, object]:
    return runner.collect_full_universe_capacity(
        quote_provider_id=7,
        valuation_provider_id=7,
        candidate_sha="c" * 40,
        target_trade_date=date(2026, 9, 24),
        source_root=source_root,
        output_dir=output_dir,
        provider_identities=(_identity("quote"), _identity("valuation")),
        provider_request_limit_per_window=request_limit,
        provider_window_seconds=60.0,
        task_deadline_seconds=3600.0,
        lock_wait_limit_seconds=5.0,
        max_dispatches=1000,
    )


def test_peak_requests_uses_sliding_window() -> None:
    receipts = [
        RehearsalHttpReceipt(
            host="relay.test",
            path_sha256="a" * 64,
            method="POST",
            started_at=instant,
            finished_at=instant,
            status_code=200,
            body_sha256="b" * 64,
            body_bytes=10,
            error_code="",
        )
        for instant in (
            "2026-09-25T01:00:00+00:00",
            "2026-09-25T01:00:30+00:00",
            "2026-09-25T01:01:01+00:00",
        )
    ]

    assert runner._peak_requests(receipts, 60.0) == 2


@pytest.mark.parametrize(
    "code",
    ["REHEARSAL_PROVIDER_IDENTITY_MISMATCH", "REHEARSAL_PROVIDER_IDENTITY_UNAVAILABLE"],
)
def test_capacity_command_preserves_allowlisted_identity_failure_code(
    tmp_path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    from apps.data_center.management.commands import rehearse_full_universe_capacity as command

    identities = tmp_path / "identities.json"
    identities.write_text(
        json.dumps([_identity("quote").__dict__, _identity("valuation").__dict__]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        command,
        "collect_full_universe_capacity",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(code)),
    )

    with pytest.raises(CommandError, match=code):
        call_command(
            "rehearse_full_universe_capacity",
            "--candidate-sha",
            "c" * 40,
            "--target-trade-date",
            "2026-09-24",
            "--quote-provider-id",
            "7",
            "--valuation-provider-id",
            "7",
            "--provider-identities",
            str(identities),
            "--provider-request-limit",
            "100",
            "--provider-window-seconds",
            "60",
            "--task-deadline-seconds",
            "3600",
            "--lock-wait-limit-seconds",
            "5",
            "--output-dir",
            str(tmp_path / "output"),
        )


def test_capacity_command_preserves_missing_asset_diagnostics(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.data_center.management.commands import rehearse_full_universe_capacity as command

    identities = tmp_path / "identities.json"
    identities.write_text(
        json.dumps([_identity("quote").__dict__, _identity("valuation").__dict__]),
        encoding="utf-8",
    )
    details = {
        "outcome": "blocked",
        "requested": 2,
        "succeeded": 1,
        "failed": 1,
        "active_asset_codes": ["000001.SZ", "600000.SH"],
        "missing_asset_codes": ["600000.SH"],
    }
    monkeypatch.setattr(
        command,
        "collect_full_universe_capacity",
        lambda **_kwargs: (_ for _ in ()).throw(
            DataFetchError(
                "valuation scope incomplete",
                code="REHEARSAL_CAPACITY_VALUATION_SCOPE_INCOMPLETE",
                details=details,
            )
        ),
    )

    with pytest.raises(CommandError) as exc_info:
        call_command(
            "rehearse_full_universe_capacity",
            "--candidate-sha",
            "c" * 40,
            "--target-trade-date",
            "2026-09-24",
            "--quote-provider-id",
            "7",
            "--valuation-provider-id",
            "7",
            "--provider-identities",
            str(identities),
            "--provider-request-limit",
            "100",
            "--provider-window-seconds",
            "60",
            "--task-deadline-seconds",
            "3600",
            "--lock-wait-limit-seconds",
            "5",
            "--output-dir",
            str(tmp_path / "output"),
        )

    message = str(exc_info.value)
    assert "REHEARSAL_CAPACITY_VALUATION_SCOPE_INCOMPLETE" in message
    assert "active_asset_codes" in message
    assert "missing_asset_codes" in message
    assert "600000.SH" in message


def test_capacity_command_emits_strict_machine_failure_line_with_diagnostics(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from io import StringIO

    from apps.data_center.management.commands import rehearse_full_universe_capacity as command

    identities = tmp_path / "identities.json"
    identities.write_text(
        json.dumps([_identity("quote").__dict__, _identity("valuation").__dict__]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        command,
        "collect_full_universe_capacity",
        lambda **_kwargs: (_ for _ in ()).throw(
            DataFetchError(
                "quote scope incomplete",
                code="REHEARSAL_CAPACITY_QUOTE_SCOPE_INCOMPLETE",
                details={"missing_asset_codes": ["600000.SH"]},
            )
        ),
    )
    output = StringIO()

    with pytest.raises(CommandError) as exc_info:
        call_command(
            "rehearse_full_universe_capacity",
            "--candidate-sha",
            "c" * 40,
            "--target-trade-date",
            "2026-09-24",
            "--quote-provider-id",
            "7",
            "--valuation-provider-id",
            "7",
            "--provider-identities",
            str(identities),
            "--provider-request-limit",
            "100",
            "--provider-window-seconds",
            "60",
            "--task-deadline-seconds",
            "3600",
            "--lock-wait-limit-seconds",
            "5",
            "--output-dir",
            str(tmp_path / "output"),
            stdout=output,
        )

    machine_line = json.loads(output.getvalue().strip())
    assert machine_line == {
        "outcome": "blocked",
        "code": "REHEARSAL_CAPACITY_QUOTE_SCOPE_INCOMPLETE",
    }
    assert "missing_asset_codes" in str(exc_info.value)


@pytest.mark.parametrize(
    "facts",
    [
        [
            ValuationFact(asset_code="000001.SZ", val_date=date(2026, 9, 24), source="x"),
            ValuationFact(asset_code="000001.SZ", val_date=date(2026, 9, 24), source="x"),
        ],
        [ValuationFact(asset_code="600000.SH", val_date=date(2026, 9, 24), source="x")],
    ],
)
def test_fact_coverage_rejects_duplicate_and_out_of_scope_provider_rows(
    facts: list[ValuationFact],
) -> None:
    with pytest.raises(DataFetchError) as exc_info:
        runner._fact_coverage(
            facts,
            requested=("000001.SZ",),
            target_trade_date=date(2026, 9, 24),
        )
    assert exc_info.value.code == "REHEARSAL_CAPACITY_PROVIDER_SCOPE_INVALID"


def test_quote_fact_coverage_does_not_count_same_day_pre_close_snapshot() -> None:
    """Capacity evidence treats a 14:55 quote as missing from the closed session."""

    code = "000001.SZ"
    observed_at = datetime(2026, 9, 24, 6, 55, tzinfo=UTC)
    coverage = runner._fact_coverage(
        [
            QuoteSnapshot(
                asset_code=code,
                snapshot_at=observed_at,
                current_price=10.0,
                source="tushare",
                fetched_at=observed_at + timedelta(minutes=10),
            )
        ],
        requested=(code,),
        target_trade_date=date(2026, 9, 24),
    )

    assert coverage["target_session_count"] == 0
    assert coverage["missing_target_session_codes"] == [code]


def test_collector_writes_validator_compatible_measured_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    for name in ("apps", "core", "shared"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "source.py").write_text("x = 1\n", encoding="utf-8")
    for name in ("pyproject.toml", "requirements-prod.txt"):
        (tmp_path / name).write_text("fixture\n", encoding="utf-8")
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "release_rehearsal_policy.json").write_text(
        json.dumps(
            {
                "schema": "release.rehearsal-policy.v1",
                "minimum_capacity_margin_ratio": 0.15,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".agom-build-identity.json").write_text(
        json.dumps({"schema_version": 1, "source_commit": "c" * 40}) + "\n",
        encoding="utf-8",
    )

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

        def fetchone(self):
            return (321,)

    @contextmanager
    def atomic():
        yield

    class Provider:
        def provider_source(self) -> str:
            return "tushare"

        def fetch_quote_snapshots_for_session(
            self, asset_codes: list[str], target_trade_date: date
        ) -> list[QuoteSnapshot]:
            assert target_trade_date == date(2026, 9, 24)
            observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
            return [
                QuoteSnapshot(
                    asset_code=code,
                    snapshot_at=observed,
                    current_price=10.0,
                    source="tushare",
                    fetched_at=observed,
                )
                for code in asset_codes
            ]

        def fetch_current_valuations(
            self, asset_codes: list[str], as_of_date: date
        ) -> list[ValuationFact]:
            assert as_of_date == date(2026, 9, 24)
            observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
            return [
                ValuationFact(
                    asset_code=code,
                    val_date=as_of_date,
                    source="tushare",
                    observed_at=observed,
                    fetched_at=observed,
                )
                for code in asset_codes
            ]

    provider = Provider()

    class Monitor:
        database_peak_connections = 2
        database_connection_limit = 100
        max_lock_wait_seconds = 0.0
        peak_memory_bytes = 100_000_000
        error_code = ""
        interval_seconds = 0.05

        def __init__(self, *, backend_pid: int) -> None:
            assert backend_pid == 321

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    receipt = RehearsalHttpReceipt(
        host="relay.test",
        path_sha256="a" * 64,
        method="POST",
        started_at="2026-09-25T01:00:00+00:00",
        finished_at="2026-09-25T01:00:01+00:00",
        status_code=200,
        body_sha256="b" * 64,
        body_bytes=10,
        error_code="",
    )

    class Capture:
        def __init__(self, **_kwargs: object) -> None:
            self.receipts = [receipt]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(vendor="postgresql", in_atomic_block=False, cursor=lambda: Cursor()),
    )
    monkeypatch.setattr(runner.transaction, "atomic", atomic)
    monkeypatch.setattr(runner, "_RuntimeMonitor", Monitor)
    monkeypatch.setattr(runner, "RehearsalHttpCapture", Capture)
    monkeypatch.setattr(
        runner, "list_active_stock_codes_for_backfill", lambda: ["600000.SH", "000001.SZ"]
    )
    monkeypatch.setattr(
        runner,
        "get_provider_registry",
        lambda: SimpleNamespace(get_by_id=lambda _provider_id: provider),
    )
    monkeypatch.setattr(runner, "_memory_limit_bytes", lambda: 1_000_000_000)
    monkeypatch.setattr(
        runner,
        "PublicationPolicyRepository",
        lambda: SimpleNamespace(
            get_active=lambda _dataset_key: PublicationPolicy(
                dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
                minimum_coverage_ratio=0.95,
                allow_partial=False,
                conflict_action="block",
                required_evidence=("source",),
                retention_days=30,
                policy_version="fixture",
            )
        ),
    )
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: ("image_release_manifest", "sha256:" + "f" * 64),
    )
    monkeypatch.setattr(
        runner,
        "verify_configured_rehearsal_identities",
        lambda supplied: supplied,
    )

    destination = tmp_path / "evidence"
    report = runner.collect_full_universe_capacity(
        quote_provider_id=7,
        valuation_provider_id=7,
        candidate_sha="c" * 40,
        target_trade_date=date(2026, 9, 24),
        source_root=tmp_path,
        output_dir=destination,
        provider_identities=(_identity("quote"), _identity("valuation")),
        provider_request_limit_per_window=100,
        provider_window_seconds=60.0,
        task_deadline_seconds=3600.0,
        lock_wait_limit_seconds=5.0,
    )

    receipt_payload = json.loads(
        (destination / "full-universe-capacity-receipt.json").read_text(encoding="utf-8")
    )
    assert report["outcome"] == "success"
    assert report["asset_codes"] == ["000001.SZ", "600000.SH"]
    assert receipt_payload["measurement_source"] == "candidate_runtime_instrumentation"
    assert receipt_payload["provider_total_requests"] == 1
    assert receipt_payload["database_peak_connections"] == 2
    validated_capacity = _validate_capacity(
        report,
        destination,
        expected_candidate="c" * 40,
        expected_image_id="sha256:" + "f" * 64,
        expected_date="2026-09-24",
        expected_universe=str(report["universe_sha256"]),
        expected_provider_digest=str(report["provider_identities_sha256"]),
    )
    assert validated_capacity.registered_asset_codes == ("000001.SZ", "600000.SH")
    assert validated_capacity.eligible_asset_codes == ("000001.SZ", "600000.SH")
    assert validated_capacity.excluded_asset_codes == ()
    assert validated_capacity.policy.snapshot == report["valuation_policy_snapshot"]


def test_capacity_receipt_preserves_current_and_target_date_scope_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(monkeypatch, tmp_path)
    candidate_codes = (
        "000001.SZ",
        "000002.SZ",
        "301716.SZ",
        "600000.SH",
        "920202.BJ",
    )
    target_codes = ("000001.SZ", "000002.SZ", "600000.SH")
    monkeypatch.setattr(
        runner,
        "list_active_stock_codes_for_backfill",
        lambda: list(candidate_codes),
    )
    monkeypatch.setattr(
        runner,
        "build_target_date_a_share_universe_scope",
        lambda target: TargetDateAssetUniverseScope(
            target_date=target,
            candidate_codes=candidate_codes,
            requested_codes=target_codes,
            excluded_not_yet_listed=(
                NotYetListedAsset(
                    asset_code="301716.SZ",
                    list_date=date(2026, 9, 25),
                    evidence_source="tushare.new_share[provider_id=7].issue_date",
                ),
                NotYetListedAsset(
                    asset_code="920202.BJ",
                    list_date=date(2026, 9, 25),
                    evidence_source="tushare.stock_basic[provider_id=7].list_date",
                ),
            ),
            unknown_listing_date_codes=("000002.SZ",),
        ),
    )

    report = _collect_capacity(source_root, output_dir)
    receipt = json.loads(
        (output_dir / "full-universe-capacity-receipt.json").read_text(encoding="utf-8")
    )

    for artifact in (report, receipt):
        assert artifact["candidate_active_asset_count"] == len(candidate_codes)
        assert artifact["candidate_active_asset_codes_sha256"] == runner.rehearsal_digest(
            candidate_codes
        )
        assert artifact["target_requested_asset_count"] == len(target_codes)
        assert artifact["target_requested_asset_codes_sha256"] == runner.rehearsal_digest(
            target_codes
        )
        assert artifact["asset_codes"] == list(target_codes)
        assert artifact["excluded_not_yet_listed_count"] == 2
        assert [item["asset_code"] for item in artifact["excluded_not_yet_listed_evidence"]] == [
            "301716.SZ",
            "920202.BJ",
        ]
        assert artifact["unknown_listing_date_codes_sample"] == ["000002.SZ"]
        assert artifact["valuation_requested_count"] == 3
    assert provider_calls == ["valuation", "quote"]


def test_collector_rejects_existing_destination_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    destination = tmp_path / "evidence"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("existing evidence\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(vendor="postgresql", in_atomic_block=False),
    )
    monkeypatch.setattr(
        runner,
        "_capacity_policy",
        lambda _root: pytest.fail("an existing destination must stop before policy loading"),
    )
    monkeypatch.setattr(
        runner,
        "list_active_stock_codes_for_backfill",
        lambda: pytest.fail("an existing destination must stop before database reads"),
    )

    with pytest.raises(ValueError, match="REHEARSAL_CAPACITY_OUTPUT_EXISTS"):
        runner.collect_full_universe_capacity(
            quote_provider_id=7,
            valuation_provider_id=7,
            candidate_sha="c" * 40,
            target_trade_date=date(2026, 9, 24),
            source_root=tmp_path,
            output_dir=destination,
            provider_identities=(_identity("quote"), _identity("valuation")),
            provider_request_limit_per_window=100,
            provider_window_seconds=60.0,
            task_deadline_seconds=3600.0,
            lock_wait_limit_seconds=5.0,
        )
    assert sentinel.read_text(encoding="utf-8") == "existing evidence\n"


def test_collector_fails_closed_when_active_valuation_policy_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        policy_available=False,
    )

    with pytest.raises(DataFetchError) as exc_info:
        _collect_capacity(source_root, output_dir)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_POLICY_UNAVAILABLE"
    assert provider_calls == []
    assert not output_dir.exists()


def test_collector_fails_closed_on_missing_valuation_without_status_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        valuation_codes=("000001.SZ",),
        policy_coverage=0.5,
    )

    with pytest.raises(DataFetchError) as exc_info:
        _collect_capacity(source_root, output_dir)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_VALUATION_SCOPE_INCOMPLETE"
    assert exc_info.value.details["outcome"] == "blocked"
    assert exc_info.value.details["requested"] == 2
    assert exc_info.value.details["succeeded"] == 1
    assert exc_info.value.details["failed"] == 1
    assert exc_info.value.details["active_asset_codes"] == ["000001.SZ", "600000.SH"]
    assert exc_info.value.details["missing_asset_codes"] == ["600000.SH"]
    assert provider_calls == ["valuation"]
    assert not output_dir.exists()


def test_collector_reports_policy_qualified_partial_valuation_without_blocking_universe(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        valuation_codes=("000001.SZ",),
        policy_coverage=0.5,
        policy_allow_partial=True,
    )

    report = _collect_capacity(source_root, output_dir)
    receipt = json.loads(
        (output_dir / "full-universe-capacity-receipt.json").read_text(encoding="utf-8")
    )

    expected_assets = ["000001.SZ", "600000.SH"]
    expected_missing = ["600000.SH"]
    expected_reasons = [
        {
            "asset_code": "600000.SH",
            "reason_code": "valuation_source_data_unavailable",
        }
    ]
    for artifact in (report, receipt):
        assert artifact["outcome"] == "success"
        assert artifact["asset_codes"] == expected_assets
        assert artifact["eligible_asset_codes"] == expected_assets
        assert artifact["excluded_asset_codes"] == []
        assert artifact["valuation_missing_target_session_codes"] == expected_missing
        assert artifact["valuation_missing_target_session_reasons"] == expected_reasons
        assert artifact["valuation_outcome"] == "partial"
        assert artifact["valuation_requested_count"] == 2
        assert artifact["valuation_returned_count"] == 1
        assert artifact["valuation_coverage_ratio"] == 0.5
    assert receipt["quote_coverage"]["missing_target_session_count"] == 0
    assert provider_calls == ["valuation", "quote"]


def test_collector_rejects_partial_valuation_under_legacy_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A legacy policy cannot authorize the versioned partial-publication path."""

    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        valuation_codes=("000001.SZ",),
        policy_coverage=0.5,
        policy_allow_partial=True,
        policy_version="legacy",
    )

    with pytest.raises(DataFetchError) as exc_info:
        _collect_capacity(source_root, output_dir)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_VALUATION_SCOPE_INCOMPLETE"
    assert provider_calls == ["valuation"]
    assert not output_dir.exists()


def test_collector_fails_closed_when_eligible_quote_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        quote_codes=("000001.SZ",),
    )

    with pytest.raises(DataFetchError) as exc_info:
        _collect_capacity(source_root, output_dir)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_QUOTE_SCOPE_INCOMPLETE"
    details = exc_info.value.details
    assert {
        key: value for key, value in details.items() if key != "target_date_universe_scope"
    } == {
        "outcome": "blocked",
        "target_trade_date": "2026-09-24",
        "requested": 2,
        "succeeded": 1,
        "failed": 1,
        "stored": 1,
        "missing": ["600000.SH"],
        "missing_asset_codes": ["600000.SH"],
        "active_asset_codes": ["000001.SZ", "600000.SH"],
        "active_universe_sha256": exc_info.value.details["active_universe_sha256"],
        "eligible_asset_codes": ["000001.SZ", "600000.SH"],
        "excluded_asset_codes": [],
        "excluded_asset_reasons": [],
        "quote_missing_target_session_reasons": [
            {
                "asset_code": "600000.SH",
                "reason_code": "quote_target_session_unverified",
            }
        ],
    }
    assert details["target_date_universe_scope"]["candidate_active_asset_count"] == 2
    assert details["target_date_universe_scope"]["target_requested_asset_count"] == 2
    assert details["target_date_universe_scope"]["excluded_not_yet_listed_count"] == 0
    assert provider_calls == ["valuation", "quote"]
    assert not output_dir.exists()


def test_collector_accepts_only_quote_gaps_with_explicit_full_day_suspension_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        quote_codes=("000001.SZ",),
        suspended_codes=("600000.SH",),
    )

    report = _collect_capacity(source_root, output_dir)
    receipt = json.loads(
        (output_dir / "full-universe-capacity-receipt.json").read_text(encoding="utf-8")
    )
    expected_reasons = [{"asset_code": "600000.SH", "reason_code": "quote_full_day_suspension"}]

    for artifact in (report, receipt):
        assert artifact["asset_codes"] == ["000001.SZ", "600000.SH"]
        assert artifact["eligible_asset_codes"] == ["000001.SZ"]
        assert artifact["eligible_asset_count"] == 1
        assert artifact["excluded_asset_codes"] == ["600000.SH"]
        assert artifact["excluded_asset_count"] == 1
        assert artifact["excluded_asset_reasons"] == expected_reasons
        assert artifact["quote_missing_target_session_codes"] == []
        assert artifact["quote_missing_target_session_reasons"] == []
        assert artifact["quote_requested_count"] == 1
        assert artifact["quote_returned_count"] == 1
    assert receipt["quote_coverage"] == {
        "requested_count": 1,
        "returned_count": 1,
        "target_session_count": 1,
        "missing_target_session_count": 0,
        "missing_target_session_codes": [],
        "extra_count": 0,
        "duplicate_count": 0,
    }
    assert provider_calls == ["valuation", "quote"]


@pytest.mark.parametrize(
    ("dataset", "returned_codes"),
    [
        ("valuation", ("000001.SZ", "000001.SZ")),
        ("valuation", ("000001.SZ", "600000.SH", "999999.SZ")),
        ("quote", ("000001.SZ", "000001.SZ")),
        ("quote", ("000001.SZ", "600000.SH", "999999.SZ")),
    ],
)
def test_collector_rejects_duplicate_or_extra_provider_rows_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    dataset: str,
    returned_codes: tuple[str, ...],
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        valuation_codes=returned_codes if dataset == "valuation" else None,
        quote_codes=returned_codes if dataset == "quote" else None,
    )

    with pytest.raises(DataFetchError) as exc_info:
        _collect_capacity(source_root, output_dir)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_PROVIDER_SCOPE_INVALID"
    assert not output_dir.exists()
    assert provider_calls == (["valuation"] if dataset == "valuation" else ["valuation", "quote"])


@pytest.mark.parametrize(
    ("receipt_count", "expected_outcome"),
    [(85, "success"), (86, "REHEARSAL_CAPACITY_LIMIT_EXCEEDED")],
)
def test_collector_enforces_governed_capacity_margin_at_boundary_and_above(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    receipt_count: int,
    expected_outcome: str,
) -> None:
    source_root, output_dir, _provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        receipt_count=receipt_count,
    )

    if expected_outcome == "success":
        report = _collect_capacity(source_root, output_dir)
        assert report["outcome"] == "success"
        assert report["capacity_margin_ratio"] == pytest.approx(0.15)
        assert output_dir.is_dir()
    else:
        with pytest.raises(DataFetchError) as exc_info:
            _collect_capacity(source_root, output_dir)
        assert exc_info.value.code == expected_outcome
        assert not output_dir.exists()


def test_collector_fails_closed_when_runtime_monitor_reports_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        monitor_error_code="REHEARSAL_CAPACITY_MONITOR_FAILED",
    )

    with pytest.raises(DataFetchError) as exc_info:
        _collect_capacity(source_root, output_dir)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_MONITOR_FAILED"
    assert provider_calls == ["valuation", "quote"]
    assert not output_dir.exists()


def test_collector_fails_closed_when_candidate_source_changes_during_measurement(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    source_root, output_dir, provider_calls = _prepare_capacity_scenario(
        monkeypatch,
        tmp_path,
        source_digests=("a" * 64, "b" * 64),
    )

    with pytest.raises(DataFetchError) as exc_info:
        _collect_capacity(source_root, output_dir)

    assert exc_info.value.code == "REHEARSAL_CAPACITY_SOURCE_CHANGED"
    assert provider_calls == ["valuation", "quote"]
    assert not output_dir.exists()
