"""Offline synthetic fixtures exercise real draft parsers and bounded evidence collection."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "_offline_replay_collector_test"
DATE = "2026-09-24"
CANDIDATE = "a" * 40
SAMPLE = ("000001.SZ", "600000.SH")
FINISHED = datetime(2026, 9, 24, 8, 0, 1, tzinfo=UTC)
NORMALIZED = datetime(2026, 9, 24, 8, 0, 1, 1000, tzinfo=UTC)


@pytest.fixture(scope="module")
def modules():
    package = ModuleType(PREFIX)
    package.__path__ = [str(ROOT / "apps/data_center/infrastructure")]
    sys.modules[PREFIX] = package
    try:
        yield {
            name: importlib.import_module(f"{PREFIX}.{name}")
            for name in (
                "rehearsal_identity",
                "rehearsal_response_store",
                "rehearsal_response_replay",
                "rehearsal_replay_collector",
            )
        }
    finally:
        for name in tuple(sys.modules):
            if name == PREFIX or name.startswith(PREFIX + "."):
                del sys.modules[name]


def _body(dataset: str, *, extra_asset: bool = True) -> bytes:
    fields = (
        ["ts_code", "trade_date", "close", "pre_close", "vol", "amount"]
        if "quote" in dataset
        else ["ts_code", "trade_date", "total_mv", "circ_mv", "pe_ttm", "pb"]
    )
    rows = [
        (
            [code, "20260924", 12.5, 12.0, 100.5, 2_000.25]
            if "quote" in dataset
            else [code, "20260924", 300.0, 200.0, 8.0, 1.2]
        )
        for code in SAMPLE
    ]
    if extra_asset:
        rows.append(["600001.SH", *rows[0][1:]])
    return json.dumps({"code": 0, "msg": None, "data": {"fields": fields, "items": rows}}).encode()


def _identities(modules):
    return modules["rehearsal_identity"].parse_rehearsal_identities(
        [
            {
                "role": role,
                "provider_id": index + 1,
                "source": "tushare",
                "version": "fixture-v1",
                "endpoint_id": "fixture-primary",
            }
            for index, role in enumerate(("quote", "valuation"))
        ]
    )


def _context(modules, dataset):
    identities = _identities(modules)
    return modules["rehearsal_response_store"].RehearsalResponseContext(
        candidate_sha=CANDIDATE,
        target_trade_date=DATE,
        universe_sha256=modules["rehearsal_replay_collector"].rehearsal_digest(SAMPLE),
        provider_identities_sha256=modules["rehearsal_identity"].rehearsal_identities_digest(
            identities
        ),
        provider_id=1 if "quote" in dataset else 2,
        provider_source="tushare",
        endpoint_id="fixture-primary",
        dataset=dataset,
        sample_codes=SAMPLE,
    )


def _contracts(modules, dataset):
    cls = modules["rehearsal_response_replay"].ReplayUnitContract
    return (
        (
            cls("close", "元", "元", 1.0),
            cls("vol", "手", "股", 100.0),
            cls("amount", "千元", "元", 1000.0),
        )
        if "quote" in dataset
        else (cls("total_mv", "万元", "元", 10000.0), cls("circ_mv", "万元", "元", 10000.0))
    )


@pytest.mark.parametrize("dataset", ["equity.quote.snapshot", "equity.valuation.fact"])
def test_actual_parser_replay_runs_seven_cases_with_superset_body(modules, dataset):
    replay = modules["rehearsal_response_replay"]
    body = _body(dataset)
    response = replay.ReplayResponse(
        _context(modules, dataset), body, hashlib.sha256(body).hexdigest(), FINISHED
    )
    result = replay.replay_retained_dataset([response], _contracts(modules, dataset))
    assert result["outcome"] == "success"
    assert set(result["replay_cases"]) == {
        "valid",
        "missing",
        "truncated",
        "stale",
        "duplicate",
        "unit_error",
        "subsequent_fact_update",
    }
    assert [case["outcome"] for case in result["case_results"]].count("rejected") == 6
    assert result["publication_immutability_verified"] is False
    assert result["observations"][0]["source_observed_at"] == "2026-09-24T07:00:00+00:00"
    assert len(result["observations"]) == len(SAMPLE)
    assert response.body == body


@pytest.mark.parametrize(
    "failure",
    ["hash", "wrong_units", "stale", "missing", "duplicate", "future_clock", "null_units"],
)
def test_replay_rejects_invalid_baseline_instead_of_generating_success(modules, failure):
    replay = modules["rehearsal_response_replay"]
    dataset = "equity.valuation.fact"
    payload = json.loads(_body(dataset))
    if failure == "stale":
        payload["data"]["items"][0][1] = "20260923"
    elif failure == "missing":
        payload["data"]["items"].pop(0)
    elif failure == "duplicate":
        payload["data"]["items"].append(payload["data"]["items"][0])
    elif failure == "null_units":
        for row in payload["data"]["items"]:
            row[2] = row[3] = None
    body = json.dumps(payload).encode()
    response = replay.ReplayResponse(
        _context(modules, dataset),
        body,
        "0" * 64 if failure == "hash" else hashlib.sha256(body).hexdigest(),
        FINISHED,
    )
    if failure == "future_clock":
        response = replace(response, finished_at=FINISHED.replace(hour=6))
    contracts = _contracts(modules, dataset)
    if failure == "wrong_units":
        contracts = (replace(contracts[0], multiplier=1.0), contracts[1])
    with pytest.raises(ValueError):
        replay.replay_retained_dataset([response], contracts)


def _fixture(modules, tmp_path):
    collector = modules["rehearsal_replay_collector"]
    source = tmp_path / "source"
    source.mkdir()
    for name in ("apps", "core", "shared"):
        (source / name).mkdir()
        (source / name / "fixture.py").write_text("# synthetic source fixture\n")
    for name in ("pyproject.toml", "requirements-prod.txt"):
        (source / name).write_text("# synthetic manifest\n")
    capture = tmp_path / "capture"
    capture.mkdir()
    store = modules["rehearsal_response_store"].RehearsalResponseStore(
        capture, max_responses=2, max_response_bytes=10000, max_total_bytes=20000
    )
    receipts = []
    probes = []
    for index, dataset in enumerate(collector.DATASETS):
        ref = store.persist_response(
            _context(modules, dataset),
            receipt_index=index,
            host="fixture.invalid",
            path_sha256="b" * 64,
            method="POST",
            started_at="2026-09-24T08:00:00+00:00",
            finished_at=FINISHED.isoformat(),
            status_code=200,
            response_body=_body(dataset),
        )
        record = asdict(ref)
        receipts.append(
            {
                **{
                    key: record[key]
                    for key in (
                        "host",
                        "path_sha256",
                        "method",
                        "started_at",
                        "finished_at",
                        "status_code",
                        "body_sha256",
                        "body_bytes",
                    )
                },
                "error_code": "",
                "response_artifact": record,
            }
        )
        observed_at = "2026-09-24T07:00:00+00:00"
        facts = []
        for asset_code in SAMPLE:
            fact = {
                "asset_code": asset_code,
                "source": "tushare",
                "observed_at": observed_at,
                "fetched_at": NORMALIZED.isoformat(),
            }
            if "quote" in dataset:
                fact.update({"current_price": 12.5, "volume": 10_050.0, "amount": 2_000_250.0})
            else:
                fact.update(
                    {
                        "val_date": DATE,
                        "market_cap": 3_000_000.0,
                        "float_market_cap": 2_000_000.0,
                        "available_at": NORMALIZED.isoformat(),
                        "raw_payload_hash": record["body_sha256"],
                    }
                )
            facts.append(fact)
        probes.append(
            {
                "dataset": dataset,
                "outcome": "success",
                "receipt_indexes": [index],
                "facts": facts,
            }
        )
    identities = _identities(modules)
    digest = modules["rehearsal_identity"].rehearsal_identities_digest(identities)
    probe = {
        "schema": "market.provider-rehearsal.v1",
        "outcome": "success",
        "mode": "read_only_live_provider",
        "database_read_only": True,
        "response_retention_enabled": True,
        "source_unchanged": True,
        "source_tree_sha256": collector.market_rehearsal_source_digest(source),
        "candidate_sha": CANDIDATE,
        "target_trade_date": DATE,
        "stored": 0,
        "publication_updated": False,
        "provider_identities": [asdict(identity) for identity in identities],
        "provider_identities_sha256": digest,
        "asset_codes": list(SAMPLE),
        "universe_count": len(SAMPLE),
        "universe_sha256": collector.rehearsal_digest(SAMPLE),
        "sample": list(SAMPLE),
        "sample_sha256": collector.rehearsal_digest(SAMPLE),
        "probes": probes,
        "started_at": "2026-09-24T08:00:00+00:00",
        "finished_at": "2026-09-24T08:00:02+00:00",
        "transport": {"receipts": receipts},
    }
    units = {
        "schema": "release.provider-unit-contract.v1",
        "candidate_sha": CANDIDATE,
        "provider_identities_sha256": digest,
        "source_reference": "synthetic-contract-for-unit-test-only",
        "datasets": {
            dataset: [asdict(contract) for contract in _contracts(modules, dataset)]
            for dataset in collector.DATASETS
        },
    }
    probe_path, unit_path = capture / "probe.json", tmp_path / "unit-contract.json"
    probe_path.write_text(json.dumps(probe), encoding="utf-8")
    unit_path.write_text(json.dumps(units), encoding="utf-8")
    kwargs = {
        "probe_path": probe_path,
        "expected_probe_sha256": hashlib.sha256(probe_path.read_bytes()).hexdigest(),
        "unit_contract_path": unit_path,
        "expected_unit_contract_sha256": hashlib.sha256(unit_path.read_bytes()).hexdigest(),
        "candidate_sha": CANDIDATE,
        "target_trade_date": DATE,
        "source_root": source,
        "output_dir": tmp_path / "result",
    }
    return kwargs, probe


def test_collector_preserves_exact_bytes_and_passes_existing_release_receipt_validator(
    modules, tmp_path
):
    from scripts import validate_release_rehearsal as validator

    collector = modules["rehearsal_replay_collector"]
    kwargs, probe = _fixture(modules, tmp_path)
    result = collector.collect_response_replay(**kwargs)
    assert result["outcome"] == "success"
    assert result["replay_case_count"] == 14
    assert result["release_ready"] is False
    assert (kwargs["output_dir"] / "probe-capture.json").read_bytes() == kwargs[
        "probe_path"
    ].read_bytes()
    validator._validate_real_replay(
        result,
        kwargs["output_dir"],
        expected_candidate=CANDIDATE,
        expected_date=DATE,
        expected_universe=probe["universe_sha256"],
        expected_provider_digest=probe["provider_identities_sha256"],
        expected_assets=SAMPLE,
    )
    quote_receipt = json.loads(
        (kwargs["output_dir"] / "quote-replay.json").read_text(encoding="utf-8")
    )
    observation = quote_receipt["observations"][0]
    assert observation["transport_received_at"] == FINISHED.isoformat()
    assert observation["normalization_completed_at"] == NORMALIZED.isoformat()


@pytest.mark.parametrize(
    "failure",
    [
        "candidate",
        "date",
        "hash",
        "source",
        "identity",
        "scope",
        "missing_ref",
        "raw_tamper",
        "path_escape",
        "missing_unit",
        "receipt_clock",
        "receipt_identity",
        "live_fact_mismatch",
        "output_exists",
    ],
)
def test_collector_failures_never_write_success_report(modules, tmp_path, failure):
    collector = modules["rehearsal_replay_collector"]
    kwargs, probe = _fixture(modules, tmp_path)
    if failure == "candidate":
        kwargs["candidate_sha"] = "c" * 40
    elif failure == "date":
        kwargs["target_trade_date"] = "2026-09-23"
    elif failure == "hash":
        kwargs["expected_probe_sha256"] = "0" * 64
    elif failure == "source":
        (kwargs["source_root"] / "apps/fixture.py").write_text("# changed source\n")
    elif failure == "identity":
        probe["provider_identities"][0]["provider_id"] = 9
    elif failure == "scope":
        probe["sample"] = [SAMPLE[0]]
    elif failure == "missing_ref":
        probe["transport"]["receipts"][0]["response_artifact"] = None
    elif failure == "raw_tamper":
        path = (
            kwargs["probe_path"].parent
            / probe["transport"]["receipts"][0]["response_artifact"]["path"]
        )
        path.write_bytes(path.read_bytes() + b" ")
    elif failure == "path_escape":
        probe["transport"]["receipts"][0]["response_artifact"]["path"] = "../unit-contract.json"
    elif failure == "missing_unit":
        unit = json.loads(kwargs["unit_contract_path"].read_bytes())
        unit["datasets"].pop("equity.quote.snapshot")
        kwargs["unit_contract_path"].write_text(json.dumps(unit))
        kwargs["expected_unit_contract_sha256"] = hashlib.sha256(
            kwargs["unit_contract_path"].read_bytes()
        ).hexdigest()
    elif failure == "receipt_clock":
        probe["transport"]["receipts"][0]["finished_at"] = "2026-09-24T08:03:00+00:00"
    elif failure == "receipt_identity":
        probe["transport"]["receipts"][0]["response_artifact"]["provider_id"] = 2
    elif failure == "live_fact_mismatch":
        probe["probes"][0]["facts"][0]["current_price"] = 99.0
    elif failure == "output_exists":
        kwargs["output_dir"].mkdir()
    if failure != "hash":
        kwargs["probe_path"].write_text(json.dumps(probe))
        kwargs["expected_probe_sha256"] = hashlib.sha256(
            kwargs["probe_path"].read_bytes()
        ).hexdigest()
    with pytest.raises((ValueError, OSError)):
        collector.collect_response_replay(**kwargs)
    assert not (kwargs["output_dir"] / "real-response-unit-replay.json").exists()


def test_public_identity_input_rejects_secret_extras_and_bool_ids(modules):
    identity = modules["rehearsal_identity"]
    values = [asdict(item) for item in _identities(modules)]
    values[0]["api_key"] = "must-never-be-read"
    with pytest.raises(ValueError):
        identity.parse_rehearsal_identities(values)
    values[0].pop("api_key")
    values[0]["provider_id"] = True
    with pytest.raises(ValueError):
        identity.parse_rehearsal_identities(values)
