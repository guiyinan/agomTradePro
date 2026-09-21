"""DATA-02 four-Publication numeric tolerance evidence contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from apps.data_center.application.data02_publication_tolerance_evidence import (
    Data02PublicationToleranceEvidenceError,
    data02_publication_tolerance_artifact_sha256,
    parse_data02_publication_tolerance_snapshot,
    serialize_data02_publication_tolerance_evidence,
)
from apps.data_center.application.publication_utils import publication_hash
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.numeric_tolerance import (
    NumericToleranceField,
    NumericTolerancePolicy,
    canonical_decimal_text,
)
from scripts.record_data02_publication_tolerance_evidence import (
    _write_append_only,
    record_data02_publication_tolerance_evidence,
)

CORE_DATASETS = (
    "equity.financial.fact",
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.valuation.fact",
)
CAPTURED_AT = "2026-09-21T16:00:00.000000Z"


def _universe_hash(*asset_codes: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "asset_codes": sorted(asset_codes),
                "schema": "active-a-share-universe.v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _snapshot_hash(dataset: dict[str, object], *, value_kind: str) -> str:
    comparisons = dataset["comparisons"]
    source = (
        dataset["reference_source"] if value_kind == "canonical" else dataset["observed_source"]
    )
    values = [
        {
            "field_name": comparison["field_name"],
            "natural_key": comparison["natural_key"],
            "unit": comparison["unit"],
            "value": canonical_decimal_text(
                comparison["canonical_value" if value_kind == "canonical" else "observed_value"],
                field_name="test_value",
            ),
        }
        for comparison in sorted(
            comparisons,
            key=lambda item: (item["natural_key"], item["field_name"]),
        )
    ]
    return hashlib.sha256(
        json.dumps(
            {
                "dataset_key": dataset["dataset_key"],
                "encoding": "data02-numeric-snapshot-v1",
                "source": source,
                "value_kind": value_kind,
                "values": values,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _refresh_snapshot_hashes(dataset: dict[str, object]) -> None:
    dataset["reference_snapshot_hash"] = _snapshot_hash(dataset, value_kind="canonical")
    dataset["observed_snapshot_hash"] = _snapshot_hash(dataset, value_kind="observed")


def _refresh_publication_identity(dataset: dict[str, object]) -> None:
    policy_identity = dataset["publication"]["policy_identity"]
    publication_hash_value = publication_hash(
        sorted(
            [_reference_from_payload(member) for member in dataset["members"]],
            key=lambda member: member.natural_key,
        ),
        policy_identity=policy_identity,
    )
    dataset["publication"]["publication_hash"] = publication_hash_value
    dataset["publication"]["publication_id"] = str(
        uuid5(
            NAMESPACE_URL,
            f"agomtradepro:{dataset['dataset_key']}:current:{publication_hash_value}",
        )
    )


def _publication_policy(dataset_key: str) -> tuple[PublicationPolicy, dict[str, object]]:
    policy = PublicationPolicy(
        dataset=DatasetKey(dataset_key, "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "payload_hash",
            "fact_content_hash",
            "source_record_id",
            "published_at",
            "raw_payload_hash",
            "raw_payload_scope",
        ),
        retention_days=3650,
        policy_version="3",
    )
    return policy, {
        "allow_partial": policy.allow_partial,
        "conflict_action": policy.conflict_action,
        "content_hash": policy.content_hash,
        "contract_version": policy.dataset.contract_version,
        "minimum_coverage_ratio": policy.minimum_coverage_ratio,
        "policy_version": policy.policy_version,
        "required_evidence": list(policy.required_evidence),
        "retention_days": policy.retention_days,
        "schema_version": policy.dataset.schema_version,
    }


def _tolerance_policy(dataset_key: str) -> tuple[NumericTolerancePolicy, dict[str, object]]:
    policy = NumericTolerancePolicy(
        dataset_key=dataset_key,
        policy_version="owner-approved-v1",
        rule="absolute_or_relative",
        fields=(
            NumericToleranceField(
                field_name="value",
                unit="canonical-unit",
                absolute_tolerance="0.01",
                relative_tolerance="0.001",
            ),
        ),
    )
    return policy, {
        "content_hash": policy.content_hash,
        "fields": [field.to_dict() for field in policy.fields],
        "identity": policy.identity,
        "policy_version": policy.policy_version,
        "rule": policy.rule,
    }


def _dataset_payload(dataset_key: str) -> dict[str, object]:
    publication_policy, publication_policy_payload = _publication_policy(dataset_key)
    _, tolerance_policy_payload = _tolerance_policy(dataset_key)
    suffix = CORE_DATASETS.index(dataset_key) + 1
    fact_table = "table_" + dataset_key.replace(".", "_")
    members = [
        PublicationFactReference(
            natural_key=f"00000{index}.SZ:latest:provider-{suffix}",
            source=f"provider-{suffix}",
            source_record_id=f"source-record-{suffix}-{index}",
            fact_table=fact_table,
            fact_pk=f"fact-{suffix}-{index}",
            observed_at=datetime(2026, 9, 21, 15, index, tzinfo=UTC),
            raw_payload_hash=hashlib.sha256(f"raw-payload:{suffix}:{index}".encode()).hexdigest(),
            quality_status="accepted",
            revision_number=1,
            available_at=datetime(2026, 9, 21, 15, index, tzinfo=UTC),
            fetched_at=datetime(2026, 9, 21, 15, index + 1, tzinfo=UTC),
            source_published_at=datetime(2026, 9, 21, 14, index, tzinfo=UTC),
            raw_payload_scope="record_response_body",
            fact_content_hash=hashlib.sha256(f"fact-content:{suffix}:{index}".encode()).hexdigest(),
        )
        for index in (1, 2)
    ]

    def member_payload(member: PublicationFactReference) -> dict[str, object]:
        return {
            "available_at": member.available_at.isoformat(),
            "fact_content_hash": member.fact_content_hash,
            "fact_pk": member.fact_pk,
            "fact_table": member.fact_table,
            "fetched_at": member.fetched_at.isoformat(),
            "natural_key": member.natural_key,
            "observed_at": member.observed_at.isoformat(),
            "quality_status": member.quality_status,
            "raw_payload_hash": member.raw_payload_hash,
            "raw_payload_scope": member.raw_payload_scope,
            "revision_number": member.revision_number,
            "source": member.source,
            "source_published_at": member.source_published_at.isoformat(),
            "source_record_id": member.source_record_id,
        }

    comparisons = [
        {
            "canonical_value": "100.00",
            "field_name": "value",
            "natural_key": members[0].natural_key,
            "observed_value": "100.009",
            "unit": "canonical-unit",
        },
        {
            "canonical_value": "200.00",
            "field_name": "value",
            "natural_key": members[1].natural_key,
            "observed_value": "200.10",
            "unit": "canonical-unit",
        },
    ]
    publication_hash_value = publication_hash(
        members,
        policy_identity=publication_policy.identity,
    )
    publication_id = str(
        uuid5(
            NAMESPACE_URL,
            f"agomtradepro:{dataset_key}:current:{publication_hash_value}",
        )
    )

    dataset = {
        "comparisons": comparisons,
        "dataset_key": dataset_key,
        "members": [member_payload(member) for member in members],
        "observed_at": CAPTURED_AT,
        "observed_snapshot_hash": "",
        "observed_source": f"provider-{suffix}",
        "publication": {
            "covered_asset_count": 2,
            "member_count": 2,
            "policy_identity": publication_policy.identity,
            "publication_hash": publication_hash_value,
            "publication_id": publication_id,
            "published_at": CAPTURED_AT,
        },
        "publication_policy": publication_policy_payload,
        "reference_snapshot_hash": "",
        "reference_source": f"canonical-{suffix}",
        "tolerance_policy": tolerance_policy_payload,
    }
    _refresh_snapshot_hashes(dataset)
    return dataset


def _payload() -> dict[str, object]:
    return {
        "candidate": {
            "commit": "a" * 40,
            "matrix_sha256": "b" * 64,
            "oci_revision": "sha256:" + "c" * 64,
            "version": "20260921.01",
        },
        "captured_at": CAPTURED_AT,
        "datasets": [_dataset_payload(dataset_key) for dataset_key in CORE_DATASETS],
        "read_mode": "select_only",
        "schema_version": "data02-four-publication-tolerance-input.v1",
        "universe": {
            "denominator": 2,
            "universe_hash": _universe_hash("000001.SZ", "000002.SZ"),
        },
    }


def _payload_bytes(payload: dict[str, object] | None = None) -> bytes:
    return json.dumps(payload or _payload(), sort_keys=True, separators=(",", ":")).encode()


def _registry_bytes() -> bytes:
    policies: list[dict[str, object]] = []
    for dataset_key in CORE_DATASETS:
        _, policy = _tolerance_policy(dataset_key)
        policies.append(
            {
                **policy,
                "approval": {
                    "approved_at": CAPTURED_AT,
                    "approved_by": "test-owner",
                    "receipt_sha256": "e" * 64,
                },
                "dataset_key": dataset_key,
            }
        )
    return json.dumps(
        {
            "policies": policies,
            "schema_version": "data02-numeric-tolerance-policy-registry.v1",
            "status": "active",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _reference_from_payload(payload: dict[str, object]) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=payload["natural_key"],
        source=payload["source"],
        source_record_id=payload["source_record_id"],
        fact_table=payload["fact_table"],
        fact_pk=payload["fact_pk"],
        observed_at=datetime.fromisoformat(payload["observed_at"]),
        raw_payload_hash=payload["raw_payload_hash"],
        quality_status=payload["quality_status"],
        revision_number=payload["revision_number"],
        available_at=datetime.fromisoformat(payload["available_at"]),
        fetched_at=datetime.fromisoformat(payload["fetched_at"]),
        source_published_at=datetime.fromisoformat(payload["source_published_at"]),
        raw_payload_scope=payload["raw_payload_scope"],
        fact_content_hash=payload["fact_content_hash"],
    )


def _parse(payload: dict[str, object] | None = None):
    return parse_data02_publication_tolerance_snapshot(
        _payload_bytes(payload),
        policy_registry_payload=_registry_bytes(),
    )


def test_four_publication_report_binds_policies_universe_units_and_deviations() -> None:
    report = parse_data02_publication_tolerance_snapshot(
        _payload_bytes(),
        policy_registry_payload=_registry_bytes(),
        as_of=datetime(2026, 9, 22, tzinfo=UTC),
    )
    decoded = json.loads(serialize_data02_publication_tolerance_evidence(report))

    assert report.reconciliation_passed is True
    assert report.breach_count == 0
    assert decoded["schema_version"] == "data02-four-publication-tolerance-evidence.v1"
    expected_universe_hash = _universe_hash("000001.SZ", "000002.SZ")
    assert decoded["universe"] == {
        "denominator": 2,
        "universe_hash": expected_universe_hash,
    }
    assert all(
        dataset["covered_asset_codes_hash"] == expected_universe_hash
        for dataset in decoded["datasets"]
    )
    assert [item["dataset_key"] for item in decoded["datasets"]] == list(CORE_DATASETS)
    assert decoded["datasets"][0]["publication_policy"]["identity"].startswith("p2:3:")
    assert decoded["datasets"][0]["tolerance_policy"]["identity"].startswith(
        "data02-tolerance-v1:owner-approved-v1:"
    )
    comparison = decoded["datasets"][0]["comparisons"][0]
    assert comparison["absolute_difference"] == "0.009"
    assert comparison["relative_difference"] == "0.00009"
    assert comparison["breached"] is False
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["runtime_enablement"] == "not_authorized"


def test_repository_publication_policy_order_is_accepted() -> None:
    payload = _payload()
    registry = json.loads(Path("governance/publication_policies.json").read_text(encoding="utf-8"))
    policies = {
        item["dataset_key"]: item
        for item in registry["policies"]
        if item["dataset_key"] in CORE_DATASETS
    }
    assert tuple(sorted(policies)) == CORE_DATASETS

    for dataset in payload["datasets"]:
        raw = policies[dataset["dataset_key"]]
        policy = PublicationPolicy(
            dataset=DatasetKey(dataset["dataset_key"], "1.0", "1.0"),
            minimum_coverage_ratio=raw["minimum_coverage_ratio"],
            allow_partial=raw["allow_partial"],
            conflict_action=raw["conflict_action"],
            required_evidence=tuple(raw["required_evidence"]),
            retention_days=raw["retention_days"],
            policy_version=raw["policy_version"],
        )
        dataset["publication_policy"] = {
            **raw,
            "content_hash": policy.content_hash,
            "contract_version": "1.0",
            "schema_version": "1.0",
        }
        dataset["publication_policy"].pop("dataset_key")
        dataset["publication"]["policy_identity"] = policy.identity
        _refresh_publication_identity(dataset)

    report = _parse(payload)

    assert [dataset.publication_policy.required_evidence for dataset in report.datasets] == [
        tuple(policies[dataset_key]["required_evidence"]) for dataset_key in CORE_DATASETS
    ]


def test_financial_member_count_can_differ_from_frozen_asset_denominator() -> None:
    payload = _payload()
    financial = payload["datasets"][0]
    third_member = dict(financial["members"][0])
    third_member.update(
        natural_key="000001.SZ:metric-2:provider-1",
        source_record_id="source-record-1-3",
        fact_pk="fact-1-3",
        raw_payload_hash=hashlib.sha256(b"raw-payload:1:3").hexdigest(),
        fact_content_hash=hashlib.sha256(b"fact-content:1:3").hexdigest(),
    )
    financial["members"].append(third_member)
    financial["comparisons"].append(
        {
            "canonical_value": "300",
            "field_name": "value",
            "natural_key": third_member["natural_key"],
            "observed_value": "300.01",
            "unit": "canonical-unit",
        }
    )
    financial["publication"]["member_count"] = 3
    _refresh_publication_identity(financial)
    _refresh_snapshot_hashes(financial)

    report = _parse(payload)

    assert report.reconciliation_passed is True
    assert report.datasets[0].member_count == 3
    assert report.datasets[0].covered_asset_count == 2


def test_breach_is_retained_without_turning_report_into_production_gate() -> None:
    payload = _payload()
    payload["datasets"][0]["comparisons"][0]["observed_value"] = "101.00"
    _refresh_snapshot_hashes(payload["datasets"][0])

    report = _parse(payload)
    decoded = report.to_dict()

    assert report.reconciliation_passed is False
    assert report.breach_count == 1
    assert decoded["datasets"][0]["breach_count"] == 1
    assert decoded["datasets"][0]["comparisons"][0]["breached"] is True
    assert decoded["production_ready"] is False


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda payload: payload.__setitem__("read_mode", "write"), "read_mode"),
        (lambda payload: payload["datasets"].pop(), "exactly the four core datasets"),
        (
            lambda payload: payload["datasets"][0]["publication"].__setitem__(
                "covered_asset_count", 1
            ),
            "frozen denominator",
        ),
        (
            lambda payload: payload["datasets"][0]["publication"].__setitem__(
                "policy_identity", "p2:forged:" + "0" * 64
            ),
            "publication policy identity",
        ),
        (
            lambda payload: payload["datasets"][0]["tolerance_policy"].__setitem__(
                "content_hash", "0" * 64
            ),
            "tolerance policy content_hash",
        ),
        (
            lambda payload: payload["datasets"][0]["comparisons"][0].__setitem__(
                "unit", "wrong-unit"
            ),
            "unit does not match",
        ),
    ],
)
def test_identity_scope_and_unit_drift_fail_closed(mutation, message: str) -> None:
    payload = _payload()
    mutation(payload)
    with pytest.raises(Data02PublicationToleranceEvidenceError, match=message):
        _parse(payload)


def test_every_publication_member_and_governed_field_must_be_compared_once() -> None:
    payload = _payload()
    payload["datasets"][0]["comparisons"].pop()
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="comparison coverage"):
        _parse(payload)

    payload = _payload()
    payload["datasets"][0]["comparisons"].append(dict(payload["datasets"][0]["comparisons"][0]))
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="unique"):
        _parse(payload)


def test_member_identity_substitution_cannot_reuse_publication_hash() -> None:
    payload = _payload()
    payload["datasets"][0]["members"][0]["fact_pk"] = "substituted-fact"

    with pytest.raises(Data02PublicationToleranceEvidenceError, match="Publication hash"):
        _parse(payload)


def test_member_evidence_and_fact_identity_are_validated_before_acceptance() -> None:
    payload = _payload()
    dataset = payload["datasets"][0]
    dataset["members"][0]["quality_status"] = "rejected"
    _refresh_publication_identity(dataset)

    with pytest.raises(Data02PublicationToleranceEvidenceError, match="not publishable"):
        _parse(payload)

    payload = _payload()
    dataset = payload["datasets"][0]
    dataset["members"][1]["fact_pk"] = dataset["members"][0]["fact_pk"]
    _refresh_publication_identity(dataset)

    with pytest.raises(Data02PublicationToleranceEvidenceError, match="fact identities"):
        _parse(payload)


def test_publication_id_and_numeric_snapshot_hashes_are_content_bound() -> None:
    payload = _payload()
    payload["datasets"][0]["publication"]["publication_id"] = "arbitrary-unique-id"
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="canonical current identity"):
        _parse(payload)

    payload = _payload()
    payload["datasets"][0]["comparisons"][0]["observed_value"] = "100.008"
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="snapshot hash"):
        _parse(payload)


def test_publication_asset_sets_must_match_the_frozen_universe_hash() -> None:
    payload = _payload()
    payload["universe"]["universe_hash"] = "0" * 64

    with pytest.raises(Data02PublicationToleranceEvidenceError, match="frozen universe hash"):
        _parse(payload)


def test_unapproved_or_incomplete_policy_registry_fails_closed() -> None:
    registry = json.loads(_registry_bytes())
    registry["status"] = "awaiting_owner_approval"
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="must be active"):
        parse_data02_publication_tolerance_snapshot(
            _payload_bytes(),
            policy_registry_payload=json.dumps(registry).encode(),
        )


def test_ambiguous_or_nonfinite_json_fails_closed() -> None:
    duplicate_payload = _payload_bytes().replace(
        b'"read_mode":"select_only"',
        b'"read_mode":"select_only","read_mode":"select_only"',
    )
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="duplicate object key"):
        parse_data02_publication_tolerance_snapshot(
            duplicate_payload,
            policy_registry_payload=_registry_bytes(),
        )

    payload = _payload()
    payload["datasets"][0]["publication_policy"]["minimum_coverage_ratio"] = float("nan")
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="non-finite numeric"):
        parse_data02_publication_tolerance_snapshot(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            policy_registry_payload=_registry_bytes(),
        )


def test_repository_policy_registry_remains_blocked_pending_real_approval(
    tmp_path: Path,
) -> None:
    registry_path = Path("governance/data02_numeric_tolerance_policies.json")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    input_path = tmp_path / "snapshot.json"
    input_path.write_bytes(_payload_bytes())

    assert registry == {
        "schema_version": "data02-numeric-tolerance-policy-registry.v1",
        "status": "awaiting_owner_approval",
        "policies": [],
    }
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="must be active"):
        record_data02_publication_tolerance_evidence(input_path)

    registry = json.loads(_registry_bytes())
    registry["policies"].pop()
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="exactly the four"):
        parse_data02_publication_tolerance_snapshot(
            _payload_bytes(),
            policy_registry_payload=json.dumps(registry).encode(),
        )


def test_zero_canonical_value_uses_absolute_tolerance_without_fake_relative_value() -> None:
    payload = _payload()
    comparison = payload["datasets"][0]["comparisons"][0]
    comparison["canonical_value"] = "0"
    comparison["observed_value"] = "0.005"
    _refresh_snapshot_hashes(payload["datasets"][0])

    report = _parse(payload)
    output = report.to_dict()["datasets"][0]["comparisons"][0]

    assert output["absolute_difference"] == "0.005"
    assert output["relative_difference"] is None
    assert output["breached"] is False


def test_serializer_and_recorder_are_deterministic_and_append_only(tmp_path: Path) -> None:
    output_root = tmp_path / "evidence"
    expected = serialize_data02_publication_tolerance_evidence(
        parse_data02_publication_tolerance_snapshot(
            _payload_bytes(), policy_registry_payload=_registry_bytes()
        )
    )
    digest = data02_publication_tolerance_artifact_sha256(expected)
    first_path, first_written = _write_append_only(output_root, digest, expected)
    second_path, second_written = _write_append_only(output_root, digest, expected)

    assert first_path.read_bytes() == expected
    assert first_written is True and second_written is False
    assert first_path == second_path
    assert first_path.with_suffix(".sha256").read_text(encoding="ascii") == f"{digest}\n"

    first_path.with_suffix(".sha256").unlink()
    with pytest.raises(ValueError, match="digest sidecar is missing"):
        _write_append_only(output_root, digest, expected)


def test_recorder_script_runs_directly_and_modules_remain_offline() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/record_data02_publication_tolerance_evidence.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "four-Publication numeric tolerance snapshot" in result.stdout

    for path in (
        Path("apps/data_center/application/data02_publication_tolerance_evidence.py"),
        Path("scripts/record_data02_publication_tolerance_evidence.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert imported.isdisjoint({"django", "psycopg", "paramiko", "requests", "redis"})
        assert ".objects" not in path.read_text(encoding="utf-8")
