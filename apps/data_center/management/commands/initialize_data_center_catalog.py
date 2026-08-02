"""Import reviewed Data Center governance projections into runtime Catalog rows."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.catalog_use_cases import (
    SynchronizeDataCenterCatalogUseCase,
)
from apps.data_center.composition import (
    get_data_owner_registry_repository,
    get_dataset_contract_repository,
    get_provider_binding_repository,
    get_publication_policy_repository,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    ProviderBinding,
    PublicationPolicy,
)


def _read_object(path: Path) -> dict[str, object]:
    """Read one JSON object and reject malformed projections."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError(f"cannot read catalog manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CommandError(f"catalog manifest {path} must contain an object")
    if str(payload.get("schema_version") or "") != "1.0":
        raise CommandError(f"catalog manifest {path} has unsupported schema_version")
    return payload


def _rows(payload: Mapping[str, object], key: str, path: Path) -> list[Mapping[str, object]]:
    """Return object rows under a manifest key."""

    raw = payload.get(key)
    if not isinstance(raw, list):
        raise CommandError(f"catalog manifest {path} must contain a {key} list")
    rows: list[Mapping[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise CommandError(f"catalog manifest {path} contains a non-object {key} row")
        rows.append(item)
    return rows


def _required_text(row: Mapping[str, object], key: str, context: str) -> str:
    """Read a required non-empty string from one manifest row."""

    value = str(row.get(key) or "").strip()
    if not value:
        raise CommandError(f"{context} requires {key}")
    return value


def _as_int(value: object, context: str) -> int:
    """Parse a JSON integer while rejecting booleans and fractional values."""

    if isinstance(value, bool):
        raise CommandError(f"{context} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise CommandError(f"{context} must be an integer") from exc
    raise CommandError(f"{context} must be an integer")


def _as_float(value: object, context: str) -> float:
    """Parse a JSON finite float at the manifest boundary."""

    if isinstance(value, bool):
        raise CommandError(f"{context} must be a number")
    if not isinstance(value, (int, float, str)):
        raise CommandError(f"{context} must be a number")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise CommandError(f"{context} must be a number") from exc
    if not parsed == parsed or parsed in {float("inf"), float("-inf")}:
        raise CommandError(f"{context} must be a finite number")
    return parsed


def _dataset_key(row: Mapping[str, object], context: str) -> DatasetKey:
    """Build a versioned DatasetKey from a manifest row."""

    return DatasetKey(
        value=_required_text(row, "dataset_key", context),
        contract_version=_required_text(row, "contract_version", context),
        schema_version=str(row.get("schema_version") or "1.0").strip(),
    )


def _load_contracts(path: Path) -> list[DatasetContract]:
    """Parse Dataset Contract rows."""

    payload = _read_object(path)
    manifest_owner = str(payload.get("owner") or "").strip()
    result: list[DatasetContract] = []
    for row in _rows(payload, "contracts", path):
        context = f"contract {row.get('dataset_key')!r}"
        fields_raw = row.get("fields")
        if not isinstance(fields_raw, list) or not fields_raw:
            raise CommandError(f"{context} requires non-empty fields")
        fields: list[DatasetFieldContract] = []
        for field_raw in fields_raw:
            if not isinstance(field_raw, Mapping):
                raise CommandError(f"{context} contains an invalid field")
            fields.append(
                DatasetFieldContract(
                    name=_required_text(field_raw, "name", context),
                    value_type=str(field_raw.get("type") or field_raw.get("value_type") or ""),
                    unit=(str(field_raw["unit"]) if field_raw.get("unit") is not None else None),
                    nullable=bool(field_raw.get("nullable", False)),
                    zero_allowed=bool(field_raw.get("zero_allowed", False)),
                    minimum=(
                        _as_float(field_raw["minimum"], f"{context}.minimum")
                        if field_raw.get("minimum") is not None
                        else None
                    ),
                    maximum=(
                        _as_float(field_raw["maximum"], f"{context}.maximum")
                        if field_raw.get("maximum") is not None
                        else None
                    ),
                )
            )
        result.append(
            DatasetContract(
                key=_dataset_key(row, context),
                owner=(
                    str(row.get("owner") or manifest_owner).strip()
                    or _required_text(row, "owner", context)
                ),
                frequency=_required_text(row, "frequency", context),
                decision_critical=bool(row.get("decision_critical", False)),
                fields=tuple(fields),
                freshness_seconds=(
                    _as_int(row["freshness_seconds"], f"{context}.freshness_seconds")
                    if row.get("freshness_seconds") is not None
                    else None
                ),
                comparable_group=(
                    str(row["comparable_group"]).strip()
                    if row.get("comparable_group") is not None
                    else None
                ),
            )
        )
    return result


def _load_bindings(
    path: Path,
    contracts: Mapping[str, DatasetContract],
) -> list[ProviderBinding]:
    """Parse provider bindings and require a matching contract version."""

    result: list[ProviderBinding] = []
    for row in _rows(_read_object(path), "bindings", path):
        context = f"binding {row.get('dataset_key')!r}"
        key = _required_text(row, "dataset_key", context)
        contract = contracts.get(key)
        if contract is None:
            raise CommandError(f"{context} references an unknown contract")
        if (
            str(row.get("contract_version") or contract.key.contract_version)
            != contract.key.contract_version
        ):
            raise CommandError(f"{context} contract_version does not match Dataset Contract")
        result.append(
            ProviderBinding(
                dataset=contract.key,
                provider=_required_text(row, "provider", context),
                capability=_required_text(row, "capability", context),
                priority=_as_int(row.get("priority", 100), f"{context}.priority"),
                freshness_seconds=(
                    _as_int(row["freshness_seconds"], f"{context}.freshness_seconds")
                    if row.get("freshness_seconds") is not None
                    else None
                ),
                validator_key=_required_text(row, "validator_key", context),
                enabled=bool(row.get("enabled", True)),
            )
        )
    return result


def _load_policies(
    path: Path,
    contracts: Mapping[str, DatasetContract],
) -> list[PublicationPolicy]:
    """Parse publication policies and require a matching contract version."""

    result: list[PublicationPolicy] = []
    for row in _rows(_read_object(path), "policies", path):
        context = f"policy {row.get('dataset_key')!r}"
        key = _required_text(row, "dataset_key", context)
        contract = contracts.get(key)
        if contract is None:
            raise CommandError(f"{context} references an unknown contract")
        evidence = row.get("required_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise CommandError(f"{context} requires evidence keys")
        result.append(
            PublicationPolicy(
                dataset=contract.key,
                minimum_coverage_ratio=_as_float(
                    row.get("minimum_coverage_ratio", 0.0),
                    f"{context}.minimum_coverage_ratio",
                ),
                allow_partial=bool(row.get("allow_partial", False)),
                conflict_action=_required_text(row, "conflict_action", context),
                required_evidence=tuple(str(item) for item in evidence),
                retention_days=_as_int(row.get("retention_days", 0), f"{context}.retention_days"),
            )
        )
    return result


def _load_owners(
    path: Path, contracts: Mapping[str, DatasetContract]
) -> list[DataOwnerRegistration]:
    """Parse ownership registrations for datasets present in the contract catalog."""

    payload = _read_object(path)
    result: list[DataOwnerRegistration] = []
    for row in _rows(payload, "datasets", path):
        context = f"owner {row.get('dataset_key')!r}"
        key = _required_text(row, "dataset_key", context)
        if key not in contracts:
            continue
        result.append(
            DataOwnerRegistration(
                dataset_key=key,
                data_platform_owner=_required_text(row, "owner", context),
                business_owner=_required_text(row, "business_owner", context),
                acceptance_owner=_required_text(row, "acceptance_owner", context),
                active=True,
            )
        )
    return result


class Command(BaseCommand):
    """Synchronize reviewed governance manifests into the runtime catalog."""

    help = "Synchronize Data Center Dataset Contracts, bindings, policies and owners."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register manifest path overrides for offline/bootstrap testing."""

        root = Path(settings.BASE_DIR) / "governance"
        parser.add_argument("--contracts", default=str(root / "dataset_contracts.json"))
        parser.add_argument("--bindings", default=str(root / "provider_bindings.json"))
        parser.add_argument("--policies", default=str(root / "publication_policies.json"))
        parser.add_argument("--owners", default=str(root / "data_ownership_contracts.json"))

    def handle(self, *args: Any, **options: Any) -> None:
        """Validate all projections before atomically writing runtime rows."""

        contract_path = Path(str(options["contracts"])).resolve()
        binding_path = Path(str(options["bindings"])).resolve()
        policy_path = Path(str(options["policies"])).resolve()
        owner_path = Path(str(options["owners"])).resolve()
        contracts = _load_contracts(contract_path)
        contract_map = {contract.key.value: contract for contract in contracts}
        result = SynchronizeDataCenterCatalogUseCase(
            contracts=get_dataset_contract_repository(),
            bindings=get_provider_binding_repository(),
            policies=get_publication_policy_repository(),
            owners=get_data_owner_registry_repository(),
        ).execute(
            contracts=contracts,
            bindings=_load_bindings(binding_path, contract_map),
            policies=_load_policies(policy_path, contract_map),
            owners=_load_owners(owner_path, contract_map),
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Data Center catalog synchronized: "
                f"contracts={result.contracts}, bindings={result.bindings}, "
                f"policies={result.policies}, owners={result.owners}"
            )
        )
