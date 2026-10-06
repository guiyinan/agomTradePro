"""Fail-closed release validation for the controlled AKShare financial slice."""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts import validate_release_rehearsal as validator


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _valid_report() -> tuple[dict[str, object], dict[str, object]]:
    identity: dict[str, object] = {
        "role": "valuation",
        "provider_id": 19,
        "source": "tencent",
        "version": "tencent-quote-batch-v1-requests-1-cfg-test",
        "endpoint_id": "provider-config-test",
    }
    route_sha = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    captures: list[dict[str, object]] = []
    for index, dataset in enumerate(
        ("equity.financial.fact", "equity.financial.source-time"), start=1
    ):
        body_sha = _sha256(f"body-{index}")
        captures.append(
            {
                "dataset_key": dataset,
                "capture_id": f"00000000-0000-4000-8000-{index:012d}",
                "raw_audit_id": str(index),
                "raw_audit_count": 1,
                "raw_audit_status": "ok",
                "raw_audit_provider_id": 19,
                "body_sha256": body_sha,
                "raw_audit_body_sha256": body_sha,
                "body_size_bytes": 100 + index,
                "typed_evidence_count": 3,
                "witness_coverage_count": 3,
            }
        )
    report: dict[str, object] = {
        "candidate_source_attestation": "image_release_manifest",
        "provider_identities": [identity],
        "database": {
            "vendor": "postgresql",
            "scope": "disposable",
            "release_rehearsal_guard": True,
            "host": "agom-s6-postgres-run-01",
            "name": "agom_release_rehearsal_run01",
            "identity_sha256": _sha256("database identity"),
        },
        "redis": {
            "scope": "disposable",
            "ping_verified": True,
            "host": "agom-s6-redis-run-01",
            "expected_host": "agom-s6-redis-run-01",
        },
        "selected_provider": {
            "provider_id": 19,
            "source_type": "akshare",
            "frozen_identity_role": "valuation",
            "frozen_route_identity_sha256": route_sha,
        },
        "request_seed": {
            "asset_code": "600000.SH",
            "announcement_date": "2025-03-28",
            "basis": "legacy_available_at_date_untrusted",
            "source": "akshare",
            "provenance_is_seed_only": True,
            "legacy_fact_id_sha256": _sha256("old-fact-id"),
            "selection_sha256": _sha256("selection"),
        },
        "sync": {
            "requested": 1,
            "succeeded": 1,
            "failed": 0,
            "stored": 3,
            "planned_provider_requests": 2,
            "provider_request_count": 2,
            "atomic_fact_write_count": 1,
            "typed_fact_evidence_count": 3,
            "source_time_witness_count": 3,
        },
        "captures": captures,
        "failure_evidence": {
            "source": "candidate_regression_evidence",
            "failure_isolated_before_real_provider_egress": True,
            "zero_fact_write_test_cases": list(validator.FINANCIAL_ZERO_WRITE_PROOF_CASES),
            "junit_sha256": _sha256("junit"),
        },
    }
    regression_report: dict[str, object] = {
        "required_tests": list(validator.REQUIRED_POSTGRESQL_TESTS),
        "junit_artifacts": [
            {"path": "financial-slice-sync-contracts.xml", "sha256": _sha256("junit")}
        ],
    }
    return report, regression_report


def test_valid_financial_slice_release_evidence_requires_isolation_and_two_audits() -> None:
    report, regression_report = _valid_report()

    validator._validate_akshare_financial_slice(
        report,
        regression_report=regression_report,
        expected_date="2025-04-01",
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("sync", "planned_provider_requests"), 4),
        (("sync", "atomic_fact_write_count"), 2),
        (("selected_provider", "provider_id"), 20),
        (("database", "vendor"), "sqlite"),
        (("redis", "ping_verified"), False),
        (("request_seed", "basis"), "period_end"),
        (("captures", 1, "raw_audit_provider_id"), 20),
        (("failure_evidence", "failure_isolated_before_real_provider_egress"), False),
    ],
)
def test_financial_slice_release_evidence_fails_closed(
    path: tuple[str | int, ...], value: object
) -> None:
    report, regression_report = _valid_report()
    current: object = report
    for component in path[:-1]:
        current = current[component]  # type: ignore[index]
    current[path[-1]] = value  # type: ignore[index]

    with pytest.raises(validator.RehearsalValidationError):
        validator._validate_akshare_financial_slice(
            report,
            regression_report=regression_report,
            expected_date="2025-04-01",
        )


def test_financial_slice_release_evidence_requires_failure_cases_in_official_ci() -> None:
    report, regression_report = _valid_report()
    regression_report["required_tests"] = []

    with pytest.raises(validator.RehearsalValidationError):
        validator._validate_akshare_financial_slice(
            report,
            regression_report=regression_report,
            expected_date="2025-04-01",
        )
