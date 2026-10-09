"""Contracts for candidate-bound, zero-write full-scope S6 financial receipts."""

from __future__ import annotations

import pytest

from apps.data_center.application.financial_scope_capacity_receipt import (
    FinancialScopeCapacityReceiptError,
    build_financial_scope_capacity_receipt,
    canonical_sha256,
    validate_financial_scope_capacity_receipt,
)

_CANDIDATE = "a" * 40
_IMAGE = "sha256:" + "b" * 64
_ARTIFACT_ROOT = "agom-s6-financial-scope-" + "e" * 32
_FINANCIAL_IDENTITY = {
    "role": "akshare_financial_route:17",
    "provider_id": 17,
    "source": "akshare_financial",
    "version": "akshare-financial-test",
    "endpoint_id": "financial-route-test",
    "deployment_region": "ap-east-1",
}
_FROZEN_PROVIDER_IDENTITIES = (_FINANCIAL_IDENTITY,)
_PROVIDER_DIGEST = canonical_sha256([_FINANCIAL_IDENTITY])
_RELEASE_ASSET_CODES = ("000001.SZ",)
_RELEASE_UNIVERSE = canonical_sha256(list(_RELEASE_ASSET_CODES))


def _scope_report() -> dict[str, object]:
    """Return one full one-asset discovery report with dual raw evidence."""

    binding: dict[str, object] = {
        "candidate_sha": _CANDIDATE,
        "provider_id": 17,
        "provider_name": "akshare",
        "provider_identity_sha256": canonical_sha256(_FINANCIAL_IDENTITY),
        "contract_id": "financial-contract",
        "contract_version": "v1",
        "contract_sha256": "2" * 64,
        "parser_id": "financial-parser",
        "parser_sha256": "3" * 64,
        "deployment_region": "ap-east-1",
    }
    discovery_authorization = {
        "approval_id": "scope-approval-1",
        "owner_event_id": "scope-event-1",
        "owner_receipt_sha256": "4" * 64,
    }
    item: dict[str, object] = {
        "asset_code": "000001.SZ",
        "announcement_date": "2026-08-31",
        "available_at": "2026-08-31T16:00:00+08:00",
        "native_row_ids": ["akshare:000001.SZ:2026-06-30:2026-08-31"],
        "financial_capture_id": "00000000-0000-4000-8000-000000000001",
        "financial_body_sha256": "5" * 64,
        "financial_raw_audit_id": 101,
        "source_time_capture_id": "00000000-0000-4000-8000-000000000002",
        "source_time_body_sha256": "6" * 64,
        "source_time_raw_audit_id": 102,
        "response_completed_at": [
            "2026-08-31T09:05:00+00:00",
            "2026-08-31T09:15:00+00:00",
        ],
    }
    candidate: dict[str, object] = {
        "schema": "data-center.financial-scope-discovery-manifest.v1",
        "status": "pending_independent_review",
        "binding": binding,
        "universe": {
            "asset_count": 1,
            "asset_codes": ["000001.SZ"],
            "sha256": canonical_sha256(["000001.SZ"]),
        },
        "generated_at": "2026-08-31T09:30:00+00:00",
        "discovery_authorization": discovery_authorization,
        "items": [item],
        "counts": {
            "requested_assets": 1,
            "captured_assets": 1,
            "missing_assets": 0,
            "duplicate_assets": 0,
            "conflicting_assets": 0,
            "logical_request_count": 2,
        },
    }
    candidate["manifest_sha256"] = canonical_sha256(candidate)
    artifacts = [
        {
            "path": f"{_ARTIFACT_ROOT}/v1/00000000-0000-4000-8000-000000000001.frb",
            "size_bytes": 120,
            "ciphertext_sha256": "7" * 64,
            "envelope_index": {
                "asset_code": "000001.SZ",
                "dataset_key": "equity.financial.fact",
                "capture_id": "00000000-0000-4000-8000-000000000001",
                "body_sha256": "5" * 64,
                "raw_audit_id": 101,
            },
        },
        {
            "path": f"{_ARTIFACT_ROOT}/v1/00000000-0000-4000-8000-000000000002.frb",
            "size_bytes": 130,
            "ciphertext_sha256": "8" * 64,
            "envelope_index": {
                "asset_code": "000001.SZ",
                "dataset_key": "equity.financial.source-time",
                "capture_id": "00000000-0000-4000-8000-000000000002",
                "body_sha256": "6" * 64,
                "raw_audit_id": 102,
            },
        },
    ]
    return {
        "schema": "release.financial-scope-discovery.v1",
        "kind": "financial_scope_discovery",
        "candidate_sha": _CANDIDATE,
        "started_at": "2026-08-31T09:00:00+00:00",
        "finished_at": "2026-08-31T09:45:00+00:00",
        "outcome": "success",
        "review_status": "pending_independent_review",
        "binding": binding,
        "database": {
            "vendor": "postgresql",
            "scope": "disposable",
            "release_rehearsal_guard": True,
            "name": "agom_release_rehearsal_financial_scope",
            "host": "agom-s6-postgres-financial-scope",
            "isolation_attestation_sha256": "9" * 64,
        },
        "authorization": discovery_authorization,
        "candidate_image_id": _IMAGE,
        "artifact_root": _ARTIFACT_ROOT,
        "encrypted_artifacts": artifacts,
        "result": {
            "schema": "data-center.financial-scope-discovery-result.v1",
            "outcome": "success",
            "error_codes": [],
            "counts": {
                "requested": 1,
                "captured": 1,
                "failed_capture": 0,
                "missing": 0,
                "duplicates": 0,
                "conflicts": 0,
                "logical_requests": 2,
                "physical_attempts": 3,
                "artifact_writes": 2,
                "raw_audit_writes": 2,
                "fact_writes": 0,
                "publication_writes": 0,
            },
            "candidate": {
                "manifest_sha256": candidate["manifest_sha256"],
                "universe_sha256": canonical_sha256(["000001.SZ"]),
                "coverage_count": 1,
                "review_status": "pending_independent_review",
            },
            "candidate_manifest": candidate,
        },
    }


def _build(scope_report: object | None = None) -> dict[str, object]:
    """Build a report using stable test identities."""

    report = _scope_report() if scope_report is None else scope_report
    return build_financial_scope_capacity_receipt(
        scope_report=report,
        scope_report_sha256="f" * 64,
        target_trade_date="2026-09-01",
        release_universe_sha256=_RELEASE_UNIVERSE,
        provider_identities_sha256=_PROVIDER_DIGEST,
        expected_release_asset_codes=_RELEASE_ASSET_CODES,
        frozen_provider_identities=_FROZEN_PROVIDER_IDENTITIES,
    )


def test_full_scope_receipt_seals_capacity_and_zero_write_evidence() -> None:
    receipt = _build()

    assert receipt["schema"] == "release.financial-scope-capacity.v1"
    assert receipt["candidate_sha"] == _CANDIDATE
    assert receipt["environment"] == "s6_isolated_disposable"
    assert receipt["scope_report"] == {
        "path": "financial-scope-discovery.json",
        "sha256": "f" * 64,
    }
    assert receipt["receipt_sha256"] == canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    assert receipt["capacity"] == {
        "asset_count": 1,
        "logical_request_count": 2,
        "logical_request_ceiling": 2,
        "physical_attempt_count": 3,
        "physical_attempt_ceiling": 4,
        "artifact_count": 2,
        "raw_audit_count": 2,
        "fact_writes": 0,
        "publication_writes": 0,
    }


def test_capacity_receipt_rejects_one_asset_when_frozen_release_universe_has_two() -> None:
    """A source report cannot define its own smaller meaning of full scope."""

    source = _scope_report()
    frozen_release_codes = ("000001.SZ", "000002.SZ")
    frozen_financial_identity = {
        "role": "akshare_financial_route:17",
        "provider_id": 17,
        "source": "akshare_financial",
        "deployment_region": "ap-east-1",
    }

    with pytest.raises(FinancialScopeCapacityReceiptError):
        build_financial_scope_capacity_receipt(
            scope_report=source,
            scope_report_sha256="f" * 64,
            target_trade_date="2026-09-01",
            release_universe_sha256=_RELEASE_UNIVERSE,
            provider_identities_sha256=_PROVIDER_DIGEST,
            expected_release_asset_codes=frozen_release_codes,
            frozen_provider_identities=(frozen_financial_identity,),
        )


def test_capacity_receipt_rejects_provider_outside_frozen_financial_route_identity() -> None:
    """The financial binding must match the frozen route, source and region member."""

    source = _scope_report()
    frozen_financial_identity = {
        "role": "akshare_financial_route:18",
        "provider_id": 18,
        "source": "akshare_financial",
        "deployment_region": "ap-east-1",
    }

    with pytest.raises(FinancialScopeCapacityReceiptError):
        build_financial_scope_capacity_receipt(
            scope_report=source,
            scope_report_sha256="f" * 64,
            target_trade_date="2026-09-01",
            release_universe_sha256=_RELEASE_UNIVERSE,
            provider_identities_sha256=_PROVIDER_DIGEST,
            expected_release_asset_codes=("000001.SZ",),
            frozen_provider_identities=(frozen_financial_identity,),
        )


@pytest.mark.parametrize("field", ["generated_at", "response_completed_at"])
def test_capacity_receipt_rejects_inner_evidence_outside_source_window(field: str) -> None:
    """Fresh outer timestamps cannot wrap older candidate or response evidence."""

    source = _scope_report()
    result = source["result"]
    assert isinstance(result, dict)
    candidate = result["candidate_manifest"]
    assert isinstance(candidate, dict)
    if field == "generated_at":
        candidate["generated_at"] = "2026-08-31T08:59:00+00:00"
    else:
        items = candidate["items"]
        assert isinstance(items, list) and isinstance(items[0], dict)
        items[0]["response_completed_at"] = [
            "2026-08-31T08:59:00+00:00",
            "2026-08-31T09:01:00+00:00",
        ]
    candidate.pop("manifest_sha256", None)
    candidate["manifest_sha256"] = canonical_sha256(candidate)
    summary = result["candidate"]
    assert isinstance(summary, dict)
    summary["manifest_sha256"] = candidate["manifest_sha256"]

    with pytest.raises(FinancialScopeCapacityReceiptError):
        _build(source)


def test_capacity_receipt_rejects_encrypted_artifact_without_item_envelope_mapping() -> None:
    """Every ciphertext must identify the exact asset, dataset, capture and audit row."""

    source = _scope_report()
    result = source["result"]
    assert isinstance(result, dict)
    candidate = result["candidate_manifest"]
    assert isinstance(candidate, dict)
    items = candidate["items"]
    assert isinstance(items, list) and isinstance(items[0], dict)
    items[0]["financial_capture_id"] = "123e4567-e89b-42d3-a456-426614174099"
    candidate.pop("manifest_sha256", None)
    candidate["manifest_sha256"] = canonical_sha256(candidate)
    summary = result["candidate"]
    assert isinstance(summary, dict)
    summary["manifest_sha256"] = candidate["manifest_sha256"]

    with pytest.raises(FinancialScopeCapacityReceiptError):
        _build(source)


def test_capacity_receipt_rejects_partial_capture_and_any_fact_write() -> None:
    report = _scope_report()
    result = report["result"]
    assert isinstance(result, dict)
    counts = result["counts"]
    assert isinstance(counts, dict)
    counts["captured"] = 0

    with pytest.raises(FinancialScopeCapacityReceiptError):
        _build(report)

    report = _scope_report()
    result = report["result"]
    assert isinstance(result, dict)
    counts = result["counts"]
    assert isinstance(counts, dict)
    counts["fact_writes"] = 1
    with pytest.raises(FinancialScopeCapacityReceiptError):
        _build(report)


def test_capacity_receipt_rejects_scope_artifact_path_and_environment_tampering() -> None:
    report = _scope_report()
    artifacts = report["encrypted_artifacts"]
    assert isinstance(artifacts, list)
    first = artifacts[0]
    assert isinstance(first, dict)
    first["path"] = "../outside.frb"
    with pytest.raises(FinancialScopeCapacityReceiptError):
        _build(report)

    report = _scope_report()
    database = report["database"]
    assert isinstance(database, dict)
    database["scope"] = "production"
    with pytest.raises(FinancialScopeCapacityReceiptError):
        _build(report)


def test_capacity_receipt_revalidates_candidate_image_and_provider_bindings() -> None:
    source = _scope_report()
    receipt = _build(source)
    raw_sha = "f" * 64

    validate_financial_scope_capacity_receipt(
        receipt=receipt,
        scope_report=source,
        scope_report_sha256=raw_sha,
        expected_candidate=_CANDIDATE,
        expected_image_id=_IMAGE,
        expected_trade_date="2026-09-01",
        expected_release_universe_sha256=_RELEASE_UNIVERSE,
        expected_provider_identities_sha256=_PROVIDER_DIGEST,
        expected_release_asset_codes=_RELEASE_ASSET_CODES,
        frozen_provider_identities=_FROZEN_PROVIDER_IDENTITIES,
    )
    altered = dict(receipt)
    altered["provider_identities_sha256"] = "0" * 64
    with pytest.raises(FinancialScopeCapacityReceiptError):
        validate_financial_scope_capacity_receipt(
            receipt=altered,
            scope_report=source,
            scope_report_sha256=raw_sha,
            expected_candidate=_CANDIDATE,
            expected_image_id=_IMAGE,
            expected_trade_date="2026-09-01",
            expected_release_universe_sha256=_RELEASE_UNIVERSE,
            expected_provider_identities_sha256=_PROVIDER_DIGEST,
            expected_release_asset_codes=_RELEASE_ASSET_CODES,
            frozen_provider_identities=_FROZEN_PROVIDER_IDENTITIES,
        )
    with pytest.raises(FinancialScopeCapacityReceiptError):
        validate_financial_scope_capacity_receipt(
            receipt=receipt,
            scope_report=source,
            scope_report_sha256=raw_sha,
            expected_candidate="0" * 40,
            expected_image_id=_IMAGE,
            expected_trade_date="2026-09-01",
            expected_release_universe_sha256=_RELEASE_UNIVERSE,
            expected_provider_identities_sha256=_PROVIDER_DIGEST,
            expected_release_asset_codes=_RELEASE_ASSET_CODES,
            frozen_provider_identities=_FROZEN_PROVIDER_IDENTITIES,
        )


def test_source_report_digest_changes_receipt_identity() -> None:
    source = _scope_report()
    first = _build(source)
    second = build_financial_scope_capacity_receipt(
        scope_report=source,
        scope_report_sha256="0" * 64,
        target_trade_date="2026-09-01",
        release_universe_sha256=_RELEASE_UNIVERSE,
        provider_identities_sha256=_PROVIDER_DIGEST,
        expected_release_asset_codes=_RELEASE_ASSET_CODES,
        frozen_provider_identities=_FROZEN_PROVIDER_IDENTITIES,
    )
    assert first["scope_pointer_sha256"] != second["scope_pointer_sha256"]
