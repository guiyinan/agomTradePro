"""Focused contracts for the tracked, read-only S6 input exporter."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import ModuleType

import pytest

from apps.data_center.infrastructure.rehearsal_identity import (
    RehearsalProviderIdentity,
    rehearsal_identities_digest,
    rehearsal_identity_dict,
)
from scripts import export_s6_rehearsal_inputs as exporter


def _identities() -> tuple[RehearsalProviderIdentity, ...]:
    """Return one complete, non-secret frozen provider identity set."""

    return (
        RehearsalProviderIdentity("quote", 1, "tushare", "1", "quotes"),
        RehearsalProviderIdentity("valuation", 2, "akshare", "1", "valuation"),
        RehearsalProviderIdentity(
            "akshare_financial_route:3",
            3,
            "akshare_financial",
            "1",
            "financial",
            "cn",
        ),
    )


def _identity_payload() -> list[dict[str, object]]:
    """Serialize the test identities as the production exporter does."""

    return [rehearsal_identity_dict(identity) for identity in _identities()]


def _unit_contract(candidate_sha: str) -> dict[str, object]:
    """Build a unit contract matching the candidate validator's required definitions."""

    from scripts import validate_release_rehearsal as validator

    identities_digest = rehearsal_identities_digest(_identities())
    return exporter._unit_contract_payload(
        candidate_sha=candidate_sha,
        provider_digest=identities_digest,
        contracts=validator.REQUIRED_REPLAY_UNIT_CONTRACTS,
    )


def _config() -> exporter.ExportConfig:
    """Return a valid synthetic contract-mode environment with no real endpoints."""

    return exporter.ExportConfig(
        candidate_sha="a" * 40,
        expected_database="production_ro",
        settings_module="core.settings.production",
        network="diagnostic-network",
        isolated_database="diagnostic_db",
        postgres_container="diagnostic-postgres",
        redis_container="diagnostic-redis",
    )


def test_help_is_side_effect_free_and_invalid_mode_has_stable_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Help exits before runtime setup; invalid modes emit only a stable code."""

    def runtime_must_not_start() -> None:
        raise AssertionError("runtime preparation must not run during CLI parsing")

    monkeypatch.setattr(exporter, "_copy_candidate_source", runtime_must_not_start)
    with pytest.raises(SystemExit) as help_exit:
        exporter.main(["--help"])
    assert help_exit.value.code == 0
    capsys.readouterr()

    assert exporter.main(["unrecognized"]) == 60
    assert capsys.readouterr().out.strip() == (
        "S6_DIAGNOSTIC_BLOCKED code=S6_DIAGNOSTIC_MODE_INVALID"
    )


def test_all_three_modes_dispatch_with_validated_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Production, universe, and contract modes share stable validated dispatch."""

    for key, value in {
        "S6_EXPECTED_CANDIDATE": "a" * 40,
        "S6_EXPECTED_DB": "production_ro",
        "S6_NETWORK": "diagnostic-network",
        "S6_DATABASE": "diagnostic_db",
        "S6_PG_CONTAINER": "diagnostic-postgres",
        "S6_REDIS_CONTAINER": "diagnostic-redis",
    }.items():
        monkeypatch.setenv(key, value)
    dispatched: list[tuple[exporter.Mode, exporter.ExportConfig]] = []

    def capture(mode: exporter.Mode, config: exporter.ExportConfig) -> None:
        dispatched.append((mode, config))

    monkeypatch.setattr(exporter, "_run", capture)
    for mode in ("production", "universe", "contract"):
        assert exporter.main([mode]) == 0

    assert [mode for mode, _config in dispatched] == ["production", "universe", "contract"]
    assert all(config.expected_database == "production_ro" for _mode, config in dispatched)
    assert "S6_CANDIDATE_EXPORT_COMPLETE mode=contract" in capsys.readouterr().out


def test_tree_digest_matches_host_snapshot_digest_and_rejects_links(tmp_path: Path) -> None:
    """The container verifies the same directory-inclusive digest as the host helper."""

    from scripts.rehearsal_checkpoint import tree_digest

    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert exporter._tree_digest(source)[0] == tree_digest(source)

    if os.name == "posix":
        link = source / "candidate-link"
        link.symlink_to(source / "nested" / "candidate.py")
        with pytest.raises(exporter.ExportBlocked, match="S6_CANDIDATE_SOURCE_SYMLINK"):
            exporter._tree_digest(source)


def test_candidate_import_provenance_accepts_copy_and_rejects_execution_image(
    tmp_path: Path,
) -> None:
    """Candidate modules resolve only below the verified runtime copy."""

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    candidate_file = runtime / "module.py"
    candidate_file.write_text("VALUE = 1\n", encoding="utf-8")
    candidate_module = ModuleType("candidate_module")
    candidate_module.__file__ = str(candidate_file)
    exporter._verify_candidate_module(candidate_module, runtime)

    execution_image_module = ModuleType("execution_image_module")
    execution_image_module.__file__ = __file__
    with pytest.raises(
        exporter.ExportBlocked,
        match="S6_CANDIDATE_IMPORT_PROVENANCE_INVALID",
    ):
        exporter._verify_candidate_module(execution_image_module, runtime)


def test_database_state_requires_exact_database_and_both_read_only_flags() -> None:
    """The guard rejects wrong database identity and either writable setting."""

    exporter._validate_database_state(("production_ro", "on", "on"), "production_ro")
    for state in (
        ("other", "on", "on"),
        ("production_ro", "off", "on"),
        ("production_ro", "on", "off"),
        ("production_ro", "on"),
    ):
        with pytest.raises(
            exporter.ExportBlocked,
            match="S6_DATABASE_READ_ONLY_GUARD_FAILED",
        ):
            exporter._validate_database_state(state, "production_ro")


def test_frozen_inputs_validate_complete_identities_and_exact_unit_contract() -> None:
    """Identity digest and unit definitions must match the selected candidate."""

    candidate_sha = "a" * 40
    identity_payload = _identity_payload()
    unit_contract = _unit_contract(candidate_sha)
    frozen = exporter._validate_frozen_inputs(identity_payload, unit_contract, candidate_sha)
    assert frozen.identities_digest == rehearsal_identities_digest(_identities())
    assert len(frozen.identities) == 3

    bad_contract = dict(unit_contract)
    bad_contract["candidate_sha"] = "b" * 40
    with pytest.raises(exporter.ExportBlocked, match="S6_UNIT_CONTRACT_INVALID"):
        exporter._validate_frozen_inputs(identity_payload, bad_contract, candidate_sha)

    incomplete = identity_payload[:2]
    with pytest.raises(exporter.ExportBlocked, match="S6_PROVIDER_IDENTITY_INVALID"):
        exporter._validate_frozen_inputs(incomplete, unit_contract, candidate_sha)


def test_universe_summary_requires_canonical_date_and_complete_partition() -> None:
    """The dynamic universe artifact binds a date, digest, and exact count partition."""

    summary: dict[str, object] = {
        "target_trade_date": "2026-10-09",
        "universe_count": 3,
        "universe_sha256": "c" * 64,
        "candidate_active_asset_count": 4,
        "excluded_not_yet_listed_count": 1,
        "unknown_listing_date_count": 2,
    }
    exporter._validate_universe_summary(summary)

    invalid = dict(summary)
    invalid["candidate_active_asset_count"] = 99
    with pytest.raises(exporter.ExportBlocked, match="S6_UNIVERSE_SUMMARY_INVALID"):
        exporter._validate_universe_summary(invalid)


def test_runner_argv_matches_real_parser_and_rejects_resume(tmp_path: Path) -> None:
    """The synthetic contract argv stays aligned with the actual runner parser."""

    from scripts import run_release_rehearsal

    candidate_sha = "a" * 40
    frozen = exporter._validate_frozen_inputs(
        _identity_payload(),
        _unit_contract(candidate_sha),
        candidate_sha,
    )
    summary: dict[str, object] = {
        "target_trade_date": "2026-10-09",
        "universe_count": 1,
        "universe_sha256": "c" * 64,
        "candidate_active_asset_count": 1,
        "excluded_not_yet_listed_count": 0,
        "unknown_listing_date_count": 1,
    }
    exporter._validate_universe_summary(summary)
    config = _config()
    runtime = tmp_path / "candidate-runtime"
    argv = exporter._build_runner_argv(
        runtime=runtime,
        inputs=frozen,
        summary=summary,
        config=config,
    )
    parsed = run_release_rehearsal._parser().parse_args(argv)
    exporter._assert_runner_argv(
        parsed,
        runtime=runtime,
        inputs=frozen,
        summary=summary,
        config=config,
    )
    assert len(parsed.transport_input) == 3

    with pytest.raises(exporter.ExportBlocked, match="S6_RUNNER_ARGV_CONTRACT_INVALID"):
        resumed = run_release_rehearsal._parser().parse_args([*argv, "--resume"])
        exporter._assert_runner_argv(
            resumed,
            runtime=runtime,
            inputs=frozen,
            summary=summary,
            config=config,
        )


def test_exclusive_output_uses_private_mode_and_refuses_overwrite(tmp_path: Path) -> None:
    """Output creation is exclusive and owner-only on POSIX hosts."""

    output = tmp_path / "snapshot.json"
    exporter._write_new(output, b'{"ok":true}\n')
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    if os.name == "posix":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(exporter.ExportBlocked, match="S6_EXPORT_OUTPUT_COLLISION"):
        exporter._write_new(output, b"replace\n")


def test_candidate_snapshot_permissions_are_checked_without_mutation(tmp_path: Path) -> None:
    """The exporter accepts the sealed POSIX mode and leaves it unchanged."""

    if os.name != "posix":
        pytest.skip("POSIX snapshot mode contract")
    source = tmp_path / "sealed"
    source.mkdir()
    child = source / "candidate.py"
    child.write_text("VALUE = 1\n", encoding="utf-8")
    child.chmod(0o440)
    source.chmod(0o550)
    try:
        exporter._validate_source_permissions(source)
        assert stat.S_IMODE(source.stat().st_mode) == 0o550
        assert stat.S_IMODE(child.stat().st_mode) == 0o440
    finally:
        source.chmod(0o700)
        child.chmod(0o600)
