"""Native PostgreSQL checks for generic calendar isolation and batch fail-closed behavior."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import UTC
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, models
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.data_center.application.calendar_catalog_bootstrap import (
    CALENDAR_DATASET_KEY,
    CalendarCatalogBootstrapRows,
    CreateCalendarCatalogBootstrapUseCase,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion
from apps.data_center.infrastructure.calendar_catalog_bootstrap_repository import (
    DjangoCalendarCatalogBootstrapRepository,
)
from apps.data_center.infrastructure.calendar_catalog_history_guard import (
    calendar_catalog_history_guard_applied_at,
)
from apps.data_center.infrastructure.catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DataOwnerRegistryRepository,
    DatasetContractRepository,
    ProviderBindingRepository,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center"],
)

_CATALOG_MODELS = (
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
    DataOwnerRegistrationModel,
)
_ORDINARY_DATASET_KEY = "fixture.generic.catalog.postgres"
_CALENDAR_REJECTION = (
    "generic catalog writes do not support the exchange-calendar dataset; "
    "the calendar bootstrap only creates an absent exact catalog or accepts "
    "an exact replay, and cannot update, repair, or switch existing catalog history"
)
_DML = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)


@pytest.fixture(autouse=True)
def _require_real_0115_postgres_guard() -> Iterator[None]:
    """Require the migrated native PostgreSQL schema and installed 0115 triggers."""

    if connection.vendor != "postgresql":
        pytest.skip("generic calendar catalog contract requires native PostgreSQL")
    table_names = set(connection.introspection.table_names())
    required_tables = {
        "django_migrations",
        *(model._meta.db_table for model in _CATALOG_MODELS),
        CanonicalPublicationModel._meta.db_table,
    }
    assert required_tables <= table_names
    assert (
        calendar_catalog_history_guard_applied_at(
            connection, server_now=timezone.now().astimezone(UTC)
        )
        is not None
    ), "the actual 0115 calendar catalog guard must be installed"
    yield


def _calendar_catalog_rows() -> CalendarCatalogBootstrapRows:
    """Build the exact four typed rows consumed by the create-only calendar bootstrap."""

    key = DatasetKey(CALENDAR_DATASET_KEY, "1.0", "exchange-calendar-snapshot-v1")
    return CalendarCatalogBootstrapRows(
        contract=DatasetContract(
            key=key,
            owner="data-platform",
            frequency="calendar",
            decision_critical=True,
            fields=(
                DatasetFieldContract("exchange", "string", None, False, False),
                DatasetFieldContract("calendar_date", "date", None, False, False),
                DatasetFieldContract("is_open", "boolean", None, False, False),
                DatasetFieldContract("previous_open_date", "date", None, False, False),
            ),
            calendar_response_max_age_seconds=900,
        ),
        binding=ProviderBinding(
            dataset=key,
            provider="tushare",
            capability="exchange_calendar",
            priority=10,
            freshness_seconds=None,
            validator_key="exchange_calendar.tushare.trade_cal.full_date.v1",
            enabled=True,
        ),
        policy=PublicationPolicy(
            dataset=key,
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=("source", "fact_content_hash"),
            retention_days=3650,
            policy_version="calendar-reference-v1",
            member_codec_version=CalendarNullableMemberCodecVersion.V1,
        ),
        owner=DataOwnerRegistration(
            dataset_key=CALENDAR_DATASET_KEY,
            data_platform_owner="data-platform",
            business_owner="simulated_trading",
            acceptance_owner="data-platform",
            active=True,
        ),
    )


def _calendar_catalog_rowsets() -> dict[str, list[dict[str, object]]]:
    """Return every persisted field for all four calendar catalog histories."""

    return {
        model._meta.db_table: list(
            model._default_manager.filter(dataset_key=CALENDAR_DATASET_KEY).order_by("pk").values()
        )
        for model in _CATALOG_MODELS
    }


def _all_catalog_rowsets() -> dict[str, list[dict[str, object]]]:
    """Return every persisted field for every row in the four catalog tables."""

    return {
        model._meta.db_table: list(model._default_manager.order_by("pk").values())
        for model in _CATALOG_MODELS
    }


def _activation_unrelated_catalog_rowsets() -> dict[str, list[dict[str, object]]]:
    """Return the three complete catalog rowsets fingerprinted as unrelated state."""

    models = (
        DatasetContractModel,
        DatasetProviderBindingModel,
        DataOwnerRegistrationModel,
    )
    return {
        model._meta.db_table: list(model._default_manager.order_by("pk").values())
        for model in models
    }


def _seed_guarded_calendar_catalog() -> None:
    """Activate the real DB guard with a state fixture, without member/Audit authority."""

    assert all(not rows for rows in _calendar_catalog_rowsets().values())
    candidate = _calendar_catalog_rows()
    CreateCalendarCatalogBootstrapUseCase(DjangoCalendarCatalogBootstrapRepository()).execute(
        candidate
    )
    CanonicalPublicationModel._default_manager.create(
        dataset_key=CALENDAR_DATASET_KEY,
        publication_key=f"exchange-calendar:generic-sync-{uuid4().hex}",
        policy_version=candidate.policy.policy_version,
        state="published",
        selected_source="generic-sync-contract-test",
        publication_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        member_count=1,
        must_not_use_for_decision=True,
        published_at=timezone.now().astimezone(UTC),
    )
    assert all(len(rows) == 1 for rows in _calendar_catalog_rowsets().values())


def _ordinary_row(kind: str) -> dict[str, object]:
    """Return one ordinary dataset row for the requested generic manifest."""

    if kind == "contracts":
        return {
            "dataset_key": _ORDINARY_DATASET_KEY,
            "contract_version": "1.0",
            "schema_version": "1.0",
            "owner": "fixture-owner",
            "frequency": "daily",
            "decision_critical": False,
            "fields": [
                {
                    "name": "value",
                    "type": "decimal",
                    "unit": "unit",
                    "nullable": False,
                    "zero_allowed": True,
                }
            ],
        }
    if kind == "bindings":
        return {
            "dataset_key": _ORDINARY_DATASET_KEY,
            "contract_version": "1.0",
            "provider": "fixture-provider",
            "capability": "snapshot",
            "priority": 10,
            "validator_key": "fixture.validator",
            "enabled": True,
        }
    if kind == "policies":
        return {
            "dataset_key": _ORDINARY_DATASET_KEY,
            "contract_version": "1.0",
            "minimum_coverage_ratio": 1.0,
            "allow_partial": False,
            "conflict_action": "block",
            "required_evidence": ["source", "payload_hash"],
            "retention_days": 30,
            "policy_version": "ordinary-policy-v1",
        }
    if kind == "owners":
        return {
            "dataset_key": _ORDINARY_DATASET_KEY,
            "owner": "fixture-owner",
            "business_owner": "fixture-business",
            "acceptance_owner": "fixture-acceptance",
        }
    raise AssertionError(f"unsupported manifest kind: {kind}")


def _calendar_manifest_row(kind: str) -> dict[str, object]:
    """Return one valid calendar row for the requested generic manifest."""

    candidate = _calendar_catalog_rows()
    if kind == "contracts":
        return {
            "dataset_key": candidate.contract.key.value,
            "contract_version": candidate.contract.key.contract_version,
            "schema_version": candidate.contract.key.schema_version,
            "owner": candidate.contract.owner,
            "frequency": candidate.contract.frequency,
            "decision_critical": candidate.contract.decision_critical,
            "fields": [
                {
                    "name": field.name,
                    "type": field.value_type,
                    "unit": field.unit,
                    "nullable": field.nullable,
                    "zero_allowed": field.zero_allowed,
                }
                for field in candidate.contract.fields
            ],
            "calendar_response_max_age_seconds": (
                candidate.contract.calendar_response_max_age_seconds
            ),
        }
    if kind == "bindings":
        return {
            "dataset_key": candidate.binding.dataset.value,
            "contract_version": candidate.binding.dataset.contract_version,
            "provider": candidate.binding.provider,
            "capability": candidate.binding.capability,
            "priority": candidate.binding.priority,
            "validator_key": candidate.binding.validator_key,
            "enabled": candidate.binding.enabled,
        }
    if kind == "policies":
        return {
            "dataset_key": candidate.policy.dataset.value,
            "contract_version": candidate.policy.dataset.contract_version,
            "minimum_coverage_ratio": candidate.policy.minimum_coverage_ratio,
            "allow_partial": candidate.policy.allow_partial,
            "conflict_action": candidate.policy.conflict_action,
            "required_evidence": list(candidate.policy.required_evidence),
            "retention_days": candidate.policy.retention_days,
            "policy_version": candidate.policy.policy_version,
            "member_codec_version": candidate.policy.member_codec_version.value,
        }
    if kind == "owners":
        return {
            "dataset_key": candidate.owner.dataset_key,
            "owner": candidate.owner.data_platform_owner,
            "business_owner": candidate.owner.business_owner,
            "acceptance_owner": candidate.owner.acceptance_owner,
        }
    raise AssertionError(f"unsupported manifest kind: {kind}")


def _write_manifest_set(
    directory: Path,
    *,
    mixed_calendar_manifest: str | None = None,
) -> dict[str, Path]:
    """Write the four exact JSON inputs consumed by the public initialization command."""

    directory.mkdir(parents=True, exist_ok=True)
    collection_names = {
        "contracts": "contracts",
        "bindings": "bindings",
        "policies": "policies",
        "owners": "datasets",
    }
    payloads: dict[str, dict[str, object]] = {
        "contracts": {"schema_version": "1.0", "owner": "fixture-owner", "contracts": []},
        "bindings": {"schema_version": "1.0", "bindings": []},
        "policies": {"schema_version": "1.0", "policies": []},
        "owners": {"schema_version": "1.0", "datasets": []},
    }
    for kind, collection_name in collection_names.items():
        rows = [_ordinary_row(kind)]
        if kind == mixed_calendar_manifest:
            rows.append(_calendar_manifest_row(kind))
        payloads[kind][collection_name] = rows

    paths: dict[str, Path] = {}
    for kind, payload in payloads.items():
        path = directory / f"{kind}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        paths[kind] = path
    return paths


def _run_initialization(paths: Mapping[str, Path]) -> None:
    """Invoke the public generic catalog command with all four manifest paths."""

    call_command(
        "initialize_data_center_catalog",
        contracts=str(paths["contracts"]),
        bindings=str(paths["bindings"]),
        policies=str(paths["policies"]),
        owners=str(paths["owners"]),
        stdout=StringIO(),
    )


def _catalog_mutation_queries(queries: list[dict[str, object]]) -> list[str]:
    """Return captured SQL writes targeting any of the four catalog tables."""

    table_names = tuple(model._meta.db_table for model in _CATALOG_MODELS)
    return [
        str(query["sql"])
        for query in queries
        if _DML.match(str(query["sql"]))
        and any(table_name in str(query["sql"]) for table_name in table_names)
    ]


def _policy_manifest_row(policy: PublicationPolicy, *, active: bool) -> dict[str, object]:
    """Project one typed policy into the exact command JSON row shape."""

    row: dict[str, object] = {
        "dataset_key": policy.dataset.value,
        "contract_version": policy.dataset.contract_version,
        "schema_version": policy.dataset.schema_version,
        "minimum_coverage_ratio": policy.minimum_coverage_ratio,
        "allow_partial": policy.allow_partial,
        "conflict_action": policy.conflict_action,
        "required_evidence": list(policy.required_evidence),
        "retention_days": policy.retention_days,
        "policy_version": policy.policy_version,
        "member_codec_version": (
            policy.member_codec_version.value if policy.member_codec_version is not None else None
        ),
    }
    if active:
        row["active"] = True
    return row


def _seed_ordinary_activation_policy() -> PublicationPolicy:
    """Create one ordinary dataset's active contract, binding, owner and legacy policy."""

    key = DatasetKey(_ORDINARY_DATASET_KEY, "1.0", "1.0")
    DatasetContractModel._default_manager.create(
        dataset_key=key.value,
        contract_version=key.contract_version,
        schema_version=key.schema_version,
        owner="fixture-owner",
        frequency="daily",
        decision_critical=True,
        fields=[
            {
                "name": "value",
                "type": "decimal",
                "unit": "unit",
                "nullable": False,
                "zero_allowed": True,
            }
        ],
        active=True,
    )
    DatasetProviderBindingModel._default_manager.create(
        dataset_key=key.value,
        contract_version=key.contract_version,
        schema_version=key.schema_version,
        provider="activation-fixture",
        capability="snapshot",
        priority=1,
        validator_key="activation-fixture.validator",
        enabled=True,
    )
    DataOwnerRegistrationModel._default_manager.create(
        dataset_key=key.value,
        data_platform_owner="fixture-owner",
        business_owner="fixture-business",
        acceptance_owner="fixture-acceptance",
        active=True,
    )
    active_policy = PublicationPolicy(
        dataset=key,
        minimum_coverage_ratio=0.8,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "payload_hash"),
        retention_days=30,
        policy_version="ordinary-policy-v1",
    )
    assert PublicationPolicyRepository().save(active_policy) == active_policy
    return active_policy


def _write_policy_activation_inputs(
    directory: Path,
    *,
    changed_calendar_policy: bool = False,
) -> tuple[Path, Path, tuple[str, ...]]:
    """Write a complete two-policy preflight and candidate with calendar as a non-target."""

    directory.mkdir(parents=True, exist_ok=True)
    active_policies = [
        row.to_domain()
        for row in DatasetPublicationPolicyModel._default_manager.filter(active=True).order_by(
            "dataset_key"
        )
    ]
    active_contract_keys = [
        {
            "dataset_key": row.dataset_key,
            "contract_version": row.contract_version,
            "schema_version": row.schema_version,
        }
        for row in DatasetContractModel._default_manager.filter(active=True).order_by("dataset_key")
    ]
    ordinary_active = next(
        policy for policy in active_policies if policy.dataset.value == _ORDINARY_DATASET_KEY
    )
    calendar_active = next(
        policy for policy in active_policies if policy.dataset.value == CALENDAR_DATASET_KEY
    )
    ordinary_candidate = replace(
        ordinary_active,
        minimum_coverage_ratio=1.0,
        policy_version="ordinary-policy-v2",
    )
    calendar_candidate = (
        replace(calendar_active, retention_days=calendar_active.retention_days + 1)
        if changed_calendar_policy
        else calendar_active
    )
    candidate_rows = [
        _policy_manifest_row(ordinary_candidate, active=False),
        _policy_manifest_row(calendar_candidate, active=False),
    ]
    candidate_rows.sort(key=lambda row: str(row["dataset_key"]))
    candidate_bytes = (
        json.dumps(
            {"schema_version": "1.0", "policies": candidate_rows},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    candidate_path = directory / "candidate-policies.json"
    candidate_path.write_bytes(candidate_bytes)

    expected_payload: dict[str, object] = {
        "read_only": True,
        "active_contract_keys": active_contract_keys,
        "active_policies": [
            _policy_manifest_row(policy, active=True) for policy in active_policies
        ],
        "unrelated_catalog_baseline": {
            table_name: {
                "row_count": count,
                "all_persisted_fields_sha256": digest,
                "encoding": "catalog-rowset-v1-including-identities-and-timestamps",
            }
            for table_name, model in (
                ("data_center_dataset_contract", DatasetContractModel),
                ("data_center_dataset_provider_binding", DatasetProviderBindingModel),
                ("data_center_data_owner_registration", DataOwnerRegistrationModel),
            )
            for count, digest in [_rowset_fingerprint(model)]
        },
        "published_current_metadata": [],
        "candidate_policy_projection_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "candidate_target_dataset_keys": [_ORDINARY_DATASET_KEY],
    }
    expected_path = directory / "expected-policy-state.json"
    expected_path.write_text(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return expected_path, candidate_path, (_ORDINARY_DATASET_KEY,)


def _rowset_fingerprint(model: type[models.Model]) -> tuple[int, str]:
    """Match the activation repository's full-row JSON fingerprint."""

    rows = list(model._default_manager.order_by("pk").values())
    encoded = json.dumps(
        rows,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return len(rows), hashlib.sha256(encoded).hexdigest()


def _all_policy_rowsets() -> dict[str, list[dict[str, object]]]:
    """Return complete policy history, including activation flags and clocks."""

    return {
        model._meta.db_table: list(model._default_manager.order_by("pk").values())
        for model in (DatasetPublicationPolicyModel,)
    }


def _run_policy_activation(expected_path: Path, candidate_path: Path) -> dict[str, object]:
    """Invoke the actual management command and decode its JSON outcome."""

    output = StringIO()
    call_command(
        "activate_publication_policies",
        expected_state=str(expected_path),
        policies=str(candidate_path),
        execute=True,
        stdout=output,
    )
    return json.loads(output.getvalue())


def test_default_manifest_sync_preserves_all_calendar_rows_and_writes_ordinary_dataset() -> None:
    """The real default manifests leave calendar identities/clocks exact and write ordinary rows."""

    _seed_guarded_calendar_catalog()
    before_calendar = _calendar_catalog_rowsets()
    call_command("initialize_data_center_catalog", stdout=StringIO())

    assert _calendar_catalog_rowsets() == before_calendar
    ordinary_key = "equity.quote.snapshot"
    contract = DatasetContractModel._default_manager.get(dataset_key=ordinary_key, active=True)
    bindings = DatasetProviderBindingModel._default_manager.filter(
        dataset_key=ordinary_key,
        enabled=True,
    )
    policy = DatasetPublicationPolicyModel._default_manager.get(
        dataset_key=ordinary_key,
        active=True,
    )
    owner = DataOwnerRegistrationModel._default_manager.get(
        dataset_key=ordinary_key,
        active=True,
    )
    assert contract.active is True
    assert bindings.exists()
    assert policy.active is True
    assert owner.active is True


def test_all_generic_single_row_saves_reject_calendar_before_catalog_mutation() -> None:
    """Each generic save port rejects the calendar key before issuing a table write."""

    candidate = _calendar_catalog_rows()
    operations = (
        (DatasetContractRepository(), candidate.contract),
        (ProviderBindingRepository(), candidate.binding),
        (PublicationPolicyRepository(), candidate.policy),
        (DataOwnerRegistryRepository(), candidate.owner),
    )
    for repository, row in operations:
        with CaptureQueriesContext(connection) as captured:
            with pytest.raises(ValueError, match="generic catalog writes do not support"):
                repository.save(row)
        assert _catalog_mutation_queries(captured.captured_queries) == []


def test_policy_activation_keeps_calendar_in_full_snapshot_as_exact_non_target(
    tmp_path: Path,
) -> None:
    """Ordinary target activation succeeds while all four calendar rows remain byte-equivalent."""

    _seed_guarded_calendar_catalog()
    _seed_ordinary_activation_policy()
    before_calendar = _calendar_catalog_rowsets()
    before_catalog = _activation_unrelated_catalog_rowsets()
    before_policies = _all_policy_rowsets()
    before_publications = list(CanonicalPublicationModel._default_manager.order_by("pk").values())
    expected_path, candidate_path, targets = _write_policy_activation_inputs(tmp_path)

    result = _run_policy_activation(expected_path, candidate_path)

    assert result["mode"] == "execute"
    assert result["activated"] is True
    assert tuple(result["target_dataset_keys"]) == targets
    assert CALENDAR_DATASET_KEY not in result["target_dataset_keys"]
    assert _calendar_catalog_rowsets() == before_calendar
    assert _activation_unrelated_catalog_rowsets() == before_catalog
    assert (
        _all_policy_rowsets()[DatasetPublicationPolicyModel._meta.db_table]
        != before_policies[DatasetPublicationPolicyModel._meta.db_table]
    )
    calendar_policy_rows = list(
        DatasetPublicationPolicyModel._default_manager.filter(dataset_key=CALENDAR_DATASET_KEY)
        .order_by("pk")
        .values()
    )
    assert calendar_policy_rows == before_calendar[DatasetPublicationPolicyModel._meta.db_table]
    active_ordinary = DatasetPublicationPolicyModel._default_manager.get(
        dataset_key=_ORDINARY_DATASET_KEY,
        active=True,
    )
    assert active_ordinary.policy_version == "ordinary-policy-v2"
    assert list(CanonicalPublicationModel._default_manager.order_by("pk").values()) == (
        before_publications
    )


def test_changed_calendar_non_target_is_rejected_before_any_catalog_write(
    tmp_path: Path,
) -> None:
    """A changed calendar candidate is compared to the full snapshot before target saves."""

    _seed_guarded_calendar_catalog()
    _seed_ordinary_activation_policy()
    before_calendar = _calendar_catalog_rowsets()
    before_catalog = _all_catalog_rowsets()
    before_policies = _all_policy_rowsets()
    before_publications = list(CanonicalPublicationModel._default_manager.order_by("pk").values())
    expected_path, candidate_path, _targets = _write_policy_activation_inputs(
        tmp_path,
        changed_calendar_policy=True,
    )

    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(CommandError, match="non-target policy content changed"):
            _run_policy_activation(expected_path, candidate_path)

    assert _catalog_mutation_queries(captured.captured_queries) == []
    assert _calendar_catalog_rowsets() == before_calendar
    assert _all_catalog_rowsets() == before_catalog
    assert _all_policy_rowsets() == before_policies
    assert list(CanonicalPublicationModel._default_manager.order_by("pk").values()) == (
        before_publications
    )


@pytest.mark.parametrize("manifest_kind", ["contracts", "bindings", "policies", "owners"])
def test_mixed_calendar_manifest_batch_fails_before_any_catalog_write(
    tmp_path: Path,
    manifest_kind: str,
) -> None:
    """Every explicit mixed manifest is rejected before the first repository mutation."""

    _seed_guarded_calendar_catalog()
    _run_initialization(_write_manifest_set(tmp_path / "seed"))
    before = _all_catalog_rowsets()
    paths = _write_manifest_set(
        tmp_path / "mixed",
        mixed_calendar_manifest=manifest_kind,
    )

    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(CommandError) as raised:
            _run_initialization(paths)

    assert str(raised.value) == _CALENDAR_REJECTION
    assert _catalog_mutation_queries(captured.captured_queries) == []
    assert _all_catalog_rowsets() == before
