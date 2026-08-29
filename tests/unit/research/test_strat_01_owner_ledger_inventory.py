"""Contract tests for the offline STRAT-01 owner-ledger recorder."""

from __future__ import annotations

import ast
import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.research.application.strat_01_owner_ledger_inventory import (
    Strat01OwnerLedgerInventoryError,
    Strat01OwnerLedgerInventoryOutcome,
    build_strat_01_owner_ledger_report,
    parse_strat_01_owner_ledger_snapshot,
    serialize_strat_01_owner_ledger_report,
)
from scripts.record_strat_01_owner_inventory import main as record_main

ROOT = Path(__file__).resolve().parents[3]
V1_PATH = ROOT / "docs/deployment/strat-01-owner-ledger-readonly-recheck-2026-08-23.json"
V2_PATH = ROOT / "docs/deployment/strat-01-owner-ledger-readonly-recheck-2026-08-23-1326.json"


def _payload(path: Path = V1_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def test_v1_snapshot_is_readable_and_zero_seed_is_not_ready() -> None:
    snapshot = parse_strat_01_owner_ledger_snapshot(V1_PATH.read_bytes())
    report = build_strat_01_owner_ledger_report(snapshot)

    assert report.outcome is Strat01OwnerLedgerInventoryOutcome.ZERO_SEED
    assert report.production_claim is False
    assert report.production_ready is False
    assert report.runtime_enablement == "not_authorized"
    assert snapshot.database_alias == "default"


def test_v2_snapshot_preserves_query_scope_and_image_identity() -> None:
    snapshot = parse_strat_01_owner_ledger_snapshot(V2_PATH.read_bytes())

    assert snapshot.database == "agomtradepro"
    assert snapshot.query_scope is not None
    assert snapshot.candidate.image_id is not None
    assert snapshot.query_scope.schema == "public"
    assert len(snapshot.query_scope.selectors) == 4


def test_nonzero_inventory_remains_unverified() -> None:
    payload = _payload()
    inventory = payload["inventory"]
    assert isinstance(inventory, dict)
    group = inventory["research_r1_to_r8"]
    assert isinstance(group, dict)
    group["row_count_total"] = 1
    group["nonzero_table_count"] = 1

    report = build_strat_01_owner_ledger_report(
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))
    )

    assert report.outcome is Strat01OwnerLedgerInventoryOutcome.NONZERO_UNVERIFIED
    assert report.production_ready is False


@pytest.mark.parametrize(
    ("path", "mutator"),
    [
        ("unknown", lambda value: value.__setitem__("unexpected", True)),
        ("secret", lambda value: value.__setitem__("api_token", "should-not-appear")),
        (
            "future",
            lambda value: value.__setitem__(
                "observed_at",
                (datetime.now(UTC) + timedelta(days=1))
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
            ),
        ),
    ],
)
def test_snapshot_rejects_unknown_secret_and_future_fields(path: str, mutator) -> None:
    payload = copy.deepcopy(_payload())
    mutator(payload)

    with pytest.raises(Strat01OwnerLedgerInventoryError):
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))


def test_v2_requires_image_id_and_exact_query_scope() -> None:
    payload = _payload(V2_PATH)
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    candidate.pop("image_id")

    with pytest.raises(Strat01OwnerLedgerInventoryError, match="candidate keys mismatch"):
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))

    payload = _payload(V2_PATH)
    query_scope = payload["query_scope"]
    assert isinstance(query_scope, dict)
    selectors = query_scope["selectors"]
    assert isinstance(selectors, dict)
    selectors["unexpected"] = "not-canonical"
    with pytest.raises(Strat01OwnerLedgerInventoryError, match="selectors keys mismatch"):
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))


def test_candidate_identity_and_read_mode_are_fail_closed() -> None:
    payload = _payload()
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    candidate["image_tag"] = "agomtradepro-web:99999999999999"
    with pytest.raises(Strat01OwnerLedgerInventoryError, match="image_tag"):
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))

    payload = _payload()
    payload["read_mode"] = "write"
    with pytest.raises(Strat01OwnerLedgerInventoryError, match="read_mode"):
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))


def test_negative_and_duplicate_inventory_counts_are_rejected() -> None:
    payload = _payload()
    inventory = payload["inventory"]
    assert isinstance(inventory, dict)
    group = inventory["portfolio_r4_r5_r8"]
    assert isinstance(group, dict)
    group["row_count_total"] = -1
    with pytest.raises(Strat01OwnerLedgerInventoryError, match="non-negative"):
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))

    payload = _payload()
    inventory = payload["inventory"]
    assert isinstance(inventory, dict)
    group = inventory["portfolio_r4_r5_r8"]
    assert isinstance(group, dict)
    group["tables"] = [
        "duplicate",
        "duplicate",
        "duplicate",
        "duplicate",
        "duplicate",
        "duplicate",
        "duplicate",
    ]
    with pytest.raises(Strat01OwnerLedgerInventoryError, match="unique"):
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))


def test_decision_claims_cannot_be_substituted() -> None:
    payload = _payload()
    decision = payload["decision"]
    assert isinstance(decision, dict)
    decision["production_ready"] = True

    with pytest.raises(Strat01OwnerLedgerInventoryError, match="fail-closed"):
        parse_strat_01_owner_ledger_snapshot(_bytes(payload))


def test_report_serialization_is_deterministic_and_non_production() -> None:
    report = build_strat_01_owner_ledger_report(
        parse_strat_01_owner_ledger_snapshot(V2_PATH.read_bytes())
    )
    first = serialize_strat_01_owner_ledger_report(report)
    second = serialize_strat_01_owner_ledger_report(report)

    assert first == second
    decoded = json.loads(first)
    assert decoded["schema"] == "strat-01-owner-ledger-inventory-report.v1"
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["runtime_enablement"] == "not_authorized"


def test_recorder_defaults_to_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["record_strat_01_owner_inventory.py", "--input", str(V1_PATH)],
    )

    assert record_main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["written"] is False
    assert output["production_ready"] is False


def test_recorder_write_is_append_only_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    argv = [
        "record_strat_01_owner_inventory.py",
        "--input",
        str(V1_PATH),
        "--output-root",
        str(tmp_path),
        "--write",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert record_main() == 0
    first = json.loads(capsys.readouterr().out)
    assert first["written"] is True
    report_path = Path(first["path"])
    assert report_path.is_file()
    report_bytes = report_path.read_bytes()

    assert record_main() == 0
    second = json.loads(capsys.readouterr().out)
    assert second["written"] is False
    assert report_path.read_bytes() == report_bytes
    assert report_path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{first['artifact_sha256']}\n"
    )


def test_application_contract_has_no_orm_or_network_imports() -> None:
    source = (ROOT / "apps/research/application/strat_01_owner_ledger_inventory.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(
        module.startswith(("django", "requests", "psycopg", "apps.research.infrastructure"))
        for module in imported
    )
