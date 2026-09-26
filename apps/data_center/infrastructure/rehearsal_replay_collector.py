"""Collect offline unit/time replay evidence from one bounded live-provider capture."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from apps.data_center.application.market_provider_rehearsal import (
    rehearsal_digest,
    select_rehearsal_sample,
)

from .market_rehearsal_runner import (
    market_rehearsal_source_digest,
    verify_candidate_release_image,
)
from .rehearsal_identity import parse_rehearsal_identities, rehearsal_identities_digest
from .rehearsal_response_replay import (
    ReplayResponse,
    ReplayUnitContract,
    replay_retained_dataset,
    verify_response_digest,
)
from .rehearsal_response_store import RehearsalResponseContext, parse_validate_tushare_response

Dataset = Literal["equity.quote.snapshot", "equity.valuation.fact"]
DATASETS: tuple[Dataset, ...] = ("equity.quote.snapshot", "equity.valuation.fact")


@dataclass(frozen=True)
class _PolicyEvidence:
    """Validated canonical publication policy bound to replay evidence."""

    snapshot: dict[str, object]
    identity: str
    content_sha256: str
    minimum_coverage_ratio: float


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("REHEARSAL_REPLAY_INPUT_INVALID")
    return cast(dict[str, object], value)


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("REHEARSAL_REPLAY_INPUT_LIMIT")
    return data


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("REHEARSAL_REPLAY_INPUT_INVALID")
    return value


def _clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("REHEARSAL_REPLAY_CLOCK_INVALID")
    return parsed.astimezone(UTC)


def _strings(value: object, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError("REHEARSAL_REPLAY_SCOPE_INVALID")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError("REHEARSAL_REPLAY_SCOPE_INVALID")
    return tuple(cast(list[str], value))


def _policy_evidence(value: object) -> _PolicyEvidence:
    """Validate canonical policy content, recompute its digest and derive its identity."""

    snapshot = _object(value)
    if set(snapshot) != {"content", "content_sha256", "identity"}:
        raise ValueError("REHEARSAL_REPLAY_POLICY_INVALID")
    content = _object(snapshot.get("content"))
    expected_keys = {
        "encoding",
        "dataset_key",
        "contract_version",
        "schema_version",
        "policy_version",
        "minimum_coverage_ratio",
        "allow_partial",
        "conflict_action",
        "required_evidence",
        "retention_days",
    }
    ratio = content.get("minimum_coverage_ratio")
    evidence = content.get("required_evidence")
    version = content.get("policy_version")
    contract_version = content.get("contract_version")
    schema_version = content.get("schema_version")
    if (
        set(content) != expected_keys
        or content.get("encoding") != "publication-policy-v1"
        or content.get("dataset_key") != "equity.valuation.fact"
        or not isinstance(contract_version, str)
        or not contract_version.strip()
        or not isinstance(schema_version, str)
        or not schema_version.strip()
        or not isinstance(version, str)
        or not version
        or len(version) > 40
        or ":" in version
        or any(character.isspace() for character in version)
        or isinstance(ratio, bool)
        or not isinstance(ratio, (int, float))
        or not math.isfinite(float(ratio))
        or not 0 <= float(ratio) <= 1
        or type(content.get("allow_partial")) is not bool
        or content.get("conflict_action") not in {"block", "quarantine", "prefer_governed_source"}
        or not isinstance(evidence, list)
        or not evidence
        or any(not isinstance(item, str) or not item.strip() for item in evidence)
        or len(evidence) != len(set(evidence))
        or type(content.get("retention_days")) is not int
        or cast(int, content.get("retention_days")) <= 0
    ):
        raise ValueError("REHEARSAL_REPLAY_POLICY_INVALID")
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    identity = (
        f"{contract_version}:{schema_version}" if version == "legacy" else f"p2:{version}:{digest}"
    )
    if snapshot.get("content_sha256") != digest or snapshot.get("identity") != identity:
        raise ValueError("REHEARSAL_REPLAY_POLICY_INVALID")
    return _PolicyEvidence(
        snapshot=snapshot,
        identity=identity,
        content_sha256=digest,
        minimum_coverage_ratio=float(ratio),
    )


def _resolve_body(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.drive or "\\" in relative:
        raise ValueError("REHEARSAL_REPLAY_PATH_INVALID")
    resolved_root = root.resolve(strict=True)
    resolved = (resolved_root / path).resolve(strict=True)
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError("REHEARSAL_REPLAY_PATH_INVALID")
    return resolved


def _contracts(snapshot: dict[str, object], dataset: Dataset) -> tuple[ReplayUnitContract, ...]:
    values = _object(snapshot.get("datasets")).get(dataset)
    if not isinstance(values, list) or not values:
        raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_MISSING")
    contracts: list[ReplayUnitContract] = []
    for value in cast(list[object], values):
        record = _object(value)
        if set(record) != {"field", "raw_unit", "canonical_unit", "multiplier"}:
            raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
        multiplier = record["multiplier"]
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
            raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
        contracts.append(
            ReplayUnitContract(
                _text(record, "field"),
                _text(record, "raw_unit"),
                _text(record, "canonical_unit"),
                float(multiplier),
            )
        )
    return tuple(contracts)


def _write_json(path: Path, payload: object) -> dict[str, str]:
    body = (
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()
    with path.open("xb") as stream:
        stream.write(body)
    return {"path": path.name, "sha256": hashlib.sha256(body).hexdigest()}


def _same_number(left: object, right: object) -> bool:
    """Compare finite provider values without accepting booleans as numbers."""

    if left is None or right is None:
        return False
    if (
        isinstance(left, bool)
        or isinstance(right, bool)
        or not isinstance(left, (int, float))
        or not isinstance(right, (int, float))
    ):
        return False
    return (
        math.isfinite(float(left))
        and math.isfinite(float(right))
        and math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-9)
    )


def _verify_probe_replay_equivalence(
    *,
    probe_rows: list[object],
    results: Mapping[Dataset, dict[str, object]],
    sample: tuple[str, ...],
    target_trade_date: str,
    identities_by_role: Mapping[str, object],
) -> None:
    """Require the live probe facts to equal facts replayed from retained bytes."""

    probes_by_dataset = {
        cast(Dataset, _object(value).get("dataset")): _object(value) for value in probe_rows
    }
    for dataset in DATASETS:
        probe = probes_by_dataset.get(dataset)
        observations = results[dataset].get("observations")
        facts = probe.get("facts") if probe is not None else None
        if (
            probe is None
            or not isinstance(facts, list)
            or not isinstance(observations, list)
            or len(facts) != len(sample)
            or len(observations) != len(sample)
        ):
            raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")
        live_by_asset = {_text(_object(value), "asset_code"): _object(value) for value in facts}
        replay_by_asset = {
            _text(_object(value), "asset_code"): _object(value) for value in observations
        }
        if set(live_by_asset) != set(sample) or set(replay_by_asset) != set(sample):
            raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")
        role = "quote" if dataset == "equity.quote.snapshot" else "valuation"
        identity = identities_by_role[role]
        source = getattr(identity, "source", None)
        for asset_code in sample:
            live = live_by_asset[asset_code]
            replay = replay_by_asset[asset_code]
            units_value = replay.get("units")
            if not isinstance(units_value, list):
                raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")
            units = {_text(_object(value), "field"): _object(value) for value in units_value}
            if (
                live.get("source") != source
                or live.get("observed_at") != replay.get("source_observed_at")
                or live.get("fetched_at") != replay.get("response_completed_at")
            ):
                raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")
            if dataset == "equity.quote.snapshot":
                if set(units) != {"close", "vol", "amount"} or any(
                    not _same_number(live.get(live_field), units[unit_field].get("canonical"))
                    for live_field, unit_field in (
                        ("current_price", "close"),
                        ("volume", "vol"),
                        ("amount", "amount"),
                    )
                ):
                    raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")
            elif (
                live.get("val_date") != target_trade_date
                or live.get("available_at") != replay.get("response_completed_at")
                or live.get("raw_payload_hash") != replay.get("body_sha256")
                or set(units) != {"total_mv", "circ_mv"}
                or not _same_number(live.get("market_cap"), units["total_mv"].get("canonical"))
                or not _same_number(live.get("float_market_cap"), units["circ_mv"].get("canonical"))
            ):
                raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")


def collect_response_replay(
    *,
    probe_path: Path,
    expected_probe_sha256: str,
    unit_contract_path: Path,
    expected_unit_contract_sha256: str,
    candidate_sha: str,
    target_trade_date: str,
    source_root: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Replay retained bytes without provider, credential, task, or database calls.

    All result files are new. Any failure leaves no success report; partial evidence
    remains for diagnosis and cannot be promoted by the release validator.
    """
    if output_dir.exists():
        raise ValueError("REHEARSAL_REPLAY_OUTPUT_EXISTS")
    probe_bytes = _read(probe_path, 4_000_000)
    unit_bytes = _read(unit_contract_path, 64_000)
    verify_response_digest(probe_bytes, expected_probe_sha256)
    verify_response_digest(unit_bytes, expected_unit_contract_sha256)
    probe = _object(json.loads(probe_bytes))
    units = _object(json.loads(unit_bytes))
    source_digest = market_rehearsal_source_digest(source_root)
    source_attestation, candidate_image_id = verify_candidate_release_image(
        source_root, candidate_sha
    )
    if (
        probe.get("schema") != "market.provider-rehearsal.v1"
        or probe.get("outcome") != "success"
        or probe.get("mode") != "read_only_live_provider"
        or probe.get("database_read_only") is not True
        or probe.get("response_retention_enabled") is not True
        or probe.get("source_unchanged") is not True
        or probe.get("source_tree_sha256") != source_digest
        or probe.get("candidate_source_attestation") != source_attestation
        or probe.get("candidate_image_id") != candidate_image_id
        or probe.get("candidate_sha") != candidate_sha
        or probe.get("target_trade_date") != target_trade_date
        or type(probe.get("stored")) is not int
        or probe.get("stored") != 0
        or probe.get("publication_updated") is not False
    ):
        raise ValueError("REHEARSAL_REPLAY_PROBE_INVALID")
    identities = parse_rehearsal_identities(probe.get("provider_identities"))
    identities_by_role = {identity.role: identity for identity in identities}
    identity_digest = rehearsal_identities_digest(identities)
    if probe.get("provider_identities_sha256") != identity_digest:
        raise ValueError("REHEARSAL_REPLAY_CONTEXT_MISMATCH")
    universe = _strings(probe.get("asset_codes"))
    if universe != tuple(sorted(set(universe))) or probe.get("universe_count") != len(universe):
        raise ValueError("REHEARSAL_REPLAY_SCOPE_INVALID")
    universe_digest = rehearsal_digest(universe)
    eligible = _strings(probe.get("eligible_asset_codes"))
    excluded = _strings(probe.get("excluded_asset_codes"), allow_empty=True)
    missing_valuation_codes = _strings(
        probe.get("valuation_missing_target_session_codes"), allow_empty=True
    )
    policy = _policy_evidence(probe.get("valuation_policy_snapshot"))
    minimum_ratio = probe.get("valuation_minimum_coverage_ratio")
    if (
        eligible != tuple(sorted(set(eligible)))
        or excluded != tuple(sorted(set(excluded)))
        or set(eligible) & set(excluded)
        or not set(eligible).issubset(set(universe))
        or not set(excluded).issubset(set(universe))
        or probe.get("eligible_asset_count") != len(eligible)
        or probe.get("excluded_asset_count") != len(excluded)
        or probe.get("valuation_policy_identity") != policy.identity
        or probe.get("valuation_policy_sha256") != policy.content_sha256
        or isinstance(minimum_ratio, bool)
        or not isinstance(minimum_ratio, (int, float))
        or float(minimum_ratio) != policy.minimum_coverage_ratio
    ):
        raise ValueError("REHEARSAL_REPLAY_ELIGIBLE_SCOPE_INVALID")
    if eligible != universe or excluded or missing_valuation_codes:
        raise ValueError("REHEARSAL_REPLAY_VALUATION_SCOPE_INCOMPLETE")
    sample_size = probe.get("sample_size")
    if isinstance(sample_size, bool) or not isinstance(sample_size, int):
        raise ValueError("REHEARSAL_REPLAY_SCOPE_INVALID")
    sample = select_rehearsal_sample(eligible, sample_size)
    if (
        probe.get("universe_sha256") != universe_digest
        or _strings(probe.get("sample")) != sample
        or probe.get("sample_sha256") != rehearsal_digest(sample)
    ):
        raise ValueError("REHEARSAL_REPLAY_SCOPE_INVALID")
    if (
        units.get("schema") != "release.provider-unit-contract.v1"
        or units.get("candidate_sha") != candidate_sha
        or units.get("provider_identities_sha256") != identity_digest
    ):
        raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
    # Frozen contract content is separately hash-bound; its provenance is not fabricated here.
    _text(units, "source_reference")
    if set(_object(units.get("datasets"))) != set(DATASETS):
        raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")
    started = _clock(_text(probe, "started_at"))
    finished = _clock(_text(probe, "finished_at"))
    if started > finished or finished > datetime.now(UTC):
        raise ValueError("REHEARSAL_REPLAY_CLOCK_INVALID")
    receipts = _object(probe.get("transport")).get("receipts")
    if not isinstance(receipts, list) or not receipts or len(receipts) > 200:
        raise ValueError("REHEARSAL_REAL_RESPONSE_MISSING")
    probe_rows = probe.get("probes")
    if not isinstance(probe_rows, list) or len(probe_rows) != 2:
        raise ValueError("REHEARSAL_REPLAY_PROBE_INVALID")
    expected_indexes: dict[int, Dataset] = {}
    observed_datasets: set[str] = set()
    live_facts: dict[Dataset, dict[str, dict[str, object]]] = {}
    for value in cast(list[object], probe_rows):
        row = _object(value)
        dataset_value = row.get("dataset")
        indexes = row.get("receipt_indexes")
        if (
            dataset_value not in DATASETS
            or row.get("outcome") != "success"
            or not isinstance(indexes, list)
            or not indexes
        ):
            raise ValueError("REHEARSAL_REPLAY_PROBE_INVALID")
        dataset = cast(Dataset, dataset_value)
        if dataset in observed_datasets:
            raise ValueError("REHEARSAL_REPLAY_PROBE_INVALID")
        observed_datasets.add(dataset)
        facts_value = row.get("facts")
        if not isinstance(facts_value, list):
            raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")
        facts_by_asset = {
            _text(_object(fact), "asset_code"): _object(fact)
            for fact in cast(list[object], facts_value)
        }
        if len(facts_by_asset) != len(facts_value) or set(facts_by_asset) != set(sample):
            raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")
        live_facts[dataset] = facts_by_asset
        for index in cast(list[object], indexes):
            if (
                type(index) is not int
                or index < 0
                or index >= len(receipts)
                or index in expected_indexes
            ):
                raise ValueError("REHEARSAL_REPLAY_PROBE_INVALID")
            expected_indexes[index] = dataset
    grouped: dict[Dataset, list[ReplayResponse]] = {dataset: [] for dataset in DATASETS}
    retained: dict[Dataset, list[tuple[str, bytes, str]]] = {dataset: [] for dataset in DATASETS}
    seen_paths: set[str] = set()
    total_bytes = 0
    for index, value in enumerate(cast(list[object], receipts)):
        receipt = _object(value)
        artifact_value = receipt.get("response_artifact")
        if artifact_value is None:
            if index in expected_indexes:
                raise ValueError("REHEARSAL_REAL_RESPONSE_MISSING")
            continue  # Authoritative calendar transport is intentionally outside raw retention.
        ref = _object(artifact_value)
        dataset_value = ref.get("dataset")
        if dataset_value not in DATASETS:
            raise ValueError("REHEARSAL_REPLAY_CONTEXT_MISMATCH")
        dataset = cast(Dataset, dataset_value)
        if expected_indexes.get(index) != dataset:
            raise ValueError("REHEARSAL_REPLAY_RECEIPT_MISMATCH")
        identity = identities_by_role["quote" if dataset == DATASETS[0] else "valuation"]
        artifact_context = RehearsalResponseContext(
            candidate_sha=candidate_sha,
            target_trade_date=target_trade_date,
            universe_sha256=universe_digest,
            provider_identities_sha256=identity_digest,
            provider_id=identity.provider_id,
            provider_source=identity.source,
            endpoint_id=identity.endpoint_id,
            dataset=dataset,
            sample_codes=universe if dataset == "equity.valuation.fact" else sample,
        )
        if ref.get("schema") != "release.provider-response-artifact-ref.v1" or any(
            ref.get(key) != (list(expected) if isinstance(expected, tuple) else expected)
            for key, expected in asdict(artifact_context).items()
        ):
            raise ValueError("REHEARSAL_REPLAY_CONTEXT_MISMATCH")
        if (
            ref.get("receipt_index") != index
            or type(ref.get("receipt_index")) is not int
            or receipt.get("error_code") != ""
            or type(receipt.get("status_code")) is not int
            or receipt.get("status_code") != 200
        ):
            raise ValueError("REHEARSAL_REPLAY_RECEIPT_INVALID")
        for key in (
            "host",
            "path_sha256",
            "method",
            "started_at",
            "finished_at",
            "status_code",
            "body_sha256",
            "body_bytes",
        ):
            if receipt.get(key) != ref.get(key):
                raise ValueError("REHEARSAL_REPLAY_RECEIPT_MISMATCH")
        response_started = _clock(_text(ref, "started_at"))
        response_finished = _clock(_text(ref, "finished_at"))
        if not started <= response_started <= response_finished <= finished:
            raise ValueError("REHEARSAL_REPLAY_CLOCK_INVALID")
        relative = _text(ref, "path")
        if relative in seen_paths:
            raise ValueError("REHEARSAL_REPLAY_DUPLICATE_RECEIPT")
        seen_paths.add(relative)
        body = _read(_resolve_body(probe_path.parent, relative), 8_000_000)
        total_bytes += len(body)
        if total_bytes > 32_000_000 or ref.get("body_bytes") != len(body):
            raise ValueError("REHEARSAL_REPLAY_INPUT_LIMIT")
        body_hash = _text(ref, "body_sha256")
        verify_response_digest(body, body_hash)
        target_compact = target_trade_date.replace("-", "")
        response_assets = {
            str(row["ts_code"])
            for row in parse_validate_tushare_response(body, artifact_context)
            if row.get("ts_code") in sample and row.get("trade_date") == target_compact
        }
        normalization_clocks = {
            _clock(_text(live_facts[dataset][asset_code], "fetched_at"))
            for asset_code in response_assets
        }
        if not response_assets or len(normalization_clocks) != 1:
            raise ValueError("REHEARSAL_REPLAY_LIVE_FACT_MISMATCH")
        normalization_completed = next(iter(normalization_clocks))
        if not response_finished <= normalization_completed <= finished:
            raise ValueError("REHEARSAL_REPLAY_CLOCK_INVALID")
        replay_context = replace(artifact_context, sample_codes=sample)
        grouped[dataset].append(
            ReplayResponse(
                replay_context,
                body,
                body_hash,
                response_finished,
                normalization_completed,
            )
        )
        retained[dataset].append((relative, body, body_hash))
    results: dict[Dataset, dict[str, object]] = {
        dataset: replay_retained_dataset(grouped[dataset], _contracts(units, dataset))
        for dataset in DATASETS
    }
    _verify_probe_replay_equivalence(
        probe_rows=cast(list[object], probe_rows),
        results=results,
        sample=sample,
        target_trade_date=target_trade_date,
        identities_by_role=identities_by_role,
    )
    # Verify unchanged source and inputs again before creating any success evidence.
    if (
        market_rehearsal_source_digest(source_root) != source_digest
        or _read(probe_path, 4_000_000) != probe_bytes
        or _read(unit_contract_path, 64_000) != unit_bytes
    ):
        raise ValueError("REHEARSAL_REPLAY_SOURCE_CHANGED")
    final_attestation, final_image_id = verify_candidate_release_image(source_root, candidate_sha)
    if final_attestation != source_attestation or final_image_id != candidate_image_id:
        raise ValueError("REHEARSAL_CANDIDATE_IMAGE_CHANGED")
    output_dir.mkdir(parents=True, exist_ok=False)
    common: dict[str, object] = {
        "candidate_sha": candidate_sha,
        "candidate_image_id": candidate_image_id,
        "candidate_source_attestation": source_attestation,
        "target_trade_date": target_trade_date,
        "universe_sha256": universe_digest,
        "provider_identities_sha256": identity_digest,
        "eligible_asset_count": len(eligible),
        "eligible_asset_codes": list(eligible),
        "excluded_asset_count": len(excluded),
        "excluded_asset_codes": list(excluded),
        "valuation_missing_target_session_codes": list(missing_valuation_codes),
        "valuation_policy_identity": policy.identity,
        "valuation_policy_sha256": policy.content_sha256,
        "valuation_policy_snapshot": policy.snapshot,
        "valuation_minimum_coverage_ratio": policy.minimum_coverage_ratio,
        "outcome": "success",
    }
    receipt_refs: list[dict[str, str]] = []
    for dataset in DATASETS:
        role = "quote" if dataset == "equity.quote.snapshot" else "valuation"
        identity = identities_by_role[role]
        operation = "daily" if role == "quote" else "daily_basic"
        response_scope = "full_market_trade_date"
        references: list[dict[str, object]] = []
        for name, body, body_hash in retained[dataset]:
            (output_dir / name).parent.mkdir(parents=True, exist_ok=True)
            with (output_dir / name).open("xb") as stream:
                stream.write(body)
            references.append(
                {
                    "path": name,
                    "sha256": body_hash,
                    "dataset": dataset,
                    "role": role,
                    "provider_id": identity.provider_id,
                    "provider_source": identity.source,
                    "provider_version": identity.version,
                    "endpoint_id": identity.endpoint_id,
                    "operation": operation,
                    "response_scope": response_scope,
                }
            )
        receipt_report: dict[str, object] = {
            **common,
            **results[dataset],
            "schema": "release.real-provider-response-replay.v2",
            "source_observed_at": _text(
                cast(dict[str, object], cast(list[object], results[dataset]["observations"])[0]),
                "source_observed_at",
            ),
            "response_body": references[0],
            "response_bodies": references,
            "response_set_scope": "all_retained_responses_for_dataset",
            "unit_contract_sha256": expected_unit_contract_sha256,
            "unit_contract": {
                "path": "unit-contract.json",
                "sha256": expected_unit_contract_sha256,
            },
        }
        name = "quote-replay.json" if dataset == DATASETS[0] else "valuation-replay.json"
        receipt_refs.append(_write_json(output_dir / name, receipt_report))
    with (output_dir / "probe-capture.json").open("xb") as stream:
        stream.write(probe_bytes)
    with (output_dir / "unit-contract.json").open("xb") as stream:
        stream.write(unit_bytes)
    report: dict[str, object] = {
        **common,
        "schema": "release.real-response-unit-replay.v1",
        "kind": "real_response_unit_replay",
        "evidence_mode": "real_provider",
        "provider_identities": [asdict(identity) for identity in identities],
        "source_tree_sha256": source_digest,
        "candidate_source_attestation": source_attestation,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "replayed_at": datetime.now(UTC).isoformat(),
        "probe_sha256": expected_probe_sha256,
        "probe_capture": {
            "path": "probe-capture.json",
            "sha256": expected_probe_sha256,
        },
        "unit_contract_sha256": expected_unit_contract_sha256,
        "units_verified": True,
        "source_time_verified": True,
        "replay_case_count": sum(
            len(cast(list[object], result["case_results"])) for result in results.values()
        ),
        "response_artifacts": receipt_refs,
        "release_ready": False,
        "remaining_release_gates": [
            "full_universe_capacity",
            "isolated_write_rehearsal",
            "candidate_regression_evidence",
        ],
    }
    if market_rehearsal_source_digest(source_root) != source_digest:
        raise ValueError("REHEARSAL_REPLAY_SOURCE_CHANGED")
    _write_json(output_dir / "real-response-unit-replay.json", report)
    return report
