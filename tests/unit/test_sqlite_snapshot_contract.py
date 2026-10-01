from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.sqlite_snapshot_contract import reconcile_snapshot_counts


def _write_counts(
    path: Path,
    *,
    vendor: str,
    counts: dict[str, int],
    serialized_row_count: int | None = None,
    serialized_tables: list[str] | None = None,
) -> None:
    serialized_table_names = list(counts) if serialized_tables is None else serialized_tables
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "database_vendor": vendor,
                "table_counts": counts,
                "serialized_tables": serialized_table_names,
                "row_count": sum(counts.values()),
                "serialized_row_count": (
                    sum(counts.values()) if serialized_row_count is None else serialized_row_count
                ),
            }
        ),
        encoding="utf-8",
    )


def test_reconciliation_accepts_exact_counts_and_zero_only_schema_growth(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    fixture = tmp_path / "snapshot.jsonl"
    report = tmp_path / "report.json"
    _write_counts(source, vendor="sqlite", counts={"publication": 1, "member": 1})
    _write_counts(
        target,
        vendor="postgresql",
        counts={"publication": 1, "member": 1, "new_table": 0},
    )
    fixture.write_text('{"model":"publication"}\n{"model":"member"}\n', encoding="utf-8")

    result = reconcile_snapshot_counts(source, target, fixture, report)

    assert result["outcome"] == "success"
    assert result["fixture_row_count"] == 2
    assert json.loads(report.read_text(encoding="utf-8")) == result


def test_reconciliation_returns_noop_for_an_empty_but_valid_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    fixture = tmp_path / "snapshot.jsonl"
    report = tmp_path / "report.json"
    _write_counts(source, vendor="sqlite", counts={"publication": 0})
    _write_counts(target, vendor="postgresql", counts={"publication": 0})
    fixture.write_text("", encoding="utf-8")

    result = reconcile_snapshot_counts(source, target, fixture, report)

    assert result["outcome"] == "noop"
    assert result["source_row_count"] == 0


def test_reconciliation_detects_missing_implicit_many_to_many_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    fixture = tmp_path / "snapshot.jsonl"
    report = tmp_path / "report.json"
    _write_counts(
        source,
        vendor="sqlite",
        counts={"account": 1, "account_groups": 1},
        serialized_row_count=1,
        serialized_tables=["account"],
    )
    _write_counts(
        target,
        vendor="postgresql",
        counts={"account": 1, "account_groups": 0},
        serialized_row_count=1,
        serialized_tables=["account"],
    )
    fixture.write_text('{"model":"account"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="account_groups"):
        reconcile_snapshot_counts(source, target, fixture, report)


@pytest.mark.parametrize(
    ("source_counts", "target_counts", "fixture", "message"),
    [
        ({}, {}, "", "no managed table counts"),
        ({"publication": 1}, {"publication": 0}, '{"model":"publication"}\n', "mismatch"),
        ({"publication": 1}, {"publication": 1}, "", "fixture row count"),
    ],
)
def test_reconciliation_fails_closed_for_empty_mismatch_or_incomplete_fixture(
    tmp_path: Path,
    source_counts: dict[str, int],
    target_counts: dict[str, int],
    fixture: str,
    message: str,
) -> None:
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    fixture_path = tmp_path / "snapshot.jsonl"
    report = tmp_path / "report.json"
    _write_counts(source, vendor="sqlite", counts=source_counts)
    _write_counts(target, vendor="postgresql", counts=target_counts)
    fixture_path.write_text(fixture, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        reconcile_snapshot_counts(source, target, fixture_path, report)
