"""Versioned same-provider D1 evidence supports heterogeneous financial rows."""

import hashlib
import json

import pytest

from apps.data_center.application.data02_publication_tolerance_evidence import (
    Data02PublicationToleranceEvidenceError,
    parse_data02_publication_tolerance_snapshot,
)
from apps.data_center.domain.numeric_tolerance import (
    NumericToleranceFieldV2,
    NumericTolerancePolicyV2,
    canonical_decimal_text,
)
from tests.unit.data_center.test_data02_publication_tolerance_evidence import (
    CAPTURED_AT,
    _payload,
    _payload_bytes,
    _refresh_publication_identity,
)


def _refresh_snapshot_hashes(dataset):
    # Exporter fixtures retain Unicode unit labels in canonical UTF-8 JSON.
    for kind, target, source_name in [
        ("canonical", "reference_snapshot_hash", "reference_source"),
        ("observed", "observed_snapshot_hash", "observed_source"),
    ]:
        values = [
            {
                "field_name": c["field_name"],
                "natural_key": c["natural_key"],
                "unit": c["unit"],
                "value": canonical_decimal_text(
                    c["canonical_value" if kind == "canonical" else "observed_value"],
                    field_name="fixture_value",
                ),
            }
            for c in sorted(
                dataset["comparisons"], key=lambda c: (c["natural_key"], c["field_name"])
            )
        ]
        body = {
            "dataset_key": dataset["dataset_key"],
            "encoding": "data02-numeric-snapshot-v1",
            "source": dataset[source_name],
            "value_kind": kind,
            "values": values,
        }
        dataset[target] = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


def prepared():
    payload = _payload()
    payload["schema_version"] = "data02-four-publication-tolerance-input.v2"
    registry = {
        "schema_version": "data02-numeric-tolerance-policy-registry.v2",
        "status": "active",
        "policies": [],
    }
    for dataset in payload["datasets"]:
        financial = dataset["dataset_key"] == "equity.financial.fact"
        fields = (
            (
                NumericToleranceFieldV2("revenue", "元", "0", "0"),
                NumericToleranceFieldV2("roe", "%", "0", "0"),
            )
            if financial
            else (NumericToleranceFieldV2("value", "CNY", "0", "0"),)
        )
        policy = NumericTolerancePolicyV2(
            dataset["dataset_key"],
            "owner-zero.v2",
            "absolute_or_relative",
            fields,
            "financial_metric_code_v1" if financial else "all_fields_per_member",
        )
        body = {
            "content_hash": policy.content_hash,
            "identity": policy.identity,
            "fields": [x.to_dict() for x in policy.fields],
            "policy_version": policy.policy_version,
            "rule": policy.rule,
            "selector": policy.selector,
        }
        dataset["tolerance_policy"] = body
        dataset["reference_source"] = dataset["observed_source"]
        original = list(zip(dataset["members"], dataset["comparisons"], strict=True))
        members, comparisons = [], []
        for i, (member, comparison) in enumerate(original):
            for metric in (("revenue", "roe") if financial else ("value",)):
                item, value = dict(member), dict(comparison)
                value["observed_value"] = value["canonical_value"]
                value["unit"] = (
                    "元" if financial and metric == "revenue" else "%" if financial else "CNY"
                )
                if financial:
                    key = f"00000{i+1}.SZ:2026-06-30:semi_annual:{metric}:{member['source']}"
                    item["natural_key"] = value["natural_key"] = key
                    item["fact_pk"] = str(member["fact_pk"]) + "-" + metric
                    item["fact_content_hash"] = hashlib.sha256(item["fact_pk"].encode()).hexdigest()
                    value["field_name"] = metric
                members.append(item)
                comparisons.append(value)
        dataset["members"], dataset["comparisons"] = members, comparisons
        dataset["publication"]["member_count"] = len(members)
        _refresh_publication_identity(dataset)
        _refresh_snapshot_hashes(dataset)
        registry["policies"].append(
            {
                **body,
                "dataset_key": dataset["dataset_key"],
                "approval": {
                    "approved_at": CAPTURED_AT,
                    "approved_by": "fixture-owner",
                    "receipt_sha256": "e" * 64,
                },
            }
        )
    return payload, registry


def parse(payload, registry):
    return parse_data02_publication_tolerance_snapshot(
        _payload_bytes(payload), policy_registry_payload=json.dumps(registry).encode()
    )


def test_v2_financial_rows_compare_only_their_metric_with_the_real_unit():
    payload, registry = prepared()
    report = parse(payload, registry)
    assert report.reconciliation_passed
    financial = report.datasets[0]
    assert [(x.field_name, x.unit) for x in financial.comparisons] == [
        ("revenue", "元"),
        ("roe", "%"),
        ("revenue", "元"),
        ("roe", "%"),
    ]
    assert report.to_dict()["schema_version"] == "data02-four-publication-tolerance-evidence.v2"
    assert financial.to_dict()["tolerance_policy"]["selector"] == "financial_metric_code_v1"
    assert report.to_dict()["production_ready"] is False


@pytest.mark.parametrize(
    "change",
    [
        "cross_provider",
        "member_source",
        "wrong_metric",
        "wrong_unit",
        "missing_member",
        "selector",
        "registry_version",
        "input_version",
    ],
)
def test_v2_does_not_relax_source_metric_unit_or_complete_member_coverage(change):
    payload, registry = prepared()
    financial = payload["datasets"][0]
    if change == "cross_provider":
        financial["reference_source"] = "another-provider"
    elif change == "member_source":
        financial["observed_source"] = financial["reference_source"] = "another-provider"
    elif change == "wrong_metric":
        financial["comparisons"][0]["field_name"] = "roe"
    elif change == "wrong_unit":
        financial["comparisons"][0]["unit"] = "万元"
    elif change == "missing_member":
        financial["comparisons"].pop()
    elif change == "selector":
        financial["tolerance_policy"]["selector"] = "all_fields_per_member"
    elif change == "registry_version":
        registry["schema_version"] = "data02-numeric-tolerance-policy-registry.v1"
    elif change == "input_version":
        payload["schema_version"] = "data02-four-publication-tolerance-input.v1"
    _refresh_snapshot_hashes(financial)
    with pytest.raises(Data02PublicationToleranceEvidenceError):
        parse(payload, registry)


def test_v2_zero_tolerance_preserves_and_reports_rounding_breach():
    payload, registry = prepared()
    financial = payload["datasets"][0]
    financial["comparisons"][0]["observed_value"] = "100.0001"
    _refresh_snapshot_hashes(financial)
    report = parse(payload, registry)
    assert not report.reconciliation_passed and report.breach_count == 1


@pytest.mark.parametrize("entire_column", [True, False])
def test_v2_cannot_hide_an_entire_metric_or_one_incomplete_report(entire_column):
    payload, registry = prepared()
    financial = payload["datasets"][0]
    removed = {
        member["natural_key"]
        for index, member in enumerate(financial["members"])
        if member["natural_key"].split(":")[3] == "roe" and (entire_column or index == 1)
    }
    financial["members"] = [m for m in financial["members"] if m["natural_key"] not in removed]
    financial["comparisons"] = [
        c for c in financial["comparisons"] if c["natural_key"] not in removed
    ]
    financial["publication"]["member_count"] = len(financial["members"])
    _refresh_publication_identity(financial)
    _refresh_snapshot_hashes(financial)
    with pytest.raises(Data02PublicationToleranceEvidenceError, match="omits governed metrics"):
        parse(payload, registry)
