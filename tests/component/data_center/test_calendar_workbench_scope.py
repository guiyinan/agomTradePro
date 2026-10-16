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
    """Persist one calendar contract row, including explicitly nullable TTL."""

    return DatasetContractModel.objects.create(
        dataset_key=dataset_key,
        contract_version=contract_version,
        schema_version=schema_version,
        owner="data-platform",
        frequency="calendar",
        decision_critical=True,
        fields=[
            {
                "name": "calendar_date",
                "type": "date",
                "unit": None,
                "nullable": False,
                "zero_allowed": False,
            }
        ],
        calendar_response_max_age_seconds=ttl,
        active=True,
    )


def _write_configuration(*, dataset_key: str = DATASET_KEY) -> None:
    """Persist the exact active contract, policy, binding, and provider metadata."""

    _write_contract(dataset_key=dataset_key)
    DatasetPublicationPolicyModel.objects.create(
        dataset_key=dataset_key,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version="calendar-v1",
        member_codec_version="calendar-nullable-member-v1",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source", "fact_content_hash"],
        retention_days=3650,
        active=True,
    )
    DatasetProviderBindingModel.objects.create(
        dataset_key=dataset_key,
        contract_version=CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION,
        provider="tushare",
        capability=CALENDAR_CAPTURE_CAPABILITY,
        priority=10,
        validator_key=CALENDAR_CAPTURE_VALIDATOR_KEY,
        enabled=True,
    )
    ProviderConfigModel.objects.create(
        name="calendar-workbench-provider-fixture",
        source_type="tushare",
        is_active=True,
        priority=10,
        http_url="",
        api_endpoint="",
        extra_config={},
        description="Non-secret metadata fixture",
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
