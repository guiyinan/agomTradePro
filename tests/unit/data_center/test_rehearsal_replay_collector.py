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
IMAGE_ID = f"sha256:{'d' * 64}"
SAMPLE = ("000001.SZ", "600000.SH")
FINISHED = datetime(2026, 9, 24, 8, 0, 1, tzinfo=UTC)
NORMALIZED = datetime(2026, 9, 24, 8, 0, 1, 1000, tzinfo=UTC)


def _validated_capacity(
    validator: ModuleType,
    policy_snapshot: dict[str, object],
    *,
    registered_asset_codes: tuple[str, ...] = SAMPLE,
    eligible_asset_codes: tuple[str, ...] = SAMPLE,
    excluded_asset_codes: tuple[str, ...] = (),
    excluded_asset_reasons: tuple[tuple[str, str], ...] = (),
    valuation_missing_asset_codes: tuple[str, ...] = (),
    valuation_missing_reasons: tuple[tuple[str, str], ...] = (),
) -> object:
    """Build complete capacity evidence for release replay contract tests."""

    assert not set(eligible_asset_codes) & set(excluded_asset_codes)
    assert set(eligible_asset_codes) | set(excluded_asset_codes) == set(registered_asset_codes)
    assert excluded_asset_reasons == tuple(
        (code, validator.QUOTE_FULL_DAY_SUSPENSION_REASON) for code in excluded_asset_codes
    )
    assert valuation_missing_reasons == tuple(
        (code, "valuation_source_data_unavailable") for code in valuation_missing_asset_codes
    )
    return validator._ValidatedCapacityEvidence(
        registered_asset_codes=registered_asset_codes,
        eligible_asset_codes=eligible_asset_codes,
        excluded_asset_codes=excluded_asset_codes,
        excluded_asset_reasons=excluded_asset_reasons,
        valuation_missing_asset_codes=valuation_missing_asset_codes,
        valuation_missing_reasons=valuation_missing_reasons,
        policy=validator._validated_policy_evidence(policy_snapshot),
    )


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


def _body(
    dataset: str,
    *,
    extra_asset: bool = True,
    asset_codes: tuple[str, ...] | None = None,
) -> bytes:
    fields = (
        ["ts_code", "trade_date", "close", "pre_close", "vol", "amount"]
        if "quote" in dataset
        else ["ts_code", "trade_date", "total_mv", "circ_mv", "pe_ttm", "pb"]
    )
    selected_codes = SAMPLE if asset_codes is None else asset_codes
    rows = [
        (
            [code, "20260924", 12.5, 12.0, 100.5, 2_000.25]
            if "quote" in dataset
            else [code, "20260924", 300.0, 200.0, 8.0, 1.2]
        )
        for code in selected_codes
    ]
    if extra_asset:
        rows.append(["600001.SH", *rows[0][1:]])
    return json.dumps({"code": 0, "msg": None, "data": {"fields": fields, "items": rows}}).encode()


def _tencent_body(asset_codes: tuple[str, ...], *, timestamp: str = "20260924150000") -> bytes:
    lines: list[str] = []
    for asset_code in asset_codes:
        numeric, exchange = asset_code.split(".", 1)
        prefix = {"SZ": "sz", "SH": "sh", "BJ": "bj"}[exchange]
        fields = [""] * 47
        fields[1] = "测试证券"
        fields[2] = numeric
        fields[30] = timestamp
        fields[39] = "8.0"
        fields[44] = "200.0"
        fields[45] = "300.0"
        fields[46] = "1.2"
        lines.append(f'v_{prefix}{numeric}="{"~".join(fields)}";')
    return ("\n".join(lines) + "\n").encode("gb18030")


def _identities(modules, *, valuation_source: str = "tushare"):
    return modules["rehearsal_identity"].parse_rehearsal_identities(
        [
            {
                "role": role,
                "provider_id": index + 1,
                "source": valuation_source if role == "valuation" else "tushare",
                "version": "fixture-v1",
                "endpoint_id": "fixture-primary",
            }
            for index, role in enumerate(("quote", "valuation"))
        ]
    )


def _context(
    modules,
    dataset,
    *,
    universe=SAMPLE,
    sample_codes=SAMPLE,
    valuation_source: str = "tushare",
):
    identities = _identities(modules, valuation_source=valuation_source)
    is_tencent = "valuation" in dataset and valuation_source == "tencent"
    return modules["rehearsal_response_store"].RehearsalResponseContext(
        candidate_sha=CANDIDATE,
        target_trade_date=DATE,
        universe_sha256=modules["rehearsal_replay_collector"].rehearsal_digest(universe),
        provider_identities_sha256=modules["rehearsal_identity"].rehearsal_identities_digest(
            identities
        ),
        provider_id=1 if "quote" in dataset else 2,
        provider_source="tencent" if is_tencent else "tushare",
        endpoint_id="fixture-primary",
        dataset=dataset,
        sample_codes=sample_codes,
        provider_format="tencent_quote_batch.v1" if is_tencent else "tushare_pro_table.v1",
    )


def _contracts(modules, dataset, *, valuation_source: str = "tushare"):
    cls = modules["rehearsal_response_replay"].ReplayUnitContract
    return (
        (
            cls("close", "CNY_per_share", "CNY_per_share", 1.0),
            cls("vol", "lot", "share", 100.0),
            cls("amount", "thousand_CNY", "CNY", 1000.0),
        )
        if "quote" in dataset
        else (
            (
                cls("total_mv", "亿元", "元", 100_000_000.0),
                cls("circ_mv", "亿元", "元", 100_000_000.0),
            )
            if valuation_source == "tencent"
            else (
                cls("total_mv", "万元", "元", 10000.0),
                cls("circ_mv", "万元", "元", 10000.0),
            )
        )
    )


def _policy_evidence(*, allow_partial=True, minimum_coverage_ratio=0.5, policy_version="fixture"):
    content = {
        "encoding": "publication-policy-v1",
        "dataset_key": "equity.valuation.fact",
        "contract_version": "1.0",
        "schema_version": "1.0",
        "policy_version": policy_version,
        "minimum_coverage_ratio": minimum_coverage_ratio,
        "allow_partial": allow_partial,
        "conflict_action": "block",
        "required_evidence": ["source"],
        "retention_days": 30,
    }
    content_hash = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "content": content,
        "content_sha256": content_hash,
        "identity": (
            "1.0:1.0" if policy_version == "legacy" else f"p2:{policy_version}:{content_hash}"
        ),
    }


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


def test_quote_replay_rejects_missing_volume_and_amount_witnesses(modules):
    replay = modules["rehearsal_response_replay"]
    payload = json.loads(_body("equity.quote.snapshot"))
    fields = payload["data"]["fields"]
    payload["data"]["fields"] = fields[:4]
    payload["data"]["items"] = [row[:4] for row in payload["data"]["items"]]
    body = json.dumps(payload).encode()
    response = replay.ReplayResponse(
        _context(modules, "equity.quote.snapshot"),
        body,
        hashlib.sha256(body).hexdigest(),
        FINISHED,
    )

    with pytest.raises(ValueError, match="REHEARSAL_REPLAY_UNIT_WITNESS_MISSING"):
        replay.replay_retained_dataset([response], _contracts(modules, "equity.quote.snapshot"))


def _fixture(
    modules,
    tmp_path,
    monkeypatch,
    *,
    missing_asset: str | None = None,
    allow_partial: bool = True,
    minimum_coverage_ratio: float = 0.5,
    valuation_source: str = "tushare",
    policy_version: str = "fixture",
    include_missing_old_tencent_row: bool = False,
    include_out_of_target_asset: bool = False,
):
    collector = modules["rehearsal_replay_collector"]
    source = tmp_path / "source"
    source.mkdir()
    for name in ("apps", "core", "shared"):
        (source / name).mkdir()
        (source / name / "fixture.py").write_text("# synthetic source fixture\n")
    for name in ("pyproject.toml", "requirements-prod.txt"):
        (source / name).write_text("# synthetic manifest\n")
    (source / ".agom-build-identity.json").write_text(
        json.dumps({"schema_version": 1, "source_commit": CANDIDATE}) + "\n"
    )
    image_id = IMAGE_ID
    manifest = source / ".agom-release-manifest.json"
    manifest.write_text(json.dumps({"source_commit": CANDIDATE, "image_id": image_id}) + "\n")
    monkeypatch.setenv("AGOM_RELEASE_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("AGOM_CANDIDATE_IMAGE_ID", image_id)
    capture = tmp_path / "capture"
    capture.mkdir()
    store = modules["rehearsal_response_store"].RehearsalResponseStore(
        capture, max_responses=2, max_response_bytes=10000, max_total_bytes=20000
    )
    universe = tuple(sorted((*SAMPLE, missing_asset))) if missing_asset else SAMPLE
    quote_sample = universe
    valuation_available = tuple(code for code in universe if code != missing_asset)
    valuation_sample = valuation_available
    receipts = []
    probes = []
    for index, dataset in enumerate(collector.DATASETS):
        is_quote = dataset == "equity.quote.snapshot"
        dataset_sample = quote_sample if is_quote else valuation_sample
        ref = store.persist_response(
            _context(
                modules,
                dataset,
                universe=universe,
                sample_codes=universe if not is_quote else quote_sample,
                valuation_source=valuation_source,
            ),
            receipt_index=index,
            host="fixture.invalid",
            path_sha256="b" * 64,
            method="POST",
            started_at="2026-09-24T08:00:00+00:00",
            finished_at=FINISHED.isoformat(),
            status_code=200,
            response_body=(
                _tencent_body(dataset_sample)
                + (
                    _tencent_body(
                        (missing_asset,),
                        timestamp="20260923150000",
                    )
                    if include_missing_old_tencent_row and missing_asset is not None
                    else b""
                )
                if not is_quote and valuation_source == "tencent"
                else _body(
                    dataset,
                    extra_asset=include_out_of_target_asset,
                    asset_codes=dataset_sample if not is_quote or missing_asset else None,
                )
            ),
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
        for asset_code in dataset_sample:
            fact = {
                "asset_code": asset_code,
                "source": (
                    "tencent" if not is_quote and valuation_source == "tencent" else "tushare"
                ),
                "observed_at": observed_at,
                "fetched_at": NORMALIZED.isoformat(),
            }
            if "quote" in dataset:
                fact.update({"current_price": 12.5, "volume": 10_050.0, "amount": 2_000_250.0})
            else:
                fact.update(
                    {
                        "val_date": DATE,
                        "pe_ttm": 8.0,
                        "pb": 1.2,
                        "market_cap": (
                            30_000_000_000.0 if valuation_source == "tencent" else 3_000_000.0
                        ),
                        "float_market_cap": (
                            20_000_000_000.0 if valuation_source == "tencent" else 2_000_000.0
                        ),
                        "available_at": NORMALIZED.isoformat(),
                        "raw_payload_hash": record["body_sha256"],
                    }
                )
            facts.append(fact)
        probe_row = {
            "dataset": dataset,
            "outcome": "success",
            "receipt_indexes": [index],
            "facts": facts,
        }
        if is_quote:
            probe_row.update(
                {
                    "requested": len(quote_sample),
                    "succeeded": len(quote_sample),
                    "failed": 0,
                }
            )
        else:
            missing_codes = [] if missing_asset is None else [missing_asset]
            returned_count = len(universe) - len(missing_codes)
            valuation_outcome = "partial" if missing_codes else "success"
            missing_reasons = [
                {
                    "asset_code": code,
                    "reason_code": "valuation_source_data_unavailable",
                }
                for code in missing_codes
            ]
            probe_row.update(
                {
                    "outcome": valuation_outcome,
                    "count_unit": "registered_asset",
                    "requested": len(universe),
                    "succeeded": returned_count,
                    "failed": len(missing_codes),
                    "valuation_coverage_ratio": returned_count / len(universe),
                    "valuation_policy_identity": "",
                    "valuation_minimum_coverage_ratio": minimum_coverage_ratio,
                    "valuation_missing_target_session_codes": missing_codes,
                    "valuation_missing_target_session_reasons": missing_reasons,
                    "issues": [
                        {"asset_code": item["asset_code"], "code": item["reason_code"]}
                        for item in missing_reasons
                    ],
                }
            )
        probes.append(probe_row)
    identities = _identities(modules, valuation_source=valuation_source)
    digest = modules["rehearsal_identity"].rehearsal_identities_digest(identities)
    policy = _policy_evidence(
        allow_partial=allow_partial,
        minimum_coverage_ratio=minimum_coverage_ratio,
        policy_version=policy_version,
    )
    missing_codes = [] if missing_asset is None else [missing_asset]
    returned_count = len(universe) - len(missing_codes)
    valuation_outcome = "partial" if missing_codes else "success"
    missing_reasons = [
        {"asset_code": code, "reason_code": "valuation_source_data_unavailable"}
        for code in missing_codes
    ]
    probes[1].update(
        {
            "valuation_policy_identity": policy["identity"],
            "valuation_minimum_coverage_ratio": minimum_coverage_ratio,
            "valuation_coverage_ratio": returned_count / len(universe),
            "valuation_missing_target_session_codes": missing_codes,
            "valuation_missing_target_session_reasons": missing_reasons,
            "issues": [
                {"asset_code": item["asset_code"], "code": item["reason_code"]}
                for item in missing_reasons
            ],
        }
    )
    probe = {
        "schema": "market.provider-rehearsal.v1",
        "outcome": "success",
        "mode": "read_only_live_provider",
        "database_read_only": True,
        "response_retention_enabled": True,
        "source_unchanged": True,
        "source_tree_sha256": collector.market_rehearsal_source_digest(source),
        "candidate_source_attestation": "image_release_manifest",
        "candidate_image_id": image_id,
        "candidate_sha": CANDIDATE,
        "target_trade_date": DATE,
        "stored": 0,
        "publication_updated": False,
        "provider_identities": [asdict(identity) for identity in identities],
        "provider_identities_sha256": digest,
        "asset_codes": list(universe),
        "universe_count": len(universe),
        "universe_sha256": collector.rehearsal_digest(universe),
        "eligible_asset_codes": list(universe),
        "eligible_asset_count": len(universe),
        "excluded_asset_codes": [],
        "excluded_asset_count": 0,
        "valuation_missing_target_session_codes": missing_codes,
        "valuation_missing_target_session_reasons": missing_reasons,
        "valuation_policy_identity": policy["identity"],
        "valuation_policy_sha256": policy["content_sha256"],
        "valuation_policy_snapshot": policy,
        "valuation_minimum_coverage_ratio": minimum_coverage_ratio,
        "valuation_coverage_ratio": returned_count / len(universe),
        "valuation_requested_count": len(universe),
        "valuation_returned_count": returned_count,
        "valuation_outcome": valuation_outcome,
        "valuation_sample": list(valuation_sample),
        "valuation_sample_sha256": collector.rehearsal_digest(valuation_sample),
        "sample": list(quote_sample),
        "sample_sha256": collector.rehearsal_digest(quote_sample),
        "sample_size": len(quote_sample),
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
            dataset: [
                asdict(contract)
                for contract in _contracts(
                    modules,
                    dataset,
                    valuation_source=valuation_source,
                )
            ]
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
    modules, tmp_path, monkeypatch
):
    from scripts import validate_release_rehearsal as validator

    collector = modules["rehearsal_replay_collector"]
    kwargs, probe = _fixture(modules, tmp_path, monkeypatch)
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
        expected_image_id=IMAGE_ID,
        expected_date=DATE,
        expected_universe=probe["universe_sha256"],
        expected_provider_digest=probe["provider_identities_sha256"],
        capacity=_validated_capacity(
            validator,
            probe["valuation_policy_snapshot"],
        ),
    )
    quote_receipt = json.loads(
        (kwargs["output_dir"] / "quote-replay.json").read_text(encoding="utf-8")
    )
    observation = quote_receipt["observations"][0]
    assert observation["transport_received_at"] == FINISHED.isoformat()
    assert observation["normalization_completed_at"] == NORMALIZED.isoformat()


def test_collector_classifies_provider_superset_without_expanding_target_scope(
    modules, tmp_path, monkeypatch
):
    collector = modules["rehearsal_replay_collector"]
    kwargs, _probe = _fixture(
        modules,
        tmp_path,
        monkeypatch,
        include_out_of_target_asset=True,
    )

    result = collector.collect_response_replay(**kwargs)

    assert result["outcome"] == "success"
    for name in ("quote-replay.json", "valuation-replay.json"):
        receipt = json.loads((kwargs["output_dir"] / name).read_text(encoding="utf-8"))
        assert receipt["observations"]
        assert {item["asset_code"] for item in receipt["observations"]} == set(SAMPLE)
        response = receipt["response_body"]
        assert response["response_asset_count"] == 3
        assert response["target_scope_asset_codes"] == list(SAMPLE)
        assert response["target_scope_asset_count"] == 2
        assert response["out_of_target_asset_codes"] == ["600001.SH"]
        assert response["out_of_target_asset_count"] == 1


def test_collector_replays_tencent_valuation_bytes_through_release_validator(
    modules, tmp_path, monkeypatch
):
    from scripts import validate_release_rehearsal as validator

    collector = modules["rehearsal_replay_collector"]
    kwargs, probe = _fixture(
        modules,
        tmp_path,
        monkeypatch,
        valuation_source="tencent",
    )
    result = collector.collect_response_replay(**kwargs)

    validator._validate_real_replay(
        result,
        kwargs["output_dir"],
        expected_candidate=CANDIDATE,
        expected_image_id=IMAGE_ID,
        expected_date=DATE,
        expected_universe=probe["universe_sha256"],
        expected_provider_digest=probe["provider_identities_sha256"],
        capacity=_validated_capacity(
            validator,
            probe["valuation_policy_snapshot"],
        ),
    )
    receipt = json.loads(
        (kwargs["output_dir"] / "valuation-replay.json").read_text(encoding="utf-8")
    )
    assert receipt["response_body"]["provider_format"] == "tencent_quote_batch.v1"
    assert receipt["response_body"]["operation"] == "tencent_quote_batch"
    assert receipt["response_body"]["response_asset_codes"] == list(SAMPLE)
    assert receipt["observations"][0]["units"][0]["multiplier"] == 100_000_000.0


@pytest.mark.parametrize(
    ("valuation_source", "include_missing_old_tencent_row"),
    [("tushare", False), ("tencent", True)],
)
def test_collector_accepts_policy_qualified_partial_valuation_scope(
    modules,
    tmp_path,
    monkeypatch,
    valuation_source,
    include_missing_old_tencent_row,
):
    from scripts import validate_release_rehearsal as validator

    collector = modules["rehearsal_replay_collector"]
    kwargs, _probe = _fixture(
        modules,
        tmp_path,
        monkeypatch,
        missing_asset="600001.SH",
        allow_partial=True,
        minimum_coverage_ratio=0.5,
        valuation_source=valuation_source,
        include_missing_old_tencent_row=include_missing_old_tencent_row,
    )
    result = collector.collect_response_replay(**kwargs)

    assert result["outcome"] == "success"
    assert result["eligible_asset_codes"] == [*SAMPLE, "600001.SH"]
    assert result["excluded_asset_codes"] == []
    assert result["valuation_missing_target_session_codes"] == ["600001.SH"]
    assert result["valuation_missing_target_session_reasons"] == [
        {
            "asset_code": "600001.SH",
            "reason_code": "valuation_source_data_unavailable",
        }
    ]
    assert result["valuation_outcome"] == "partial"
    quote_receipt = json.loads(
        (kwargs["output_dir"] / "quote-replay.json").read_text(encoding="utf-8")
    )
    valuation_receipt = json.loads(
        (kwargs["output_dir"] / "valuation-replay.json").read_text(encoding="utf-8")
    )
    assert quote_receipt["outcome"] == "success"
    assert quote_receipt["sampled_assets"] == [*SAMPLE, "600001.SH"]
    assert len(quote_receipt["observations"]) == 3
    assert valuation_receipt["outcome"] == "partial"
    assert valuation_receipt["requested"] == 3
    assert valuation_receipt["succeeded"] == 2
    assert valuation_receipt["failed"] == 1
    assert (
        valuation_receipt["valuation_missing_target_session_reasons"]
        == result["valuation_missing_target_session_reasons"]
    )
    validator._validate_real_replay(
        result,
        kwargs["output_dir"],
        expected_candidate=CANDIDATE,
        expected_image_id=IMAGE_ID,
        expected_date=DATE,
        expected_universe=_probe["universe_sha256"],
        expected_provider_digest=_probe["provider_identities_sha256"],
        capacity=_validated_capacity(
            validator,
            _probe["valuation_policy_snapshot"],
            registered_asset_codes=(*SAMPLE, "600001.SH"),
            eligible_asset_codes=(*SAMPLE, "600001.SH"),
            valuation_missing_asset_codes=("600001.SH",),
            valuation_missing_reasons=(("600001.SH", "valuation_source_data_unavailable"),),
        ),
    )


@pytest.mark.parametrize(
    ("allow_partial", "minimum_coverage_ratio", "policy_version"),
    [(False, 0.5, "fixture"), (True, 0.75, "fixture"), (True, 0.5, "legacy")],
)
def test_collector_blocks_partial_valuation_without_policy_coverage(
    modules,
    tmp_path,
    monkeypatch,
    allow_partial,
    minimum_coverage_ratio,
    policy_version,
):
    collector = modules["rehearsal_replay_collector"]
    kwargs, _probe = _fixture(
        modules,
        tmp_path,
        monkeypatch,
        missing_asset="600001.SH",
        allow_partial=allow_partial,
        minimum_coverage_ratio=minimum_coverage_ratio,
        policy_version=policy_version,
    )
    with pytest.raises(ValueError, match="REHEARSAL_REPLAY_ELIGIBLE_SCOPE_INVALID"):
        collector.collect_response_replay(**kwargs)
    assert not kwargs["output_dir"].exists()


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
        "live_valuation_pe_mismatch",
        "live_valuation_pb_mismatch",
        "output_exists",
    ],
)
def test_collector_failures_never_write_success_report(modules, tmp_path, monkeypatch, failure):
    collector = modules["rehearsal_replay_collector"]
    valuation_source = (
        "tencent"
        if failure in {"live_valuation_pe_mismatch", "live_valuation_pb_mismatch"}
        else "tushare"
    )
    kwargs, probe = _fixture(
        modules,
        tmp_path,
        monkeypatch,
        valuation_source=valuation_source,
    )
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
    elif failure == "live_valuation_pe_mismatch":
        probe["probes"][1]["facts"][0]["pe_ttm"] = 9.0
    elif failure == "live_valuation_pb_mismatch":
        probe["probes"][1]["facts"][0]["pb"] = 1.3
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
