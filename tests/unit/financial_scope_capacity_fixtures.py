"""Filesystem fixture for the S6 financial scope receipt and its copied graph."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
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
    now: datetime,
    scope_report: dict[str, object] | None = None,
) -> Path:
    """Write a complete source report, encrypted artifact tree, and capacity receipt."""

    output_dir.mkdir(parents=True, exist_ok=True)
    scope_report = _scope_report() if scope_report is None else scope_report
    scope_report["candidate_image_id"] = candidate_image_id
    scope_report["started_at"] = (now.replace(microsecond=0)).isoformat()
    scope_report["finished_at"] = (now.replace(microsecond=0)).isoformat()
    artifacts = scope_report["encrypted_artifacts"]
    root_name = str(scope_report["artifact_root"])
    artifact_root = output_dir / root_name
    artifact_root.mkdir()
    if not isinstance(artifacts, list):
        raise AssertionError("scope fixture artifacts must be a list")
    for index, raw_artifact in enumerate(artifacts, start=1):
        if not isinstance(raw_artifact, dict):
            raise AssertionError("scope fixture artifact must be a mapping")
        relative = str(raw_artifact["path"]).removeprefix(f"{root_name}/")
        artifact_path = output_dir / str(raw_artifact["path"])
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        content = f"encrypted-financial-capture-{index}".encode("ascii")
        artifact_path.write_bytes(content)
        raw_artifact["size_bytes"] = len(content)
        raw_artifact["ciphertext_sha256"] = hashlib.sha256(content).hexdigest()
        if not (artifact_root / relative).is_file():
            raise AssertionError("scope fixture artifact path did not resolve")

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
    )
    receipt_path = output_dir / "financial-full-scope-capacity.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt_path
