"""Preview or execute a candidate-bound, policy-only catalog activation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.publication_policy_activation import (
    CATALOG_FINGERPRINT_TABLES,
    ActivatePublicationPoliciesUseCase,
    CatalogFingerprint,
    PublicationPolicyActivationError,
    PublicationPolicyActivationExpectedState,
    PublicationPolicyActivationRequest,
    PublishedCurrentMetadata,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.publication_policy_activation_composition import (
    get_publication_policy_activation_use_case,
)


def _read_json_object(path: Path, *, require_schema: bool) -> dict[str, object]:
    """Read one JSON object at the command input boundary."""

    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CommandError(f"cannot read activation input {path}: {error}") from error
    return _read_json_object_bytes(raw, path=path, require_schema=require_schema)


def _read_json_object_bytes(
    raw: bytes,
    *,
    path: Path,
    require_schema: bool,
) -> dict[str, object]:
    """Parse one already-read JSON object without reopening its source path."""

    try:
        payload: object = cast(object, json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CommandError(f"cannot parse activation input {path}: {error}") from error
    if not isinstance(payload, dict):
        raise CommandError(f"activation input {path} must contain a JSON object")
    result = cast(dict[str, object], payload)
    if require_schema and result.get("schema_version") != "1.0":
        raise CommandError(f"activation policy manifest {path} has unsupported schema_version")
    return result


def _rows(payload: Mapping[str, object], key: str, context: str) -> list[dict[str, object]]:
    """Return JSON object rows under one required list key."""

    raw = payload.get(key)
    if not isinstance(raw, list):
        raise CommandError(f"{context} must contain a {key} list")
    rows: list[dict[str, object]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise CommandError(f"{context}.{key}[{index}] must be an object")
        rows.append(cast(dict[str, object], dict(item)))
    return rows


def _required_text(
    row: Mapping[str, object], key: str, context: str, *, allow_empty: bool = False
) -> str:
    """Read one bounded text field without silently coercing JSON values."""

    value = row.get(key)
    if type(value) is not str or value != value.strip() or (not allow_empty and not value):
        raise CommandError(f"{context}.{key} must be bounded text")
    if len(value) > 300 or any(character in value for character in ("\r", "\n")):
        raise CommandError(f"{context}.{key} is too long or contains a newline")
    return value


def _required_hash(row: Mapping[str, object], key: str, context: str) -> str:
    """Read a lowercase SHA-256 digest."""

    value = _required_text(row, key, context)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CommandError(f"{context}.{key} must be a lowercase SHA-256 digest")
    return value


def _required_bool(row: Mapping[str, object], key: str, context: str) -> bool:
    """Read one strict JSON boolean."""

    value = row.get(key)
    if type(value) is not bool:
        raise CommandError(f"{context}.{key} must be boolean")
    return value


def _required_float(row: Mapping[str, object], key: str, context: str) -> float:
    """Read a finite JSON number."""

    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError(f"{context}.{key} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise CommandError(f"{context}.{key} must be finite")
    return converted


def _required_int(row: Mapping[str, object], key: str, context: str) -> int:
    """Read an integral JSON value while rejecting booleans and fractions."""

    value = row.get(key)
    if isinstance(value, bool):
        raise CommandError(f"{context}.{key} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise CommandError(f"{context}.{key} must be an integer")


def _required_list(row: Mapping[str, object], key: str, context: str) -> list[object]:
    """Read one JSON list."""

    value = row.get(key)
    if not isinstance(value, list):
        raise CommandError(f"{context}.{key} must be a list")
    return value


def _dataset_key(row: Mapping[str, object], context: str) -> str:
    """Read a dataset key from one expected-state row."""

    return _required_text(row, "dataset_key", context)


def _contract_keys(payload: Mapping[str, object]) -> tuple[DatasetKey, ...]:
    """Parse the active Dataset Contract key set from preflight evidence."""

    rows = _rows(payload, "active_contract_keys", "expected state")
    result: list[DatasetKey] = []
    for index, row in enumerate(rows):
        context = f"expected state.active_contract_keys[{index}]"
        result.append(
            DatasetKey(
                value=_required_text(row, "dataset_key", context),
                contract_version=_required_text(row, "contract_version", context),
                schema_version=_required_text(row, "schema_version", context),
            )
        )
    return tuple(sorted(result, key=lambda key: key.value))


def _policy(
    row: Mapping[str, object],
    *,
    context: str,
    contracts: Mapping[str, DatasetKey],
    require_active: bool,
) -> PublicationPolicy:
    """Parse one policy row against an expected active contract key."""

    dataset_key = _dataset_key(row, context)
    contract = contracts.get(dataset_key)
    if contract is None:
        raise CommandError(f"{context} references an unknown active contract")
    declared_contract = row.get("contract_version")
    if declared_contract is not None and declared_contract != contract.contract_version:
        raise CommandError(f"{context}.contract_version does not match expected contract")
    declared_schema = row.get("schema_version")
    if declared_schema is not None and declared_schema != contract.schema_version:
        raise CommandError(f"{context}.schema_version does not match expected contract")
    evidence = _required_list(row, "required_evidence", context)
    if not evidence or any(type(item) is not str or not item for item in evidence):
        raise CommandError(f"{context}.required_evidence must contain non-empty text keys")
    policy_version = row.get("policy_version", "legacy")
    if type(policy_version) is not str or not policy_version:
        raise CommandError(f"{context}.policy_version must be non-empty text")
    if "active" in row and require_active and _required_bool(row, "active", context) is not True:
        raise CommandError(f"{context}.active must be true in expected state")
    return PublicationPolicy(
        dataset=contract,
        minimum_coverage_ratio=_required_float(row, "minimum_coverage_ratio", context),
        allow_partial=_required_bool(row, "allow_partial", context),
        conflict_action=_required_text(row, "conflict_action", context),
        required_evidence=tuple(cast(str, item) for item in evidence),
        retention_days=_required_int(row, "retention_days", context),
        policy_version=policy_version,
    )


def _expected_state(path: Path) -> PublicationPolicyActivationExpectedState:
    """Parse the complete read-only rollout preflight artifact."""

    payload = _read_json_object(path, require_schema=False)
    if payload.get("read_only") is not True:
        raise CommandError("expected state must be a read-only preflight")
    contracts = _contract_keys(payload)
    contract_map = {key.value: key for key in contracts}
    policy_rows = _rows(payload, "active_policies", "expected state")
    policies = tuple(
        sorted(
            (
                _policy(
                    row,
                    context=f"expected state.active_policies[{index}]",
                    contracts=contract_map,
                    require_active=True,
                )
                for index, row in enumerate(policy_rows)
            ),
            key=lambda policy: policy.dataset.value,
        )
    )

    raw_baseline = payload.get("unrelated_catalog_baseline")
    if not isinstance(raw_baseline, Mapping):
        raise CommandError("expected state must contain unrelated_catalog_baseline")
    baseline: list[CatalogFingerprint] = []
    for table_name in sorted(CATALOG_FINGERPRINT_TABLES):
        item = raw_baseline.get(table_name)
        if not isinstance(item, Mapping):
            raise CommandError(f"expected state baseline is missing {table_name}")
        context = f"expected state.unrelated_catalog_baseline.{table_name}"
        baseline.append(
            CatalogFingerprint(
                table_name=table_name,
                row_count=_required_int(cast(Mapping[str, object], item), "row_count", context),
                sha256=_required_hash(
                    cast(Mapping[str, object], item), "all_persisted_fields_sha256", context
                ),
            )
        )
        if item.get("encoding") != "catalog-rowset-v1-including-identities-and-timestamps":
            raise CommandError(f"{context}.encoding is unsupported")

    metadata_rows = _rows(payload, "published_current_metadata", "expected state")
    metadata: list[PublishedCurrentMetadata] = []
    for index, row in enumerate(metadata_rows):
        context = f"expected state.published_current_metadata[{index}]"
        as_of = row.get("as_of")
        published_at = row.get("published_at")
        if as_of is not None and type(as_of) is not str:
            raise CommandError(f"{context}.as_of must be text or null")
        if published_at is not None and type(published_at) is not str:
            raise CommandError(f"{context}.published_at must be text or null")
        metadata.append(
            PublishedCurrentMetadata(
                dataset_key=_required_text(row, "dataset_key", context),
                publication_id=_required_text(row, "publication_id", context),
                policy_version=_required_text(row, "policy_version", context),
                publication_hash=_required_text(row, "publication_hash", context),
                member_count=_required_int(row, "member_count", context),
                as_of=as_of,
                published_at=published_at,
                must_not_use_for_decision=_required_bool(row, "must_not_use_for_decision", context),
                blocked_reason=_required_text(row, "blocked_reason", context, allow_empty=True),
            )
        )
    metadata_tuple = tuple(sorted(metadata, key=lambda item: item.dataset_key))

    target_values = _required_list(payload, "candidate_target_dataset_keys", "expected state")
    if any(type(item) is not str for item in target_values):
        raise CommandError("expected state candidate targets must be text")
    targets = tuple(cast(str, item) for item in target_values)
    return PublicationPolicyActivationExpectedState(
        active_policies=policies,
        active_contract_keys=contracts,
        unrelated_catalog_baseline=tuple(baseline),
        published_current_metadata=metadata_tuple,
        candidate_policy_projection_sha256=_required_hash(
            payload, "candidate_policy_projection_sha256", "expected state"
        ),
        candidate_target_dataset_keys=targets,
    )


def _candidate_policies(
    path: Path,
    expected: PublicationPolicyActivationExpectedState,
) -> tuple[tuple[PublicationPolicy, ...], str]:
    """Parse the candidate policy projection and return its exact byte hash."""

    try:
        candidate_bytes = path.read_bytes()
    except OSError as error:
        raise CommandError(f"cannot read candidate policy manifest {path}: {error}") from error
    manifest_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    payload = _read_json_object_bytes(candidate_bytes, path=path, require_schema=True)
    contracts = {key.value: key for key in expected.active_contract_keys}
    policies = tuple(
        sorted(
            (
                _policy(
                    row,
                    context=f"candidate policies[{index}]",
                    contracts=contracts,
                    require_active=False,
                )
                for index, row in enumerate(_rows(payload, "policies", "candidate manifest"))
            ),
            key=lambda policy: policy.dataset.value,
        )
    )
    return policies, manifest_sha256


class Command(BaseCommand):
    """Guard and optionally commit one exact policy-only activation."""

    help = "Preview or execute candidate-bound Data Center publication policy activation."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register explicit preflight and candidate manifest inputs."""

        root = Path(settings.BASE_DIR)
        parser.add_argument("--expected-state", required=True)
        parser.add_argument(
            "--policies",
            default=str(root / "governance" / "publication_policies.json"),
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Commit the activation after the guarded preflight; preview is the default.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Parse both artifacts and invoke preview or execute through composition."""

        del args
        expected_value = options.get("expected_state")
        policies_value = options.get("policies")
        if type(expected_value) is not str or type(policies_value) is not str:
            raise CommandError("--expected-state and --policies must be paths")
        try:
            expected = _expected_state(Path(expected_value).resolve())
            candidates, manifest_sha256 = _candidate_policies(
                Path(policies_value).resolve(), expected
            )
            request = PublicationPolicyActivationRequest(
                expected_state=expected,
                candidate_policies=candidates,
                candidate_manifest_sha256=manifest_sha256,
            )
            use_case: ActivatePublicationPoliciesUseCase = (
                get_publication_policy_activation_use_case()
            )
            result = (
                use_case.execute(request)
                if options.get("execute") is True
                else use_case.preview(request)
            )
        except (OSError, TypeError, ValueError, PublicationPolicyActivationError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )


__all__ = ["Command"]
