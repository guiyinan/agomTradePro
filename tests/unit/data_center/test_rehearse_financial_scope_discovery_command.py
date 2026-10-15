"""Tests for the isolated financial scope discovery management command."""

import json
from datetime import date
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from apps.data_center.application.financial_scope_capacity_receipt import canonical_sha256
from apps.data_center.management.commands import rehearse_financial_scope_discovery
from core.exceptions import DataFetchError


def test_blocked_discovery_preserves_report_without_capacity_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the source failure evidence and avoid deriving a success receipt."""
    report: dict[str, object] = {
        "result": {
            "outcome": "blocked",
            "error_codes": ["REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_PROVIDER_MISMATCH"],
        }
    }
    writes: list[str] = []
    observed_target_dates: list[date] = []
    builder_called = False

    def record_write(path: Path, payload: dict[str, object]) -> None:
        writes.append(path.name)

    def fail_if_called(**kwargs: object) -> dict[str, object]:
        nonlocal builder_called
        builder_called = True
        raise AssertionError("blocked source reports cannot produce a capacity receipt")

    def run_discovery(**kwargs: object) -> dict[str, object]:
        target_trade_date = kwargs.get("target_trade_date")
        assert isinstance(target_trade_date, date)
        observed_target_dates.append(target_trade_date)
        return report

    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_validate_inputs",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_validate_release_universe_report",
        lambda *args, **kwargs: ("000001.SZ",),
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "load_rehearsal_identities",
        lambda path: (),
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_run_discovery",
        run_discovery,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_write_exclusive_json",
        record_write,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "build_financial_scope_capacity_receipt",
        fail_if_called,
    )

    with pytest.raises(
        CommandError,
        match="REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_PROVIDER_MISMATCH",
    ):
        rehearse_financial_scope_discovery.Command().handle(
            candidate_sha="a" * 40,
            target_trade_date="2026-10-09",
            release_universe_sha256="b" * 64,
            release_universe_capacity_report=Path("release-universe.json"),
            provider_identities=Path("provider-identities.json"),
            provider_identities_sha256="c" * 64,
            expected_database_name="isolated",
            expected_database_host="isolated",
            artifact_root=Path("artifacts"),
            output_dir=Path("output"),
        )

    assert writes == ["financial-scope-discovery.json"]
    assert observed_target_dates == [date(2026, 10, 9)]
    assert not builder_called


def test_command_preserves_safe_failure_report_without_exception_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_validate_inputs",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_validate_release_universe_report",
        lambda *args, **kwargs: ("000001.SZ",),
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "load_rehearsal_identities",
        lambda path: (),
    )

    def fail_discovery(**kwargs: object) -> dict[str, object]:
        raise rehearse_financial_scope_discovery.FinancialScopeDiscoveryError(
            "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID"
        )

    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_run_discovery",
        fail_discovery,
    )

    with pytest.raises(
        CommandError,
        match="REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID",
    ):
        rehearse_financial_scope_discovery.Command().handle(
            candidate_sha="a" * 40,
            target_trade_date="2026-10-09",
            release_universe_sha256="b" * 64,
            release_universe_capacity_report=tmp_path / "capacity.json",
            provider_identities=tmp_path / "provider-identities.json",
            provider_identities_sha256="c" * 64,
            expected_database_name="isolated",
            expected_database_host="isolated",
            artifact_root=tmp_path / "artifacts",
            output_dir=output_dir,
        )

    report_path = output_dir / "financial-scope-discovery.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["error_codes"] == [
        "REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID"
    ]
    assert report["fact_writes"] == 0
    assert report["publication_writes"] == 0


def test_command_reports_stable_code_when_safe_failure_report_cannot_be_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_validate_inputs",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_validate_release_universe_report",
        lambda *args, **kwargs: ("000001.SZ",),
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "load_rehearsal_identities",
        lambda path: (),
    )

    def fail_discovery(**kwargs: object) -> dict[str, object]:
        raise PermissionError("private provider response and credential detail")

    def fail_evidence_write(path: Path, payload: dict[str, object]) -> None:
        raise PermissionError("private filesystem diagnostic")

    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_run_discovery",
        fail_discovery,
    )
    monkeypatch.setattr(
        rehearse_financial_scope_discovery,
        "_write_exclusive_json",
        fail_evidence_write,
    )

    with pytest.raises(CommandError) as exc_info:
        rehearse_financial_scope_discovery.Command().handle(
            candidate_sha="a" * 40,
            target_trade_date="2026-10-09",
            release_universe_sha256="b" * 64,
            release_universe_capacity_report=tmp_path / "capacity.json",
            provider_identities=tmp_path / "provider-identities.json",
            provider_identities_sha256="c" * 64,
            expected_database_name="isolated",
            expected_database_host="isolated",
            artifact_root=tmp_path / "artifacts",
            output_dir=output_dir,
        )

    assert str(exc_info.value) == "REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_EVIDENCE_WRITE_FAILED"
    assert "private provider response" not in str(exc_info.value)
    assert "credential detail" not in str(exc_info.value)
    assert "private filesystem diagnostic" not in str(exc_info.value)


def test_safe_failure_report_rejects_existing_success_report(tmp_path: Path) -> None:
    report_path = tmp_path / "financial-scope-discovery.json"
    report_path.write_text(
        json.dumps(
            {
                "schema": "release.financial-scope-discovery.v1",
                "kind": "financial_scope_discovery",
                "candidate_sha": "a" * 40,
                "outcome": "success",
                "error_codes": [],
                "fact_writes": 0,
                "publication_writes": 0,
            }
        ),
        encoding="utf-8",
    )

    assert not rehearse_financial_scope_discovery._write_safe_failure_report(
        report_path,
        candidate_sha="a" * 40,
        code="REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_FAILED",
    )


def test_safe_failure_report_accepts_only_matching_existing_blocked_report(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "financial-scope-discovery.json"
    code = "REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_FAILED"
    report_path.write_text(
        json.dumps(
            {
                "schema": "release.financial-scope-discovery.v1",
                "kind": "financial_scope_discovery",
                "candidate_sha": "a" * 40,
                "outcome": "blocked",
                "error_codes": [code],
                "fact_writes": 0,
                "publication_writes": 0,
            }
        ),
        encoding="utf-8",
    )

    assert rehearse_financial_scope_discovery._write_safe_failure_report(
        report_path,
        candidate_sha="a" * 40,
        code=code,
    )
    assert not rehearse_financial_scope_discovery._write_safe_failure_report(
        report_path,
        candidate_sha="b" * 40,
        code=code,
    )


def test_release_universe_report_rejects_one_asset_against_frozen_two_asset_digest(
    tmp_path: Path,
) -> None:
    """A one-asset capacity report cannot authorize full-scope capture for two assets."""
    codes = ["000001.SZ"]
    report = {
        "schema": "release.full-universe-capacity.v2",
        "kind": "full_universe_capacity",
        "outcome": "success",
        "candidate_sha": "a" * 40,
        "target_trade_date": "2026-10-09",
        "universe_sha256": "b" * 64,
        "universe_count": 1,
        "measured_asset_count": 1,
        "asset_codes": codes,
    }
    path = tmp_path / "capacity.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(rehearse_financial_scope_discovery.FinancialScopeDiscoveryError):
        rehearse_financial_scope_discovery._validate_release_universe_report(
            path,
            candidate_sha="a" * 40,
            target_trade_date="2026-10-09",
            universe_sha256=canonical_sha256(["000001.SZ", "000002.SZ"]),
        )


@pytest.mark.parametrize(
    "source_code",
    [
        "REHEARSAL_ARTIFACT_ROOT_DATABASE_INVALID",
        "REHEARSAL_ARTIFACT_ROOT_PATH_INVALID",
    ],
)
def test_artifact_root_failures_map_to_allowlisted_financial_scope_code(
    source_code: str,
) -> None:
    """Keep artifact isolation failures stable without exposing their diagnostics."""

    error = DataFetchError("private filesystem diagnostic", code=source_code)

    assert rehearse_financial_scope_discovery._stable_rehearsal_code(error) == (
        "REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID"
    )
