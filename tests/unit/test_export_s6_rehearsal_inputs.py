"""Focused contracts for the tracked, read-only S6 input exporter."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from apps.data_center.infrastructure.rehearsal_identity import (
    RehearsalProviderIdentity,
    rehearsal_identities_digest,
    rehearsal_identities_payload,
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

    return rehearsal_identities_payload(_identities())


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


def _refresh_config() -> exporter.ExportConfig:
    """Return the explicitly opted-in isolated graph-refresh export context."""

    return exporter.ExportConfig(
        candidate_sha="a" * 40,
        expected_database="agom_release_rehearsal_" + "b" * 32,
        settings_module="core.settings.production",
        network="agom-s6-network-" + "c" * 32,
        isolated_database="agom_release_rehearsal_" + "b" * 32,
        postgres_container="agom-s6-postgres-" + "b" * 32,
        redis_container="agom-s6-redis-" + "d" * 32,
        advance_isolated_market_graph=True,
        attempt_id="e" * 32,
        attempt_plan_sha256="f" * 64,
        postgres_container_id="1" * 64,
        redis_container_id="2" * 64,
        network_id="3" * 64,
        execution_image_id="sha256:" + "4" * 64,
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


def test_graph_refresh_export_context_is_opt_in_and_identity_bound() -> None:
    """Exporter defaults to no refresh and rejects malformed identity on opt-in."""

    environment = {
        "S6_EXPECTED_CANDIDATE": "a" * 40,
        "S6_EXPECTED_DB": "agom_release_rehearsal_" + "b" * 32,
        "S6_NETWORK": "agom-s6-network-" + "c" * 32,
        "S6_DATABASE": "agom_release_rehearsal_" + "b" * 32,
        "S6_PG_CONTAINER": "agom-s6-postgres-" + "b" * 32,
        "S6_REDIS_CONTAINER": "agom-s6-redis-" + "d" * 32,
    }
    default_config = exporter._load_config("universe", environment)
    assert default_config.advance_isolated_market_graph is False

    opted_in_environment = {
        **environment,
        "S6_ADVANCE_ISOLATED_MARKET_GRAPH": "1",
        "S6_ATTEMPT_ID": "e" * 32,
        "S6_ATTEMPT_PLAN_SHA256": "f" * 64,
        "S6_PG_CONTAINER_ID": "1" * 64,
        "S6_REDIS_CONTAINER_ID": "2" * 64,
        "S6_NETWORK_ID": "3" * 64,
        "S6_EXECUTION_IMAGE_ID": "sha256:" + "4" * 64,
    }
    opted_in_config = exporter._load_config("universe", opted_in_environment)
    assert opted_in_config.advance_isolated_market_graph is True
    assert opted_in_config.attempt_plan_sha256 == "f" * 64

    with pytest.raises(exporter.ExportBlocked, match="S6_GRAPH_REFRESH_IDENTITY_INVALID"):
        exporter._load_config(
            "universe",
            {**opted_in_environment, "S6_PG_CONTAINER_ID": "mutable-container"},
        )


def test_exporter_receipt_validator_reuses_exact_runtime_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exporter passes the candidate/attempt/container identity to fresh graph read."""

    from scripts import s6_isolated_market_graph_receipt as receipt_module

    config = _refresh_config()
    captured: list[tuple[Path, dict[str, str]]] = []
    expected = {"target_trade_date": "2026-10-09"}

    def validate(path: Path, *, context: dict[str, str]) -> dict[str, object]:
        captured.append((path, context))
        return expected

    monkeypatch.setattr(receipt_module, "read_and_validate_refresh_receipt", validate)
    assert exporter._validate_isolated_market_graph_refresh(config) == expected
    assert captured == [
        (
            exporter.INPUT_ROOT / "current-market-graph-refresh.json",
            {
                "candidate_sha": config.candidate_sha,
                "attempt_id": config.attempt_id,
                "attempt_plan_sha256": config.attempt_plan_sha256,
                "database": config.isolated_database,
                "postgres_container": config.postgres_container,
                "redis_container": config.redis_container,
                "postgres_container_id": config.postgres_container_id,
                "redis_container_id": config.redis_container_id,
                "network": config.network,
                "network_id": config.network_id,
                "execution_image_id": config.execution_image_id,
            },
        )
    ]


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
    """The guard rejects wrong identity, writable state, or weak isolation."""

    exporter._validate_database_state(
        ("production_ro", "on", "on", "repeatable read"), "production_ro"
    )
    for state in (
        ("other", "on", "on", "repeatable read"),
        ("production_ro", "off", "on", "repeatable read"),
        ("production_ro", "on", "off", "repeatable read"),
        ("production_ro", "on", "on", "read committed"),
        ("production_ro", "on", "on"),
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


def _current_market_rows() -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    """Return one complete atomic current-publication graph for target-date tests."""

    datasets = (
        "equity.price.bar",
        "equity.quote.snapshot",
        "equity.valuation.fact",
    )
    pointers: list[dict[str, object]] = []
    publications: list[dict[str, object]] = []
    manifests: list[dict[str, object]] = []
    publication_ids: list[str] = []
    run_id = "run-1"
    activation_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:current-market-activation:{run_id}"))
    for index, dataset_key in enumerate(datasets, start=1):
        publication_id = f"publication-{index}"
        publication_ids.append(publication_id)
        publication_hash = f"hash-{index}"
        pointers.append(
            {
                "dataset_key": dataset_key,
                "publication_id": publication_id,
                "publication_hash": publication_hash,
                "activation_id": activation_id,
            }
        )
        publications.append(
            {
                "dataset_key": dataset_key,
                "publication_key": "current",
                "publication_id": publication_id,
                "publication_hash": publication_hash,
                "computed_publication_hash": publication_hash,
                "_active_policy_evidence_validated": True,
                "policy_version": f"p2:{dataset_key}:policy",
                "selected_source": "tushare",
                "state": "published",
                "must_not_use_for_decision": False,
                "member_count": 2,
                "coverage_requested_count": 2,
                "coverage_eligible_count": 2,
                "coverage_selected_count": 2,
                "coverage_missing_count": 0,
                "scope_blocks": [],
                "member_manifest_hash": "a" * 64,
                "as_of": datetime(2026, 10, 9, 7 + (index == 3), tzinfo=UTC),
                "published_at": datetime(2026, 10, 9, 10, tzinfo=UTC),
                "members_sealed_at": datetime(2026, 10, 9, 9, 59, tzinfo=UTC),
                "run_id": run_id,
            }
        )
        manifests.append(
            {
                "publication_id": publication_id,
                "publication_hash": publication_hash,
                "run_id": run_id,
                "dataset_key": dataset_key,
                "publication_key": "current",
                "task_attempt_id": "attempt-1",
                "raw_audit_count": 1,
                "raw_audit_hash": f"{index}" * 64,
                "manifest_hash": f"{index + 3}" * 64,
            }
        )
    publications[0]["computed_member_manifest_hash"] = "a" * 64
    members: list[dict[str, object]] = []
    prices: list[dict[str, object]] = []
    for index, asset_code in enumerate(("000001.SZ", "600000.SH"), start=1):
        natural_key = f"{asset_code}:2026-10-09:1d:none:tushare"
        identity = {
            "natural_key": natural_key,
            "source": "tushare",
            "source_record_id": natural_key,
            "observed_at": datetime(2026, 10, 9, 7, tzinfo=UTC),
            "raw_payload_hash": f"raw-{index}",
            "quality_status": "accepted",
            "revision_number": 1,
            "fact_content_hash": f"{index}" * 64,
        }
        members.append(
            {
                "publication_id": "publication-1",
                "dataset_key": "equity.price.bar",
                "fact_table": "data_center_price_bar",
                "fact_pk": str(index),
                **identity,
            }
        )
        prices.append(
            {
                "fact_pk": str(index),
                "bar_date": date(2026, 10, 9),
                "freq": "1d",
                "adjustment": "none",
                **identity,
            }
        )
    task_results = [
        {
            "outcome": "success",
            "success": True,
            "phase": "completed",
            "publication_updated": True,
            "must_not_use_for_decision": False,
            "run_id": run_id,
            "publication_run_id": run_id,
            "target_trade_date": "2026-10-09",
            "requested": 2,
            "succeeded": 2,
            "failed": 0,
            "stored": 4,
            "count_unit": "valuation_asset",
            "stored_count_unit": "fact_row",
            "operation_requested": 6,
            "operation_succeeded": 6,
            "operation_failed": 0,
            "requested_asset_count": 2,
            "succeeded_asset_count": 2,
            "failed_asset_count": 0,
            "missing_asset_codes": [],
            "published_members": 6,
            "publication_ids": publication_ids,
            "datasets": [
                {
                    "dataset_key": publication["dataset_key"],
                    "publication_id": publication["publication_id"],
                    "publication_hash": publication["publication_hash"],
                    "member_count": publication["member_count"],
                    "requested_asset_count": publication["coverage_requested_count"],
                    "covered_asset_count": publication["coverage_selected_count"],
                    "missing_asset_count": publication["coverage_missing_count"],
                    "outcome": "success",
                    "scope_blocks": publication["scope_blocks"],
                    "policy_identity": publication["policy_version"],
                    "as_of": publication["as_of"].isoformat(),
                    "published_at": publication["published_at"].isoformat(),
                    "run_id": run_id,
                    "publication_run_id": run_id,
                }
                for publication in publications
            ],
            "scope_blocks": [],
            "quote_scope_blocks": [],
            "excluded_non_trading_codes": [],
            "_task_id": "task-1",
            "_task_attempt_id": "attempt-1",
            "_task_status": "success",
        }
    ]
    return pointers, publications, members, prices, manifests, task_results


def test_current_market_target_requires_atomic_closed_fresh_publications() -> None:
    """Target dates come from one sealed activation after the 15:00 close."""

    pointers, publications, members, prices, manifests, task_results = _current_market_rows()
    assert exporter._validate_current_market_publication_target(
        pointers,
        publications,
        members,
        prices,
        manifests,
        task_results,
    ) == date(2026, 10, 9)


def test_current_market_target_accepts_manifest_bound_scope_block() -> None:
    """An explained partial price scope remains a valid producer target."""

    pointers, publications, members, prices, manifests, task_results = _current_market_rows()
    price_publication = publications[0]
    price_publication["coverage_requested_count"] = 3
    price_publication["coverage_eligible_count"] = 2
    price_publication["coverage_missing_count"] = 1
    price_publication["scope_blocks"] = [
        {
            "asset_code": "000002.SZ",
            "reason_code": "price_full_day_suspension",
            "target_trade_date": "2026-10-09",
            "source": "tushare",
            "publication_run_id": "run-1",
            "policy_version": price_publication["policy_version"],
            "publication_id": price_publication["publication_id"],
            "evidence_source": "tushare.suspend_d",
        }
    ]
    price_summary = task_results[0]["datasets"][0]
    price_summary["requested_asset_count"] = 3
    price_summary["missing_asset_count"] = 1
    price_summary["outcome"] = "partial"
    price_summary["scope_blocks"] = price_publication["scope_blocks"]
    task_results[0]["scope_blocks"] = price_publication["scope_blocks"]
    for publication, summary in zip(publications[1:], task_results[0]["datasets"][1:], strict=True):
        publication["member_count"] = 3
        publication["coverage_requested_count"] = 3
        publication["coverage_eligible_count"] = 3
        publication["coverage_selected_count"] = 3
        summary["member_count"] = 3
        summary["requested_asset_count"] = 3
        summary["covered_asset_count"] = 3
    task_results[0]["requested"] = 3
    task_results[0]["succeeded"] = 3
    task_results[0]["requested_asset_count"] = 3
    task_results[0]["succeeded_asset_count"] = 3
    task_results[0]["published_members"] = 8

    assert exporter._validate_current_market_publication_target(
        pointers,
        publications,
        members,
        prices,
        manifests,
        task_results,
    ) == date(2026, 10, 9)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_pointer",
        "activation_drift",
        "hash_drift",
        "computed_hash_drift",
        "active_policy_evidence_missing",
        "before_close",
        "run_drift",
        "unsealed",
        "manifest_drift",
        "member_gap",
        "fact_gap",
        "mixed_fact_date",
        "adjusted_fact",
        "fact_hash_drift",
        "manifest_attempt_drift",
        "derived_activation_drift",
        "dataset_summary_drift",
        "missing_task_result",
        "producer_target_drift",
    ),
)
def test_current_market_target_fails_closed_for_incomplete_or_stale_graph(
    mutation: str,
) -> None:
    """No partial graph, pre-close timestamp, drift, or stale date becomes S6 input."""

    pointers, publications, members, prices, manifests, task_results = _current_market_rows()
    if mutation == "missing_pointer":
        pointers.pop()
    elif mutation == "activation_drift":
        pointers[-1]["activation_id"] = "activation-2"
    elif mutation == "hash_drift":
        publications[-1]["publication_hash"] = "different"
    elif mutation == "computed_hash_drift":
        publications[-1]["computed_publication_hash"] = "different"
    elif mutation == "active_policy_evidence_missing":
        publications[-1].pop("_active_policy_evidence_validated")
    elif mutation == "before_close":
        publications[0]["as_of"] = datetime(2026, 10, 9, 6, 55, tzinfo=UTC)
    elif mutation == "run_drift":
        publications[-1]["run_id"] = "run-2"
    elif mutation == "unsealed":
        publications[-1]["members_sealed_at"] = None
    elif mutation == "manifest_drift":
        publications[0]["computed_member_manifest_hash"] = "b" * 64
    elif mutation == "member_gap":
        members.pop()
    elif mutation == "fact_gap":
        prices.pop()
    elif mutation == "mixed_fact_date":
        prices[-1]["bar_date"] = date(2026, 10, 8)
    elif mutation == "adjusted_fact":
        prices[-1]["adjustment"] = "forward"
    elif mutation == "fact_hash_drift":
        prices[-1]["fact_content_hash"] = "f" * 64
    elif mutation == "manifest_attempt_drift":
        manifests[-1]["task_attempt_id"] = "attempt-2"
    elif mutation == "derived_activation_drift":
        for pointer in pointers:
            pointer["activation_id"] = "shared-but-not-derived"
    elif mutation == "dataset_summary_drift":
        task_results[0]["datasets"][0]["publication_hash"] = "different"
    elif mutation == "missing_task_result":
        task_results.clear()
    elif mutation == "producer_target_drift":
        task_results[0]["target_trade_date"] = "2026-10-08"

    with pytest.raises(
        exporter.ExportBlocked,
        match="S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID",
    ):
        exporter._validate_current_market_publication_target(
            pointers,
            publications,
            members,
            prices,
            manifests,
            task_results,
        )


def test_task_result_parser_accepts_json_and_literal_and_rejects_code() -> None:
    """Task Monitor's two historical encodings parse without evaluating input."""

    expected = {"publication_run_id": "run-1", "success": True}
    assert exporter._parse_task_result(json.dumps(expected)) == expected
    assert exporter._parse_task_result(str(expected)) == expected
    assert exporter._parse_task_result("__import__('os').system('echo no')") is None


def test_universe_export_uses_snapshot_publications_without_provider_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The internal prepare network never needs live calendar egress."""

    from apps.data_center import target_date_universe_composition
    from apps.data_center.application import market_calendar

    candidate_sha = "a" * 40
    monkeypatch.setattr(
        market_calendar,
        "latest_completed_cn_market_session",
        lambda _now: (_ for _ in ()).throw(AssertionError("provider calendar must not run")),
    )
    monkeypatch.setattr(
        exporter,
        "_current_market_publication_target_date",
        lambda: date(2026, 10, 9),
    )
    monkeypatch.setattr(
        target_date_universe_composition,
        "build_target_date_a_share_universe_scope",
        lambda target: SimpleNamespace(
            requested_codes=("000001.SZ",),
            candidate_codes=("000001.SZ",),
            excluded_not_yet_listed=(),
            unknown_listing_date_codes=(),
            target_date=target,
        ),
    )
    monkeypatch.setattr(
        exporter,
        "_read_json",
        lambda _path, _limit: _identity_payload(),
    )
    monkeypatch.setattr(
        exporter,
        "_read_json_object",
        lambda _path, _limit: _unit_contract(candidate_sha),
    )

    @contextmanager
    def read_only(_database: str) -> Iterator[None]:
        yield

    monkeypatch.setattr(exporter, "_read_only_database", read_only)
    published: list[dict[str, bytes]] = []
    monkeypatch.setattr(exporter, "_publish_outputs", published.append)

    exporter._export_universe(
        exporter.ExportConfig(candidate_sha, "production_ro", "core.settings.production")
    )

    assert len(published) == 1
    summary = json.loads(published[0]["universe-summary.json"])
    assert summary["target_trade_date"] == "2026-10-09"
    assert summary["universe_count"] == 1


def test_universe_export_rejects_refresh_receipt_for_another_target_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale refresh receipt cannot move the exporter to a different graph date."""

    from apps.data_center import target_date_universe_composition

    candidate_sha = "a" * 40
    monkeypatch.setattr(
        exporter,
        "_current_market_publication_target_date",
        lambda: date(2026, 10, 9),
    )
    monkeypatch.setattr(
        target_date_universe_composition,
        "build_target_date_a_share_universe_scope",
        lambda target: SimpleNamespace(
            requested_codes=("000001.SZ",),
            candidate_codes=("000001.SZ",),
            excluded_not_yet_listed=(),
            unknown_listing_date_codes=(),
            target_date=target,
        ),
    )
    monkeypatch.setattr(exporter, "_read_json", lambda _path, _limit: _identity_payload())
    monkeypatch.setattr(
        exporter,
        "_read_json_object",
        lambda _path, _limit: _unit_contract(candidate_sha),
    )
    monkeypatch.setattr(
        exporter,
        "_validate_isolated_market_graph_refresh",
        lambda _config: {"target_trade_date": "2026-10-10"},
    )

    @contextmanager
    def read_only(_database: str) -> Iterator[None]:
        yield

    monkeypatch.setattr(exporter, "_read_only_database", read_only)
    with pytest.raises(exporter.ExportBlocked, match="S6_GRAPH_REFRESH_RECEIPT_MISMATCH"):
        exporter._export_universe(_refresh_config())


def test_contract_export_rechecks_refresh_receipt_against_universe_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The final exporter mode binds the same refresh target as universe evidence."""

    monkeypatch.setattr(exporter, "_read_json", lambda _path, _limit: _identity_payload())
    monkeypatch.setattr(
        exporter,
        "_read_json_object",
        lambda _path, _limit: {"target_trade_date": "2026-10-09", "settings": True},
    )
    monkeypatch.setattr(exporter, "_validate_frozen_inputs", lambda *_args: object())
    monkeypatch.setattr(exporter, "_validate_universe_summary", lambda _summary: None)
    monkeypatch.setattr(
        exporter,
        "_validate_isolated_market_graph_refresh",
        lambda _config: {"target_trade_date": "2026-10-10"},
    )

    @contextmanager
    def read_only(_database: str) -> Iterator[None]:
        yield

    monkeypatch.setattr(exporter, "_read_only_database", read_only)
    with pytest.raises(exporter.ExportBlocked, match="S6_GRAPH_REFRESH_RECEIPT_MISMATCH"):
        exporter._export_contract(tmp_path / "runtime", _refresh_config())


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
