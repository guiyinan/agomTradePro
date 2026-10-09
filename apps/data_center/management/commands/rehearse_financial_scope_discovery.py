"""Run the isolated provider-native financial scope and manifest bootstrap."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from argparse import ArgumentParser
from dataclasses import replace
from datetime import UTC, date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.utils import timezone

from apps.data_center.application.financial_scope_capacity_receipt import (
    build_financial_scope_capacity_receipt,
)
from apps.data_center.application.financial_scope_manifest_bootstrap import (
    FinancialScopeDiscoveryResult,
    ScopeDiscoveryRequest,
)
from apps.data_center.domain.financial_scope_discovery import (
    FINANCIAL_SCOPE_DISCOVERY_ERROR_CODES,
    FinancialScopeDiscoveryError,
)
from apps.data_center.financial_scope_discovery_composition import (
    build_financial_scope_discovery_binding,
    make_financial_scope_discovery_use_case,
)
from apps.data_center.infrastructure.akshare_financial_slice_rehearsal import (
    verify_configured_rehearsal_identities,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeDiscoveryUniverseSource,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.rehearsal_identity import (
    akshare_financial_route_role,
    load_rehearsal_identities,
    rehearsal_identities_digest,
)

_CANDIDATE_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ROOT_NAME = re.compile(r"^agom-s6-financial-scope-[0-9a-f]{32}$")
_ARTIFACT_RELATIVE_PATH = re.compile(r"^v1/[0-9a-f-]{36}\.frb$")


class Command(BaseCommand):
    """Create a review-required full-scope manifest using isolated real-provider reads."""

    help = "Capture a candidate financial source-time manifest in isolated S6 storage."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Accept only the frozen candidate, identity snapshot, and disposable output paths."""

        parser.add_argument("--candidate-sha", required=True)
        parser.add_argument("--target-trade-date", required=True)
        parser.add_argument("--release-universe-sha256", required=True)
        parser.add_argument("--provider-identities", required=True, type=Path)
        parser.add_argument("--provider-identities-sha256", required=True)
        parser.add_argument("--expected-database-name", required=True)
        parser.add_argument("--expected-database-host", required=True)
        parser.add_argument("--artifact-root", required=True, type=Path)
        parser.add_argument("--output-dir", required=True, type=Path)

    def handle(
        self,
        *args: object,
        candidate_sha: str,
        target_trade_date: str,
        release_universe_sha256: str,
        provider_identities: Path,
        provider_identities_sha256: str,
        expected_database_name: str,
        expected_database_host: str,
        artifact_root: Path,
        output_dir: Path,
        **options: object,
    ) -> str | None:
        """Run one complete dynamic discovery and emit safe evidence before failing closed."""

        report_path = output_dir / "financial-scope-discovery.json"
        receipt_path = output_dir / "financial-full-scope-capacity.json"
        try:
            _validate_inputs(
                candidate_sha=candidate_sha,
                target_trade_date=target_trade_date,
                release_universe_sha256=release_universe_sha256,
                provider_identities_path=provider_identities,
                provider_identities_sha256=provider_identities_sha256,
                expected_database_name=expected_database_name,
                expected_database_host=expected_database_host,
                artifact_root=artifact_root,
                output_dir=output_dir,
                output_path=report_path,
                receipt_path=receipt_path,
            )
            report = _run_discovery(
                candidate_sha=candidate_sha,
                provider_identities_path=provider_identities,
                provider_identities_sha256=provider_identities_sha256,
                expected_database_name=expected_database_name,
                expected_database_host=expected_database_host,
                artifact_root=artifact_root,
                output_dir=output_dir,
            )
            _write_exclusive_json(report_path, report)
            result = report.get("result")
            if isinstance(result, dict) and result.get("outcome") == "success":
                capacity_receipt = build_financial_scope_capacity_receipt(
                    scope_report=report,
                    scope_report_sha256=hashlib.sha256(_encoded_json(report)).hexdigest(),
                    target_trade_date=target_trade_date,
                    release_universe_sha256=release_universe_sha256,
                    provider_identities_sha256=provider_identities_sha256,
                )
                _write_exclusive_json(receipt_path, capacity_receipt)
        except Exception as exc:
            code = _stable_rehearsal_code(exc)
            _write_safe_failure_report(report_path, candidate_sha=candidate_sha, code=code)
            raise CommandError(code) from None

        result = report["result"]
        if not isinstance(result, dict):
            raise CommandError("REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_REPORT_INVALID")
        if result.get("outcome") != "success":
            error_codes = result.get("error_codes")
            if not isinstance(error_codes, list) or not error_codes:
                raise CommandError("REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_BLOCKED")
            first_code = error_codes[0]
            if type(first_code) is not str or not first_code.startswith(
                "REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_"
            ):
                raise CommandError("REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_BLOCKED")
            raise CommandError(first_code)
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return None


def _run_discovery(
    *,
    candidate_sha: str,
    provider_identities_path: Path,
    provider_identities_sha256: str,
    expected_database_name: str,
    expected_database_host: str,
    artifact_root: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Compose the exact live provider binding, then discover every active security."""

    started_at = timezone.now()
    build_identity = FileFinancialCapacityBuildIdentitySource(
        Path(settings.AGOM_BUILD_IDENTITY_PATH)
    ).source_commit()
    if build_identity != candidate_sha:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID")
    identities = load_rehearsal_identities(provider_identities_path)
    identity_digest = rehearsal_identities_digest(identities)
    if identity_digest != provider_identities_sha256:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID")
    verified_identities = verify_configured_rehearsal_identities(identities)
    financial_identities = tuple(
        item
        for item in verified_identities
        if item.source == "akshare_financial"
        and item.role == akshare_financial_route_role(item.provider_id)
    )
    if len(financial_identities) != 1:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID")
    provider_identity = financial_identities[0]
    try:
        provider_row = ProviderConfigModel._default_manager.get(
            pk=provider_identity.provider_id,
            source_type="akshare",
            is_active=True,
        )
    except (DatabaseError, ProviderConfigModel.DoesNotExist):
        raise FinancialScopeDiscoveryError(
            "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID"
        ) from None
    provider = provider_row.to_domain()
    binding = build_financial_scope_discovery_binding(
        provider=provider,
        candidate_sha=candidate_sha,
    )
    use_case = make_financial_scope_discovery_use_case(
        provider=provider,
        candidate_sha=candidate_sha,
        expected_database_name=expected_database_name,
        expected_database_host=expected_database_host,
        artifact_storage_root=artifact_root,
    )
    universe = DjangoFinancialScopeDiscoveryUniverseSource().get_active_asset_codes()
    result = use_case.use_case.execute(
        ScopeDiscoveryRequest(
            environment="isolated",
            asset_codes=universe,
            binding=binding,
            now=started_at,
        )
    )
    try:
        encrypted_artifacts = _encrypted_artifact_projection(artifact_root)
    except FinancialScopeDiscoveryError as exc:
        result = replace(
            result,
            outcome="blocked",
            candidate=None,
            error_codes=tuple(sorted(set(result.error_codes) | {exc.code})),
        )
        encrypted_artifacts = []
    finished_at = timezone.now()
    candidate_image_id = os.environ.get("AGOM_CANDIDATE_IMAGE_ID", "")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_image_id) is None:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
    return {
        "schema": "release.financial-scope-discovery.v1",
        "kind": "financial_scope_discovery",
        "candidate_sha": candidate_sha,
        "started_at": started_at.astimezone(UTC).isoformat(),
        "finished_at": finished_at.astimezone(UTC).isoformat(),
        "outcome": result.outcome,
        "review_status": "pending_independent_review" if result.candidate else "not_eligible",
        "binding": {
            "provider_id": binding.provider_id,
            "provider_name": binding.provider_name,
            "provider_identity_sha256": binding.provider_identity_sha256,
            "contract_id": binding.contract_id,
            "contract_version": binding.contract_version,
            "contract_sha256": binding.contract_sha256,
            "parser_id": binding.parser_id,
            "parser_sha256": binding.parser_sha256,
            "deployment_region": binding.deployment_region,
        },
        "database": {
            "vendor": "postgresql",
            "scope": "disposable",
            "release_rehearsal_guard": True,
            "name": expected_database_name,
            "host": expected_database_host,
            "isolation_attestation_sha256": use_case.isolation_attestation_sha256,
        },
        "authorization": _authorization_projection(result),
        "candidate_image_id": candidate_image_id,
        "artifact_root": artifact_root.name,
        "encrypted_artifacts": encrypted_artifacts,
        "result": _result_projection(result.to_dict()),
    }


def _authorization_projection(
    result: FinancialScopeDiscoveryResult,
) -> dict[str, object] | None:
    """Expose the owner authorization that is sealed into a complete manifest."""

    candidate = result.candidate
    if candidate is None:
        return None
    return {
        "approval_id": candidate.discovery_approval_id,
        "owner_event_id": candidate.discovery_owner_event_id,
        "owner_receipt_sha256": candidate.discovery_owner_receipt_sha256,
    }


def _result_projection(value: dict[str, object]) -> dict[str, object]:
    """Convert internal stable codes to the S6 REHEARSAL allowlist namespace."""

    raw_codes = value.get("error_codes")
    if not isinstance(raw_codes, list):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
    codes: list[str] = []
    for item in raw_codes:
        if type(item) is not str or item not in FINANCIAL_SCOPE_DISCOVERY_ERROR_CODES:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
        codes.append(f"REHEARSAL_{item}")
    projected = dict(value)
    projected["error_codes"] = codes
    return projected


def _encrypted_artifact_projection(root: Path) -> list[dict[str, object]]:
    """Enumerate only opaque encrypted artifacts and reject links or special files."""

    if root.is_symlink() or not root.is_dir():
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID")
    artifacts: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID")
        if path.is_dir():
            continue
        try:
            metadata = path.lstat()
        except OSError:
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID"
            ) from None
        relative_path = path.relative_to(root).as_posix()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or _ARTIFACT_RELATIVE_PATH.fullmatch(relative_path) is None
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts.append(
            {
                "path": f"{root.name}/{relative_path}",
                "size_bytes": metadata.st_size,
                "ciphertext_sha256": digest,
            }
        )
    return artifacts


def _validate_inputs(
    *,
    candidate_sha: str,
    target_trade_date: str,
    release_universe_sha256: str,
    provider_identities_path: Path,
    provider_identities_sha256: str,
    expected_database_name: str,
    expected_database_host: str,
    artifact_root: Path,
    output_dir: Path,
    output_path: Path,
    receipt_path: Path,
) -> None:
    """Reject stale identities and unsafe output paths before constructing providers."""

    if (
        _CANDIDATE_SHA.fullmatch(candidate_sha) is None
        or _SHA256.fullmatch(release_universe_sha256) is None
        or not _valid_trade_date(target_trade_date)
        or _SHA256.fullmatch(provider_identities_sha256) is None
        or not provider_identities_path.is_file()
        or provider_identities_path.is_symlink()
        or not output_dir.is_dir()
        or output_dir.is_symlink()
        or output_path.exists()
        or output_path.is_symlink()
        or receipt_path.exists()
        or receipt_path.is_symlink()
        or artifact_root.is_symlink()
        or artifact_root.exists()
        or not artifact_root.is_absolute()
        or _ARTIFACT_ROOT_NAME.fullmatch(artifact_root.name) is None
        or artifact_root.parent.resolve() != output_dir.resolve()
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
    if not expected_database_name.startswith(
        "agom_release_rehearsal_"
    ) or not expected_database_host.startswith("agom-s6-postgres-"):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_ENVIRONMENT_FORBIDDEN")


def _valid_trade_date(value: str) -> bool:
    """Check the S6 release date before any financial provider request begins."""

    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _write_exclusive_json(path: Path, payload: dict[str, object]) -> None:
    """Write one immutable canonical JSON report and fsync the file and directory."""

    raw = _encoded_json(payload)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            if stream.write(raw) != len(raw):
                raise OSError("short scope discovery evidence write")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _encoded_json(payload: dict[str, object]) -> bytes:
    """Return the exact exclusive-report encoding used by both S6 outputs."""

    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _write_safe_failure_report(path: Path, *, candidate_sha: str, code: str) -> None:
    """Preserve one stable, secret-free stage failure if output is safely writable."""

    if path.exists() or path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        return
    payload: dict[str, object] = {
        "schema": "release.financial-scope-discovery.v1",
        "kind": "financial_scope_discovery",
        "candidate_sha": candidate_sha if _CANDIDATE_SHA.fullmatch(candidate_sha) else None,
        "outcome": "blocked",
        "error_codes": [code],
        "fact_writes": 0,
        "publication_writes": 0,
    }
    try:
        _write_exclusive_json(path, payload)
    except OSError:
        return


def _stable_rehearsal_code(exc: BaseException) -> str:
    """Map only internal allowlisted codes to the stable S6 diagnostic namespace."""

    code = getattr(exc, "code", "")
    if isinstance(code, str) and code in FINANCIAL_SCOPE_DISCOVERY_ERROR_CODES:
        return f"REHEARSAL_{code}"
    return "REHEARSAL_FINANCIAL_SCOPE_DISCOVERY_FAILED"


def _fsync_directory(path: Path) -> None:
    """Fsync a directory on POSIX, while remaining portable for local contract tests."""

    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["Command"]
