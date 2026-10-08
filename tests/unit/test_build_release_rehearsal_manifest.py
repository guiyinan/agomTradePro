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
POLICY_SETTINGS = {"status": "active", "default_source": "tushare"}
POLICY_SETTINGS_RAW = (
    json.dumps(POLICY_SETTINGS, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
).encode("utf-8")
POLICY_SETTINGS_RAW_SHA256 = hashlib.sha256(POLICY_SETTINGS_RAW).hexdigest()
POLICY_SETTINGS_CANONICAL_SHA256 = hashlib.sha256(
    json.dumps(
        POLICY_SETTINGS,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
).hexdigest()


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
        report_payload: dict[str, object] = {
            "schema": schema,
            "kind": kind,
            "outcome": "success",
            "candidate_sha": CANDIDATE,
            "candidate_image_id": IMAGE_ID,
            "target_trade_date": DATE,
            "universe_sha256": UNIVERSE,
            "provider_identities_sha256": PROVIDERS,
            "artifact": {"path": receipt.name, "sha256": receipt_digest},
        }
        if kind == "production_policy_parity":
            report_payload.update(
                {
                    "provider_settings": POLICY_SETTINGS,
                    "provider_settings_raw_file_sha256": POLICY_SETTINGS_RAW_SHA256,
                    "provider_settings_canonical_payload_sha256": (
                        POLICY_SETTINGS_CANONICAL_SHA256
                    ),
                }
            )
        if kind == "isolated_database_migrations":
            report_payload.pop("artifact")
            pending = [
                "data_center.0090_financial_publication_capacity_workflow",
                "data_center.0091_financial_capacity_governance_record",
                "data_center.0092_financial_capacity_owner_approval_events",
                "data_center.0093_financial_capacity_slice_ledger",
            ]
            report_payload.update(
                {
                    "candidate_source_attestation": "image_release_manifest",
                    "database_name": "agom_release_rehearsal_attempt_1234",
                    "database_host": "agom-s6-postgres-attempt-1234",
                    "database_address": "172.20.0.3",
                    "database_port": 5432,
                    "database_container_id": "e" * 64,
                    "migration_command": (
                        "python -m scripts.manage_vps_migrations migrate --noinput"
                    ),
                    "migrator_database_role": "agomtradepro_migrator",
                    "pending_before": pending,
                    "pending_after": [],
                    "applied_migrations": pending,
                    "started_at": "2026-09-24T23:40:00+00:00",
                    "finished_at": "2026-09-24T23:41:00+00:00",
                    "evidence_mode": "isolated_postgresql_migrations",
                }
            )
        _write(report, report_payload)
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
        provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
        provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
        candidate_image_id=IMAGE_ID,
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["provider_settings_raw_file_sha256"] == POLICY_SETTINGS_RAW_SHA256
    assert (
        manifest["provider_settings_canonical_payload_sha256"] == POLICY_SETTINGS_CANONICAL_SHA256
    )

    assert [item["kind"] for item in manifest["reports"]] == list(REQUIRED_SCHEMAS)
    assert all(
        (output / kind / "receipt.json").is_file()
        for kind in REQUIRED_SCHEMAS
        if kind != "isolated_database_migrations"
    )
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        build_manifest(
            reports=_reports(tmp_path / "second"),
            output_dir=output,
            candidate_sha=CANDIDATE,
            target_trade_date=DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDERS,
            provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
            provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
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
            provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
            provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
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
            provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
            provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
            candidate_image_id=IMAGE_ID,
        )


def test_builder_accepts_noop_candidate_migration_report(tmp_path: Path) -> None:
    reports = _reports(tmp_path)
    migration_report = reports["isolated_database_migrations"]
    payload = json.loads(migration_report.read_text(encoding="utf-8"))
    payload.update(
        {
            "database_address": "2001:db8::1",
            "pending_before": [],
            "pending_after": [],
            "applied_migrations": [],
        }
    )
    _write(migration_report, payload)

    manifest = build_manifest(
        reports=reports,
        output_dir=tmp_path / "bundle",
        candidate_sha=CANDIDATE,
        target_trade_date=DATE,
        universe_sha256=UNIVERSE,
        provider_identities_sha256=PROVIDERS,
        provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
        provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
        candidate_image_id=IMAGE_ID,
    )

    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert "isolated_database_migrations" in {item["kind"] for item in manifest_payload["reports"]}


def test_builder_requires_isolated_database_migration_report(tmp_path: Path) -> None:
    reports = _reports(tmp_path)
    reports.pop("isolated_database_migrations")

    with pytest.raises(ValueError, match="IDENTITY_INVALID"):
        build_manifest(
            reports=reports,
            output_dir=tmp_path / "bundle",
            candidate_sha=CANDIDATE,
            target_trade_date=DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDERS,
            provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
            provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
            candidate_image_id=IMAGE_ID,
        )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (
            {"pending_after": ["data_center.0093_financial_capacity_slice_ledger"]},
            "MIGRATION_REPORT_INVALID",
        ),
        (
            {"applied_migrations": ["data_center.0090_financial_publication_capacity_workflow"]},
            "MIGRATION_REPORT_INVALID",
        ),
        ({"candidate_image_id": "sha256:" + "e" * 64}, "REPORT_MISMATCH"),
        ({"database_host": "production-db.internal"}, "MIGRATION_REPORT_INVALID"),
        ({"database_address": "production-db.internal"}, "MIGRATION_REPORT_INVALID"),
        ({"database_address": "172.20.0.3/24"}, "MIGRATION_REPORT_INVALID"),
        ({"database_address": "postgresql://172.20.0.3/db"}, "MIGRATION_REPORT_INVALID"),
        ({"database_port": 65536}, "MIGRATION_REPORT_INVALID"),
        ({"database_port": True}, "MIGRATION_REPORT_INVALID"),
        ({"migration_command": "python manage.py migrate"}, "MIGRATION_REPORT_INVALID"),
        ({"migrator_database_role": "agomtradepro_owner"}, "MIGRATION_REPORT_INVALID"),
        (
            {"database_url": "postgresql://user:secret@production/db"},
            "MIGRATION_REPORT_INVALID",
        ),
    ],
)
def test_builder_rejects_invalid_isolated_migration_evidence(
    tmp_path: Path, mutation: dict[str, object], expected_error: str
) -> None:
    reports = _reports(tmp_path)
    migration_report = reports["isolated_database_migrations"]
    payload = json.loads(migration_report.read_text(encoding="utf-8"))
    payload.update(mutation)
    _write(migration_report, payload)

    with pytest.raises(ValueError, match=expected_error):
        build_manifest(
            reports=reports,
            output_dir=tmp_path / "bundle",
            candidate_sha=CANDIDATE,
            target_trade_date=DATE,
            universe_sha256=UNIVERSE,
            provider_identities_sha256=PROVIDERS,
            provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
            provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
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
            provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
            provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
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
            provider_settings_raw_file_sha256=POLICY_SETTINGS_RAW_SHA256,
            provider_settings_canonical_payload_sha256=POLICY_SETTINGS_CANONICAL_SHA256,
            candidate_image_id=IMAGE_ID,
        )
