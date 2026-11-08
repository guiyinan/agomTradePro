"""Portable PUBLIC replay contracts, independent of local audit directories."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import replay_ref05_public_evidence as replay
from scripts.replay_ref05_public_evidence import run_replay
from scripts.select_tests import select_tests

REPO = Path(__file__).resolve().parents[2]


def test_source_only_change_selects_replay_contracts() -> None:
    selected = select_tests(set(), ["scripts/replay_ref05_public_evidence.py"], "logic_guardrails")
    assert "tests/unit/test_replay_ref05_public_evidence.py" in selected


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    sources = []
    values = [
        (6, "0.2", "2024-07-10"),
        (7, "0.5", "2024-08-09"),
        (8, "0.6", "2024-09-09"),
        (9, "0.4", "2024-10-13"),
        (10, "0.3", "2024-11-09"),
    ]
    for month, value, day in [(0, "", "2024-10-31"), *values]:
        is_pmi = month == 0
        label = "pmi" if is_pmi else f"cpi-{month}"
        title = (
            "2024年10月中国采购经理指数运行情况 - 国家统计局"
            if is_pmi
            else f"2024年{month}月份居民消费价格同比上涨{value}% - 国家统计局"
        )
        visible = day.replace("-", "/") + " 09:30"
        observations = (
            [
                {"period": f"2024-{m:02d}", "value": v}
                for m, v in [(7, "49.4"), (8, "49.1"), (9, "49.8"), (10, "50.1")]
            ]
            if is_pmi
            else [{"period": f"2024-{month:02d}", "value": value}]
        )
        if is_pmi:
            table = "<tr><td>单位：%</td></tr><tr><td></td><td>PMI</td></tr>" + "".join(
                f"<tr><td>2024年{int(o['period'][-2:])}月</td><td>{o['value']}</td></tr>"
                for o in observations
            )
            narrative = ""
        else:
            table = f"<tr><td></td><td>环比涨跌幅（%）</td><td>同比涨跌幅（%）</td></tr><tr><td>居民消费价格</td><td>-9.9</td><td>{value}</td></tr>"
            narrative = f"2024年{month}月份，全国居民消费价格同比上涨{value}%。"
        raw = f'<html><title>{title}</title><meta name="PubDate" content="{visible}"><body>{visible}<p>{narrative}</p><table>{table}</table></body></html>'.encode()
        (evidence / (label + ".html")).write_bytes(raw)
        sources.append(
            {
                "label": label,
                "parser": "nbs_pmi_table" if is_pmi else "nbs_cpi_yoy",
                "url": f"https://www.stats.gov.cn/sj/zxfb/{day[:7].replace('-', '')}/t{day.replace('-', '')}_test.html",
                "raw_path": label + ".html",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "title": title,
                "published_at": day + "T09:30:00+08:00",
                "retrieved_at": "2026-11-08T12:00:00+00:00",
                "indicator": "CN_PMI" if is_pmi else "CN_CPI_NATIONAL_YOY",
                "unit": "指数" if is_pmi else "%",
                "observations": observations,
            }
        )
    source_path = "apps/regime/domain/services_v2.py"
    recipe = {
        "schema": "ref05.public-replay.v1",
        "code_inputs": [
            {
                "path": source_path,
                "sha256": hashlib.sha256(
                    (REPO / source_path).read_bytes().replace(b"\r\n", b"\n")
                ).hexdigest(),
                "hash_basis": "lf_normalized_bytes",
            }
        ],
        "parameters": {
            "pmi_expansion": 50.0,
            "pmi_contraction": 50.0,
            "cpi_high": 2.0,
            "cpi_low": 1.0,
            "cpi_deflation": 0.0,
            "momentum_weight": 0.3,
            "high_confidence_threshold": 0.6,
        },
        "roles": {"growth": "CN_PMI", "inflation": "CN_CPI_NATIONAL_YOY"},
        "sources": sources,
        "cutoffs": [
            {
                "at": f"2024-11-{day}T09:00:00+08:00",
                "expected_periods": {
                    "CN_PMI": ["2024-07", "2024-08", "2024-09", "2024-10"],
                    "CN_CPI_NATIONAL_YOY": [f"2024-{m:02d}" for m in months],
                },
            }
            for day, months in [("08", range(6, 10)), ("11", range(7, 11))]
        ],
    }
    raw = "沪市投资者账户新开户739.40万户".encode()
    (evidence / "archive.html").write_bytes(raw)
    original = "http://www.stcn.com/article/detail/1401103.html"
    cdx = json.dumps(
        [
            ["timestamp", "original", "digest", "statuscode"],
            [
                "20241106113607",
                original,
                base64.b32encode(hashlib.sha1(raw).digest()).decode(),
                "200",
            ],
        ]
    ).encode()
    (evidence / "cdx.json").write_bytes(cdx)
    recipe["archive_sample"] = {
        "raw_path": "archive.html",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "cdx_path": "cdx.json",
        "cdx_sha256": hashlib.sha256(cdx).hexdigest(),
        "original_url": original,
        "required_text": raw.decode(),
    }
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    return path, evidence


def test_replay_uses_public_versions_without_tmp_or_database(tmp_path: Path) -> None:
    recipe, evidence = _fixture(tmp_path)
    result = run_replay(recipe, evidence)
    rows = result["cutoffs"]
    assert [r["result"]["inflation_level"] for r in rows] == [0.4, 0.3]
    assert [r["system_visible_fact_count"] for r in rows] == [0, 0]
    assert all(r["manifest_verified"] and r["selected_count"] == 8 for r in rows)
    assert result["archive_sample"]["public_usable_from"] == "2024-11-06T19:36:07+08:00"
    assert result["database_writes"] == 0


def test_code_hash_accepts_both_checkout_line_endings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe, evidence = _fixture(tmp_path)
    code_root = tmp_path / "checkout"
    source = "apps/regime/domain/services_v2.py"
    target = code_root / source
    target.parent.mkdir(parents=True)
    raw = (REPO / source).read_bytes().replace(b"\r\n", b"\n")
    monkeypatch.setattr(replay, "REPO", code_root)
    target.write_bytes(raw)
    linux_result = run_replay(recipe, evidence)
    target.write_bytes(raw.replace(b"\n", b"\r\n"))
    assert run_replay(recipe, evidence) == linux_result


@pytest.mark.parametrize(
    "mutation",
    [
        "payload",
        "raw_newlines",
        "value",
        "empty",
        "duplicate",
        "naive",
        "escape",
        "code",
        "archive",
    ],
)
def test_replay_rejects_invalid_evidence(tmp_path: Path, mutation: str) -> None:
    recipe, evidence = _fixture(tmp_path)
    data = json.loads(recipe.read_text())
    if mutation == "payload":
        (evidence / "pmi.html").write_text("tampered")
    elif mutation == "raw_newlines":
        path = evidence / "pmi.html"
        path.write_bytes(path.read_bytes().replace(b"</title>", b"</title>\r\n"))
    elif mutation == "value":
        data["sources"][1]["observations"][0]["value"] = "99"
    elif mutation == "empty":
        data["cutoffs"][0]["expected_periods"]["CN_PMI"] = []
    elif mutation == "duplicate":
        data["sources"].append(data["sources"][0])
    elif mutation == "naive":
        data["sources"][0]["published_at"] = "2024-10-31T09:30:00"
    elif mutation == "escape":
        data["sources"][0]["raw_path"] = "../recipe.json"
    elif mutation == "code":
        data["code_inputs"][0]["sha256"] = "0" * 64
    else:
        (evidence / "archive.html").write_text("other historical body")
    recipe.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        run_replay(recipe, evidence)


def test_cli_missing_evidence_fails_without_output(tmp_path: Path) -> None:
    recipe, evidence = _fixture(tmp_path)
    (evidence / "pmi.html").unlink()
    output = tmp_path / "result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/replay_ref05_public_evidence.py"),
            "--recipe",
            str(recipe),
            "--evidence-dir",
            str(evidence),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 2
    assert not output.exists()
    assert "error" in completed.stderr.lower()


def test_cli_preserves_existing_output(tmp_path: Path) -> None:
    recipe, evidence = _fixture(tmp_path)
    output = tmp_path / "result.json"
    output.write_text("existing")
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/replay_ref05_public_evidence.py"),
            "--recipe",
            str(recipe),
            "--evidence-dir",
            str(evidence),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 2
    assert output.read_text() == "existing"


@pytest.mark.parametrize("value,phrase", [("-0.2", "下降0.2%"), ("0.0", "持平")])
@pytest.mark.parametrize("explanation", [False, True])
def test_cpi_signed_and_flat_narratives(
    tmp_path: Path, value: str, phrase: str, explanation: bool
) -> None:
    recipe, evidence = _fixture(tmp_path)
    data = json.loads(recipe.read_text())
    source = data["sources"][1]
    raw = (evidence / source["raw_path"]).read_text(encoding="utf-8")
    raw = raw.replace("同比上涨0.2%", "同比" + phrase).replace("<td>0.2</td>", f"<td>{value}</td>")
    if explanation:
        raw = raw.replace(
            "2024年6月份，全国", "环比保持稳定。6月份，受上年同期春节错月高基数影响，全国"
        )
    (evidence / source["raw_path"]).write_text(raw, encoding="utf-8")
    source["title"] = source["title"].replace("同比上涨0.2%", "同比" + phrase)
    source["sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    source["observations"][0]["value"] = value
    recipe.write_text(json.dumps(data))
    result = run_replay(recipe, evidence)
    assert result["cutoffs"][0]["selected"]["CN_CPI_NATIONAL_YOY"][0]["value"] == float(value)
    bad = raw.replace("全国居民消费价格同比" + phrase, "全国居民消费价格同比上涨9.9%")
    (evidence / source["raw_path"]).write_text(bad, encoding="utf-8")
    source["sha256"] = hashlib.sha256(bad.encode()).hexdigest()
    recipe.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="narrative"):
        run_replay(recipe, evidence)


@pytest.mark.parametrize("metadata", [False, True])
def test_visible_release_header_is_independent_of_url_date(tmp_path: Path, metadata: bool) -> None:
    recipe, evidence = _fixture(tmp_path)
    data = json.loads(recipe.read_text())
    source = data["sources"][0]
    raw = (evidence / source["raw_path"]).read_text(encoding="utf-8")
    if not metadata:
        raw = raw.replace('<meta name="PubDate" content="2024/10/31 09:30">', "")
    raw = raw.replace(
        "<body>", '<body><div class="detail-title-des"><h2><p>2024/10/31 09:30</p></h2></div>'
    )
    (evidence / source["raw_path"]).write_text(raw, encoding="utf-8")
    source["sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    source["url"] = source["url"].replace("t20241031_", "t20241112_")
    source["publication_basis"] = "visible_release_header"
    recipe.write_text(json.dumps(data))
    result = run_replay(recipe, evidence)
    assert (
        result["cutoffs"][0]["selected"]["CN_PMI"][-1]["available_at"]
        == "2024-11-01T00:00:00+08:00"
    )
    bad = raw.replace("<p>2024/10/31 09:30</p>", "<p>2024/11/30 09:30</p>")
    (evidence / source["raw_path"]).write_text(bad, encoding="utf-8")
    source["sha256"] = hashlib.sha256(bad.encode()).hexdigest()
    recipe.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="publication"):
        run_replay(recipe, evidence)


def test_frozen_grid_is_bound_and_archive_sample_is_optional(tmp_path: Path) -> None:
    recipe, evidence = _fixture(tmp_path)
    data = json.loads(recipe.read_text())
    del data["archive_sample"]
    frozen = {key: data[key] for key in ("cutoffs", "roles", "parameters")}
    raw = json.dumps(frozen).encode()
    (evidence / "grid.json").write_bytes(raw)
    data["grid_freeze"] = {"raw_path": "grid.json", "sha256": hashlib.sha256(raw).hexdigest()}
    recipe.write_text(json.dumps(data))
    assert run_replay(recipe, evidence)["archive_sample"] is None
    data["cutoffs"][0]["at"] = "2024-11-08T10:00:00+08:00"
    recipe.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="frozen"):
        run_replay(recipe, evidence)


@pytest.mark.parametrize("mutation", ["missing", "future", "metadata_conflict"])
def test_monthly_grid_rejects_unusable_sources(tmp_path: Path, mutation: str) -> None:
    recipe, evidence = _fixture(tmp_path)
    data = json.loads(recipe.read_text())
    if mutation == "missing":
        del data["sources"][1]
    elif mutation == "future":
        data["cutoffs"][0]["at"] = "2024-10-31T12:00:00+08:00"
    else:
        source = data["sources"][0]
        raw = (evidence / source["raw_path"]).read_text(encoding="utf-8")
        raw = raw.replace("<body>", '<body><div class="detail-title-des">2024/10/31 09:30</div>')
        raw = raw.replace('content="2024/10/31 09:30"', 'content="2024/10/30 09:30"')
        (evidence / source["raw_path"]).write_text(raw, encoding="utf-8")
        source["sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        source["publication_basis"] = "visible_release_header"
    recipe.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        run_replay(recipe, evidence)


def test_tracked_monthly_sample_preserves_scope_and_required_keys() -> None:
    data = json.loads(
        (REPO / "docs/reviews/ref05-monthly-2024-replay-20261108.json").read_text(encoding="utf-8")
    )
    assert [c["at"] for c in data["cutoffs"]] == [
        f"2024-{m:02}-15T09:00:00+08:00" for m in range(1, 13)
    ]
    required: set[tuple[str, str]] = set()
    for month, cutoff in enumerate(data["cutoffs"], 1):
        expected = []
        for offset in range(4, 0, -1):
            year, index = divmod(2024 * 12 + month - 1 - offset, 12)
            expected.append(f"{year:04}-{index + 1:02}")
        assert cutoff["expected_periods"] == dict.fromkeys(data["roles"].values(), expected)
        required.update(
            (indicator, period) for indicator in data["roles"].values() for period in expected
        )
    supplied = {(s["indicator"], o["period"]) for s in data["sources"] for o in s["observations"]}
    assert required == supplied and len(supplied) == 30
    assert len(data["sources"]) == 30
    for source in data["sources"]:
        assert source["unit"] == source["source_unit"] == "%"
        assert source["source_first_publication_at"] is None
        assert source["source_revision_number"] is None
        assert source["independent_historical_capture_at"] is None
        assert source["historical_system_known_at"] is None
        assert source["retrieved_at"] > data["frozen_at_utc"]
