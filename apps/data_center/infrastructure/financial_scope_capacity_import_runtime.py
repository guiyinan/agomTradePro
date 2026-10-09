"""Read, revalidate, and append one production S6 capacity handoff record."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

from django.conf import settings
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    FinancialCapacityWorkflowError,
    GovernedFinancialProductionCeiling,
)
from apps.data_center.application.financial_scope_capacity_import import (
    FinancialScopeCapacityArtifactDigest,
    FinancialScopeCapacityImportError,
    prepare_financial_scope_capacity_import_record,
)
from apps.data_center.application.financial_scope_capacity_input import (
    FinancialScopeCapacityInputError,
    _parse_reviewable_report,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryCandidate,
    FinancialScopeDiscoveryError,
    FinancialScopeManifestReview,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.infrastructure.financial_capacity_governance import (
    DjangoFinancialCapacityGovernanceSource,
)
from apps.data_center.infrastructure.financial_publication_capacity_runtime import (
    DjangoFinancialCapacityBindingSource,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeDiscoveryUniverseSource,
    DjangoFinancialScopeManifestReviewSource,
)
from apps.data_center.infrastructure.models import (
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityOwnerApprovalEventModel,
    FinancialScopeCapacityImportModel,
)
from shared.release_rehearsal_file_io import RehearsalFileReadError, read_regular_file

_MAX_BUNDLE_BYTES = 64 * 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024
_ARTIFACT_RELATIVE_PATH = re.compile(
    r"^agom-s6-financial-scope-[0-9a-f]{32}/v1/[0-9a-f-]{8}-[0-9a-f-]{4}-"
    r"[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.frb$"
)
_HEX_256 = re.compile(r"^[0-9a-f]{64}$")
_REPORT_PATH = "financial_scope_capacity/financial-full-scope-capacity.json"
_MANIFEST_PATH = "release-rehearsal-manifest.json"


class FinancialScopeCapacityImportRuntimeError(FinancialScopeCapacityImportError):
    """One stable failure at the filesystem/database import boundary."""


@dataclass(frozen=True, slots=True)
class _BundleSnapshot:
    """Immutable parsed bytes and hashes from one exact copied handoff graph."""

    release_manifest: dict[str, object]
    release_manifest_sha256: str
    capacity_receipt: dict[str, object]
    capacity_receipt_raw_sha256: str
    scope_report: dict[str, object]
    scope_report_raw_sha256: str
    artifacts: tuple[FinancialScopeCapacityArtifactDigest, ...]


def import_financial_scope_capacity_bundle(
    *, bundle_dir: Path, imported_by: str, now: datetime | None = None
) -> FinancialScopeCapacityImportModel:
    """Append one exact production import record without touching facts or publications."""

    _require_production_database()
    observed_now = now or timezone.now()
    if not _is_aware(observed_now):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_TIME_INVALID")
    first_snapshot = _read_bundle_snapshot(bundle_dir)
    runtime_binding = _load_runtime_binding(first_snapshot.release_manifest)
    active_asset_codes = _load_active_asset_codes()
    candidate, canonical_report_sha256 = _parse_scope_report(first_snapshot.scope_report)
    reviews = _load_reviews(
        candidate=candidate,
        report_sha256=canonical_report_sha256,
        now=observed_now,
    )
    receipt_sha256 = _text(first_snapshot.capacity_receipt, "receipt_sha256")
    production_ceiling = _load_production_ceiling(
        receipt_sha256=receipt_sha256,
        candidate_sha=runtime_binding.candidate_sha,
        manifest_sha256=candidate.manifest_sha256,
    )
    ceiling_event_id, ceiling_record_sha256 = _production_ceiling_event_identity(production_ceiling)
    initial_record = prepare_financial_scope_capacity_import_record(
        release_manifest=first_snapshot.release_manifest,
        release_manifest_sha256=first_snapshot.release_manifest_sha256,
        capacity_receipt=first_snapshot.capacity_receipt,
        capacity_receipt_raw_sha256=first_snapshot.capacity_receipt_raw_sha256,
        scope_report=first_snapshot.scope_report,
        scope_report_raw_sha256=first_snapshot.scope_report_raw_sha256,
        artifacts=first_snapshot.artifacts,
        runtime_binding=runtime_binding,
        active_asset_codes=active_asset_codes,
        reviews=reviews,
        production_ceiling=production_ceiling,
        production_ceiling_event_id=ceiling_event_id,
        production_ceiling_record_sha256=ceiling_record_sha256,
        imported_by=imported_by,
        now=observed_now,
    )

    try:
        with transaction.atomic():
            _lock_authority_rows(
                owner_approval_id=_review_field(initial_record, "owner_approval_id"),
                reviewer_approval_id=_review_field(initial_record, "reviewer_approval_id"),
                ceiling_approval_id=production_ceiling.approval_id,
            )
            second_snapshot = _read_bundle_snapshot(bundle_dir)
            if not _same_snapshot(first_snapshot, second_snapshot):
                raise FinancialScopeCapacityImportRuntimeError(
                    "FINANCIAL_SCOPE_IMPORT_BUNDLE_CHANGED"
                )
            reviews = _load_reviews(
                candidate=candidate,
                report_sha256=canonical_report_sha256,
                now=observed_now,
            )
            refreshed_binding = _load_runtime_binding(second_snapshot.release_manifest)
            if refreshed_binding != runtime_binding:
                raise FinancialScopeCapacityImportRuntimeError(
                    "FINANCIAL_SCOPE_IMPORT_RUNTIME_BINDING_CHANGED"
                )
            refreshed_asset_codes = _load_active_asset_codes()
            if refreshed_asset_codes != active_asset_codes:
                raise FinancialScopeCapacityImportRuntimeError(
                    "FINANCIAL_SCOPE_IMPORT_UNIVERSE_CHANGED"
                )
            production_ceiling = _load_production_ceiling(
                receipt_sha256=receipt_sha256,
                candidate_sha=runtime_binding.candidate_sha,
                manifest_sha256=candidate.manifest_sha256,
            )
            ceiling_event_id, ceiling_record_sha256 = _production_ceiling_event_identity(
                production_ceiling
            )
            record = prepare_financial_scope_capacity_import_record(
                release_manifest=second_snapshot.release_manifest,
                release_manifest_sha256=second_snapshot.release_manifest_sha256,
                capacity_receipt=second_snapshot.capacity_receipt,
                capacity_receipt_raw_sha256=second_snapshot.capacity_receipt_raw_sha256,
                scope_report=second_snapshot.scope_report,
                scope_report_raw_sha256=second_snapshot.scope_report_raw_sha256,
                artifacts=second_snapshot.artifacts,
                runtime_binding=refreshed_binding,
                active_asset_codes=refreshed_asset_codes,
                reviews=reviews,
                production_ceiling=production_ceiling,
                production_ceiling_event_id=ceiling_event_id,
                production_ceiling_record_sha256=ceiling_record_sha256,
                imported_by=imported_by,
                now=observed_now,
            )
            _reject_replay(record)
            model = _model_from_record(record)
            model.save(force_insert=True)
            return model
    except FinancialScopeCapacityImportRuntimeError:
        raise
    except FinancialScopeCapacityImportError:
        raise
    except IntegrityError:
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_DUPLICATE") from None
    except (DatabaseError, OSError, RuntimeError, TypeError, ValueError):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_REVALIDATION_FAILED"
        ) from None


def _require_production_database() -> None:
    """Fail closed unless this command is running against a production PostgreSQL DB."""

    database = connection.settings_dict
    name = database.get("NAME")
    host = database.get("HOST")
    settings_module = getattr(settings, "SETTINGS_MODULE", "")
    if (
        bool(getattr(settings, "DEBUG", True))
        or type(settings_module) is not str
        or not settings_module.endswith(".production")
        or connection.vendor != "postgresql"
        or type(name) is not str
        or name.lower().startswith("agom_release_rehearsal_")
        or (type(host) is str and host.startswith("agom-s6-postgres-"))
    ):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_ENVIRONMENT_INVALID")


def _read_bundle_snapshot(bundle_dir: Path) -> _BundleSnapshot:
    root = _checked_bundle_root(bundle_dir)
    manifest_raw = _read_checked_file(root, _MANIFEST_PATH, _MAX_JSON_BYTES)
    manifest = _parse_json_object(manifest_raw)
    receipt_raw = _read_checked_file(root, _REPORT_PATH, _MAX_JSON_BYTES)
    receipt = _parse_json_object(receipt_raw)
    if _manifest_capacity_digest(manifest) != _sha256(receipt_raw):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_MANIFEST_BINDING_INVALID"
        )
    source_ref = receipt.get("scope_report")
    if (
        not isinstance(source_ref, Mapping)
        or source_ref.get("path") != "financial-scope-discovery.json"
    ):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_SOURCE_INVALID")
    source_path = "financial_scope_capacity/financial-scope-discovery.json"
    source_raw = _read_checked_file(root, source_path, _MAX_JSON_BYTES)
    if source_ref.get("sha256") != _sha256(source_raw):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_SOURCE_DIGEST_INVALID"
        )
    source = _parse_json_object(source_raw)
    raw_artifacts = source.get("encrypted_artifacts")
    artifact_root = source.get("artifact_root")
    if (
        not isinstance(raw_artifacts, list)
        or type(artifact_root) is not str
        or re.fullmatch(r"agom-s6-financial-scope-[0-9a-f]{32}", artifact_root) is None
    ):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_ARTIFACT_INVALID")
    artifact_digests: list[FinancialScopeCapacityArtifactDigest] = []
    expected_paths: set[str] = set()
    total_bytes = len(manifest_raw) + len(receipt_raw) + len(source_raw)
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, Mapping):
            raise FinancialScopeCapacityImportRuntimeError(
                "FINANCIAL_SCOPE_IMPORT_ARTIFACT_INVALID"
            )
        relative = _text(raw_artifact, "path")
        if _ARTIFACT_RELATIVE_PATH.fullmatch(relative) is None or not relative.startswith(
            f"{artifact_root}/"
        ):
            raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_PATH_INVALID")
        bundle_relative = f"financial_scope_capacity/{relative}"
        ciphertext = _read_checked_file(root, bundle_relative, _MAX_BUNDLE_BYTES)
        total_bytes += len(ciphertext)
        if total_bytes > _MAX_BUNDLE_BYTES:
            raise FinancialScopeCapacityImportRuntimeError(
                "FINANCIAL_SCOPE_IMPORT_BUNDLE_TOO_LARGE"
            )
        expected_digest = _text(raw_artifact, "ciphertext_sha256")
        expected_size = raw_artifact.get("size_bytes")
        actual_digest = _sha256(ciphertext)
        if (
            _HEX_256.fullmatch(expected_digest) is None
            or type(expected_size) is not int
            or expected_size != len(ciphertext)
            or expected_digest != actual_digest
            or relative in expected_paths
        ):
            raise FinancialScopeCapacityImportRuntimeError(
                "FINANCIAL_SCOPE_IMPORT_ARTIFACT_DIGEST_INVALID"
            )
        expected_paths.add(relative)
        artifact_digests.append(
            FinancialScopeCapacityArtifactDigest(
                path=relative,
                size_bytes=len(ciphertext),
                ciphertext_sha256=actual_digest,
            )
        )
    listed_paths = _list_checked_artifact_paths(root, artifact_root)
    if listed_paths != expected_paths:
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_ARTIFACT_LEDGER_MISMATCH"
        )
    return _BundleSnapshot(
        release_manifest=manifest,
        release_manifest_sha256=_sha256(manifest_raw),
        capacity_receipt=receipt,
        capacity_receipt_raw_sha256=_sha256(receipt_raw),
        scope_report=source,
        scope_report_raw_sha256=_sha256(source_raw),
        artifacts=tuple(artifact_digests),
    )


def _checked_bundle_root(bundle_dir: Path) -> Path:
    if not bundle_dir.is_absolute():
        bundle_dir = bundle_dir.absolute()
    _assert_no_symlink_chain(bundle_dir, invalid_code="FINANCIAL_SCOPE_IMPORT_BUNDLE_INVALID")
    if not bundle_dir.is_dir():
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_BUNDLE_INVALID")
    return bundle_dir.resolve(strict=True)


def _read_checked_file(root: Path, relative: str, limit: int) -> bytes:
    try:
        return read_regular_file(root, relative, limit)
    except RehearsalFileReadError as exc:
        code = {
            "file_too_large": "FINANCIAL_SCOPE_IMPORT_FILE_TOO_LARGE",
            "file_changed": "FINANCIAL_SCOPE_IMPORT_FILE_CHANGED",
            "symlink_forbidden": "FINANCIAL_SCOPE_IMPORT_SYMLINK_FORBIDDEN",
        }.get(str(exc), "FINANCIAL_SCOPE_IMPORT_FILE_INVALID")
        raise FinancialScopeCapacityImportRuntimeError(code) from None


def _list_checked_artifact_paths(root: Path, artifact_root: str) -> set[str]:
    relative_root = f"financial_scope_capacity/{artifact_root}"
    directory = root / relative_root
    try:
        metadata = directory.lstat()
    except OSError:
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_ARTIFACT_INVALID"
        ) from None
    _assert_no_symlink_chain(directory)
    if not stat.S_ISDIR(metadata.st_mode) or _is_symlink_or_reparse_point(metadata):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_SYMLINK_FORBIDDEN")
    observed: set[str] = set()
    for current, directories, files in os.walk(directory, followlinks=False):
        current_path = Path(current)
        if _is_symlink_or_reparse_point(current_path.lstat()):
            raise FinancialScopeCapacityImportRuntimeError(
                "FINANCIAL_SCOPE_IMPORT_SYMLINK_FORBIDDEN"
            )
        for name in directories:
            entry = current_path / name
            info = entry.lstat()
            if _is_symlink_or_reparse_point(info) or not stat.S_ISDIR(info.st_mode):
                raise FinancialScopeCapacityImportRuntimeError(
                    "FINANCIAL_SCOPE_IMPORT_SYMLINK_FORBIDDEN"
                )
        for name in files:
            entry = current_path / name
            info = entry.lstat()
            if _is_symlink_or_reparse_point(info) or not stat.S_ISREG(info.st_mode):
                raise FinancialScopeCapacityImportRuntimeError(
                    "FINANCIAL_SCOPE_IMPORT_SYMLINK_FORBIDDEN"
                )
            observed.add(entry.relative_to(root / "financial_scope_capacity").as_posix())
    _assert_no_symlink_chain(directory)
    return observed


def _parse_json_object(raw: bytes) -> dict[str, object]:
    try:
        value: object = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_JSON_INVALID"
        ) from None
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_JSON_INVALID")
    return cast(dict[str, object], value)


def _reject_json_constant(value: str) -> None:
    raise ValueError(value)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _parse_scope_report(
    report: object,
) -> tuple[FinancialScopeDiscoveryCandidate, str]:
    try:
        return _parse_reviewable_report(report, environment="isolated")
    except (FinancialScopeCapacityInputError, FinancialScopeDiscoveryError, TypeError, ValueError):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_SOURCE_INVALID"
        ) from None


def _load_runtime_binding(manifest: Mapping[str, object]) -> FinancialCapacityBinding:
    candidate_sha = _text(manifest, "candidate_sha")
    try:
        source = FileFinancialCapacityBuildIdentitySource(Path(settings.AGOM_BUILD_IDENTITY_PATH))
        if source.source_commit() != candidate_sha:
            raise FinancialScopeCapacityImportRuntimeError(
                "FINANCIAL_SCOPE_IMPORT_CANDIDATE_MISMATCH"
            )
        return DjangoFinancialCapacityBindingSource().snapshot(
            environment="production",
            candidate_sha=candidate_sha,
        )
    except FinancialScopeCapacityImportError:
        raise
    except (FinancialCapacityWorkflowError, OSError, RuntimeError, TypeError, ValueError):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_RUNTIME_BINDING_INVALID"
        ) from None


def _load_active_asset_codes() -> tuple[str, ...]:
    try:
        codes = DjangoFinancialScopeDiscoveryUniverseSource().get_active_asset_codes()
    except (DatabaseError, RuntimeError, TypeError, ValueError):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_UNIVERSE_UNAVAILABLE"
        ) from None
    if not codes or codes != tuple(sorted(set(codes))):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_UNIVERSE_INVALID")
    return codes


def _load_reviews(
    *, candidate: FinancialScopeDiscoveryCandidate, report_sha256: str, now: datetime
) -> tuple[FinancialScopeManifestReview, ...]:
    try:
        reviews = DjangoFinancialScopeManifestReviewSource().get(
            candidate=candidate,
            environment="production",
            report_sha256=report_sha256,
            now=now,
        )
    except (DatabaseError, FinancialScopeCapacityInputError, RuntimeError, TypeError, ValueError):
        reviews = None
    if reviews is None or len(reviews) != 2:
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_REVIEW_REQUIRED")
    return reviews


def _load_production_ceiling(
    *, receipt_sha256: str, candidate_sha: str, manifest_sha256: str
) -> GovernedFinancialProductionCeiling:
    try:
        ceiling = DjangoFinancialCapacityGovernanceSource().get(
            receipt_sha256=receipt_sha256,
            candidate_sha=candidate_sha,
            manifest_sha256=manifest_sha256,
        )
    except (DatabaseError, FinancialCapacityWorkflowError, RuntimeError, TypeError, ValueError):
        ceiling = None
    if ceiling is None:
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_CEILING_REQUIRED")
    return ceiling


def _production_ceiling_event_identity(
    ceiling: GovernedFinancialProductionCeiling,
) -> tuple[str, str]:
    try:
        row = FinancialCapacityGovernanceRecordModel._default_manager.select_related(
            "owner_approval_event"
        ).get(
            stage=FinancialCapacityGovernanceRecordModel.PRODUCTION,
            approval_id=ceiling.approval_id,
            revocation__isnull=True,
        )
        event = row.owner_approval_event
        record_digest = _canonical_sha256(row.record)
        if (
            not event.event_id
            or event.approved_by != ceiling.approved_by
            or event.approved_at != ceiling.approved_at
            or event.approval_receipt_sha256 != ceiling.approval_receipt_sha256
            or event.record_sha256 != record_digest
        ):
            raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_CEILING_INVALID")
        return event.event_id, record_digest
    except FinancialScopeCapacityImportRuntimeError:
        raise
    except (DatabaseError, FinancialCapacityOwnerApprovalEventModel.DoesNotExist):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_CEILING_REQUIRED"
        ) from None


def _lock_authority_rows(
    *, owner_approval_id: str, reviewer_approval_id: str, ceiling_approval_id: str
) -> None:
    approval_ids = (owner_approval_id, reviewer_approval_id, ceiling_approval_id)
    rows = tuple(
        FinancialCapacityGovernanceRecordModel._default_manager.select_for_update()
        .filter(approval_id__in=approval_ids, revocation__isnull=True)
        .order_by("approval_id")
    )
    if len(rows) != len(set(approval_ids)):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_AUTHORITY_REVOKED")


def _reject_replay(record: Mapping[str, object]) -> None:
    receipt_sha256 = _text(record, "receipt_sha256")
    pointer_sha256 = _text(record, "scope_pointer_sha256")
    review = record.get("review")
    ceiling = record.get("production_ceiling")
    if not isinstance(review, Mapping) or not isinstance(ceiling, Mapping):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_RECORD_INVALID")
    event_ids = (
        _text(review, "owner_event_id"),
        _text(review, "reviewer_event_id"),
        _text(ceiling, "event_id"),
    )
    if (
        FinancialScopeCapacityImportModel._default_manager.filter(
            receipt_sha256=receipt_sha256
        ).exists()
        or FinancialScopeCapacityImportModel._default_manager.filter(
            scope_pointer_sha256=pointer_sha256
        ).exists()
        or FinancialScopeCapacityImportModel._default_manager.filter(
            owner_event_id__in=event_ids
        ).exists()
        or FinancialScopeCapacityImportModel._default_manager.filter(
            reviewer_event_id__in=event_ids
        ).exists()
        or FinancialScopeCapacityImportModel._default_manager.filter(
            production_ceiling_event_id__in=event_ids
        ).exists()
    ):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_DUPLICATE")


def _model_from_record(record: dict[str, object]) -> FinancialScopeCapacityImportModel:
    review = _mapping(record.get("review"))
    ceiling = _mapping(record.get("production_ceiling"))
    try:
        target_trade_date = date.fromisoformat(_text(record, "target_trade_date"))
        financial_provider_id = _positive_int(record, "financial_provider_id")
        return FinancialScopeCapacityImportModel(
            release_manifest_sha256=_text(record, "release_manifest_sha256"),
            capacity_receipt_raw_sha256=_text(record, "capacity_receipt_raw_sha256"),
            scope_report_raw_sha256=_text(record, "scope_report_raw_sha256"),
            scope_report_review_sha256=_text(record, "scope_report_review_sha256"),
            receipt_sha256=_text(record, "receipt_sha256"),
            scope_pointer_sha256=_text(record, "scope_pointer_sha256"),
            candidate_sha=_text(record, "candidate_sha"),
            candidate_image_id=_text(record, "candidate_image_id"),
            target_trade_date=target_trade_date,
            release_universe_sha256=_text(record, "release_universe_sha256"),
            provider_identities_sha256=_text(record, "provider_identities_sha256"),
            scope_manifest_sha256=_text(record, "scope_manifest_sha256"),
            financial_universe_sha256=_text(record, "financial_universe_sha256"),
            financial_provider_id=financial_provider_id,
            financial_provider_identity_sha256=_text(record, "financial_provider_identity_sha256"),
            source_revision_sha256=_text(record, "source_revision_sha256"),
            evidence_ledger_sha256=_text(record, "evidence_ledger_sha256"),
            artifact_ledger_sha256=_text(record, "artifact_ledger_sha256"),
            owner_approval_id=_text(review, "owner_approval_id"),
            owner_event_id=_text(review, "owner_event_id"),
            reviewer_approval_id=_text(review, "reviewer_approval_id"),
            reviewer_event_id=_text(review, "reviewer_event_id"),
            production_ceiling_approval_id=_text(ceiling, "approval_id"),
            production_ceiling_event_id=_text(ceiling, "event_id"),
            production_ceiling_record_sha256=_text(ceiling, "record_sha256"),
            record_payload=record,
            record_sha256=_text(record, "record_sha256"),
            imported_by=_text(record, "imported_by"),
            imported_at=datetime.fromisoformat(_text(record, "imported_at")),
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialScopeCapacityImportRuntimeError(
            "FINANCIAL_SCOPE_IMPORT_RECORD_INVALID"
        ) from None


def _same_snapshot(left: _BundleSnapshot, right: _BundleSnapshot) -> bool:
    return (
        left.release_manifest_sha256 == right.release_manifest_sha256
        and left.capacity_receipt_raw_sha256 == right.capacity_receipt_raw_sha256
        and left.scope_report_raw_sha256 == right.scope_report_raw_sha256
        and left.artifacts == right.artifacts
    )


def _manifest_capacity_digest(manifest: Mapping[str, object]) -> str:
    reports = manifest.get("reports")
    if not isinstance(reports, list):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    matches = [
        value
        for value in reports
        if isinstance(value, Mapping) and value.get("kind") == "financial_scope_capacity"
    ]
    if len(matches) != 1 or matches[0].get("path") != _REPORT_PATH:
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    return _text(matches[0], "sha256")


def _relative_parts(relative: str) -> tuple[str, ...]:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or ":" in relative
    ):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_PATH_INVALID")
    return tuple(relative.split("/"))


def _assert_no_symlink_chain(path: Path, *, invalid_code: str | None = None) -> None:
    """Reject symlinks and Windows reparse points in every exact path component."""

    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError:
            code = invalid_code or "FINANCIAL_SCOPE_IMPORT_FILE_INVALID"
            raise FinancialScopeCapacityImportRuntimeError(code) from None
        if _is_symlink_or_reparse_point(metadata):
            raise FinancialScopeCapacityImportRuntimeError(
                "FINANCIAL_SCOPE_IMPORT_SYMLINK_FORBIDDEN"
            )


def _is_symlink_or_reparse_point(metadata: os.stat_result) -> bool:
    """Recognize symbolic links plus Windows junction/reparse entries."""

    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(file_attributes & reparse_flag)


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_RECORD_INVALID")
    return cast(Mapping[str, object], value)


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if type(value) is not str or not value or value != value.strip():
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_RECORD_INVALID")
    return value


def _positive_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int or value <= 0:
        raise FinancialScopeCapacityImportRuntimeError("FINANCIAL_SCOPE_IMPORT_RECORD_INVALID")
    return value


def _review_field(record: Mapping[str, object], key: str) -> str:
    review = _mapping(record.get("review"))
    return _text(review, key)


def _is_aware(value: datetime) -> bool:
    offset = value.utcoffset()
    return value.tzinfo is not None and offset is not None


__all__ = ["import_financial_scope_capacity_bundle"]
