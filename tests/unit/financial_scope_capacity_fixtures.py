"""Filesystem fixture for the S6 financial scope receipt and its copied graph."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from apps.data_center.application.financial_scope_capacity_receipt import (
    build_financial_scope_capacity_receipt,
)
from tests.unit.test_financial_scope_capacity_receipt import _scope_report


def write_financial_scope_capacity_fixture(
    output_dir: Path,
    *,
    candidate_image_id: str,
    target_trade_date: str,
    release_universe_sha256: str,
    provider_identities_sha256: str,
    expected_release_asset_codes: tuple[str, ...],
    frozen_provider_identities: tuple[dict[str, object], ...],
    now: datetime,
    scope_report: dict[str, object] | None = None,
) -> Path:
    """Write a complete source report, encrypted artifact tree, and capacity receipt."""

    output_dir.mkdir(parents=True, exist_ok=True)
    scope_report = _scope_report() if scope_report is None else scope_report
    scope_report["candidate_image_id"] = candidate_image_id
    scope_report["started_at"] = (now - timedelta(hours=1)).replace(microsecond=0).isoformat()
    scope_report["finished_at"] = (now.replace(microsecond=0)).isoformat()
    root_name = str(scope_report["artifact_root"])
    artifact_root = output_dir / root_name
    artifact_root.mkdir()
    result = scope_report["result"]
    if not isinstance(result, dict):
        raise AssertionError("scope fixture result must be a mapping")
    candidate = result["candidate_manifest"]
    if not isinstance(candidate, dict):
        raise AssertionError("scope fixture candidate must be a mapping")
    binding = candidate["binding"]
    if not isinstance(binding, dict):
        raise AssertionError("scope fixture binding must be a mapping")
    financial_identities = [
        item
        for item in frozen_provider_identities
        if item.get("role") == f"akshare_financial_route:{item.get('provider_id')}"
    ]
    if len(financial_identities) != 1:
        raise AssertionError("fixture needs exactly one frozen financial provider identity")
    financial_identity = financial_identities[0]
    binding["provider_id"] = financial_identity["provider_id"]
    binding["provider_identity_sha256"] = hashlib.sha256(
        json.dumps(financial_identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    binding["deployment_region"] = financial_identity["deployment_region"]

    raw_items = candidate["items"]
    if not isinstance(raw_items, list) or not raw_items or not isinstance(raw_items[0], dict):
        raise AssertionError("scope fixture needs one seed item")
    seed_item = raw_items[0]
    items: list[dict[str, object]] = []
    artifacts: list[dict[str, object]] = []
    observed_at = (now - timedelta(minutes=30)).replace(microsecond=0)
    for index, asset_code in enumerate(expected_release_asset_codes, start=1):
        item: dict[str, object] = dict(seed_item)
        financial_capture_id = f"00000000-0000-4000-8000-{index * 2 - 1:012x}"
        source_time_capture_id = f"00000000-0000-4000-8000-{index * 2:012x}"
        financial_body_sha = hashlib.sha256(f"financial:{asset_code}".encode()).hexdigest()
        source_time_body_sha = hashlib.sha256(f"source-time:{asset_code}".encode()).hexdigest()
        announcement_date = observed_at.date().isoformat()
        item.update(
            {
                "asset_code": asset_code,
                "announcement_date": announcement_date,
                "available_at": (observed_at - timedelta(minutes=1)).isoformat(),
                "native_row_ids": [f"akshare:{asset_code}:2026-06-30:{announcement_date}"],
                "financial_capture_id": financial_capture_id,
                "financial_body_sha256": financial_body_sha,
                "financial_raw_audit_id": 10_000 + index * 2 - 1,
                "source_time_capture_id": source_time_capture_id,
                "source_time_body_sha256": source_time_body_sha,
                "source_time_raw_audit_id": 10_000 + index * 2,
                "response_completed_at": [observed_at.isoformat(), observed_at.isoformat()],
            }
        )
        items.append(item)
        for capture_id, dataset_key, body_sha, audit_id in (
            (
                financial_capture_id,
                "equity.financial.fact",
                financial_body_sha,
                item["financial_raw_audit_id"],
            ),
            (
                source_time_capture_id,
                "equity.financial.source-time",
                source_time_body_sha,
                item["source_time_raw_audit_id"],
            ),
        ):
            relative = f"{root_name}/v1/{capture_id}.frb"
            content = f"encrypted-financial-capture-{capture_id}".encode("ascii")
            artifact_path = output_dir / relative
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(content)
            artifacts.append(
                {
                    "path": relative,
                    "size_bytes": len(content),
                    "ciphertext_sha256": hashlib.sha256(content).hexdigest(),
                    "envelope_index": {
                        "asset_code": asset_code,
                        "dataset_key": dataset_key,
                        "capture_id": capture_id,
                        "body_sha256": body_sha,
                        "raw_audit_id": audit_id,
                    },
                }
            )
    candidate["items"] = items
    candidate["universe"] = {
        "asset_count": len(expected_release_asset_codes),
        "asset_codes": list(expected_release_asset_codes),
        "sha256": hashlib.sha256(
            json.dumps(
                list(expected_release_asset_codes), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }
    candidate["generated_at"] = (observed_at + timedelta(minutes=10)).isoformat()
    candidate_counts = candidate["counts"]
    if not isinstance(candidate_counts, dict):
        raise AssertionError("scope fixture candidate counts must be a mapping")
    candidate_counts.update(
        {
            "requested_assets": len(items),
            "captured_assets": len(items),
            "missing_assets": 0,
            "duplicate_assets": 0,
            "conflicting_assets": 0,
            "logical_request_count": len(items) * 2,
        }
    )
    candidate.pop("manifest_sha256", None)
    candidate["manifest_sha256"] = hashlib.sha256(
        json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    summary = result["candidate"]
    if not isinstance(summary, dict):
        raise AssertionError("scope fixture candidate summary must be a mapping")
    summary.update(
        {
            "manifest_sha256": candidate["manifest_sha256"],
            "universe_sha256": candidate["universe"]["sha256"],
            "coverage_count": len(items),
        }
    )
    scope_report["binding"] = {
        key: value for key, value in binding.items() if key != "candidate_sha"
    }
    scope_report["encrypted_artifacts"] = artifacts
    scope_report["result"] = result
    counts = result["counts"]
    if not isinstance(counts, dict):
        raise AssertionError("scope fixture counts must be a mapping")
    counts.update(
        {
            "requested": len(items),
            "captured": len(items),
            "logical_requests": len(items) * 2,
            "physical_attempts": len(items) * 3,
            "artifact_writes": len(items) * 2,
            "raw_audit_writes": len(items) * 2,
        }
    )

    source_path = output_dir / "financial-scope-discovery.json"
    source_bytes = (
        json.dumps(scope_report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    source_path.write_bytes(source_bytes)
    receipt = build_financial_scope_capacity_receipt(
        scope_report=scope_report,
        scope_report_sha256=hashlib.sha256(source_bytes).hexdigest(),
        target_trade_date=target_trade_date,
        release_universe_sha256=release_universe_sha256,
        provider_identities_sha256=provider_identities_sha256,
        expected_release_asset_codes=expected_release_asset_codes,
        frozen_provider_identities=tuple(frozen_provider_identities),
    )
    receipt_path = output_dir / "financial-full-scope-capacity.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt_path
