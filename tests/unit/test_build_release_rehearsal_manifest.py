"""Release manifest builder copies only verified candidate-bound artifact graphs."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_release_rehearsal_manifest import REQUIRED_SCHEMAS, build_manifest

CANDIDATE = "c" * 40
DATE = "2026-09-24"
UNIVERSE = "a" * 64
PROVIDERS = "b" * 64
IMAGE_ID = "sha256:" + "d" * 64


def _write(path: Path, value: object) -> str:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _reports(tmp_path: Path) -> dict[str, Path]:
    reports: dict[str, Path] = {}
    for kind, schema in REQUIRED_SCHEMAS.items():
        root = tmp_path / kind
        root.mkdir(parents=True)
        receipt = root / "receipt.json"
        receipt_digest = _write(receipt, {"kind": kind, "evidence": "fixture"})
        report = root / "report.json"
        _write(
            report,
            {
                "schema": schema,
                "kind": kind,
                "outcome": "success",
                "candidate_sha": CANDIDATE,
                "candidate_image_id": IMAGE_ID,
                "target_trade_date": DATE,
                "universe_sha256": UNIVERSE,
                "provider_identities_sha256": PROVIDERS,
                "artifact": {"path": receipt.name, "sha256": receipt_digest},
            },
        )
        reports[kind] = report
    return reports


def test_builder_copies_hash_linked_graph_and_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    path = build_manifest(
        reports=_reports(tmp_path),
        output_dir=output,
        candidate_sha=CANDIDATE,
        target_trade_date=DATE,
        universe_sha256=UNIVERSE,
        provider_identities_sha256=PROVIDERS,
        candidate_image_id=IMAGE_ID,
    )

    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert [item["kind"] for item in manifest["reports"]] == list(REQUIRED_SCHEMAS)
    assert all((output / kind / "receipt.json").is_file() for kind in REQUIRED_SCHEMAS)
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        build_manifest(
            reports=_reports(tmp_path / "second"),
            output_dir=output,
            candidate_sha=CANDIDATE,
            target_trade_date=DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDERS,
            candidate_image_id=IMAGE_ID,
        )


def test_builder_rejects_tampered_child_and_removes_partial_bundle(tmp_path: Path) -> None:
    reports = _reports(tmp_path)
    replay_receipt = reports["real_response_unit_replay"].parent / "receipt.json"
    replay_receipt.write_text("tampered\n", encoding="utf-8")
    output = tmp_path / "bundle"

    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        build_manifest(
            reports=reports,
            output_dir=output,
            candidate_sha=CANDIDATE,
            target_trade_date=DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDERS,
            candidate_image_id=IMAGE_ID,
        )

    assert not output.exists()


def test_builder_rejects_runtime_report_from_another_image(tmp_path: Path) -> None:
    reports = _reports(tmp_path)
    capacity = reports["full_universe_capacity"]
    payload = json.loads(capacity.read_text(encoding="utf-8"))
    payload["candidate_image_id"] = "sha256:" + "e" * 64
    _write(capacity, payload)

    with pytest.raises(ValueError, match="REPORT_MISMATCH"):
        build_manifest(
            reports=reports,
            output_dir=tmp_path / "bundle",
            candidate_sha=CANDIDATE,
            target_trade_date=DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDERS,
            candidate_image_id=IMAGE_ID,
        )


def test_builder_rejects_parent_traversal_and_symlink_artifacts(tmp_path: Path) -> None:
    reports = _reports(tmp_path)
    replay = reports["real_response_unit_replay"]
    outside = tmp_path / "outside.json"
    outside_digest = _write(outside, {"outside": True})
    payload = json.loads(replay.read_text(encoding="utf-8"))
    payload["artifact"] = {"path": "../outside.json", "sha256": outside_digest}
    _write(replay, payload)

    with pytest.raises(ValueError, match="PATH_INVALID"):
        build_manifest(
            reports=reports,
            output_dir=tmp_path / "traversal-bundle",
            candidate_sha=CANDIDATE,
            target_trade_date=DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDERS,
            candidate_image_id=IMAGE_ID,
        )

    reports = _reports(tmp_path / "symlink-source")
    receipt = reports["full_universe_capacity"].parent / "receipt.json"
    receipt.unlink()
    try:
        receipt.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks are unavailable on this platform")
    with pytest.raises(ValueError, match="ARTIFACT_INVALID"):
        build_manifest(
            reports=reports,
            output_dir=tmp_path / "symlink-bundle",
            candidate_sha=CANDIDATE,
            target_trade_date=DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDERS,
            candidate_image_id=IMAGE_ID,
        )
