#!/usr/bin/env python3
"""Export read-only S6 inputs from a sealed candidate source snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Protocol, cast

SOURCE_ROOT = Path("/candidate-src")
INPUT_ROOT = Path("/candidate-inputs")
OUTPUT_ROOT = Path("/candidate-output")
_CANDIDATE_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TREE_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_MODES = frozenset({"production", "universe", "contract"})
_REQUIRED_SOURCE_FILES = (
    "manage.py",
    "scripts/export_s6_rehearsal_inputs.py",
    "scripts/run_release_rehearsal.py",
    "scripts/validate_release_rehearsal.py",
    "apps/data_center/management/commands/export_provider_settings_snapshot.py",
    "apps/data_center/management/commands/export_rehearsal_provider_identities.py",
    "apps/data_center/management/commands/preflight_full_market_publication.py",
    "apps/data_center/application/market_calendar.py",
    "apps/data_center/application/market_provider_rehearsal.py",
    "apps/data_center/application/target_date_universe_scope.py",
    "apps/data_center/target_date_universe_composition.py",
    "apps/data_center/infrastructure/rehearsal_identity.py",
)
_CANDIDATE_MODULES = (
    "scripts.run_release_rehearsal",
    "scripts.validate_release_rehearsal",
    "apps.data_center.management.commands.export_provider_settings_snapshot",
    "apps.data_center.management.commands.export_rehearsal_provider_identities",
    "apps.data_center.management.commands.preflight_full_market_publication",
    "apps.data_center.application.market_calendar",
    "apps.data_center.application.market_provider_rehearsal",
    "apps.data_center.application.target_date_universe_scope",
    "apps.data_center.target_date_universe_composition",
    "apps.data_center.infrastructure.rehearsal_identity",
    "apps.data_center.infrastructure.models",
)

Mode = Literal["production", "universe", "contract"]
UnitContracts = Mapping[str, Mapping[str, tuple[str, str, float, bool]]]


class ExportBlocked(Exception):
    """A safe exporter failure represented by one stable diagnostic code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExportConfig:
    """Validated environment values needed by one exporter mode."""

    candidate_sha: str
    expected_database: str
    settings_module: str
    network: str | None = None
    isolated_database: str | None = None
    postgres_container: str | None = None
    redis_container: str | None = None


@dataclass(frozen=True)
class FrozenProviderInputs:
    """Validated complete provider identities and their bound unit contract."""

    identities: tuple[_ProviderIdentity, ...]
    identities_digest: str
    unit_contract: dict[str, object]


class _ProviderIdentity(Protocol):
    """The attributes consumed from the candidate identity value object."""

    role: str
    provider_id: int
    source: str
    deployment_region: str | None


class _RunnerNamespace(Protocol):
    """The parsed runner fields that bind the exporter argv contract."""

    root: Path
    output_dir: Path
    resume: bool
    transport_input: list[Path]
    target_trade_date: str
    universe_sha256: str
    provider_identities: Path
    provider_settings_json: Path
    unit_contract: Path
    docker_network: str
    isolated_database_name: str
    isolated_database_host: str
    isolated_database_container: str
    isolated_redis_host: str
    isolated_redis_container: str
    quote_provider_id: int
    valuation_provider_id: int
    github_repository: str
    github_run_id: int


def _blocked(code: str) -> int:
    """Print one safe stable diagnostic and return the blocked exit status."""

    print(f"S6_DIAGNOSTIC_BLOCKED code={code}", flush=True)
    return 60


def _parser() -> argparse.ArgumentParser:
    """Build a side-effect-free parser for the three supported exporter modes."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", help="production, universe, or contract")
    return parser


def _required_environment(environment: Mapping[str, str], key: str) -> str:
    """Return a nonempty environment value without including it in diagnostics."""

    value = environment.get(key, "")
    if not value or value != value.strip():
        raise ExportBlocked("S6_EXPORT_ENVIRONMENT_INVALID")
    return value


def _load_config(mode: Mode, environment: Mapping[str, str]) -> ExportConfig:
    """Validate mode-specific environment inputs while keeping secret values private."""

    candidate_sha = _required_environment(environment, "S6_EXPECTED_CANDIDATE")
    expected_database = _required_environment(environment, "S6_EXPECTED_DB")
    if _CANDIDATE_SHA.fullmatch(candidate_sha) is None:
        raise ExportBlocked("S6_CANDIDATE_SHA_INVALID")
    settings_module = environment.get("DJANGO_SETTINGS_MODULE", "core.settings.production")
    if _MODULE_NAME.fullmatch(settings_module) is None:
        raise ExportBlocked("S6_CANDIDATE_SETTINGS_INVALID")
    if mode != "contract":
        return ExportConfig(candidate_sha, expected_database, settings_module)

    return ExportConfig(
        candidate_sha=candidate_sha,
        expected_database=expected_database,
        settings_module=settings_module,
        network=_required_environment(environment, "S6_NETWORK"),
        isolated_database=_required_environment(environment, "S6_DATABASE"),
        postgres_container=_required_environment(environment, "S6_PG_CONTAINER"),
        redis_container=_required_environment(environment, "S6_REDIS_CONTAINER"),
    )


def _file_digest(path: Path) -> str:
    """Hash one regular file in bounded memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> tuple[str, int]:
    """Hash every directory and file, rejecting links and non-regular entries."""

    if root.is_symlink() or not root.is_dir():
        raise ExportBlocked("S6_CANDIDATE_MOUNT_INVALID")
    entries: list[tuple[str, str]] = []
    file_count = 0
    try:
        paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
        for path in paths:
            metadata = path.lstat()
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(metadata.st_mode):
                raise ExportBlocked("S6_CANDIDATE_SOURCE_SYMLINK")
            if stat.S_ISDIR(metadata.st_mode):
                entries.append((relative, "directory"))
            elif stat.S_ISREG(metadata.st_mode):
                entries.append((relative, _file_digest(path)))
                file_count += 1
            else:
                raise ExportBlocked("S6_CANDIDATE_SOURCE_ENTRY_INVALID")
    except ExportBlocked:
        raise
    except OSError as exc:
        raise ExportBlocked("S6_CANDIDATE_SOURCE_ENTRY_INVALID") from exc
    payload = json.dumps(entries, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), file_count


def _validate_source_permissions(root: Path) -> None:
    """Require the exact read-only POSIX snapshot permissions and caller group."""

    if os.name != "posix":
        return
    get_gid = cast(Callable[[], int] | None, getattr(os, "getgid", None))
    if get_gid is None:
        raise ExportBlocked("S6_CANDIDATE_SOURCE_PERMISSIONS_INVALID")
    expected_gid = get_gid()
    try:
        paths = (root, *tuple(root.rglob("*")))
        for path in paths:
            metadata = path.lstat()
            expected_mode = 0o550 if stat.S_ISDIR(metadata.st_mode) else 0o440
            if (
                stat.S_IMODE(metadata.st_mode) != expected_mode
                or metadata.st_gid != expected_gid
                or not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode))
            ):
                raise ExportBlocked("S6_CANDIDATE_SOURCE_PERMISSIONS_INVALID")
    except ExportBlocked:
        raise
    except OSError as exc:
        raise ExportBlocked("S6_CANDIDATE_SOURCE_PERMISSIONS_INVALID") from exc


def _copy_candidate_source() -> tuple[Path, str, int]:
    """Copy the mounted snapshot to private runtime storage and verify byte identity."""

    if SOURCE_ROOT.is_symlink() or not SOURCE_ROOT.is_dir():
        raise ExportBlocked("S6_CANDIDATE_MOUNT_INVALID")
    if OUTPUT_ROOT.is_symlink() or not OUTPUT_ROOT.is_dir():
        raise ExportBlocked("S6_CANDIDATE_MOUNT_INVALID")
    if INPUT_ROOT.is_symlink() or not INPUT_ROOT.is_dir():
        raise ExportBlocked("S6_CANDIDATE_MOUNT_INVALID")
    _validate_source_permissions(SOURCE_ROOT)
    source_digest, source_count = _tree_digest(SOURCE_ROOT)
    if source_count == 0:
        raise ExportBlocked("S6_CANDIDATE_SOURCE_TREE_EMPTY")
    for relative in _REQUIRED_SOURCE_FILES:
        path = SOURCE_ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise ExportBlocked("S6_CANDIDATE_KEY_FILE_MISSING")

    runtime_text = tempfile.mkdtemp(prefix="s6-candidate-runtime-", dir="/tmp")
    runtime = Path(runtime_text)
    try:
        shutil.copytree(SOURCE_ROOT, runtime, dirs_exist_ok=True)
        for path in (runtime, *tuple(runtime.rglob("*"))):
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                path.chmod(0o700)
            elif stat.S_ISREG(metadata.st_mode):
                path.chmod(0o600)
            else:
                raise ExportBlocked("S6_CANDIDATE_SOURCE_ENTRY_INVALID")
        copied_digest, copied_count = _tree_digest(runtime)
        current_digest, current_count = _tree_digest(SOURCE_ROOT)
        if (source_digest, source_count) != (copied_digest, copied_count) or (
            source_digest,
            source_count,
        ) != (current_digest, current_count):
            raise ExportBlocked("S6_CANDIDATE_COPY_MISMATCH")
        return runtime, copied_digest, copied_count
    except ExportBlocked:
        shutil.rmtree(runtime, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(runtime, ignore_errors=True)
        raise ExportBlocked("S6_CANDIDATE_COPY_FAILED") from exc


def _inside(path: Path, root: Path) -> bool:
    """Return whether a resolved module path is a descendant of the candidate copy."""

    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _verify_candidate_module(module: ModuleType, runtime: Path) -> None:
    """Reject any candidate module imported from the execution image or another path."""

    module_path = getattr(module, "__file__", None)
    if not isinstance(module_path, str) or not _inside(Path(module_path), runtime):
        raise ExportBlocked("S6_CANDIDATE_IMPORT_PROVENANCE_INVALID")


def _prepare_candidate_imports(runtime: Path, settings_module: str) -> None:
    """Load Django and candidate modules only after placing the private copy first."""

    os.chdir(runtime)
    os.environ.pop("PYTHONPATH", None)
    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    sys.path[:] = [
        str(runtime),
        *(
            item
            for item in sys.path
            if item
            and not _inside(Path(item), SOURCE_ROOT)
            and not _inside(Path(item), Path("/app"))
        ),
    ]
    try:
        import django

        django.setup()
        names = (settings_module, *_CANDIDATE_MODULES)
        for name in names:
            module = importlib.import_module(name)
            _verify_candidate_module(module, runtime)
    except ExportBlocked:
        raise
    except Exception as exc:
        raise ExportBlocked("S6_CANDIDATE_IMPORT_PROVENANCE_INVALID") from exc


def _validate_database_state(value: object, expected_database: str) -> None:
    """Require the exact PostgreSQL database and read-only transaction defaults."""

    if (
        not isinstance(value, tuple)
        or len(value) != 3
        or not all(isinstance(item, str) for item in value)
        or value[0] != expected_database
        or value[1] != "on"
        or value[2] != "on"
    ):
        raise ExportBlocked("S6_DATABASE_READ_ONLY_GUARD_FAILED")


@contextmanager
def _read_only_database(expected_database: str) -> Iterator[None]:
    """Pin one Django database transaction read-only before any mode query runs."""

    from django.db import connection, transaction

    with transaction.atomic():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT current_database(), "
                    "current_setting('transaction_read_only'), "
                    "current_setting('default_transaction_read_only')"
                )
                state = cast(tuple[object, ...] | None, cursor.fetchone())
        except Exception as exc:
            raise ExportBlocked("S6_DATABASE_READ_ONLY_GUARD_FAILED") from exc
        _validate_database_state(state, expected_database)
        yield


def _read_json(path: Path, maximum_bytes: int) -> object:
    """Read a bounded regular JSON file without following symlinks."""

    if path.is_symlink() or not path.is_file():
        raise ExportBlocked("S6_EXPORT_INPUT_INVALID")
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ExportBlocked("S6_EXPORT_INPUT_INVALID")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes:
            raise ExportBlocked("S6_EXPORT_INPUT_INVALID")
        return json.loads(raw.decode("utf-8"))
    except ExportBlocked:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportBlocked("S6_EXPORT_INPUT_INVALID") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_json_object(path: Path, maximum_bytes: int) -> dict[str, object]:
    """Read a bounded JSON object and narrow it at the untrusted file boundary."""

    value = _read_json(path, maximum_bytes)
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ExportBlocked("S6_EXPORT_INPUT_INVALID")
    return cast(dict[str, object], value)


def _write_new(path: Path, payload: bytes) -> None:
    """Create an exclusive private output file and durably write its bytes."""

    if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
        raise ExportBlocked("S6_EXPORT_OUTPUT_INVALID")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ExportBlocked("S6_EXPORT_OUTPUT_COLLISION") from exc
    except OSError as exc:
        raise ExportBlocked("S6_EXPORT_OUTPUT_INVALID") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise ExportBlocked("S6_EXPORT_OUTPUT_INVALID") from exc


def _json_bytes(payload: object, *, pretty: bool = True) -> bytes:
    """Encode a JSON-safe payload deterministically as UTF-8."""

    separators = None if pretty else (",", ":")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=separators,
        allow_nan=False,
    )
    return (encoded + "\n").encode("utf-8")


def _publish_outputs(outputs: Mapping[str, bytes]) -> None:
    """Publish mode outputs exclusively with owner-only permissions."""

    if OUTPUT_ROOT.is_symlink() or not OUTPUT_ROOT.is_dir():
        raise ExportBlocked("S6_CANDIDATE_MOUNT_INVALID")
    for name in outputs:
        if (
            Path(name).name != name
            or (OUTPUT_ROOT / name).exists()
            or (OUTPUT_ROOT / name).is_symlink()
        ):
            raise ExportBlocked("S6_EXPORT_OUTPUT_COLLISION")
    for name, payload in outputs.items():
        _write_new(OUTPUT_ROOT / name, payload)


def _validate_identity_completeness(identities: Sequence[_ProviderIdentity]) -> None:
    """Require core identities and exactly one explicit financial route identity."""

    roles: list[str] = []
    financial_regions: list[str] = []
    for identity in identities:
        role = identity.role
        region = identity.deployment_region
        source = identity.source
        roles.append(role)
        if role.startswith("akshare_financial_route:"):
            if source != "akshare_financial" or not isinstance(region, str) or not region:
                raise ExportBlocked("S6_PROVIDER_IDENTITY_INVALID")
            financial_regions.append(region)
    if "quote" not in roles or "valuation" not in roles or len(financial_regions) != 1:
        raise ExportBlocked("S6_PROVIDER_IDENTITY_INVALID")


def _unit_contract_payload(
    *,
    candidate_sha: str,
    provider_digest: str,
    contracts: UnitContracts,
) -> dict[str, object]:
    """Build the validator-shaped unit contract from its exact candidate definitions."""

    datasets: dict[str, object] = {}
    for dataset, fields in contracts.items():
        rows: list[dict[str, object]] = []
        for field, (raw_unit, canonical_unit, multiplier, _allow_zero) in fields.items():
            rows.append(
                {
                    "field": field,
                    "raw_unit": raw_unit,
                    "canonical_unit": canonical_unit,
                    "multiplier": multiplier,
                }
            )
        datasets[dataset] = rows
    return {
        "schema": "release.provider-unit-contract.v1",
        "candidate_sha": candidate_sha,
        "provider_identities_sha256": provider_digest,
        "source_reference": (
            "candidate:scripts/validate_release_rehearsal.py#REQUIRED_REPLAY_UNIT_CONTRACTS"
        ),
        "datasets": datasets,
    }


def _validate_frozen_inputs(
    identities_value: object,
    unit_value: object,
    candidate_sha: str,
) -> FrozenProviderInputs:
    """Parse all identities and verify their candidate-bound unit contract."""

    from apps.data_center.infrastructure.rehearsal_identity import (
        parse_rehearsal_identities,
        rehearsal_identities_digest,
    )
    from scripts import validate_release_rehearsal as validator

    try:
        identities = parse_rehearsal_identities(identities_value)
        _validate_identity_completeness(cast(tuple[_ProviderIdentity, ...], identities))
        digest = rehearsal_identities_digest(identities)
        valuation = next(identity for identity in identities if identity.role == "valuation")
    except ExportBlocked:
        raise
    except Exception as exc:
        raise ExportBlocked("S6_PROVIDER_IDENTITY_INVALID") from exc

    contracts = (
        validator.TENCENT_REPLAY_UNIT_CONTRACTS
        if valuation.source == "tencent"
        else validator.REQUIRED_REPLAY_UNIT_CONTRACTS
    )
    if not isinstance(unit_value, dict):
        raise ExportBlocked("S6_UNIT_CONTRACT_INVALID")
    try:
        payload = cast(dict[str, Any], unit_value)
        validator._validate_unit_contract_artifact(
            payload,
            expected_candidate=candidate_sha,
            expected_provider_digest=digest,
            expected_contracts=contracts,
        )
        return FrozenProviderInputs(
            identities=cast(tuple[_ProviderIdentity, ...], identities),
            identities_digest=digest,
            unit_contract=cast(dict[str, object], unit_value),
        )
    except ExportBlocked:
        raise
    except Exception as exc:
        raise ExportBlocked("S6_UNIT_CONTRACT_INVALID") from exc


def _export_production(config: ExportConfig) -> None:
    """Export fresh settings, complete identities, unit contract, and policy preflight."""

    from django.core.management import call_command

    from apps.data_center.infrastructure.models import ProviderConfigModel
    from apps.data_center.infrastructure.rehearsal_identity import (
        parse_rehearsal_identities,
        rehearsal_identities_digest,
    )
    from scripts import validate_release_rehearsal as validator

    with tempfile.TemporaryDirectory(prefix="s6-input-export-", dir="/tmp") as temporary:
        temporary_root = Path(temporary)
        settings_path = temporary_root / "provider-settings.json"
        identities_path = temporary_root / "provider-identities.json"
        try:
            call_command(
                "export_provider_settings_snapshot",
                output=settings_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
            settings_value = _read_json_object(settings_path, 65_536)
            if not settings_value:
                raise ExportBlocked("S6_PROVIDER_SETTINGS_INVALID")
            quote_provider_id = (
                ProviderConfigModel._default_manager.filter(source_type="tushare", is_active=True)
                .order_by("priority", "pk")
                .values_list("pk", flat=True)
                .first()
            )
            valuation_provider_id = (
                ProviderConfigModel._default_manager.filter(source_type="akshare", is_active=True)
                .order_by("priority", "pk")
                .values_list("pk", flat=True)
                .first()
            )
            if (
                isinstance(quote_provider_id, bool)
                or not isinstance(quote_provider_id, int)
                or isinstance(valuation_provider_id, bool)
                or not isinstance(valuation_provider_id, int)
            ):
                raise ExportBlocked("S6_PROVIDER_SELECTION_INVALID")
            call_command(
                "export_rehearsal_provider_identities",
                quote_provider_id=quote_provider_id,
                valuation_provider_id=valuation_provider_id,
                provider_settings_json=settings_path,
                output=identities_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
            identities_value = _read_json(identities_path, 16_384)
            identities = parse_rehearsal_identities(identities_value)
            _validate_identity_completeness(cast(tuple[_ProviderIdentity, ...], identities))
            identities_digest = rehearsal_identities_digest(identities)
            valuation = next(identity for identity in identities if identity.role == "valuation")
            expected_contracts = (
                validator.TENCENT_REPLAY_UNIT_CONTRACTS
                if valuation.source == "tencent"
                else validator.REQUIRED_REPLAY_UNIT_CONTRACTS
            )
            unit_contract = _unit_contract_payload(
                candidate_sha=config.candidate_sha,
                provider_digest=identities_digest,
                contracts=expected_contracts,
            )
            validator._validate_unit_contract_artifact(
                cast(dict[str, Any], unit_contract),
                expected_candidate=config.candidate_sha,
                expected_provider_digest=identities_digest,
                expected_contracts=expected_contracts,
            )
            preflight_stdout = io.StringIO()
            call_command(
                "preflight_full_market_publication",
                provider_settings_json=settings_path,
                checks=["provider_policy_and_routes"],
                stdout=preflight_stdout,
                stderr=io.StringIO(),
            )
            preflight_value: object = json.loads(preflight_stdout.getvalue())
            _validate_preflight(preflight_value)
            output_bytes: dict[str, bytes] = {
                "provider-settings.json": settings_path.read_bytes(),
                "provider-identities.json": identities_path.read_bytes(),
                "unit-contract.json": _json_bytes(unit_contract),
                "provider-policy-preflight.json": _json_bytes(preflight_value),
            }
            _publish_outputs(output_bytes)
            print(
                "S6_CANDIDATE_EXPORTS "
                f"settings_sha256={hashlib.sha256(output_bytes['provider-settings.json']).hexdigest()} "
                f"identity_count={len(identities)} identity_sha256="
                f"{hashlib.sha256(output_bytes['provider-identities.json']).hexdigest()} "
                f"identity_digest={identities_digest} financial_region_field=present",
                flush=True,
            )
            print(
                "S6_UNIT_CONTRACT_VALIDATED "
                f"datasets={len(expected_contracts)} "
                f"fields={sum(len(fields) for fields in expected_contracts.values())} "
                f"sha256={hashlib.sha256(output_bytes['unit-contract.json']).hexdigest()}",
                flush=True,
            )
        except ExportBlocked:
            raise
        except Exception as exc:
            raise ExportBlocked("S6_PRODUCTION_INPUT_EXPORT_FAILED") from exc


def _validate_preflight(value: object) -> None:
    """Require exactly the successful provider-policy preflight check."""

    if not isinstance(value, dict):
        raise ExportBlocked("S6_PROVIDER_POLICY_PREFLIGHT_BLOCKED")
    report = cast(dict[str, object], value)
    checks = report.get("checks")
    if (
        report.get("outcome") != "pass"
        or not isinstance(checks, list)
        or len(checks) != 1
        or not isinstance(checks[0], dict)
        or checks[0].get("name") != "provider_policy_and_routes"
        or checks[0].get("status") != "pass"
    ):
        raise ExportBlocked("S6_PROVIDER_POLICY_PREFLIGHT_BLOCKED")


def _validate_universe_summary(summary: Mapping[str, object]) -> None:
    """Validate the complete dynamic-universe summary shape and count partition."""

    expected_keys = {
        "target_trade_date",
        "universe_count",
        "universe_sha256",
        "candidate_active_asset_count",
        "excluded_not_yet_listed_count",
        "unknown_listing_date_count",
    }
    target = summary.get("target_trade_date")
    digest = summary.get("universe_sha256")
    counts = (
        summary.get("universe_count"),
        summary.get("candidate_active_asset_count"),
        summary.get("excluded_not_yet_listed_count"),
        summary.get("unknown_listing_date_count"),
    )
    if (
        set(summary) != expected_keys
        or not isinstance(target, str)
        or not isinstance(digest, str)
        or _TREE_SHA.fullmatch(digest) is None
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts
        )
    ):
        raise ExportBlocked("S6_UNIVERSE_SUMMARY_INVALID")
    try:
        if date.fromisoformat(target).isoformat() != target:
            raise ValueError("noncanonical date")
    except ValueError as exc:
        raise ExportBlocked("S6_UNIVERSE_SUMMARY_INVALID") from exc
    universe_count, active_count, excluded_count, unknown_count = cast(
        tuple[int, int, int, int], counts
    )
    if (
        universe_count <= 0
        or active_count != universe_count + excluded_count
        or unknown_count > universe_count
    ):
        raise ExportBlocked("S6_UNIVERSE_SUMMARY_INVALID")


def _export_universe(config: ExportConfig) -> None:
    """Resolve the latest completed session and export its dynamic A-share scope."""

    from apps.data_center.application.market_calendar import latest_completed_cn_market_session
    from apps.data_center.application.market_provider_rehearsal import rehearsal_digest
    from apps.data_center.target_date_universe_composition import (
        build_target_date_a_share_universe_scope,
    )

    identities_value = _read_json(INPUT_ROOT / "provider-identities.json", 16_384)
    unit_value = _read_json_object(INPUT_ROOT / "unit-contract.json", 65_536)
    _validate_frozen_inputs(identities_value, unit_value, config.candidate_sha)
    with _read_only_database(config.expected_database):
        target_date = latest_completed_cn_market_session(datetime.now(UTC))
        if target_date is None:
            raise ExportBlocked("S6_TARGET_SESSION_UNAVAILABLE")
        scope = build_target_date_a_share_universe_scope(target_date)
        codes = tuple(scope.requested_codes)
        if not codes:
            raise ExportBlocked("S6_TARGET_UNIVERSE_EMPTY")
        summary: dict[str, object] = {
            "target_trade_date": target_date.isoformat(),
            "universe_count": len(codes),
            "universe_sha256": rehearsal_digest(codes),
            "candidate_active_asset_count": len(scope.candidate_codes),
            "excluded_not_yet_listed_count": len(scope.excluded_not_yet_listed),
            "unknown_listing_date_count": len(scope.unknown_listing_date_codes),
        }
    _validate_universe_summary(summary)
    _publish_outputs({"universe-summary.json": _json_bytes(summary, pretty=False)})
    print(
        "S6_UNIVERSE "
        f"target={summary['target_trade_date']} count={summary['universe_count']} "
        f"sha256={summary['universe_sha256']}",
        flush=True,
    )


def _build_runner_argv(
    *,
    runtime: Path,
    inputs: FrozenProviderInputs,
    summary: Mapping[str, object],
    config: ExportConfig,
) -> list[str]:
    """Build diagnostic-only argv covering every required runner parser option."""

    if (
        config.network is None
        or config.isolated_database is None
        or config.postgres_container is None
        or config.redis_container is None
    ):
        raise ExportBlocked("S6_RUNNER_ARGV_CONTRACT_INVALID")
    target_date = summary.get("target_trade_date")
    universe_sha = summary.get("universe_sha256")
    if not isinstance(target_date, str) or not isinstance(universe_sha, str):
        raise ExportBlocked("S6_RUNNER_ARGV_CONTRACT_INVALID")
    quote_id = next(
        (identity.provider_id for identity in inputs.identities if identity.role == "quote"),
        None,
    )
    valuation_id = next(
        (identity.provider_id for identity in inputs.identities if identity.role == "valuation"),
        None,
    )
    if not isinstance(quote_id, int) or not isinstance(valuation_id, int):
        raise ExportBlocked("S6_RUNNER_ARGV_CONTRACT_INVALID")
    transport_inputs = (
        SOURCE_ROOT / "scripts" / "export_s6_rehearsal_inputs.py",
        runtime / "scripts" / "run_release_rehearsal.py",
        runtime / "scripts" / "validate_release_rehearsal.py",
    )
    return [
        "--root",
        str(runtime),
        "--output-dir",
        str(OUTPUT_ROOT / "runner-output"),
        "--build-host",
        "diagnostic.invalid",
        "--build-user",
        "diagnostic",
        "--password-file",
        str(INPUT_ROOT / "diagnostic-password"),
        "--provider-env-file",
        str(INPUT_ROOT / "provider.env"),
        "--isolated-postgres-env-file",
        str(INPUT_ROOT / "isolated-postgres.env"),
        "--isolated-migrator-env-file",
        str(INPUT_ROOT / "isolated-migrator.env"),
        "--docker-network",
        config.network,
        "--isolated-database-name",
        config.isolated_database,
        "--isolated-database-host",
        config.postgres_container,
        "--isolated-database-container",
        config.postgres_container,
        "--isolated-redis-host",
        config.redis_container,
        "--isolated-redis-container",
        config.redis_container,
        "--target-trade-date",
        target_date,
        "--universe-sha256",
        universe_sha,
        "--provider-identities",
        str(INPUT_ROOT / "provider-identities.json"),
        "--provider-settings-json",
        str(INPUT_ROOT / "provider-settings.json"),
        "--unit-contract",
        str(INPUT_ROOT / "unit-contract.json"),
        "--transport-input",
        str(transport_inputs[0]),
        "--transport-input",
        str(transport_inputs[1]),
        "--transport-input",
        str(transport_inputs[2]),
        "--quote-provider-id",
        str(quote_id),
        "--valuation-provider-id",
        str(valuation_id),
        "--provider-request-limit",
        "1",
        "--provider-window-seconds",
        "1",
        "--task-deadline-seconds",
        "10",
        "--lock-wait-limit-seconds",
        "10",
        "--github-repository",
        "diagnostic/rehearsal",
        "--github-run-id",
        "1",
    ]


def _assert_runner_argv(
    args: _RunnerNamespace,
    *,
    runtime: Path,
    inputs: FrozenProviderInputs,
    summary: Mapping[str, object],
    config: ExportConfig,
) -> None:
    """Check parsed argv values, exact transport list, and disabled resume mode."""

    expected_transport = [
        SOURCE_ROOT / "scripts" / "export_s6_rehearsal_inputs.py",
        runtime / "scripts" / "run_release_rehearsal.py",
        runtime / "scripts" / "validate_release_rehearsal.py",
    ]
    quote_id = next(
        identity.provider_id for identity in inputs.identities if identity.role == "quote"
    )
    valuation_id = next(
        identity.provider_id for identity in inputs.identities if identity.role == "valuation"
    )
    if (
        args.root != runtime
        or args.output_dir != OUTPUT_ROOT / "runner-output"
        or args.resume
        or args.transport_input != expected_transport
        or args.target_trade_date != summary.get("target_trade_date")
        or args.universe_sha256 != summary.get("universe_sha256")
        or args.provider_identities != INPUT_ROOT / "provider-identities.json"
        or args.provider_settings_json != INPUT_ROOT / "provider-settings.json"
        or args.unit_contract != INPUT_ROOT / "unit-contract.json"
        or args.docker_network != config.network
        or args.isolated_database_name != config.isolated_database
        or args.isolated_database_host != config.postgres_container
        or args.isolated_database_container != config.postgres_container
        or args.isolated_redis_host != config.redis_container
        or args.isolated_redis_container != config.redis_container
        or args.quote_provider_id != quote_id
        or args.valuation_provider_id != valuation_id
        or args.github_repository != "diagnostic/rehearsal"
        or args.github_run_id != 1
    ):
        raise ExportBlocked("S6_RUNNER_ARGV_CONTRACT_INVALID")


def _export_contract(runtime: Path, config: ExportConfig) -> None:
    """Validate frozen inputs and parse the exact current S6 runner CLI contract."""

    identities_value = _read_json(INPUT_ROOT / "provider-identities.json", 16_384)
    unit_value = _read_json_object(INPUT_ROOT / "unit-contract.json", 65_536)
    settings_value = _read_json_object(INPUT_ROOT / "provider-settings.json", 65_536)
    summary = _read_json_object(INPUT_ROOT / "universe-summary.json", 16_384)
    if not settings_value:
        raise ExportBlocked("S6_PROVIDER_SETTINGS_INVALID")
    inputs = _validate_frozen_inputs(identities_value, unit_value, config.candidate_sha)
    _validate_universe_summary(summary)
    try:
        from scripts import run_release_rehearsal as runner

        argv = _build_runner_argv(
            runtime=runtime,
            inputs=inputs,
            summary=summary,
            config=config,
        )
        parsed = cast(_RunnerNamespace, runner._parser().parse_args(argv))
        _assert_runner_argv(
            parsed,
            runtime=runtime,
            inputs=inputs,
            summary=summary,
            config=config,
        )
    except ExportBlocked:
        raise
    except Exception as exc:
        raise ExportBlocked("S6_RUNNER_ARGV_CONTRACT_INVALID") from exc
    print("S6_RUNNER_ARGV_PARSED transport_inputs=3 resume=0", flush=True)


def _run(mode: Mode, config: ExportConfig) -> None:
    """Prepare the exact candidate import tree and execute one read-only mode."""

    runtime: Path | None = None
    try:
        runtime, digest, count = _copy_candidate_source()
        print(
            f"S6_CANDIDATE_COPY_VERIFIED tree_sha256={digest} files={count}",
            flush=True,
        )
        _prepare_candidate_imports(runtime, config.settings_module)
        if mode == "production":
            with _read_only_database(config.expected_database):
                _export_production(config)
        elif mode == "universe":
            _export_universe(config)
        else:
            with _read_only_database(config.expected_database):
                _export_contract(runtime, config)
    finally:
        if runtime is not None and runtime.exists() and not runtime.is_symlink():
            shutil.rmtree(runtime, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one input-export mode without exposing provider or runtime diagnostics."""

    args = _parser().parse_args(argv)
    if args.mode not in _MODES:
        return _blocked("S6_DIAGNOSTIC_MODE_INVALID")
    mode = cast(Mode, args.mode)
    try:
        config = _load_config(mode, os.environ)
        _run(mode, config)
    except ExportBlocked as exc:
        return _blocked(exc.code)
    except Exception:
        return _blocked("S6_CANDIDATE_RUNTIME_ERROR")
    print(f"S6_CANDIDATE_EXPORT_COMPLETE mode={mode}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
