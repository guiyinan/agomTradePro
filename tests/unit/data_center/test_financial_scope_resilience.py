"""Behavioral contracts for quarantined provider data and capability isolation."""

from __future__ import annotations

import copy
import json
from datetime import date
from typing import Any

import pytest

from apps.data_center.application.financial_scope_capacity_receipt import (
    FinancialScopeCapacityReceiptError,
    build_financial_scope_capacity_receipt,
    build_financial_scope_partial_receipt,
    canonical_sha256,
)
from apps.data_center.infrastructure.financial_scope_discovery_reader import (
    _parse_provider_rows,
    _ScopeResponseValidator,
)
from tests.unit.test_financial_scope_capacity_receipt import (
    _FROZEN_PROVIDER_IDENTITIES,
    _PROVIDER_DIGEST,
    _scope_report,
)


def partial_source() -> dict[str, Any]:
    """Model one eligible asset plus an exhausted external request in the full universe."""
    source: dict[str, Any] = _scope_report()
    source.update(
        outcome="partial",
        review_status="not_eligible",
        started_at="2026-09-01T09:00:00+00:00",
        finished_at="2026-09-01T09:45:00+00:00",
    )
    source["binding"]["contract_version"] = "2026-10-16.v2"
    result = source["result"]
    item = result["candidate_manifest"]["items"][0]
    item["available_at"] = "2026-08-31T16:00:00+00:00"
    item["response_completed_at"] = ["2026-09-01T09:05:00+00:00", "2026-09-01T09:15:00+00:00"]
    result.update(
        outcome="partial",
        candidate=None,
        candidate_manifest=None,
        error_codes=[
            "REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_COVERAGE_INCOMPLETE",
            "REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED",
        ],
    )
    result["counts"].update(requested=2, missing=1, failed_capture=1, logical_requests=4)
    result["asset_results"] = [
        {
            "asset_code": "000001.SZ",
            "status": "eligible",
            "reason_code": None,
            "selected_scope": item,
            "must_not_use_for_decision": True,
            "quarantined_rows": 1,
            "unavailable_rows": 1,
        },
        {
            "asset_code": "600000.SH",
            "status": "blocked",
            "reason_code": "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED",
            "selected_scope": None,
            "must_not_use_for_decision": True,
            "quarantined_rows": 0,
            "unavailable_rows": 0,
        },
    ]
    result["captures"] = [
        {
            **artifact["envelope_index"],
            "response_completed_at": item["response_completed_at"][index],
        }
        for index, artifact in enumerate(source["encrypted_artifacts"])
    ]
    return source


def build_partial(source: object) -> dict[str, object]:
    """Build capability evidence retaining the complete two-asset denominator."""
    return build_financial_scope_partial_receipt(
        scope_report=source,
        scope_report_sha256="f" * 64,
        target_trade_date="2026-09-01",
        release_universe_sha256=canonical_sha256(["000001.SZ", "600000.SH"]),
        provider_identities_sha256=_PROVIDER_DIGEST,
        expected_release_asset_codes=("000001.SZ", "600000.SH"),
        frozen_provider_identities=_FROZEN_PROVIDER_IDENTITIES,
    )


@pytest.mark.parametrize("invalid", [None, "1900-01-01 00:05:43", "1900-01-01"])
def test_history_date_defect_is_quarantined_without_losing_valid_rows(invalid: object) -> None:
    body = json.dumps(
        {
            "success": True,
            "code": 0,
            "result": {
                "count": 2,
                "data": [
                    {"SECUCODE": "000001.SZ", "REPORT_DATE": "2001-06-30", "NOTICE_DATE": invalid},
                    {
                        "SECUCODE": "000001.SZ",
                        "REPORT_DATE": "2026-06-30",
                        "NOTICE_DATE": "2026-08-31",
                    },
                ],
            },
        }
    ).encode()
    rows = _parse_provider_rows(body, asset_code="000001.SZ", maximum_rows=200)
    assert len(rows) == 2
    assert rows[0].quarantined_row_sha256 is not None
    assert rows[1].announcement_date == date(2026, 8, 31)
    assert rows[1].quarantined_row_sha256 is None


def test_partial_evidence_never_grants_full_financial_refresh() -> None:
    source = partial_source()
    receipt = build_partial(source)
    assert receipt["outcome"] == "partial"
    assert receipt["capabilities"] == {"financial_refresh": False}
    assert receipt["release_universe"]["asset_count"] == 2
    with pytest.raises(FinancialScopeCapacityReceiptError):
        build_financial_scope_capacity_receipt(
            scope_report=source,
            scope_report_sha256="f" * 64,
            target_trade_date="2026-09-01",
            release_universe_sha256=canonical_sha256(["000001.SZ", "600000.SH"]),
            provider_identities_sha256=_PROVIDER_DIGEST,
            expected_release_asset_codes=("000001.SZ", "600000.SH"),
            frozen_provider_identities=_FROZEN_PROVIDER_IDENTITIES,
        )


def test_valid_empty_response_is_retained_for_asset_local_classification() -> None:
    rows = _parse_provider_rows(
        b'{"success":true,"code":0,"result":{"count":0,"data":[]}}',
        asset_code="000001.SZ",
        maximum_rows=200,
    )
    assert rows == ()


def test_complete_v2_scope_still_requires_every_asset_result_and_native_availability() -> None:
    """The full capability cannot bypass v2 accounting merely by claiming success."""
    from tests.unit.test_financial_scope_capacity_receipt import _build

    source = _scope_report()
    partial = partial_source()
    source["started_at"], source["finished_at"] = partial["started_at"], partial["finished_at"]
    source["binding"]["contract_version"] = "2026-10-16.v2"
    result = source["result"]
    candidate = result["candidate_manifest"]
    item = candidate["items"][0]
    item.update(partial["result"]["asset_results"][0]["selected_scope"])
    candidate["generated_at"] = "2026-09-01T09:30:00+00:00"
    candidate["manifest_sha256"] = canonical_sha256(
        {key: val for key, val in candidate.items() if key != "manifest_sha256"}
    )
    result["candidate"]["manifest_sha256"] = candidate["manifest_sha256"]
    result["asset_results"] = [partial["result"]["asset_results"][0]]
    assert _build(source)["outcome"] == "success"
    result["asset_results"] = []
    with pytest.raises(FinancialScopeCapacityReceiptError):
        _build(source)
    fabricated_full = _scope_report()
    fabricated_full["result"]["captures"] = []
    with pytest.raises(FinancialScopeCapacityReceiptError):
        _build(fabricated_full)


@pytest.mark.parametrize("code", [401, 403, 9501])
def test_provider_permission_or_query_error_never_becomes_asset_local_retry(code: int) -> None:
    validator = _ScopeResponseValidator(asset_code="000001.SZ", maximum_rows=200)
    result = validator(json.dumps({"success": False, "code": code}).encode())
    assert result.accepted is False
    assert result.retryable is False
    assert validator.error_code == "FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID"


@pytest.mark.parametrize(
    "defect",
    [
        "missing_asset",
        "unknown_failure",
        "audit",
        "future",
        "artifact",
        "counts",
        "authorization",
        "old_contract",
    ],
)
def test_partial_evidence_cannot_hide_integrity_or_authority_defects(defect: str) -> None:
    source = copy.deepcopy(partial_source())
    result = source["result"]
    if defect == "missing_asset":
        result["asset_results"].pop()
    elif defect == "unknown_failure":
        result["asset_results"][1][
            "reason_code"
        ] = "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID"
    elif defect == "audit":
        result["captures"][0]["raw_audit_id"] = 0
    elif defect == "future":
        result["asset_results"][0]["selected_scope"]["available_at"] = "2026-09-02T16:00:00+00:00"
    elif defect == "artifact":
        source["encrypted_artifacts"].pop()
    elif defect == "counts":
        result["counts"]["missing"] = 0
    elif defect == "authorization":
        source["authorization"] = None
    elif defect == "old_contract":
        source["binding"]["contract_version"] = "2026-10-09.v1"
    with pytest.raises(FinancialScopeCapacityReceiptError):
        build_partial(source)
