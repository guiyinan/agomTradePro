"""Real catalog-backed metadata selection for the calendar workbench scope."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from pytest_django.plugin import DjangoDbBlocker

from apps.data_center.application.calendar_capture_configuration import (
    CALENDAR_CAPTURE_CAPABILITY,
    CALENDAR_CAPTURE_VALIDATOR_KEY,
    CalendarCaptureConfigurationError,
)
from apps.data_center.application.calendar_workbench_scope import (
    CalendarWorkbenchCurrentPointerStatus,
    CalendarWorkbenchScopeMetadataStatus,
    CalendarWorkbenchSecretRuntimeStatus,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_workbench_scope_context,
)
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationPointerModel,
)
from shared.config import secrets
from tests.support.isolated_schema import isolated_schema
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

DATASET_KEY = "data_center.exchange_calendar_snapshot"
CONTRACT_VERSION = "2.0"
SCHEMA_VERSION = "1.0"
pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Calendar workbench catalog component requires Native PostgreSQL",
)
_CONFIGURATION_TABLES = (
    DatasetContractModel._meta.db_table,
    DatasetPublicationPolicyModel._meta.db_table,
    DatasetProviderBindingModel._meta.db_table,
    ProviderConfigModel._meta.db_table,
)
_SCHEMA_MODELS = (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
    DatasetProviderBindingModel,
    ProviderConfigModel,
    CanonicalPublicationPointerModel,
)


@pytest.fixture(autouse=True)
def _isolated_catalog(
    django_db_setup: str,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Verify TEST.NAME around cleanup and isolate only the selected catalog tables."""

    def verify_database_before_cleanup() -> None:
        """Prevent fixture cleanup if PostgreSQL no longer points at TEST.NAME."""

        assert_native_postgres_test_database(expected_name=django_db_setup)

    with django_db_blocker.unblock():
        assert_native_postgres_test_database(expected_name=django_db_setup)
        with isolated_schema(_SCHEMA_MODELS, before_cleanup=verify_database_before_cleanup):
            yield


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Use the shared explicitly targeted setup for this Native-only module."""

    return native_postgres_test_database


def _write_contract(
    *,
    dataset_key: str = DATASET_KEY,
    contract_version: str = CONTRACT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    ttl: int | None = 900,
) -> DatasetContractModel:
    """Persist or reuse one exact calendar contract, without changing row clocks."""

    expected: dict[str, object] = {
        "dataset_key": dataset_key,
        "contract_version": contract_version,
        "schema_version": schema_version,
        "owner": "data-platform",
        "frequency": "calendar",
        "decision_critical": True,
        "fields": [
            {
                "name": "calendar_date",
                "type": "date",
                "unit": None,
                "nullable": False,
                "zero_allowed": False,
            }
        ],
        "freshness_seconds": None,
        "execution_freshness_seconds": None,
        "calendar_response_max_age_seconds": ttl,
        "comparable_group": "",
        "active": True,
    }
    lookup = {
        "dataset_key": dataset_key,
        "contract_version": contract_version,
        "schema_version": schema_version,
    }
    rows = list(DatasetContractModel.objects.filter(**lookup))
    if len(rows) > 1:
        raise AssertionError("DatasetContractModel fixture identity is ambiguous")
    if rows:
        _assert_exact_fixture_fields(rows[0], expected, label="DatasetContractModel")
        return rows[0]
    return DatasetContractModel.objects.create(**expected)


def _assert_exact_fixture_fields(
    row: object,
    expected: dict[str, object],
    *,
    label: str,
) -> None:
    """Reject an existing fixture row unless every configured value is exact."""

    for field_name, expected_value in expected.items():
        if getattr(row, field_name, None) != expected_value:
            raise AssertionError(
                f"{label}.{field_name} conflicts with expected calendar fixture settings"
            )


def _write_configuration(*, dataset_key: str = DATASET_KEY) -> None:
    """Create missing exact fixture rows or reuse matching rows without mutation."""

    contract_values: dict[str, object] = {
        "dataset_key": dataset_key,
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "owner": "data-platform",
        "frequency": "calendar",
        "decision_critical": True,
        "fields": [
            {
                "name": "calendar_date",
                "type": "date",
                "unit": None,
                "nullable": False,
                "zero_allowed": False,
            }
        ],
        "freshness_seconds": None,
        "execution_freshness_seconds": None,
        "calendar_response_max_age_seconds": 900,
        "comparable_group": "",
        "active": True,
    }
    contract_lookup = {
        "dataset_key": dataset_key,
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
    }
    contract_rows = list(DatasetContractModel.objects.filter(**contract_lookup))
    if len(contract_rows) > 1:
        raise AssertionError("DatasetContractModel fixture identity is ambiguous")
    contract_row = contract_rows[0] if contract_rows else None
    if contract_row is not None:
        _assert_exact_fixture_fields(contract_row, contract_values, label="DatasetContractModel")

    policy_values: dict[str, object] = {
        "dataset_key": dataset_key,
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "policy_version": "calendar-v1",
        "member_codec_version": "calendar-nullable-member-v1",
        "minimum_coverage_ratio": 1.0,
        "allow_partial": False,
        "conflict_action": "block",
        "required_evidence": ["source", "fact_content_hash"],
        "retention_days": 3650,
        "active": True,
    }
    policy_lookup = {
        "dataset_key": dataset_key,
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "policy_version": "calendar-v1",
    }
    policy_rows = list(DatasetPublicationPolicyModel.objects.filter(**policy_lookup))
    if len(policy_rows) > 1:
        raise AssertionError("DatasetPublicationPolicyModel fixture identity is ambiguous")
    policy_row = policy_rows[0] if policy_rows else None
    if policy_row is not None:
        _assert_exact_fixture_fields(
            policy_row, policy_values, label="DatasetPublicationPolicyModel"
        )

    binding_values: dict[str, object] = {
        "dataset_key": dataset_key,
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "provider": "tushare",
        "capability": CALENDAR_CAPTURE_CAPABILITY,
        "priority": 10,
        "freshness_seconds": None,
        "validator_key": CALENDAR_CAPTURE_VALIDATOR_KEY,
        "enabled": True,
    }
    binding_lookup = {
        "dataset_key": dataset_key,
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "provider": "tushare",
        "capability": CALENDAR_CAPTURE_CAPABILITY,
    }
    binding_rows = list(DatasetProviderBindingModel.objects.filter(**binding_lookup))
    if len(binding_rows) > 1:
        raise AssertionError("DatasetProviderBindingModel fixture identity is ambiguous")
    binding_row = binding_rows[0] if binding_rows else None
    if binding_row is not None:
        _assert_exact_fixture_fields(
            binding_row, binding_values, label="DatasetProviderBindingModel"
        )

    provider_values: dict[str, object] = {
        "name": "calendar-workbench-provider-fixture",
        "source_type": "tushare",
        "is_active": True,
        "priority": 10,
        "http_url": "",
        "api_endpoint": "",
        "extra_config": {},
        "description": "Non-secret metadata fixture",
    }
    provider_lookup = {"name": "calendar-workbench-provider-fixture"}
    provider_rows = list(ProviderConfigModel.objects.filter(**provider_lookup))
    if len(provider_rows) > 1:
        raise AssertionError("ProviderConfigModel fixture identity is ambiguous")
    provider_row = provider_rows[0] if provider_rows else None
    if provider_row is not None:
        _assert_exact_fixture_fields(provider_row, provider_values, label="ProviderConfigModel")

    expected_contract_identity = (
        dataset_key,
        CONTRACT_VERSION,
        SCHEMA_VERSION,
    )
    active_calendar_contracts = DatasetContractModel.objects.filter(
        active=True, calendar_response_max_age_seconds__isnull=False
    )
    if any(
        (row.dataset_key, row.contract_version, row.schema_version) != expected_contract_identity
        for row in active_calendar_contracts
    ):
        raise AssertionError("an unrelated active calendar contract conflicts with this fixture")
    if (
        DatasetContractModel.objects.filter(dataset_key=dataset_key, active=True)
        .exclude(
            contract_version=CONTRACT_VERSION,
            schema_version=SCHEMA_VERSION,
        )
        .exists()
    ):
        raise AssertionError("another active contract version conflicts with this fixture")

    active_policies = DatasetPublicationPolicyModel.objects.filter(
        dataset_key=dataset_key, active=True
    )
    if any(policy.pk != getattr(policy_row, "pk", None) for policy in active_policies):
        raise AssertionError("another active publication policy conflicts with this fixture")

    enabled_calendar_bindings = DatasetProviderBindingModel.objects.filter(
        dataset_key=dataset_key,
        capability=CALENDAR_CAPTURE_CAPABILITY,
        enabled=True,
    )
    if any(binding.pk != getattr(binding_row, "pk", None) for binding in enabled_calendar_bindings):
        raise AssertionError("another enabled calendar binding conflicts with this fixture")

    active_tushare_providers = ProviderConfigModel.objects.filter(
        source_type="tushare", is_active=True
    )
    if any(
        provider.pk != getattr(provider_row, "pk", None) for provider in active_tushare_providers
    ):
        raise AssertionError("another active Tushare provider conflicts with this fixture")

    # Validate every existing row before creating missing members of the bundle.
    # A later insert error rolls the whole local fixture addition back.
    with transaction.atomic():
        if contract_row is None:
            _write_contract(dataset_key=dataset_key)
        if policy_row is None:
            DatasetPublicationPolicyModel.objects.create(**policy_values)
        if binding_row is None:
            DatasetProviderBindingModel.objects.create(**binding_values)
        if provider_row is None:
            ProviderConfigModel.objects.create(**provider_values)


def test_configuration_fixture_reuses_exact_existing_rows_without_clock_updates() -> None:
    """A retained contract can be reused while missing exact catalog rows are seeded."""

    contract = _write_contract()
    original_contract_clocks = (contract.pk, contract.created_at, contract.updated_at)

    _write_configuration()
    first_policy = DatasetPublicationPolicyModel.objects.get(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version="calendar-v1",
    )
    first_binding = DatasetProviderBindingModel.objects.get(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        provider="tushare",
        capability=CALENDAR_CAPTURE_CAPABILITY,
    )
    first_provider = ProviderConfigModel.objects.get(name="calendar-workbench-provider-fixture")
    original_bundle_clocks = (
        (first_policy.pk, first_policy.created_at, first_policy.updated_at),
        (first_binding.pk, first_binding.created_at, first_binding.updated_at),
        (first_provider.pk, first_provider.created_at, first_provider.updated_at),
    )

    _write_contract()
    _write_configuration()

    saved_contract = DatasetContractModel.objects.get(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    saved_policy = DatasetPublicationPolicyModel.objects.get(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version="calendar-v1",
    )
    saved_binding = DatasetProviderBindingModel.objects.get(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        provider="tushare",
        capability=CALENDAR_CAPTURE_CAPABILITY,
    )
    saved_provider = ProviderConfigModel.objects.get(name="calendar-workbench-provider-fixture")
    assert (saved_contract.pk, saved_contract.created_at, saved_contract.updated_at) == (
        original_contract_clocks
    )
    assert (
        (saved_policy.pk, saved_policy.created_at, saved_policy.updated_at),
        (saved_binding.pk, saved_binding.created_at, saved_binding.updated_at),
        (saved_provider.pk, saved_provider.created_at, saved_provider.updated_at),
    ) == original_bundle_clocks
    assert DatasetContractModel.objects.filter(dataset_key=DATASET_KEY).count() == 1
    assert DatasetPublicationPolicyModel.objects.filter(dataset_key=DATASET_KEY).count() == 1
    assert DatasetProviderBindingModel.objects.filter(dataset_key=DATASET_KEY).count() == 1
    assert (
        ProviderConfigModel.objects.filter(name="calendar-workbench-provider-fixture").count() == 1
    )


def test_configuration_fixture_rejects_each_existing_row_with_changed_settings() -> None:
    """Existing rows with different TTL, policy, binding, or provider data fail explicitly."""

    _write_configuration()

    DatasetContractModel.objects.filter(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
    ).update(calendar_response_max_age_seconds=901)
    with pytest.raises(
        AssertionError,
        match="DatasetContractModel.calendar_response_max_age_seconds",
    ):
        _write_contract()
    with pytest.raises(
        AssertionError,
        match="DatasetContractModel.calendar_response_max_age_seconds",
    ):
        _write_configuration()
    assert (
        DatasetContractModel.objects.get(dataset_key=DATASET_KEY).calendar_response_max_age_seconds
        == 901
    )

    DatasetContractModel.objects.filter(dataset_key=DATASET_KEY).update(
        calendar_response_max_age_seconds=900
    )
    DatasetPublicationPolicyModel.objects.filter(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version="calendar-v1",
    ).update(minimum_coverage_ratio=0.99)
    with pytest.raises(
        AssertionError,
        match="DatasetPublicationPolicyModel.minimum_coverage_ratio",
    ):
        _write_configuration()
    assert (
        DatasetPublicationPolicyModel.objects.get(dataset_key=DATASET_KEY).minimum_coverage_ratio
        == 0.99
    )

    DatasetPublicationPolicyModel.objects.filter(dataset_key=DATASET_KEY).update(
        minimum_coverage_ratio=1.0
    )
    DatasetProviderBindingModel.objects.filter(
        dataset_key=DATASET_KEY,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        provider="tushare",
        capability=CALENDAR_CAPTURE_CAPABILITY,
    ).update(priority=11)
    with pytest.raises(AssertionError, match="DatasetProviderBindingModel.priority"):
        _write_configuration()
    assert DatasetProviderBindingModel.objects.get(dataset_key=DATASET_KEY).priority == 11

    DatasetProviderBindingModel.objects.filter(dataset_key=DATASET_KEY).update(priority=10)
    ProviderConfigModel.objects.filter(name="calendar-workbench-provider-fixture").update(
        description="different metadata"
    )
    with pytest.raises(AssertionError, match="ProviderConfigModel.description"):
        _write_configuration()
    assert (
        ProviderConfigModel.objects.get(name="calendar-workbench-provider-fixture").description
        == "different metadata"
    )
    assert DatasetContractModel.objects.filter(dataset_key=DATASET_KEY).count() == 1
    assert DatasetPublicationPolicyModel.objects.filter(dataset_key=DATASET_KEY).count() == 1
    assert DatasetProviderBindingModel.objects.filter(dataset_key=DATASET_KEY).count() == 1
    assert (
        ProviderConfigModel.objects.filter(name="calendar-workbench-provider-fixture").count() == 1
    )


def _assert_no_configuration_reads(queries: list[dict[str, str]]) -> None:
    """Verify a composition guard rejected before the four catalog queries."""

    assert not any(
        table_name in query["sql"] for table_name in _CONFIGURATION_TABLES for query in queries
    )


def test_scope_composition_selects_safe_metadata_without_secrets_provider_or_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real selection returns exact metadata and never resolves runtime/current state."""

    _write_configuration()
    forbidden_calls: list[str] = []

    def forbid_secret_or_provider_io(*_args: object, **_kwargs: object) -> None:
        forbidden_calls.append("called")
        raise AssertionError("Metadata scope must not resolve credentials or call a provider")

    monkeypatch.setattr(secrets, "get_secrets", forbid_secret_or_provider_io)
    monkeypatch.setattr(ProviderConfigRepository, "get_by_id", forbid_secret_or_provider_io)
    monkeypatch.setattr(tushare_client, "_create_requests_session", forbid_secret_or_provider_io)

    with CaptureQueriesContext(connection) as captured:
        context = read_calendar_workbench_scope_context()

    assert context.metadata_status is CalendarWorkbenchScopeMetadataStatus.METADATA_SELECTED
    assert context.metadata is not None
    assert context.metadata.dataset_key == DATASET_KEY
    assert context.metadata.contract_version == CONTRACT_VERSION
    assert context.metadata.schema_version == SCHEMA_VERSION
    assert context.metadata.calendar_response_max_age_seconds == 900
    assert context.metadata.validator_key == CALENDAR_CAPTURE_VALIDATOR_KEY
    assert context.secret_runtime_status is CalendarWorkbenchSecretRuntimeStatus.NOT_CHECKED
    assert context.current_pointer_status is CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED
    assert CanonicalPublicationPointerModel.objects.count() == 0
    assert not any(
        CanonicalPublicationPointerModel._meta.db_table in query["sql"]
        for query in captured.captured_queries
    )
    assert forbidden_calls == []


@pytest.mark.parametrize(
    ("rows", "expected_reason"),
    [
        ("missing", "CALENDAR_CAPTURE_DATASET_MISSING"),
        ("multiple_active", "CALENDAR_CAPTURE_DATASET_AMBIGUOUS"),
        ("active_null_ttl_version", "CALENDAR_CAPTURE_DATASET_AMBIGUOUS"),
    ],
)
def test_scope_composition_fails_closed_for_missing_or_ambiguous_catalog(
    rows: str,
    expected_reason: str,
) -> None:
    """Missing and ambiguous active catalog rows retain the selector's reason."""

    if rows == "multiple_active":
        _write_configuration()
        _write_contract(dataset_key="data_center.secondary_calendar")
    elif rows == "active_null_ttl_version":
        _write_configuration()
        _write_contract(contract_version="1.0", schema_version="0.9", ttl=None)

    context = read_calendar_workbench_scope_context()

    assert context.metadata_status is CalendarWorkbenchScopeMetadataStatus.BLOCKED
    assert context.metadata is None
    assert context.blocked_reason == expected_reason
    assert context.secret_runtime_status is CalendarWorkbenchSecretRuntimeStatus.NOT_CHECKED
    assert context.current_pointer_status is CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED


def test_existing_current_pointer_is_not_required_or_read_for_metadata_scope() -> None:
    """An absent current row does not turn metadata selection into a current query."""

    _write_configuration()
    assert CanonicalPublicationPointerModel.objects.count() == 0

    context = read_calendar_workbench_scope_context()

    assert context.metadata_status is CalendarWorkbenchScopeMetadataStatus.METADATA_SELECTED
    assert context.current_pointer_status is CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED
    assert CanonicalPublicationPointerModel.objects.count() == 0


def test_caller_owned_atomic_is_rejected_before_configuration_reads() -> None:
    """The composition owns its transaction and rejects nesting without catalog reads."""

    with CaptureQueriesContext(connection) as captured:
        with transaction.atomic():
            with pytest.raises(CalendarCaptureConfigurationError) as raised:
                read_calendar_workbench_scope_context()

    assert raised.value.code == "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED"
    _assert_no_configuration_reads(captured.captured_queries)


def test_disabled_autocommit_is_rejected_before_configuration_reads() -> None:
    """The composition requires autocommit before opening its own transaction."""

    assert connection.get_autocommit()
    connection.set_autocommit(False)
    try:
        with CaptureQueriesContext(connection) as captured:
            with pytest.raises(CalendarCaptureConfigurationError) as raised:
                read_calendar_workbench_scope_context()
    finally:
        connection.set_autocommit(True)

    assert raised.value.code == "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED"
    _assert_no_configuration_reads(captured.captured_queries)
