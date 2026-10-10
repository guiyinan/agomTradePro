#!/usr/bin/env python3
"""Export read-only S6 inputs from a sealed candidate source snapshot."""

from __future__ import annotations

import argparse
import ast
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
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

SOURCE_ROOT = Path("/candidate-src")
INPUT_ROOT = Path("/candidate-inputs")
OUTPUT_ROOT = Path("/candidate-output")
_CANDIDATE_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TREE_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_MODES = frozenset({"production", "universe", "contract"})
_CORE_MARKET_DATASETS = frozenset(
    {
        "equity.price.bar",
        "equity.quote.snapshot",
        "equity.valuation.fact",
    }
)
_PRICE_DATASET = "equity.price.bar"
_PRICE_FACT_TABLE = "data_center_price_bar"
_FULL_MARKET_TASK_NAME = "data_center.refresh_full_market_publications"
_REQUIRED_SOURCE_FILES = (
    "manage.py",
    "scripts/export_s6_rehearsal_inputs.py",
    "scripts/run_release_rehearsal.py",
    "scripts/s6_isolated_market_graph_receipt.py",
    "apps/data_center/application/s6_market_graph_task_result.py",
    "scripts/validate_release_rehearsal.py",
    "apps/data_center/management/commands/export_provider_settings_snapshot.py",
    "apps/data_center/management/commands/export_rehearsal_provider_identities.py",
    "apps/data_center/management/commands/preflight_full_market_publication.py",
    "apps/data_center/application/market_calendar.py",
    "apps/data_center/application/market_provider_rehearsal.py",
    "apps/data_center/application/target_date_universe_scope.py",
    "apps/data_center/target_date_universe_composition.py",
    "apps/data_center/infrastructure/publication_fact_identity.py",
    "apps/data_center/infrastructure/candidate_raw_audit_manifest_models.py",
    "apps/data_center/infrastructure/publication_member_store.py",
    "apps/data_center/infrastructure/publication_rollback_models.py",
    "apps/data_center/infrastructure/rehearsal_identity.py",
    "apps/task_monitor/infrastructure/models.py",
)
_CANDIDATE_MODULES = (
    "scripts.run_release_rehearsal",
    "scripts.validate_release_rehearsal",
    "scripts.s6_isolated_market_graph_receipt",
    "apps.data_center.application.s6_market_graph_task_result",
    "apps.data_center.management.commands.export_provider_settings_snapshot",
    "apps.data_center.management.commands.export_rehearsal_provider_identities",
    "apps.data_center.management.commands.preflight_full_market_publication",
    "apps.data_center.application.market_calendar",
    "apps.data_center.application.market_provider_rehearsal",
    "apps.data_center.application.target_date_universe_scope",
    "apps.data_center.target_date_universe_composition",
    "apps.data_center.infrastructure.publication_fact_identity",
    "apps.data_center.infrastructure.candidate_raw_audit_manifest_models",
    "apps.data_center.infrastructure.publication_member_store",
    "apps.data_center.infrastructure.publication_rollback_models",
    "apps.data_center.infrastructure.rehearsal_identity",
    "apps.data_center.infrastructure.models",
    "apps.task_monitor.infrastructure.models",
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
    advance_isolated_market_graph: bool = False
    attempt_id: str | None = None
    attempt_plan_sha256: str | None = None
    postgres_container_id: str | None = None
    redis_container_id: str | None = None
    network_id: str | None = None
    execution_image_id: str | None = None


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
    if mode == "production":
        return ExportConfig(candidate_sha, expected_database, settings_module)

    advance_flag = environment.get("S6_ADVANCE_ISOLATED_MARKET_GRAPH", "0")
    if advance_flag not in {"0", "1"}:
        raise ExportBlocked("S6_GRAPH_REFRESH_ENVIRONMENT_INVALID")
    network = _required_environment(environment, "S6_NETWORK")
    database = _required_environment(environment, "S6_DATABASE")
    postgres = _required_environment(environment, "S6_PG_CONTAINER")
    redis = _required_environment(environment, "S6_REDIS_CONTAINER")
    graph_values: dict[str, str] = {}
    if advance_flag == "1":
        graph_values = {
            "attempt_id": _required_environment(environment, "S6_ATTEMPT_ID"),
            "attempt_plan_sha256": _required_environment(environment, "S6_ATTEMPT_PLAN_SHA256"),
            "postgres_container_id": _required_environment(environment, "S6_PG_CONTAINER_ID"),
            "redis_container_id": _required_environment(environment, "S6_REDIS_CONTAINER_ID"),
            "network_id": _required_environment(environment, "S6_NETWORK_ID"),
            "execution_image_id": _required_environment(environment, "S6_EXECUTION_IMAGE_ID"),
        }
        if (
            re.fullmatch(r"[0-9a-f]{32}", graph_values["attempt_id"]) is None
            or _TREE_SHA.fullmatch(graph_values["attempt_plan_sha256"]) is None
            or any(
                _TREE_SHA.fullmatch(graph_values[field]) is None
                for field in (
                    "postgres_container_id",
                    "redis_container_id",
                    "network_id",
                )
            )
            or re.fullmatch(r"sha256:[0-9a-f]{64}", graph_values["execution_image_id"]) is None
            or re.fullmatch(r"agom-s6-postgres-[a-f0-9]{32}", postgres) is None
            or re.fullmatch(r"agom-s6-redis-[a-f0-9]{32}", redis) is None
            or database != expected_database
        ):
            raise ExportBlocked("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    if mode == "universe":
        return ExportConfig(
            candidate_sha=candidate_sha,
            expected_database=expected_database,
            settings_module=settings_module,
            network=network,
            isolated_database=database,
            postgres_container=postgres,
            redis_container=redis,
            advance_isolated_market_graph=advance_flag == "1",
            attempt_id=graph_values.get("attempt_id"),
            attempt_plan_sha256=graph_values.get("attempt_plan_sha256"),
            postgres_container_id=graph_values.get("postgres_container_id"),
            redis_container_id=graph_values.get("redis_container_id"),
            network_id=graph_values.get("network_id"),
            execution_image_id=graph_values.get("execution_image_id"),
        )
    return ExportConfig(
        candidate_sha=candidate_sha,
        expected_database=expected_database,
        settings_module=settings_module,
        network=network,
        isolated_database=database,
        postgres_container=postgres,
        redis_container=redis,
        advance_isolated_market_graph=advance_flag == "1",
        attempt_id=graph_values.get("attempt_id"),
        attempt_plan_sha256=graph_values.get("attempt_plan_sha256"),
        postgres_container_id=graph_values.get("postgres_container_id"),
        redis_container_id=graph_values.get("redis_container_id"),
        network_id=graph_values.get("network_id"),
        execution_image_id=graph_values.get("execution_image_id"),
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
    """Require the exact PostgreSQL database and repeatable read-only transaction."""

    if (
        not isinstance(value, tuple)
        or len(value) != 4
        or not all(isinstance(item, str) for item in value)
        or value[0] != expected_database
        or value[1] != "on"
        or value[2] != "on"
        or value[3] != "repeatable read"
    ):
        raise ExportBlocked("S6_DATABASE_READ_ONLY_GUARD_FAILED")


@contextmanager
def _read_only_database(expected_database: str) -> Iterator[None]:
    """Pin one repeatable read-only snapshot before any mode query runs."""

    from django.db import connection, transaction

    with transaction.atomic():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute(
                    "SELECT current_database(), "
                    "current_setting('transaction_read_only'), "
                    "current_setting('default_transaction_read_only'), "
                    "current_setting('transaction_isolation')"
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
        parse_complete_rehearsal_identities,
        rehearsal_identities_digest,
    )
    from scripts import validate_release_rehearsal as validator

    try:
        identities = parse_complete_rehearsal_identities(identities_value)
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
        parse_complete_rehearsal_identities,
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
            identities = parse_complete_rehearsal_identities(identities_value)
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


def _validate_current_market_publication_target(
    pointer_rows: Sequence[Mapping[str, object]],
    publication_rows: Sequence[Mapping[str, object]],
    member_rows: Sequence[Mapping[str, object]],
    price_rows: Sequence[Mapping[str, object]],
    manifest_rows: Sequence[Mapping[str, object]],
    task_results: Sequence[Mapping[str, object]],
) -> date:
    """Return the producer target bound to one exact current publication graph."""

    from apps.data_center.application.s6_market_graph_task_result import (
        MarketGraphTaskResultError,
        validate_market_graph_task_result,
    )

    pointers: dict[str, Mapping[str, object]] = {}
    activation_ids: set[str] = set()
    for row in pointer_rows:
        dataset_key = row.get("dataset_key")
        publication_id = row.get("publication_id")
        publication_hash = row.get("publication_hash")
        activation_id = row.get("activation_id")
        if (
            not isinstance(dataset_key, str)
            or dataset_key not in _CORE_MARKET_DATASETS
            or dataset_key in pointers
            or publication_id is None
            or not isinstance(publication_hash, str)
            or not publication_hash
            or not isinstance(activation_id, str)
            or not activation_id
        ):
            raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
        pointers[dataset_key] = row
        activation_ids.add(activation_id)
    if set(pointers) != _CORE_MARKET_DATASETS or len(activation_ids) != 1:
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")

    publications: dict[str, Mapping[str, object]] = {}
    run_ids: set[object] = set()
    published_at_values: set[datetime] = set()
    for row in publication_rows:
        dataset_key = row.get("dataset_key")
        if (
            not isinstance(dataset_key, str)
            or dataset_key not in pointers
            or dataset_key in publications
        ):
            raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
        pointer = pointers[dataset_key]
        as_of = row.get("as_of")
        published_at = row.get("published_at")
        members_sealed_at = row.get("members_sealed_at")
        member_count = row.get("member_count")
        coverage_requested_count = row.get("coverage_requested_count")
        coverage_eligible_count = row.get("coverage_eligible_count")
        coverage_selected_count = row.get("coverage_selected_count")
        coverage_missing_count = row.get("coverage_missing_count")
        scope_blocks = row.get("scope_blocks")
        member_manifest_hash = row.get("member_manifest_hash")
        run_id = row.get("run_id")
        if (
            row.get("publication_id") != pointer.get("publication_id")
            or row.get("publication_hash") != pointer.get("publication_hash")
            or row.get("publication_key") != "current"
            or row.get("state") != "published"
            or row.get("must_not_use_for_decision") is not False
            or row.get("_active_policy_evidence_validated") is not True
            or row.get("computed_publication_hash") != row.get("publication_hash")
            or not isinstance(member_count, int)
            or isinstance(member_count, bool)
            or member_count <= 0
            or coverage_selected_count != member_count
            or isinstance(coverage_requested_count, bool)
            or not isinstance(coverage_requested_count, int)
            or isinstance(coverage_eligible_count, bool)
            or not isinstance(coverage_eligible_count, int)
            or isinstance(coverage_missing_count, bool)
            or not isinstance(coverage_missing_count, int)
            or coverage_requested_count <= 0
            or coverage_selected_count != coverage_eligible_count
            or cast(int, coverage_selected_count) + coverage_missing_count
            != coverage_requested_count
            or not isinstance(scope_blocks, list)
            or len(scope_blocks) != coverage_missing_count
            or not isinstance(member_manifest_hash, str)
            or _TREE_SHA.fullmatch(member_manifest_hash) is None
            or not isinstance(as_of, datetime)
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or not isinstance(published_at, datetime)
            or published_at.tzinfo is None
            or published_at.utcoffset() is None
            or not isinstance(members_sealed_at, datetime)
            or members_sealed_at.tzinfo is None
            or members_sealed_at.utcoffset() is None
            or run_id is None
            or as_of > published_at
            or members_sealed_at > published_at
        ):
            raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
        publications[dataset_key] = row
        run_ids.add(run_id)
        published_at_values.add(published_at)
    if (
        set(publications) != _CORE_MARKET_DATASETS
        or len(run_ids) != 1
        or len(published_at_values) != 1
    ):
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")

    manifests: dict[str, Mapping[str, object]] = {}
    task_attempt_ids: set[str] = set()
    for row in manifest_rows:
        dataset_key = row.get("dataset_key")
        task_attempt_id = row.get("task_attempt_id")
        if (
            not isinstance(dataset_key, str)
            or dataset_key not in publications
            or dataset_key in manifests
            or row.get("publication_key") != "current"
            or row.get("publication_id") != publications[dataset_key].get("publication_id")
            or row.get("publication_hash") != publications[dataset_key].get("publication_hash")
            or str(row.get("run_id")) != str(publications[dataset_key].get("run_id"))
            or not isinstance(task_attempt_id, str)
            or not task_attempt_id.strip()
            or isinstance(row.get("raw_audit_count"), bool)
            or not isinstance(row.get("raw_audit_count"), int)
            or cast(int, row["raw_audit_count"]) <= 0
            or not isinstance(row.get("raw_audit_hash"), str)
            or _TREE_SHA.fullmatch(cast(str, row["raw_audit_hash"])) is None
            or not isinstance(row.get("manifest_hash"), str)
            or _TREE_SHA.fullmatch(cast(str, row["manifest_hash"])) is None
        ):
            raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
        manifests[dataset_key] = row
        task_attempt_ids.add(task_attempt_id)
    if set(manifests) != _CORE_MARKET_DATASETS or len(task_attempt_ids) != 1:
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")

    price_publication = publications[_PRICE_DATASET]
    price_publication_id = price_publication["publication_id"]
    price_member_count = price_publication["member_count"]
    members_by_fact: dict[str, Mapping[str, object]] = {}
    for member in member_rows:
        fact_pk = member.get("fact_pk")
        if (
            member.get("publication_id") != price_publication_id
            or member.get("dataset_key") != _PRICE_DATASET
            or member.get("fact_table") != _PRICE_FACT_TABLE
            or not isinstance(fact_pk, str)
            or not fact_pk.isascii()
            or not fact_pk.isdecimal()
            or fact_pk.startswith("0")
            or fact_pk in members_by_fact
        ):
            raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
        members_by_fact[fact_pk] = member
    if len(members_by_fact) != price_member_count:
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
    if price_publication.get("computed_member_manifest_hash") != price_publication.get(
        "member_manifest_hash"
    ):
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")

    target_dates: set[date] = set()
    seen_price_facts: set[str] = set()
    identity_fields = (
        "natural_key",
        "source",
        "source_record_id",
        "observed_at",
        "raw_payload_hash",
        "quality_status",
        "revision_number",
        "fact_content_hash",
    )
    for price in price_rows:
        fact_pk = price.get("fact_pk")
        selected_member = members_by_fact.get(fact_pk) if isinstance(fact_pk, str) else None
        bar_date = price.get("bar_date")
        if (
            selected_member is None
            or fact_pk in seen_price_facts
            or not isinstance(bar_date, date)
            or isinstance(bar_date, datetime)
            or price.get("freq") != "1d"
            or price.get("adjustment") != "none"
            or any(selected_member.get(field) != price.get(field) for field in identity_fields)
        ):
            raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
        target_dates.add(bar_date)
        seen_price_facts.add(cast(str, fact_pk))
    if seen_price_facts != set(members_by_fact) or len(target_dates) != 1:
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")

    target_date = next(iter(target_dates))
    from apps.data_center.domain.market_time import (
        cn_market_date_from_observation,
        cn_market_session_close_utc,
    )

    if price_publication.get("as_of") != cn_market_session_close_utc(target_date):
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
    for publication in publications.values():
        as_of = cast(datetime, publication["as_of"])
        if cn_market_date_from_observation(as_of) != target_date:
            raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")

    publication_ids = {str(publication["publication_id"]) for publication in publications.values()}
    total_member_count = sum(
        cast(int, publication["member_count"]) for publication in publications.values()
    )
    run_id = str(next(iter(run_ids)))
    expected_activation_id = str(
        uuid5(NAMESPACE_URL, f"agomtradepro:current-market-activation:{run_id}")
    )
    if activation_ids != {expected_activation_id}:
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
    if len(task_results) != 1:
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
    result = task_results[0]
    try:
        producer_target = date.fromisoformat(cast(str, result.get("target_trade_date")))
    except (TypeError, ValueError):
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID") from None
    if (
        producer_target.isoformat() != result.get("target_trade_date")
        or producer_target != target_date
        or result.get("_task_status") != "success"
        or result.get("_task_attempt_id") != next(iter(task_attempt_ids))
    ):
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
    if total_member_count <= 0 or not publication_ids:
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
    try:
        validate_market_graph_task_result(
            result,
            tuple(publications.values()),
            target_trade_date=target_date.isoformat(),
            run_id=run_id,
        )
    except MarketGraphTaskResultError as exc:
        raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID") from exc
    return target_date


def _parse_task_result(raw_result: object) -> dict[str, object] | None:
    """Parse the two bounded Task Monitor encodings without executing input."""

    if not isinstance(raw_result, str) or not raw_result or len(raw_result) > 1_000_000:
        return None
    parsed: object
    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(raw_result)
        except (SyntaxError, ValueError):
            return None
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        return None
    return cast(dict[str, object], parsed)


def _current_market_publication_target_date() -> date:
    """Read a provider-free target from exact production publication evidence."""

    from apps.data_center.application.current_publication_evidence import (
        current_publication_evidence_blocked_reason,
    )
    from apps.data_center.application.publication_utils import (
        member_reference,
        publication_hash,
        publication_member_manifest_hash,
    )
    from apps.data_center.infrastructure.candidate_raw_audit_manifest_models import (
        CandidateRawAuditManifestModel,
    )
    from apps.data_center.infrastructure.models import PriceBarModel
    from apps.data_center.infrastructure.publication_member_store import (
        publication_fact_content_hashes,
    )
    from apps.data_center.infrastructure.publication_models import (
        CanonicalPublicationModel,
        CanonicalPublicationPointerModel,
        PublicationMemberModel,
    )
    from apps.data_center.infrastructure.publication_policy_repository import (
        PublicationPolicyRepository,
    )
    from apps.task_monitor.infrastructure.models import TaskExecutionModel

    policy_repository = PublicationPolicyRepository()

    pointer_rows: list[dict[str, object]] = [
        dict(row)
        for row in CanonicalPublicationPointerModel._default_manager.filter(
            dataset_key__in=_CORE_MARKET_DATASETS,
            publication_key="current",
        ).values(
            "dataset_key",
            "publication_id",
            "publication_hash",
            "activation_id",
        )
    ]
    publication_ids: tuple[UUID, ...] = tuple(
        cast(UUID, row["publication_id"])
        for row in pointer_rows
        if isinstance(row.get("publication_id"), UUID)
    )
    publication_rows: list[dict[str, object]] = [
        dict(row)
        for row in CanonicalPublicationModel._default_manager.filter(
            publication_id__in=publication_ids,
        ).values(
            "dataset_key",
            "publication_key",
            "publication_id",
            "publication_hash",
            "state",
            "must_not_use_for_decision",
            "selected_source",
            "member_count",
            "coverage_selected_count",
            "member_manifest_hash",
            "policy_version",
            "scope_blocks",
            "coverage_requested_count",
            "coverage_eligible_count",
            "coverage_missing_count",
            "as_of",
            "published_at",
            "members_sealed_at",
            "run_id",
        )
    ]
    price_publications = [
        row for row in publication_rows if row.get("dataset_key") == _PRICE_DATASET
    ]
    members = []
    price_rows: list[dict[str, object]] = []
    task_results: list[Mapping[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    if len(price_publications) == 1:
        price_publication = price_publications[0]
        price_publication_id = price_publication.get("publication_id")
        if not isinstance(price_publication_id, UUID):
            raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
        members = list(
            PublicationMemberModel._default_manager.filter(
                publication_id=price_publication_id,
                dataset_key=_PRICE_DATASET,
            ).order_by("natural_key")
        )
        domain_members = tuple(member.to_domain() for member in members)
        try:
            fact_hashes = publication_fact_content_hashes(domain_members)
            price_publication["computed_member_manifest_hash"] = publication_member_manifest_hash(
                domain_members,
                policy_identity=cast(str, price_publication["policy_version"]),
            )
            fact_pks = [int(member.fact_pk) for member in members]
        except (AttributeError, TypeError, ValueError):
            fact_hashes = {}
            fact_pks = []
        facts = PriceBarModel._default_manager.in_bulk(fact_pks)
        from apps.data_center.infrastructure.publication_fact_identity import (
            build_publication_fact_identity,
        )

        for fact_pk, fact in facts.items():
            identity = build_publication_fact_identity(_PRICE_DATASET, fact)
            price_rows.append(
                {
                    "fact_pk": str(fact_pk),
                    "bar_date": fact.bar_date,
                    "freq": fact.freq,
                    "adjustment": fact.adjustment,
                    "natural_key": identity.natural_key,
                    "source": identity.source,
                    "source_record_id": identity.source_record_id,
                    "observed_at": identity.observed_at,
                    "raw_payload_hash": identity.raw_payload_hash,
                    "quality_status": identity.quality_status,
                    "revision_number": identity.revision_number,
                    "fact_content_hash": fact_hashes.get((_PRICE_FACT_TABLE, str(fact_pk))),
                }
            )
        publication_objects = {
            str(item.publication_id): item
            for item in CanonicalPublicationModel._default_manager.filter(
                publication_id__in=publication_ids
            )
        }
        for publication_row in publication_rows:
            dataset_key = publication_row.get("dataset_key")
            publication_id = publication_row.get("publication_id")
            if not isinstance(dataset_key, str) or not isinstance(publication_id, UUID):
                raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
            publication_object = publication_objects.get(str(publication_id))
            publication_members = (
                domain_members
                if publication_row.get("dataset_key") == _PRICE_DATASET
                else tuple(
                    item.to_domain()
                    for item in PublicationMemberModel._default_manager.filter(
                        publication_id=publication_id
                    ).order_by("natural_key")
                )
            )
            if publication_object is None:
                raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
            try:
                domain_publication = publication_object.to_domain()
                publication_fact_hashes = publication_fact_content_hashes(publication_members)
                active_policy = policy_repository.get_active(dataset_key)
                published_at = domain_publication.published_at
                blocked_reason = (
                    "publication_knowledge_unavailable"
                    if published_at is None
                    else current_publication_evidence_blocked_reason(
                        domain_publication,
                        policy=active_policy,
                        members=publication_members,
                        fact_content_hashes=publication_fact_hashes,
                        knowledge_cutoff=published_at,
                    )
                )
                publication_row["computed_publication_hash"] = publication_hash(
                    tuple(member_reference(member) for member in publication_members),
                    policy_identity=cast(str, publication_row["policy_version"]),
                    scope_blocks=domain_publication.scope_blocks,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID") from exc
            if blocked_reason is not None:
                raise ExportBlocked("S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID")
            publication_row["_active_policy_evidence_validated"] = True
        manifest_rows = [
            dict(row)
            for row in CandidateRawAuditManifestModel._default_manager.filter(
                publication_id__in=publication_ids
            ).values(
                "publication_id",
                "publication_hash",
                "run_id",
                "dataset_key",
                "publication_key",
                "task_attempt_id",
                "raw_audit_count",
                "raw_audit_hash",
                "manifest_hash",
            )
        ]
        run_id = price_publication.get("run_id")
        if run_id is not None:
            task_rows = TaskExecutionModel._default_manager.filter(
                task_name=_FULL_MARKET_TASK_NAME,
                status="success",
                result__contains=str(run_id),
            ).values("task_id", "attempt_id", "status", "result")
            for task_row in task_rows:
                parsed_result = _parse_task_result(task_row.get("result"))
                if isinstance(parsed_result, dict) and parsed_result.get(
                    "publication_run_id"
                ) == str(run_id):
                    parsed_result["_task_id"] = task_row.get("task_id")
                    parsed_result["_task_attempt_id"] = task_row.get("attempt_id")
                    parsed_result["_task_status"] = task_row.get("status")
                    task_results.append(cast(Mapping[str, object], parsed_result))
    member_rows = [
        {
            "publication_id": member.publication_id,
            "dataset_key": member.dataset_key,
            "natural_key": member.natural_key,
            "source": member.source,
            "source_record_id": member.source_record_id,
            "fact_table": member.fact_table,
            "fact_pk": member.fact_pk,
            "observed_at": member.observed_at,
            "raw_payload_hash": member.raw_payload_hash,
            "quality_status": member.quality_status,
            "revision_number": member.revision_number,
            "fact_content_hash": member.fact_content_hash,
        }
        for member in members
    ]
    return _validate_current_market_publication_target(
        cast(Sequence[Mapping[str, object]], pointer_rows),
        cast(Sequence[Mapping[str, object]], publication_rows),
        member_rows,
        price_rows,
        manifest_rows,
        task_results,
    )


def _validate_isolated_market_graph_refresh(config: ExportConfig) -> dict[str, object] | None:
    """Rebuild the opt-in refresh receipt from the current isolated PostgreSQL snapshot."""

    if not config.advance_isolated_market_graph:
        return None
    required = (
        config.attempt_id,
        config.attempt_plan_sha256,
        config.postgres_container_id,
        config.redis_container_id,
        config.network,
        config.network_id,
        config.execution_image_id,
        config.postgres_container,
        config.redis_container,
        config.isolated_database,
    )
    if any(value is None or not value for value in required):
        raise ExportBlocked("S6_GRAPH_REFRESH_IDENTITY_INVALID")
    from scripts.s6_isolated_market_graph_receipt import (
        MarketGraphReceiptError,
        read_and_validate_refresh_receipt,
    )

    try:
        return read_and_validate_refresh_receipt(
            INPUT_ROOT / "current-market-graph-refresh.json",
            context={
                "candidate_sha": config.candidate_sha,
                "attempt_id": cast(str, config.attempt_id),
                "attempt_plan_sha256": cast(str, config.attempt_plan_sha256),
                "database": cast(str, config.isolated_database),
                "postgres_container": cast(str, config.postgres_container),
                "redis_container": cast(str, config.redis_container),
                "postgres_container_id": cast(str, config.postgres_container_id),
                "redis_container_id": cast(str, config.redis_container_id),
                "network": cast(str, config.network),
                "network_id": cast(str, config.network_id),
                "execution_image_id": cast(str, config.execution_image_id),
            },
        )
    except MarketGraphReceiptError as exc:
        raise ExportBlocked(exc.error_code) from exc


def _export_universe(config: ExportConfig) -> None:
    """Export the dynamic A-share scope bound to current formal publications."""

    from apps.data_center.application.market_provider_rehearsal import rehearsal_digest
    from apps.data_center.target_date_universe_composition import (
        build_target_date_a_share_universe_scope,
    )

    identities_value = _read_json(INPUT_ROOT / "provider-identities.json", 16_384)
    unit_value = _read_json_object(INPUT_ROOT / "unit-contract.json", 65_536)
    _validate_frozen_inputs(identities_value, unit_value, config.candidate_sha)
    with _read_only_database(config.expected_database):
        refresh_receipt = _validate_isolated_market_graph_refresh(config)
        target_date = _current_market_publication_target_date()
        if (
            refresh_receipt is not None
            and refresh_receipt.get("target_trade_date") != target_date.isoformat()
        ):
            raise ExportBlocked("S6_GRAPH_REFRESH_RECEIPT_MISMATCH")
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
    refresh_receipt = _validate_isolated_market_graph_refresh(config)
    if refresh_receipt is not None and refresh_receipt.get("target_trade_date") != summary.get(
        "target_trade_date"
    ):
        raise ExportBlocked("S6_GRAPH_REFRESH_RECEIPT_MISMATCH")
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
