"""Pure contract tests for the EVID-01 offline inventory recorder."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from apps.research.application.evid_01_authority_inventory import (
    EVID_01_INVENTORY_MIGRATIONS,
    EVID_01_INVENTORY_TABLES,
    Evid01AuthorityInventoryError,
    Evid01AuthorityInventoryOutcome,
    build_evid_01_authority_inventory_report,
    evid_01_authority_inventory_artifact_sha256,
    parse_evid_01_authority_inventory_snapshot,
    serialize_evid_01_authority_inventory_report,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "record_evid_01_authority_inventory.py"


def _payload(*, row_counts: dict[str, int] | None = None) -> bytes:
    """Build one canonical-shaped external snapshot fixture."""

    counts = row_counts or dict.fromkeys(EVID_01_INVENTORY_TABLES, 0)
    value: dict[str, Any] = {
        "version": "evid-01-authority-inventory-snapshot.v1",
        "environment": "production",
        "captured_at": "2026-08-19T12:10:43.123456Z",
        "candidate": {
            "stable_version": "20260819195103",
            "source_commit": "0ad5df129fbc5d0d6c3030287a0a88c83b6ae871",
            "release": "agomtradepro-web:20260819195103",
        },
        "read_only": True,
        "database": {
            "backend": "postgresql",
            "schema": "public",
            "migrations": [
                {
                    "app": "account",
                    "name": name,
                    "applied_at": f"2026-08-15T05:32:{index:02d}.123456Z",
                }
                for index, name in enumerate(EVID_01_INVENTORY_MIGRATIONS, start=7)
            ],
        },
        "row_counts": counts,
    }
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def test_zero_seed_report_is_fixed_non_production_and_stable() -> None:
    """All-zero counts derive the blocked status and cannot claim readiness."""

    snapshot = parse_evid_01_authority_inventory_snapshot(_payload())
    report = build_evid_01_authority_inventory_report(snapshot)
    assert report.outcome is Evid01AuthorityInventoryOutcome.BLOCKED_ZERO_SEED_AUTHORITY
    encoded = serialize_evid_01_authority_inventory_report(report)
    assert encoded == serialize_evid_01_authority_inventory_report(report)
    assert b'"authority_ready":false' in encoded
    assert b'"production_claim":false' in encoded
    assert b'"production_ready":false' in encoded
    assert b'"runtime_enablement":"not_authorized"' in encoded
    assert len(evid_01_authority_inventory_artifact_sha256(encoded)) == 64


def test_nonzero_counts_never_become_authority_ready() -> None:
    """Observed rows remain unverified rather than being promoted by counts."""

    counts = dict.fromkeys(EVID_01_INVENTORY_TABLES, 0)
    counts["account_user_authority_source_v3_ledger"] = 1
    report = build_evid_01_authority_inventory_report(
        parse_evid_01_authority_inventory_snapshot(_payload(row_counts=counts))
    )
    assert report.outcome is Evid01AuthorityInventoryOutcome.BLOCKED_UNVERIFIED_AUTHORITY
    assert report.authority_ready is False
    assert report.production_ready is False


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("row_counts", "missing"), None),
        (("row_counts", "extra"), 0),
        (("row_counts", EVID_01_INVENTORY_TABLES[0]), True),
        (("database", "backend"), "sqlite"),
        (("database", "migrations", 0, "name"), "0001_fake"),
        (("read_only",), False),
        (("candidate", "source_commit"), "deadbeef"),
        (("captured_at",), "2026-08-19T12:10:43+00:00"),
    ],
)
def test_snapshot_tamper_fails_closed(path: tuple[str | int, ...], replacement: object) -> None:
    """Schema, type, backend, identity, and UTC substitutions are rejected."""

    value = json.loads(_payload().decode("utf-8"))
    cursor: Any = value
    for key in path[:-1]:
        cursor = cursor[key]
    leaf = path[-1]
    if leaf == "missing":
        del cursor[EVID_01_INVENTORY_TABLES[0]]
    elif leaf == "extra":
        cursor["unexpected_table"] = replacement
    else:
        cursor[leaf] = replacement
    with pytest.raises(Evid01AuthorityInventoryError):
        parse_evid_01_authority_inventory_snapshot(
            json.dumps(value, ensure_ascii=False).encode("utf-8")
        )


def test_forbidden_secret_key_and_unknown_top_level_key_are_rejected() -> None:
    """The offline report boundary cannot carry secret or out-of-contract data."""

    secret = json.loads(_payload().decode("utf-8"))
    secret["database"]["session_token"] = "must-not-enter"
    with pytest.raises(Evid01AuthorityInventoryError):
        parse_evid_01_authority_inventory_snapshot(json.dumps(secret).encode())

    unknown = json.loads(_payload().decode("utf-8"))
    unknown["claimed_ready"] = True
    with pytest.raises(Evid01AuthorityInventoryError):
        parse_evid_01_authority_inventory_snapshot(json.dumps(unknown).encode())


def test_duplicate_or_missing_table_set_is_rejected() -> None:
    """The fixed twelve-table inventory cannot be shortened or expanded."""

    value = json.loads(_payload().decode("utf-8"))
    value["row_counts"] = {EVID_01_INVENTORY_TABLES[0]: 0}
    with pytest.raises(Evid01AuthorityInventoryError):
        parse_evid_01_authority_inventory_snapshot(json.dumps(value).encode())


def test_cli_dry_run_and_content_addressed_write_are_idempotent(tmp_path: Path) -> None:
    """The CLI defaults to dry-run and repeated writes preserve exact bytes."""

    input_path = tmp_path / "snapshot.json"
    input_path.write_bytes(_payload())
    dry = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(input_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    dry_result = json.loads(dry.stdout)
    assert dry_result["written"] is False
    assert dry_result["production_claim"] is False
    first = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--write",
            "--output-root",
            str(tmp_path / "reports"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--write",
            "--output-root",
            str(tmp_path / "reports"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    first_result = json.loads(first.stdout)
    second_result = json.loads(second.stdout)
    assert first_result["written"] is True
    assert second_result["written"] is False
    assert first_result["artifact_sha256"] == second_result["artifact_sha256"]
    assert Path(first_result["path"]).read_bytes()


def test_application_contract_has_no_orm_or_network_boundary() -> None:
    """The Application contract remains a pure external-payload validator."""

    source = (
        (ROOT / "apps" / "research" / "application" / "evid_01_authority_inventory.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "import django" not in source
    assert "from django" not in source
    assert ".objects" not in source
    assert "psycopg" not in source
    assert "paramiko" not in source
    assert "requests" not in source


def test_fixture_builder_does_not_mutate_input_counts() -> None:
    """Report construction remains immutable with respect to the source mapping."""

    counts = dict.fromkeys(EVID_01_INVENTORY_TABLES, 0)
    original = deepcopy(counts)
    parse_evid_01_authority_inventory_snapshot(_payload(row_counts=counts))
    assert counts == original
