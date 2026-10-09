"""Tests for the isolated financial scope discovery management command."""

import json
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from apps.data_center.application.financial_scope_capacity_receipt import canonical_sha256
from apps.data_center.management.commands import rehearse_financial_scope_discovery


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
    builder_called = False

    def record_write(path: Path, payload: dict[str, object]) -> None:
        writes.append(path.name)

    def fail_if_called(**kwargs: object) -> dict[str, object]:
        nonlocal builder_called
        builder_called = True
        raise AssertionError("blocked source reports cannot produce a capacity receipt")

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
        lambda **kwargs: report,
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
    assert not builder_called


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
