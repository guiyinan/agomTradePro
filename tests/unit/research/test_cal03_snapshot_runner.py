"""Offline archive identity, holdout isolation, and descriptive scoring regressions."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pytest

from scripts import run_cal03_snapshot_walk_forward as runner


def table(archive, queries, kind, params, fields, rows):
    name = f"{len(queries)}-{kind}.json"
    raw = json.dumps({"code": 0, "data": {"fields": fields, "items": rows}}).encode()
    (archive / name).write_bytes(raw)
    queries.append(
        {
            "kind": kind,
            "params": params,
            "fields": ",".join(fields),
            "raw_path": name,
            "body_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )


@pytest.fixture
def archive(tmp_path, monkeypatch):
    inputs = tmp_path / "archive"
    inputs.mkdir()
    start = date(2010, 1, 4)
    stop = date(2026, 11, 18)
    dates = [start + timedelta(days=i) for i in range((stop - start).days + 1)]
    dates = [d.strftime("%Y%m%d") for d in dates if d.weekday() < 5]
    early = [d for d in dates if d <= "20181231"]
    queries = []
    table(
        inputs,
        queries,
        "calendar",
        {"exchange": "SSE", "start_date": dates[0], "end_date": dates[-1]},
        ["exchange", "cal_date", "is_open", "pretrade_date"],
        [["SSE", d, 1, ""] for d in dates],
    )
    for code in ("000300.SH", "000016.SH", "000905.SH"):
        table(
            inputs,
            queries,
            "full_date_coverage",
            {"ts_code": code, "start_date": dates[0], "end_date": dates[-1]},
            ["ts_code", "trade_date"],
            [[code, d] for d in dates],
        )
        table(
            inputs,
            queries,
            "early_price_quality",
            {"ts_code": code, "start_date": dates[0], "end_date": "20181231"},
            ["ts_code", "trade_date", "close"],
            [[code, d, 100 + (i % 37) / 10 + i / 900] for i, d in enumerate(early)],
        )
    # A later price file is deliberately absent. Any attempt to open it fails.
    queries.append({"kind": "later_price", "raw_path": "locked.json"})
    pin(inputs, queries, monkeypatch)
    return inputs, queries


def pin(inputs, queries, monkeypatch):
    raw = json.dumps({"queries": queries}).encode()
    (inputs / "report.json").write_bytes(raw)
    monkeypatch.setattr(runner, "ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())


def test_repeatable_report_and_full_validation_folds(archive, tmp_path):
    inputs, _ = archive
    output = tmp_path / "report"
    runner.write_snapshot(inputs, output)
    saved = (output / "results.json").read_bytes()
    runner.write_snapshot(inputs, output)
    assert (output / "results.json").read_bytes() == saved
    data = json.loads(saved)
    assert len(data["results"]) == 9
    assert not data["oos_evaluated"] and not data["pit_qualified"]
    assert data["last_available_price"] < data["date_axis_final_reserved_start"]
    for row in data["results"]:
        folds = row["folds"]
        assert len(folds) >= 5
        assert all(
            f["validation"] == 126 and f["last_label"] <= data["last_available_price"]
            for f in folds
        )
        assert row["mse"] == pytest.approx(
            [sum(f["mse"][i] for f in folds) / len(folds) for i in range(3)]
        )
        assert row["paired_loss"]["count"] == 126 * len(folds)
        assert row["paired_loss"]["mean"] == pytest.approx(row["mse"][1] - row["mse"][2], abs=1e-20)
    assert "六候" in (output / "report.md").read_text(encoding="utf8")


def test_changed_manifest_and_input_refused(archive, tmp_path):
    inputs, queries = archive
    path = inputs / queries[0]["raw_path"]
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="SHA-256"):
        runner.write_snapshot(inputs, tmp_path / "out")
    (inputs / "report.json").write_text("{}")
    with pytest.raises(ValueError, match="SHA-256"):
        runner.write_snapshot(inputs, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_later_price_range_refused_before_file_access(archive, tmp_path, monkeypatch):
    inputs, queries = archive
    q = next(q for q in queries if q["kind"] == "early_price_quality")
    q["params"]["end_date"] = "20261118"
    (inputs / q["raw_path"]).unlink()
    pin(inputs, queries, monkeypatch)
    with pytest.raises(ValueError, match="price range"):
        runner.write_snapshot(inputs, tmp_path / "out")


def test_holdout_checked_from_calendar_before_opening_prices(archive, tmp_path, monkeypatch):
    inputs, queries = archive
    calendar = queries[0]
    path = inputs / calendar["raw_path"]
    obj = json.loads(path.read_bytes())
    obj["data"]["items"] = [
        row for row in obj["data"]["items"] if row[1] <= "20181231" or row[1] == "20261118"
    ]
    raw = json.dumps(obj).encode()
    path.write_bytes(raw)
    calendar["body_sha256"] = hashlib.sha256(raw).hexdigest()
    pin(inputs, queries, monkeypatch)
    for q in queries:
        if q["kind"] == "early_price_quality":
            (inputs / q["raw_path"]).unlink()
    with pytest.raises(ValueError, match="reserved period"):
        runner.write_snapshot(inputs, tmp_path / "out")


def test_conflicting_report_is_preserved(tmp_path):
    output = tmp_path / "report"
    runner._publish(output, {"report.md": b"original", "results.json": b"{}"})
    with pytest.raises(ValueError, match="already exists"):
        runner._publish(output, {"report.md": b"changed", "results.json": b"[]"})
    assert (output / "report.md").read_bytes() == b"original"
    assert (output / "results.json").read_bytes() == b"{}"
