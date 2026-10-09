"""Adversarial contracts for production-bound S6 financial scope imports."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from django.db import connection

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    GovernedFinancialProductionCeiling,
)
from apps.data_center.application.financial_scope_capacity_import import (
    FinancialScopeCapacityArtifactDigest,
    FinancialScopeCapacityImportError,
    prepare_financial_scope_capacity_import_record,
)
from apps.data_center.application.financial_scope_capacity_receipt import canonical_sha256
from apps.data_center.domain.financial_scope_discovery import FinancialScopeManifestReview
from apps.data_center.infrastructure import (
    financial_scope_capacity_import_runtime as import_runtime,
)
from apps.data_center.infrastructure.models import FinancialScopeCapacityImportModel
from tests.unit.financial_scope_capacity_fixtures import write_financial_scope_capacity_fixture

_CANDIDATE = "a" * 40
_IMAGE = "sha256:" + "b" * 64
_PROVIDER_DIGEST = "c" * 64
_RELEASE_UNIVERSE = "d" * 64
_NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _payloads(
    tmp_path: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    str,
    str,
    tuple[FinancialScopeCapacityArtifactDigest, ...],
]:
    """Write one valid copied graph and return raw-payload identities."""

    capacity_dir = tmp_path / "financial_scope_capacity"
    receipt_path = write_financial_scope_capacity_fixture(
        capacity_dir,
        candidate_image_id=_IMAGE,
        target_trade_date=_NOW.date().isoformat(),
        release_universe_sha256=_RELEASE_UNIVERSE,
        provider_identities_sha256=_PROVIDER_DIGEST,
        now=_NOW,
        scope_report=_scope_report_for_import(),
    )
    receipt_raw = receipt_path.read_bytes()
    receipt = cast(dict[str, object], json.loads(receipt_raw))
    source_path = capacity_dir / "financial-scope-discovery.json"
    source_raw = source_path.read_bytes()
    source = cast(dict[str, object], json.loads(source_raw))
    manifest = {
        "schema": "release.rehearsal-manifest.v1",
        "candidate_sha": _CANDIDATE,
        "target_trade_date": _NOW.date().isoformat(),
        "universe_sha256": _RELEASE_UNIVERSE,
        "provider_identities_sha256": _PROVIDER_DIGEST,
        "provider_settings_raw_file_sha256": "1" * 64,
        "provider_settings_canonical_payload_sha256": "2" * 64,
        "candidate_image_id": _IMAGE,
        "reports": [
            {
                "kind": "financial_scope_capacity",
                "path": "financial_scope_capacity/financial-full-scope-capacity.json",
                "sha256": hashlib.sha256(receipt_raw).hexdigest(),
            }
        ]
        + [
            {"kind": kind, "path": f"{kind}/report.json", "sha256": "3" * 64}
            for kind in (
                "real_response_unit_replay",
                "full_universe_capacity",
                "production_policy_parity",
                "isolated_write_rehearsal",
                "akshare_financial_slice",
                "stage_environment_preflight",
                "isolated_database_migrations",
                "candidate_regression_evidence",
            )
        ],
    }
    manifest_raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    raw_artifacts = source["encrypted_artifacts"]
    assert isinstance(raw_artifacts, list)
    artifacts = tuple(
        FinancialScopeCapacityArtifactDigest(
            path=cast(str, value["path"]),
            size_bytes=cast(int, value["size_bytes"]),
            ciphertext_sha256=cast(str, value["ciphertext_sha256"]),
        )
        for value in raw_artifacts
        if isinstance(value, dict)
    )
    assert len(artifacts) == len(raw_artifacts)
    return (
        manifest,
        receipt,
        source,
        hashlib.sha256(manifest_raw).hexdigest(),
        hashlib.sha256(receipt_raw).hexdigest(),
        artifacts,
    )


def _scope_report_for_import() -> dict[str, object]:
    """Adapt the domain-valid report fixture to the S6 copied encrypted graph."""

    from tests.unit.data_center.test_financial_scope_capacity_input import _report

    report = _report()
    report["candidate_image_id"] = _IMAGE
    report["started_at"] = (_NOW - timedelta(minutes=10)).isoformat()
    report["finished_at"] = _NOW.isoformat()
    report["artifact_root"] = "agom-s6-financial-scope-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    report["encrypted_artifacts"] = [
        {
            "path": (
                "agom-s6-financial-scope-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee/"
                f"v1/00000000-0000-4000-8000-00000000000{index}.frb"
            ),
            "size_bytes": index,
            "ciphertext_sha256": str(index) * 64,
        }
        for index in (1, 2)
    ]
    return report


def _binding(candidate_sha: str = _CANDIDATE) -> FinancialCapacityBinding:
    """Return the exact production provider/parser identity embedded in the fixture."""

    return FinancialCapacityBinding(
        environment="production",
        candidate_sha=candidate_sha,
        provider_id=17,
        provider_name="akshare",
        provider_source="akshare",
        provider_identity_sha256="b" * 64,
        contract_id="akshare.financial-scope.latest-notice",
        contract_version="2026-10-09.v1",
        contract_sha256="c" * 64,
        parser_id="akshare.financial-scope-parser.v1",
        parser_sha256="d" * 64,
        deployment_region="isolated-test",
        publication_policy_version="3",
        publication_policy_sha256="4" * 64,
        isolation_attestation_sha256="",
    )


def _reviews(
    report: dict[str, object],
    *,
    environment: Literal["isolated", "production"] = "production",
    expiry: datetime | None = None,
) -> tuple[FinancialScopeManifestReview, FinancialScopeManifestReview]:
    """Return exact separate production owner and reviewer approvals."""

    result = cast(dict[str, object], report["result"])
    candidate = cast(dict[str, object], result["candidate_manifest"])
    binding = cast(dict[str, object], candidate["binding"])
    universe = cast(dict[str, object], candidate["universe"])
    report_sha256 = canonical_sha256(report)
    generated_at = datetime.fromisoformat(cast(str, candidate["generated_at"]))
    approved_at = generated_at + timedelta(minutes=10)
    end = expiry or (_NOW + timedelta(days=30))
    reviews = tuple(
        FinancialScopeManifestReview(
            candidate_sha=_CANDIDATE,
            manifest_sha256=cast(str, candidate["manifest_sha256"]),
            universe_sha256=cast(str, universe["sha256"]),
            provider_identity_sha256=cast(str, binding["provider_identity_sha256"]),
            contract_sha256=cast(str, binding["contract_sha256"]),
            deployment_region=cast(str, binding["deployment_region"]),
            approval_id=f"production-scope-review-{role}",
            approved_by=f"{role}-approver",
            recorded_by=f"scope-operator-{role}",
            event_id=f"production-scope-event-{role}",
            receipt_sha256=("5" if role == "data_owner" else "6") * 64,
            role=cast(Literal["data_owner", "independent_reviewer"], role),
            environment=environment,
            report_sha256=report_sha256,
            approved_at=approved_at,
            expires_at=end,
        )
        for role in ("data_owner", "independent_reviewer")
    )
    return cast(tuple[FinancialScopeManifestReview, FinancialScopeManifestReview], reviews)


def _ceiling(
    receipt: dict[str, object], *, binding: FinancialCapacityBinding | None = None
) -> GovernedFinancialProductionCeiling:
    """Return the exact currently approved production ceiling for one asset."""

    return GovernedFinancialProductionCeiling(
        approval_id="production-capacity-ceiling",
        approved_by="production-data-owner",
        approved_at=datetime(2026, 10, 10, 11, 0, tzinfo=UTC),
        approval_receipt_sha256="7" * 64,
        receipt_sha256=cast(str, receipt["receipt_sha256"]),
        binding=binding or _binding(),
        manifest_sha256=cast(str, receipt["scope_manifest_sha256"]),
        maximum_slices=1,
        maximum_provider_requests=2,
        expires_at=_NOW + timedelta(days=1),
        approved=True,
    )


def _prepare(
    payloads: tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        str,
        str,
        tuple[FinancialScopeCapacityArtifactDigest, ...],
    ],
    *,
    runtime_binding: FinancialCapacityBinding | None = None,
    active_asset_codes: tuple[str, ...] = ("000001.SZ",),
    reviews: tuple[FinancialScopeManifestReview, ...] | None = None,
    production_ceiling: GovernedFinancialProductionCeiling | None = None,
    now: datetime = _NOW,
) -> dict[str, object]:
    """Invoke the production import validator with its exact frozen inputs."""

    manifest, receipt, source, manifest_sha, receipt_file_sha, artifacts = payloads
    return prepare_financial_scope_capacity_import_record(
        release_manifest=manifest,
        release_manifest_sha256=manifest_sha,
        capacity_receipt=receipt,
        capacity_receipt_raw_sha256=receipt_file_sha,
        scope_report=source,
        scope_report_raw_sha256=cast(str, receipt["scope_report"]["sha256"]),
        artifacts=artifacts,
        runtime_binding=runtime_binding or _binding(),
        active_asset_codes=active_asset_codes,
        reviews=reviews or _reviews(source),
        production_ceiling=production_ceiling or _ceiling(receipt),
        production_ceiling_event_id="production-capacity-owner-event",
        production_ceiling_record_sha256="8" * 64,
        imported_by="production-operator",
        now=now,
    )


def test_import_record_binds_every_hash_review_event_and_exact_production_ceiling(
    tmp_path: Path,
) -> None:
    payloads = _payloads(tmp_path)
    record = _prepare(payloads)

    assert record["schema"] == "data-center.financial-scope-capacity-import.v1"
    assert record["environment"] == "production"
    assert record["receipt_sha256"] == payloads[1]["receipt_sha256"]
    assert record["scope_pointer_sha256"] == payloads[1]["scope_pointer_sha256"]
    assert record["evidence_ledger_sha256"] == payloads[1]["evidence_ledger_sha256"]
    assert record["artifact_ledger_sha256"] == payloads[1]["artifact_ledger_sha256"]
    assert record["record_sha256"] == canonical_sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _write_release_manifest(
    tmp_path: Path,
    payloads: tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        str,
        str,
        tuple[FinancialScopeCapacityArtifactDigest, ...],
    ],
) -> Path:
    manifest = payloads[0]
    path = tmp_path / "release-rehearsal-manifest.json"
    path.write_bytes((json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return path


def test_bundle_reader_revalidates_exact_manifest_receipt_source_and_artifact_graph(
    tmp_path: Path,
) -> None:
    payloads = _payloads(tmp_path)
    _write_release_manifest(tmp_path, payloads)

    snapshot = import_runtime._read_bundle_snapshot(tmp_path)

    assert snapshot.release_manifest_sha256 == payloads[3]
    assert snapshot.capacity_receipt["receipt_sha256"] == payloads[1]["receipt_sha256"]
    assert len(snapshot.artifacts) == 2


def test_bundle_reader_rejects_tampered_ciphertext(tmp_path: Path) -> None:
    payloads = _payloads(tmp_path)
    _write_release_manifest(tmp_path, payloads)
    artifact = tmp_path / "financial_scope_capacity" / payloads[5][0].path
    artifact.write_bytes(b"tampered")

    with pytest.raises(import_runtime.FinancialScopeCapacityImportRuntimeError) as caught:
        import_runtime._read_bundle_snapshot(tmp_path)

    assert caught.value.code == "FINANCIAL_SCOPE_IMPORT_ARTIFACT_DIGEST_INVALID"


@pytest.mark.linux_symlink
def test_bundle_reader_rejects_symlinked_artifact(tmp_path: Path) -> None:
    payloads = _payloads(tmp_path)
    _write_release_manifest(tmp_path, payloads)
    artifact = tmp_path / "financial_scope_capacity" / payloads[5][0].path
    outside = tmp_path / "outside.frb"
    outside.write_bytes(artifact.read_bytes())
    artifact.unlink()
    try:
        artifact.symlink_to(outside)
    except OSError:
        if os.name == "nt":
            pytest.skip("Windows test host does not permit symlink creation")
        raise

    with pytest.raises(import_runtime.FinancialScopeCapacityImportRuntimeError) as caught:
        import_runtime._read_bundle_snapshot(tmp_path)

    assert caught.value.code in {
        "FINANCIAL_SCOPE_IMPORT_SYMLINK_FORBIDDEN",
        "FINANCIAL_SCOPE_IMPORT_FILE_INVALID",
    }


def test_bundle_reader_detects_same_size_file_change_during_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = _payloads(tmp_path)
    _write_release_manifest(tmp_path, payloads)
    artifact = tmp_path / "financial_scope_capacity" / payloads[5][0].path
    read_descriptor = import_runtime._read_descriptor

    def change_after_read(descriptor: int, limit: int) -> bytes:
        raw = read_descriptor(descriptor, limit)
        artifact.write_bytes(b"x" * len(raw))
        return raw

    monkeypatch.setattr(import_runtime, "_read_descriptor", change_after_read)
    with pytest.raises(import_runtime.FinancialScopeCapacityImportRuntimeError) as caught:
        import_runtime._read_checked_file(
            tmp_path,
            f"financial_scope_capacity/{payloads[5][0].path}",
            import_runtime._MAX_BUNDLE_BYTES,
        )

    assert caught.value.code == "FINANCIAL_SCOPE_IMPORT_FILE_CHANGED"


def test_bundle_reader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    with pytest.raises(import_runtime.FinancialScopeCapacityImportRuntimeError) as caught:
        import_runtime._parse_json_object(b'{"schema":"one","schema":"two"}')

    assert caught.value.code == "FINANCIAL_SCOPE_IMPORT_JSON_INVALID"


def _patch_runtime_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace production-only live reads while keeping the ledger transaction real."""

    monkeypatch.setattr(import_runtime, "_require_production_database", lambda: None)
    monkeypatch.setattr(import_runtime, "_load_runtime_binding", lambda manifest: _binding())
    monkeypatch.setattr(import_runtime, "_load_active_asset_codes", lambda: ("000001.SZ",))
    monkeypatch.setattr(
        import_runtime,
        "_load_reviews",
        lambda *, candidate, report_sha256, now: _reviews(
            {"result": {"candidate_manifest": {"generated_at": _NOW.isoformat()}}}
        ),
    )


def _patch_runtime_for_fixture(
    monkeypatch: pytest.MonkeyPatch,
    source_report: dict[str, object],
    receipt: dict[str, object],
) -> None:
    """Install exact fixture approvals for the real append-only import transaction."""

    _patch_runtime_sources(monkeypatch)
    monkeypatch.setattr(
        import_runtime,
        "_load_reviews",
        lambda *, candidate, report_sha256, now: _reviews(source_report),
    )
    monkeypatch.setattr(
        import_runtime,
        "_load_production_ceiling",
        lambda *, receipt_sha256, candidate_sha, manifest_sha256: _ceiling(receipt),
    )
    monkeypatch.setattr(
        import_runtime,
        "_production_ceiling_event_identity",
        lambda ceiling: ("production-capacity-owner-event", "8" * 64),
    )
    monkeypatch.setattr(import_runtime, "_lock_authority_rows", lambda **kwargs: None)


def _table_counts() -> dict[str, int]:
    """Return row counts to prove import only writes its own append-only ledger."""

    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names(cursor):
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")
            row = cursor.fetchone()
            counts[table] = 0 if row is None else int(row[0])
    return counts


@pytest.mark.django_db
def test_import_appends_only_ledger_record_and_rejects_duplicate_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = _payloads(tmp_path)
    _write_release_manifest(tmp_path, payloads)
    _patch_runtime_for_fixture(monkeypatch, payloads[2], payloads[1])
    before = _table_counts()

    imported = import_runtime.import_financial_scope_capacity_bundle(
        bundle_dir=tmp_path,
        imported_by="production-operator",
        now=_NOW,
    )

    after = _table_counts()
    assert imported.environment == "production"
    assert FinancialScopeCapacityImportModel._default_manager.count() == 1
    assert (
        after[FinancialScopeCapacityImportModel._meta.db_table]
        == before[FinancialScopeCapacityImportModel._meta.db_table] + 1
    )
    changed_tables = {table for table in before if before[table] != after[table]}
    assert changed_tables == {FinancialScopeCapacityImportModel._meta.db_table}
    with pytest.raises(import_runtime.FinancialScopeCapacityImportRuntimeError) as caught:
        import_runtime.import_financial_scope_capacity_bundle(
            bundle_dir=tmp_path,
            imported_by="production-operator",
            now=_NOW,
        )
    assert caught.value.code == "FINANCIAL_SCOPE_IMPORT_DUPLICATE"


@pytest.mark.django_db
def test_import_rechecks_review_revocation_before_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = _payloads(tmp_path)
    _write_release_manifest(tmp_path, payloads)
    _patch_runtime_for_fixture(monkeypatch, payloads[2], payloads[1])
    review_calls = 0

    def revoke_between_checks(
        *, candidate: object, report_sha256: str, now: datetime
    ) -> tuple[FinancialScopeManifestReview, FinancialScopeManifestReview]:
        nonlocal review_calls
        review_calls += 1
        if review_calls > 1:
            raise import_runtime.FinancialScopeCapacityImportRuntimeError(
                "FINANCIAL_SCOPE_IMPORT_AUTHORITY_REVOKED"
            )
        return _reviews(payloads[2])

    monkeypatch.setattr(import_runtime, "_load_reviews", revoke_between_checks)

    with pytest.raises(import_runtime.FinancialScopeCapacityImportRuntimeError) as caught:
        import_runtime.import_financial_scope_capacity_bundle(
            bundle_dir=tmp_path,
            imported_by="production-operator",
            now=_NOW,
        )

    assert caught.value.code == "FINANCIAL_SCOPE_IMPORT_AUTHORITY_REVOKED"
    assert FinancialScopeCapacityImportModel._default_manager.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("change", ("candidate", "universe"))
def test_import_rejects_runtime_candidate_or_universe_change_before_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    payloads = _payloads(tmp_path)
    _write_release_manifest(tmp_path, payloads)
    _patch_runtime_for_fixture(monkeypatch, payloads[2], payloads[1])
    if change == "candidate":
        bindings = iter((_binding(), _binding("f" * 40)))
        monkeypatch.setattr(
            import_runtime,
            "_load_runtime_binding",
            lambda manifest: next(bindings),
        )
        expected_code = "FINANCIAL_SCOPE_IMPORT_RUNTIME_BINDING_CHANGED"
    else:
        active_asset_codes = iter((("000001.SZ",), ("000002.SZ",)))
        monkeypatch.setattr(
            import_runtime,
            "_load_active_asset_codes",
            lambda: next(active_asset_codes),
        )
        expected_code = "FINANCIAL_SCOPE_IMPORT_UNIVERSE_CHANGED"

    with pytest.raises(import_runtime.FinancialScopeCapacityImportRuntimeError) as caught:
        import_runtime.import_financial_scope_capacity_bundle(
            bundle_dir=tmp_path,
            imported_by="production-operator",
            now=_NOW,
        )

    assert caught.value.code == expected_code
    assert FinancialScopeCapacityImportModel._default_manager.count() == 0


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("candidate", "FINANCIAL_SCOPE_IMPORT_CANDIDATE_MISMATCH"),
        ("provider", "FINANCIAL_SCOPE_IMPORT_PROVIDER_MISMATCH"),
        ("universe", "FINANCIAL_SCOPE_IMPORT_UNIVERSE_MISMATCH"),
        ("environment", "FINANCIAL_SCOPE_IMPORT_REVIEW_REQUIRED"),
        ("expired_review", "FINANCIAL_SCOPE_IMPORT_REVIEW_REQUIRED"),
        ("ceiling", "FINANCIAL_SCOPE_IMPORT_CEILING_INVALID"),
        ("receipt_universe", "FINANCIAL_SCOPE_IMPORT_RECEIPT_INVALID"),
        ("artifact", "FINANCIAL_SCOPE_IMPORT_ARTIFACT_MISMATCH"),
    ],
)
def test_import_record_rejects_mismatched_or_stale_authority(
    tmp_path: Path, case: str, code: str
) -> None:
    payloads = _payloads(tmp_path)
    manifest, receipt, source, manifest_sha, receipt_file_sha, artifacts = payloads
    runtime_binding: FinancialCapacityBinding | None = None
    active_asset_codes = ("000001.SZ",)
    reviews: tuple[FinancialScopeManifestReview, ...] | None = None
    ceiling: GovernedFinancialProductionCeiling | None = None
    if case == "candidate":
        runtime_binding = _binding("f" * 40)
    elif case == "provider":
        runtime_binding = replace(_binding(), provider_identity_sha256="0" * 64)
    elif case == "universe":
        active_asset_codes = ("000002.SZ",)
    elif case == "environment":
        reviews = _reviews(source, environment="isolated")
    elif case == "expired_review":
        reviews = _reviews(source, expiry=_NOW - timedelta(seconds=1))
    elif case == "ceiling":
        ceiling = replace(_ceiling(receipt), maximum_slices=2, maximum_provider_requests=4)
    elif case == "receipt_universe":
        manifest["universe_sha256"] = "0" * 64
    elif case == "artifact":
        changed = list(artifacts)
        changed[0] = replace(changed[0], ciphertext_sha256="0" * 64)
        artifacts = tuple(changed)

    with pytest.raises(FinancialScopeCapacityImportError) as caught:
        prepare_financial_scope_capacity_import_record(
            release_manifest=manifest,
            release_manifest_sha256=manifest_sha,
            capacity_receipt=receipt,
            capacity_receipt_raw_sha256=receipt_file_sha,
            scope_report=source,
            scope_report_raw_sha256=cast(str, receipt["scope_report"]["sha256"]),
            artifacts=artifacts,
            runtime_binding=runtime_binding or _binding(),
            active_asset_codes=active_asset_codes,
            reviews=reviews or _reviews(source),
            production_ceiling=ceiling or _ceiling(receipt),
            production_ceiling_event_id="production-capacity-owner-event",
            production_ceiling_record_sha256="8" * 64,
            imported_by="production-operator",
            now=_NOW,
        )
    assert caught.value.code == code
