"""Offline archive identity, holdout isolation, and descriptive scoring regressions."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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


def test_future_price_change_preserves_every_earlier_prediction(archive, tmp_path, monkeypatch):
    inputs, queries = archive
    original = runner.ridge_predict
    predictions = []

    def observe(*args, **kwargs):
        values = original(*args, **kwargs)
        predictions.append(values)
        return values

    monkeypatch.setattr(runner, "ridge_predict", observe)
    runner.write_snapshot(inputs, tmp_path / "reference")
    reports = json.loads((tmp_path / "reference/results.json").read_bytes())["results"]
    saved = predictions.copy()
    predictions.clear()
    query = next(q for q in queries if q["kind"] == "early_price_quality")
    path = inputs / query["raw_path"]
    data = json.loads(path.read_bytes())
    rows = data["data"]["items"]
    dates = [row[1] for row in rows]
    # Place the change inside a held-out fold. Its earlier validation labels
    # can now differ, but its earlier predictions still must be identical.
    change = dates[dates.index(reports[0]["folds"][2]["start"]) + 47]
    for row in rows:
        if row[1] >= change:
            row[2] *= 1.01 if int(row[1][-2:]) % 2 else 1.04
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    query["body_sha256"] = hashlib.sha256(raw).hexdigest()
    pin(inputs, queries, monkeypatch)
    runner.write_snapshot(inputs, tmp_path / "perturbed")
    i = 0
    changed = False
    for result in reports:
        for fold in result["folds"]:
            origins = [d for d in dates if fold["start"] <= d <= fold["end"]]
            for _ in range(3):
                for d, a, b in zip(origins, saved[i], predictions[i], strict=True):
                    if d < change or result["target"] != query["params"]["ts_code"]:
                        assert a == b
                    else:
                        changed |= a != b
                i += 1
    assert i == len(saved) == len(predictions) and changed


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


@pytest.fixture
def later_bundle(archive, tmp_path, monkeypatch):
    inputs, queries = archive
    later = tmp_path / "later"
    later.mkdir()
    design = runner.load_validation_design(
        Path(__file__).resolve().parents[3] / "tests/fixtures/research/cal_event_study_v1.json"
    )
    zone = ZoneInfo(design.clock.timezone_name)
    sessions = runner._sessions(inputs, queries, {}, zone)
    days = [s.session_on for s in sessions]
    reserve = len(days) - design.policy.final_oos_sessions - max(design.clock.horizons)
    plan = runner.plan_walk_forward(
        sessions=sessions[20:],
        calendar_version="fixture",
        complete_price_dates=frozenset(days),
        known_at=datetime.combine(days[-1], design.clock.local_cutoff, zone),
        clock=design.clock,
        policy=design.policy,
        prior_final_oos_uses=0,
    )
    frozen = []
    for fold in plan.folds:
        start = 20 + fold.validation_origins.start
        end = 20 + fold.validation_origins.stop - 1
        if days[start].year >= 2019 and end + 10 < reserve:
            frozen.append([str(days[start]), str(days[end]), str(days[end + 5])])
    upper = days[reserve - 1].strftime("%Y%m%d")
    record = {
        "spec_sha256": runner.SPEC_SHA256,
        "archive_sha256": runner.ARCHIVE_SHA256,
        "reserved_start": days[reserve].strftime("%Y%m%d"),
        "end_date": upper,
        "targets": [s + ".SH" for s in design.targets],
        "folds": frozen,
    }
    raw = json.dumps(record).encode()
    (later / "design.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(runner, "LATER_DESIGN_SHA256", digest)
    q = []
    # Omit a close right at a fold boundary: earlier labels and subsequent features are affected.
    missing = date.fromisoformat(frozen[3][0])
    for code in record["targets"]:
        table(
            later,
            q,
            "later_price",
            {"ts_code": code, "start_date": "20190101", "end_date": upper},
            ["ts_code", "trade_date", "close"],
            [
                [code, str(d).replace("-", ""), 110 + (i % 7) / 5]
                for i, d in enumerate(days[:reserve])
                if d.year >= 2019 and d != missing
            ],
        )
    manifest = {"design_sha256": digest, "queries": q}
    raw = json.dumps(manifest).encode()
    (later / "report.json").write_bytes(raw)
    monkeypatch.setattr(runner, "LATER_ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())
    return inputs, later, days, missing, manifest


def test_later_period_preserves_calendar_and_excludes_both_contaminated_folds(
    later_bundle, tmp_path
):
    inputs, later, days, missing, _ = later_bundle
    output = tmp_path / "result"
    runner.write_snapshot(inputs, output, later_archive=later)
    report = json.loads((output / "results.json").read_bytes())
    assert not report["oos_evaluated"] and not report["pit_qualified"]
    for r in report["results"]:
        assert report["missing_closes"][r["target"]] == [str(missing)]
        support = report["later_fold_support"][r["target"]][str(r["horizon"])]
        excluded = [f for f in support if f["reason"]]
        assert len(excluded) == 2 and len(r["folds"]) + 2 == len(support)
        assert any(f["training_valid"] < f["training_expected"] for f in support if not f["reason"])
        for f in support:
            start, end = days.index(date.fromisoformat(f["start"])), days.index(
                date.fromisoformat(f["end"])
            )
            assert f["validation_valid"] == sum(
                missing not in days[i - 20 : i + 6] for i in range(start, end + 1)
            )
        assert r["folds"][0]["start"] >= "20190101"
        assert all(f["last_label"] < report["date_axis_final_reserved_start"] for f in r["folds"])
    assert len(report["later_comparisons"]) == 9


def test_later_range_refused_before_opening_out_of_bounds_file(later_bundle, tmp_path, monkeypatch):
    inputs, later, _, _, manifest = later_bundle
    query = manifest["queries"][0]
    query["params"]["end_date"] = "20261118"
    (later / query["raw_path"]).unlink()
    raw = json.dumps(manifest).encode()
    (later / "report.json").write_bytes(raw)
    monkeypatch.setattr(runner, "LATER_ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="price range"):
        runner.write_snapshot(inputs, tmp_path / "unexpected", later_archive=later)


@pytest.mark.parametrize("fault", ["", "query_end", "missing_session", "disagreement", "tamper"])
def test_csi_source_switch_validates_range_sessions_and_paired_closes(tmp_path, monkeypatch, fault):
    folder = tmp_path / "csi-history"
    folder.mkdir()
    days = (date(2019, 1, 2), date(2019, 1, 3))
    name = "000300-2019.json"
    rows = [
        {"indexCode": "000300", "tradeDate": d, "close": p}
        for d, p in [
            ("20190101", 99),
            ("20190102", 200 if fault == "disagreement" else 100.01),
            ("20190103", 101),
        ]
    ]
    if fault == "missing_session":
        rows.pop()
    body = json.dumps({"code": "200", "data": rows}).encode()
    end = "20260101" if fault == "query_end" else "20190103"
    entry = {
        "raw": name,
        "url": f"{runner._CSI_URL}?indexCode=000300&startDate=20190101&endDate={end}",
        "rows": len(rows),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    manifest = json.dumps(
        {"source": runner._CSI_URL, "end": "20190103", "retrievals": [entry]}
    ).encode()
    (tmp_path / "coverage.json").write_bytes(manifest)
    monkeypatch.setattr(runner, "CSI_COVERAGE_SHA256", hashlib.sha256(manifest).hexdigest())
    if fault != "query_end":
        (folder / name).write_bytes(body + b" " if fault == "tamper" else body)
    relay = (100.0, float("nan"))
    if fault:
        msg = {
            "query_end": "query range",
            "missing_session": "session coverage",
            "disagreement": "more than 1%",
            "tamper": "SHA-256",
        }[fault]
        with pytest.raises(ValueError, match=msg):
            runner._csi_closes(tmp_path, "000300", days, relay, {})
    else:
        values, check = runner._csi_closes(tmp_path, "000300", days, relay, {})
        assert values == (100.01, 101)
        assert check.common_sessions == 1 and check.recovered == (days[1],)
        assert check.ignored_non_sessions == (date(2019, 1, 1),)


def test_official_source_restores_folds_and_preserves_matched_control(
    later_bundle, tmp_path, monkeypatch
):
    inputs, later, days, missing, manifest = later_bundle
    folder = tmp_path / "csi-history"
    folder.mkdir()
    entries = []
    upper = manifest["queries"][0]["params"]["end_date"]
    axis = [d for d in days if d.year >= 2019 and d <= date.fromisoformat(upper)]
    for query in manifest["queries"]:
        code = query["params"]["ts_code"].split(".")[0]
        relay = {
            date.fromisoformat(d): p
            for _, d, p in json.loads((later / query["raw_path"]).read_bytes())["data"]["items"]
        }
        for year in sorted({d.year for d in axis}):
            end = min(f"{year}1231", upper)
            name = f"{code}-{year}.json"
            rows = [
                {"indexCode": code, "tradeDate": d.strftime("%Y%m%d"), "close": relay.get(d, 110.0)}
                for d in axis
                if d.year == year
            ]
            raw = json.dumps({"code": "200", "data": rows}).encode()
            (folder / name).write_bytes(raw)
            entries.append(
                {
                    "raw": name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "rows": len(rows),
                    "url": f"{runner._CSI_URL}?indexCode={code}&startDate={year}0101&endDate={end}",
                }
            )
    raw = json.dumps({"source": runner._CSI_URL, "end": upper, "retrievals": entries}).encode()
    (tmp_path / "coverage.json").write_bytes(raw)
    monkeypatch.setattr(runner, "CSI_COVERAGE_SHA256", hashlib.sha256(raw).hexdigest())
    output = tmp_path / "official"
    runner.write_snapshot(inputs, output, later_archive=later, csi_archive=tmp_path)
    report = json.loads((output / "results.json").read_bytes())
    assert not report["oos_evaluated"]
    from apps.research.infrastructure.sse_holiday_overlap import (
        Closure,
        HolidayMarker,
        HolidayPanel,
    )

    # Put the marker in a fold uniquely restored by the official source.
    selected_day = missing
    closure = Closure(
        "测试休市",
        selected_day + timedelta(days=2),
        selected_day + timedelta(days=5),
        "test",
        date(2010, 1, 1),
    )

    def panel_for(archive, dates, start, end):
        assert end == date.fromisoformat(upper)
        return HolidayPanel(start, end, (HolidayMarker(selected_day, closure),), {})

    monkeypatch.setattr(runner, "load_holiday_panel", panel_for)
    with_events = tmp_path / "official-events"
    runner.write_snapshot(
        inputs, with_events, later_archive=later, csi_archive=tmp_path, event_archive=inputs
    )
    overlap = json.loads((with_events / "results.json").read_bytes())
    assert overlap["results"] == report["results"]
    rows = overlap["overlap_sensitivities"]["results"]
    assert len(rows) == 27
    for result in report["results"]:
        full, single, exclusive = [
            r for r in rows if (r["target"], r["horizon"]) == (result["target"], result["horizon"])
        ]
        assert full["inference"] == result["paired_loss"]
        assert len(single["fold_counts"]) == len(result["folds"])
        assert sum(single["fold_counts"]) == single["observations"] == full["observations"] - 1
        assert exclusive["observations"] <= single["observations"]
    for control, full in zip(report["source_controls"], report["results"], strict=True):
        assert report["source_checks"][full["target"]]["recovered"] == [str(missing)]
        assert control["official_matched"] == control["relay_matched"]
        restored = control["official_restored_training"]["folds"]
        assert len(full["folds"]) == len(restored) + 2
        assert restored == [
            f for f in full["folds"] if f["start"] in {row["start"] for row in restored}
        ]


def test_conflicting_report_is_preserved(tmp_path):
    output = tmp_path / "report"
    runner._publish(output, {"report.md": b"original", "results.json": b"{}"})
    with pytest.raises(ValueError, match="already exists"):
        runner._publish(output, {"report.md": b"changed", "results.json": b"[]"})
    assert (output / "report.md").read_bytes() == b"original"
    assert (output / "results.json").read_bytes() == b"{}"


def test_event_report_rescores_same_predictions_and_preserves_original(
    archive, tmp_path, monkeypatch
):
    from apps.research.infrastructure.sse_holiday_overlap import (
        Closure,
        HolidayMarker,
        HolidayPanel,
    )

    inputs, _ = archive
    before = tmp_path / "before"
    runner.write_snapshot(inputs, before)
    baseline = json.loads((before / "results.json").read_bytes())
    marker = date.fromisoformat(baseline["results"][0]["folds"][0]["start"])
    closure = Closure(
        "测试休市", marker + timedelta(days=2), marker + timedelta(days=5), "test", date(2009, 1, 1)
    )
    panel = HolidayPanel(
        date(2010, 1, 4), date(2018, 12, 31), (HolidayMarker(marker, closure),), {}
    )
    monkeypatch.setattr(runner, "load_holiday_panel", lambda *_: panel)
    after = tmp_path / "after"
    runner.write_snapshot(inputs, after, event_archive=inputs)
    report = json.loads((after / "results.json").read_bytes())
    assert report["results"] == baseline["results"] and not report["oos_evaluated"]
    rows = report["overlap_sensitivities"]["results"]
    assert len(rows) == 27
    for result in baseline["results"]:
        all_days, single, exclusive = [
            r for r in rows if (r["target"], r["horizon"]) == (result["target"], result["horizon"])
        ]
        assert all_days["inference"] == result["paired_loss"]
        assert single["observations"] == all_days["observations"] - 1
        assert exclusive["observations"] <= single["observations"]
        assert single["fold_counts"][0] == 125
        assert all(
            r["holm_adjusted_p"] is not None and r["exploratory_bh_q"] is not None
            for r in (all_days, single, exclusive)
        )
