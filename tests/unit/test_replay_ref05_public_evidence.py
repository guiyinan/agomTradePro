"""Portable PUBLIC replay contracts, independent of local audit directories."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import replay_ref05_public_evidence as replay
from scripts.replay_ref05_public_evidence import run_replay
from scripts.select_tests import select_tests

REPO = Path(__file__).resolve().parents[2]


def _projection_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Derive a synthetic grid; none of these bytes are historical evidence."""
    history_path, evidence = _history_fixture(tmp_path)
    history = json.loads(history_path.read_text())
    base_path = evidence / history["base_recipe"]["raw_path"]
    base = json.loads(base_path.read_text())
    base["cutoffs"][1] = deepcopy(base["cutoffs"][0])
    base["cutoffs"][1]["at"] = "2024-11-08T09:00:02+08:00"
    base_path.write_text(json.dumps(base))
    history["base_recipe"]["sha256"] = hashlib.sha256(base_path.read_bytes()).hexdigest()
    history_path.write_text(json.dumps(history))
    (evidence / "history.json").write_bytes(history_path.read_bytes())
    for code in base["code_inputs"]:
        target = evidence / "old-code" / code["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO / code["path"]).read_bytes())
    recipe = {
        "schema": "ref05.history-projection.v1",
        "code_inputs": base["code_inputs"],
        "history_recipe": {
            "raw_path": "history.json",
            "sha256": hashlib.sha256(history_path.read_bytes()).hexdigest(),
        },
        "history_code_root": "old-code",
        "base_code_root": "old-code",
    }
    path = tmp_path / "projection.json"
    path.write_text(json.dumps(recipe))
    return path, evidence


def test_projection_blocks_partial_grid_without_calculation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe, evidence = _projection_fixture(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Historical qualification must never calculate Regime")

    monkeypatch.setattr(replay, "RegimeCalculatorV2", forbidden)
    result = run_replay(recipe, evidence)
    assert result == run_replay(recipe, evidence)
    assert result["required_key_count"] == 16
    assert result["source_asserted_public_count"] == 16
    assert result["independent_public_count"] == 2
    assert result["verified_observation_count"] == 0
    assert result["downstream_calculation_count"] == 0
    for row, value in zip(result["cutoffs"], [0.2, 0.9], strict=True):
        assert len(row["keys"]) == 8
        assert row["manifest_verified"] is False
        assert row["manifest"]["coverage"] == {"CN_PMI": 0.0, "CN_CPI_NATIONAL_YOY": 0.25}
        assert len(row["manifest"]["missing"]) == len(row["manifest"]["unknown"]) == 7
        assert row["manifest"]["selected_versions"][0]["value"] == value
        assert row["system_manifest_verified"] is False
        assert len(row["system_manifest"]["missing"]) == 8
        assert len(row["system_manifest"]["unknown"]) == 8
        target = next(k for k in row["keys"] if k["business_key"].endswith(":2024-06"))
        assert target["independent_public"]["value"] == value
        assert target["historical_system_known_at"] is None
        assert "independent_capture_unproved" in {v["public_result"] for v in target["versions"]}
    assert "after_cutoff" in {
        v["public_result"] for v in result["cutoffs"][0]["keys"][4]["versions"]
    }


@pytest.mark.parametrize("mutation", ["old-code", "new-code", "history", "body", "escape"])
def test_projection_verifies_both_lineages_and_new_candidate(tmp_path: Path, mutation: str) -> None:
    recipe, evidence = _projection_fixture(tmp_path)
    data = json.loads(recipe.read_text())
    if mutation == "old-code":
        (evidence / "old-code" / data["code_inputs"][0]["path"]).write_text("tampered")
    elif mutation == "new-code":
        data["code_inputs"][0]["sha256"] = "0" * 64
    elif mutation == "history":
        (evidence / "history.json").write_text("{}")
    elif mutation == "body":
        (evidence / "before.html").write_text("tampered")
    else:
        data["base_code_root"] = ".."
    recipe.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash mismatch|escapes"):
        run_replay(recipe, evidence)


def _update_projection_history(recipe: Path, evidence: Path, history: dict[str, object]) -> None:
    raw = json.dumps(history).encode()
    (evidence / "history.json").write_bytes(raw)
    data = json.loads(recipe.read_text())
    data["history_recipe"]["sha256"] = hashlib.sha256(raw).hexdigest()
    recipe.write_text(json.dumps(data))


def test_projection_empty_captures_preserves_unknown_and_source_assertions(tmp_path: Path) -> None:
    recipe, evidence = _projection_fixture(tmp_path)
    history = json.loads((evidence / "history.json").read_bytes())
    history["captures"] = []
    _update_projection_history(recipe, evidence, history)
    result = run_replay(recipe, evidence)
    assert result["independent_public_count"] == 0
    assert result["source_asserted_public_count"] == 16
    for row in result["cutoffs"]:
        assert row["manifest_verified"] is False
        assert len(row["manifest"]["missing"]) == len(row["manifest"]["unknown"]) == 8
        reasons = {k["blocking_reason"] for k in row["keys"]}
        assert reasons == {"no_independent_version_by_cutoff", "not_independently_audited"}


def test_projection_complete_synthetic_grid_uses_domain_verification(tmp_path: Path) -> None:
    """Positive fixture proves blocking is evidence-based, never historical coverage."""
    recipe, evidence = _projection_fixture(tmp_path)
    history = json.loads((evidence / "history.json").read_bytes())
    base_path = evidence / "base.json"
    base = json.loads(base_path.read_bytes())
    for cutoff in base["cutoffs"]:
        cutoff["expected_periods"] = {"CN_PMI": ["2024-07"], "CN_CPI_NATIONAL_YOY": ["2024-06"]}
    base_path.write_text(json.dumps(base))
    history["base_recipe"]["sha256"] = hashlib.sha256(base_path.read_bytes()).hexdigest()
    freeze = json.loads((evidence / "freeze.json").read_bytes())
    source = base["sources"][0]
    freeze["targets"].append(
        {
            "label": source["label"],
            "source": source,
            "business_key": "CN_PMI:2024-07",
            "cutoff": base["cutoffs"][0]["at"],
            "addresses": [source["url"]],
        }
    )
    (evidence / "freeze.json").write_text(json.dumps(freeze))
    history["query_freeze"]["sha256"] = hashlib.sha256(
        (evidence / "freeze.json").read_bytes()
    ).hexdigest()
    document = deepcopy(source)
    document["observations"] = [document["observations"][0]]
    raw = (evidence / document["raw_path"]).read_bytes()
    cdx_raw = json.dumps(
        [
            ["timestamp", "original", "digest", "statuscode"],
            [
                "20241108005959",
                source["url"],
                base64.b32encode(hashlib.sha1(raw).digest()).decode(),
                "200",
            ],
        ]
    ).encode()
    (evidence / "pmi-cdx.json").write_bytes(cdx_raw)
    history["captures"].append(
        {
            "label": source["label"],
            "source": document,
            "original_url": source["url"],
            "raw_path": document["raw_path"],
            "sha256": document["sha256"],
            "required_text": document["title"],
            "cdx_path": "pmi-cdx.json",
            "cdx_sha256": hashlib.sha256(cdx_raw).hexdigest(),
        }
    )
    _update_projection_history(recipe, evidence, history)
    result = run_replay(recipe, evidence)
    assert result["verified_observation_count"] == 2
    assert result["independent_public_count"] == result["required_key_count"] == 4
    for row in result["cutoffs"]:
        assert row["manifest_verified"] is True
        assert not row["manifest"]["missing"] and not row["manifest"]["unknown"]
        assert row["system_manifest_verified"] is False
    assert result["downstream_calculation_count"] == 0


def test_source_only_change_selects_replay_contracts() -> None:
    selected = select_tests(set(), ["scripts/replay_ref05_public_evidence.py"], "logic_guardrails")
    assert "tests/unit/test_replay_ref05_public_evidence.py" in selected


def _history_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Synthetic captures exercise clocks; they are not historical evidence."""
    base_path, evidence = _fixture(tmp_path)
    base = json.loads(base_path.read_text())
    (evidence / "base.json").write_bytes(base_path.read_bytes())
    source = base["sources"][1]
    target = {
        "label": source["label"],
        "business_key": "CN_CPI_NATIONAL_YOY:2024-06",
        "cutoff": base["cutoffs"][0]["at"],
        "source": source,
        "addresses": [source["url"], source["url"].replace("https:", "http:")],
    }
    freeze = {"targets": [target]}
    frozen_raw = json.dumps(freeze).encode()
    (evidence / "freeze.json").write_bytes(frozen_raw)
    captures = []
    for name, timestamp, value in [
        ("before", "20241108005959", "0.2"),
        ("after", "20241108010001", "0.9"),
    ]:
        document = deepcopy(source)
        raw = (evidence / source["raw_path"]).read_bytes().replace(b"0.2", value.encode())
        document.update(raw_path=name + ".html", sha256=hashlib.sha256(raw).hexdigest())
        document["title"] = document["title"].replace("0.2", value)
        document["observations"][0]["value"] = value
        (evidence / document["raw_path"]).write_bytes(raw)
        original = target["addresses"][1]
        cdx_raw = json.dumps(
            [
                ["timestamp", "original", "digest", "statuscode"],
                [timestamp, original, base64.b32encode(hashlib.sha1(raw).digest()).decode(), "200"],
            ]
        ).encode()
        (evidence / (name + "-cdx.json")).write_bytes(cdx_raw)
        captures.append(
            {
                "label": source["label"],
                "source": document,
                "original_url": original,
                "raw_path": document["raw_path"],
                "sha256": document["sha256"],
                "required_text": document["title"],
                "cdx_path": name + "-cdx.json",
                "cdx_sha256": hashlib.sha256(cdx_raw).hexdigest(),
            }
        )
    audit = {
        "schema": "ref05.history-audit.v1",
        "code_inputs": base["code_inputs"],
        "base_recipe": {
            "raw_path": "base.json",
            "sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        },
        "base_evidence_dir": ".",
        "query_freeze": {
            "raw_path": "freeze.json",
            "sha256": hashlib.sha256(frozen_raw).hexdigest(),
        },
        "captures": captures,
    }
    path = tmp_path / "history.json"
    path.write_text(json.dumps(audit))
    return path, evidence


def _historical_alias_fixture(tmp_path: Path, scheme: str = "https") -> tuple[Path, Path]:
    """Bind a synthetic prior official address without changing the original source."""
    recipe, evidence = _history_fixture(tmp_path)
    data = json.loads(recipe.read_text())
    data["captures"] = data["captures"][:1]
    capture = data["captures"][0]
    alias = "https://www.stats.gov.cn/sj/zxfb/202407/t20240710_legacy.html"
    capture["source"]["url"] = alias
    capture["original_url"] = alias.replace("https:", scheme + ":", 1)
    cdx_path = evidence / capture["cdx_path"]
    cdx = json.loads(cdx_path.read_text())
    cdx[1][1] = capture["original_url"]
    raw = json.dumps(cdx).encode()
    cdx_path.write_bytes(raw)
    capture["cdx_sha256"] = hashlib.sha256(raw).hexdigest()
    freeze_path = evidence / data["query_freeze"]["raw_path"]
    freeze = json.loads(freeze_path.read_text())
    freeze["targets"][0]["addresses"].append(capture["original_url"])
    freeze["targets"][0]["alternate_documents"] = [deepcopy(capture["source"])]
    raw = json.dumps(freeze).encode()
    freeze_path.write_bytes(raw)
    data["query_freeze"]["sha256"] = hashlib.sha256(raw).hexdigest()
    recipe.write_text(json.dumps(data))
    return recipe, evidence


@pytest.mark.parametrize("scheme", ["https", "http"])
def test_historical_alias_preserves_provenance_and_clocks(tmp_path: Path, scheme: str) -> None:
    recipe, evidence = _historical_alias_fixture(tmp_path, scheme)
    result = run_replay(recipe, evidence)
    row = result["cutoffs"][0]
    selected = row["independent_public"]
    assert "_legacy.html#2024-06@" in selected["source_record_id"]
    assert selected["source_record_id"].startswith(scheme + ":")
    assert "_legacy.html" not in row["source_asserted_public"]["source_record_id"]
    assert selected["available_at"] == "2024-11-08T08:59:59+08:00"
    assert row["system"] is None
    assert result["first_publication"] is result["revision_history_complete"] is None
    assert result["historical_system_clock"] is None


@pytest.mark.parametrize(
    "mutation",
    ["not_frozen", "address", "title", "date", "indicator", "unit", "parser", "period", "bytes"],
)
def test_historical_alias_rejects_unbound_or_different_announcement(
    tmp_path: Path, mutation: str
) -> None:
    recipe, evidence = _historical_alias_fixture(tmp_path)
    data = json.loads(recipe.read_text())
    capture = data["captures"][0]
    freeze_path = evidence / data["query_freeze"]["raw_path"]
    freeze = json.loads(freeze_path.read_text())
    target = freeze["targets"][0]
    if mutation == "not_frozen":
        target["alternate_documents"] = []
    elif mutation == "address":
        target["addresses"].remove(capture["original_url"])
    elif mutation == "bytes":
        (evidence / capture["raw_path"]).write_text("not the frozen historical bytes")
    else:
        if mutation == "period":
            capture["source"]["observations"][0]["period"] = "2024-07"
        else:
            field, value = {
                "title": ("title", "Another announcement - 国家统计局"),
                "date": ("published_at", "2024-07-09T09:30:00+08:00"),
                "indicator": ("indicator", "CN_PMI"),
                "unit": ("unit", "basis-points"),
                "parser": ("parser", "nbs_pmi_table"),
            }[mutation]
            capture["source"][field] = value
        target["alternate_documents"] = [deepcopy(capture["source"])]
        capture["required_text"] = capture["source"]["title"]
    raw = json.dumps(freeze).encode()
    freeze_path.write_bytes(raw)
    data["query_freeze"]["sha256"] = hashlib.sha256(raw).hexdigest()
    recipe.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        run_replay(recipe, evidence)


def test_history_clocks_reject_late_revision_and_current_bytes(tmp_path: Path) -> None:
    recipe, evidence = _history_fixture(tmp_path)
    result = run_replay(recipe, evidence)
    row = result["cutoffs"][0]
    assert row["source_asserted_public"]["value"] == 0.2
    assert row["independent_public"]["value"] == 0.2
    assert row["independent_public"]["available_at"] == "2024-11-08T08:59:59+08:00"
    assert row["system"] is None
    assert {v["public_result"] for v in row["versions"]} == {
        "selected",
        "after_cutoff",
        "independent_capture_unproved",
    }
    assert result == run_replay(recipe, evidence)
    assert result["database_writes"] == 0
    assert result["first_publication"] is None
    assert result["revision_history_complete"] is None


def test_history_no_captures_does_not_disqualify_source_asserted_public(tmp_path: Path) -> None:
    recipe, evidence = _history_fixture(tmp_path)
    data = json.loads(recipe.read_text())
    data["captures"] = []
    recipe.write_text(json.dumps(data))
    row = run_replay(recipe, evidence)["cutoffs"][0]
    assert row["source_asserted_public"]["value"] == 0.2
    assert row["independent_public"] is None
    assert row["system"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "digest",
        "original",
        "clock",
        "body",
        "source",
        "scope",
        "duplicate",
        "base",
        "freeze",
        "escape",
    ],
)
def test_history_rejects_unbound_capture(tmp_path: Path, mutation: str) -> None:
    recipe, evidence = _history_fixture(tmp_path)
    data = json.loads(recipe.read_text())
    capture = data["captures"][0]
    if mutation in {"digest", "original", "clock"}:
        path = evidence / capture["cdx_path"]
        cdx = json.loads(path.read_text())
        index, value = {
            "digest": (2, "INVALID"),
            "original": (1, "https://example.com/"),
            "clock": (0, "20271108005959"),
        }[mutation]
        cdx[1][index] = value
        raw = json.dumps(cdx).encode()
        path.write_bytes(raw)
        capture["cdx_sha256"] = hashlib.sha256(raw).hexdigest()
    elif mutation == "body":
        (evidence / capture["raw_path"]).write_text("tampered")
    elif mutation == "source":
        capture["source"]["observations"][0]["value"] = "99"
    elif mutation == "scope":
        capture["label"] = "not-admitted"
    elif mutation == "duplicate":
        data["captures"].append(capture)
    elif mutation in {"base", "freeze"}:
        data["base_recipe" if mutation == "base" else "query_freeze"]["sha256"] = "0" * 64
    else:
        data["base_evidence_dir"] = ".."
    recipe.write_text(json.dumps(data))
    message = {
        "digest": "CDX digest differs",
        "original": "CDX digest differs",
        "clock": "Capture clock contradicts",
        "body": "Evidence hash mismatch",
        "source": "Declared observation differs",
        "scope": "outside frozen targets",
        "duplicate": "Duplicate historical capture",
        "base": "Evidence hash mismatch",
        "freeze": "Evidence hash mismatch",
        "escape": "Base evidence escapes",
    }[mutation]
    with pytest.raises(ValueError, match=message):
        run_replay(recipe, evidence)


def test_history_cutoff_equality_and_latest_eligible_version(tmp_path: Path) -> None:
    recipe, evidence = _history_fixture(tmp_path)
    data = json.loads(recipe.read_text())
    capture = data["captures"][1]
    path = evidence / capture["cdx_path"]
    cdx = json.loads(path.read_text())
    cdx[1][0] = "20241108010000"
    raw = json.dumps(cdx).encode()
    path.write_bytes(raw)
    capture["cdx_sha256"] = hashlib.sha256(raw).hexdigest()
    recipe.write_text(json.dumps(data))
    row = run_replay(recipe, evidence)["cutoffs"][0]
    assert row["independent_public"]["value"] == 0.9
    assert "superseded_by_later_eligible" in {v["public_result"] for v in row["versions"]}


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
