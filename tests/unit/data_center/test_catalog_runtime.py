"""Runtime Dataset Catalog persistence and bootstrap contracts."""

from __future__ import annotations

import json
from contextlib import nullcontext
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.application.public import (
    get_active_dataset_contract,
    get_active_publication_policy,
    list_active_data_owner_registrations,
    list_active_dataset_contracts,
    list_active_provider_bindings,
)
from apps.data_center.domain.contracts import (
    MAX_CATALOG_TTL_SECONDS,
    DataOwnerRegistration,
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    QuoteMetricSourceContract,
)
from apps.data_center.infrastructure import catalog_runtime_repositories
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DataOwnerRegistryRepository,
    DatasetContractRepository,
)
from apps.data_center.management.commands.initialize_data_center_catalog import _load_contracts
from tests.support.tui_research.market_consumer_state import (
    CONTRACT_VERSIONS,
    MARKET_DATASET_KEYS,
    SCHEMA_VERSIONS,
    _matches_expected_market_contract_version,
)


def _contract(
    version: str = "test-1",
    *,
    execution_freshness_seconds: int | None = None,
    calendar_response_max_age_seconds: int | None = None,
) -> DatasetContract:
    """Build a minimal valid contract for repository idempotency tests."""

    return DatasetContract(
        key=DatasetKey("test.catalog", version, "1.0"),
        owner="data-platform",
        frequency="daily",
        decision_critical=True,
        fields=(
            DatasetFieldContract(
                name="observed_at",
                value_type="datetime",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
        ),
        execution_freshness_seconds=execution_freshness_seconds,
        calendar_response_max_age_seconds=calendar_response_max_age_seconds,
    )


def test_tui_market_fixture_selects_exact_fixed_catalog_versions() -> None:
    """The fixture tracks each required contract version, never the latest row."""

    expected_versions = {
        "equity.price.bar": ("1.0", "1.0"),
        "equity.quote.snapshot": ("2.0", "2.0"),
        "equity.valuation.fact": ("1.0", "1.0"),
        "equity.financial.fact": ("1.0", "1.0"),
    }
    contracts = _load_contracts(Path(settings.BASE_DIR) / "governance" / "dataset_contracts.json")
    selected_versions = {
        contract.key.value: (contract.key.contract_version, contract.key.schema_version)
        for contract in contracts
        if _matches_expected_market_contract_version(
            dataset_key=contract.key.value,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
        )
    }

    assert set(CONTRACT_VERSIONS) == set(MARKET_DATASET_KEYS)
    assert set(SCHEMA_VERSIONS) == set(MARKET_DATASET_KEYS)
    configured_versions = {
        key: (CONTRACT_VERSIONS[key], SCHEMA_VERSIONS[key]) for key in MARKET_DATASET_KEYS
    }
    assert configured_versions == expected_versions
    assert selected_versions == expected_versions
    assert _matches_expected_market_contract_version("equity.quote.snapshot", "2.0", "2.0")
    assert not _matches_expected_market_contract_version("equity.quote.snapshot", "1.0", "1.0")

    quote_contract = next(
        contract for contract in contracts if contract.key.value == "equity.quote.snapshot"
    )
    change_pct = next(field for field in quote_contract.fields if field.name == "change_pct")
    assert (
        change_pct.value_type,
        change_pct.unit,
        change_pct.nullable,
        change_pct.zero_allowed,
    ) == ("decimal", "percent", True, True)


def test_owner_registration_requires_all_accountability_roles() -> None:
    """A catalog row cannot omit the platform, business or acceptance owner."""

    with pytest.raises(ValueError, match="acceptance_owner"):
        DataOwnerRegistration(
            dataset_key="test.catalog",
            data_platform_owner="data-platform",
            business_owner="equity",
            acceptance_owner="",
        )


def test_catalog_loader_requires_explicit_execution_ttl_without_inheriting_research_ttl(
    tmp_path: Path,
) -> None:
    """An omitted execution budget remains missing even when research TTL exists."""

    manifest = {
        "schema_version": "1.0",
        "owner": "data-platform",
        "contracts": [
            {
                "dataset_key": "equity.quote.snapshot",
                "contract_version": "2.0",
                "schema_version": "1.0",
                "frequency": "intraday",
                "freshness_seconds": 14_400,
                "decision_critical": True,
                "fields": [{"name": "snapshot_at", "type": "datetime"}],
            },
            {
                "dataset_key": "equity.quote.snapshot",
                "contract_version": "3.0",
                "schema_version": "1.0",
                "frequency": "intraday",
                "freshness_seconds": 14_400,
                "execution_freshness_seconds": 5,
                "decision_critical": True,
                "fields": [{"name": "snapshot_at", "type": "datetime"}],
            },
        ],
    }
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = _load_contracts(path)

    assert [contract.execution_freshness_seconds for contract in loaded] == [None, 5]
    assert [contract.freshness_seconds for contract in loaded] == [14_400, 14_400]


def test_catalog_loader_keeps_calendar_response_ttl_separate_and_optional(
    tmp_path: Path,
) -> None:
    """Calendar response age must not inherit either existing TTL clock."""

    path = tmp_path / "contracts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "owner": "data-platform",
                "contracts": [
                    {
                        "dataset_key": "test.calendar",
                        "contract_version": "1.0",
                        "schema_version": "1.0",
                        "frequency": "daily",
                        "freshness_seconds": 86_400,
                        "execution_freshness_seconds": 60,
                        "calendar_response_max_age_seconds": 45,
                        "decision_critical": True,
                        "fields": [{"name": "calendar_date", "type": "date"}],
                    },
                    {
                        "dataset_key": "test.legacy",
                        "contract_version": "1.0",
                        "schema_version": "1.0",
                        "frequency": "daily",
                        "freshness_seconds": 86_400,
                        "execution_freshness_seconds": 60,
                        "decision_critical": True,
                        "fields": [{"name": "calendar_date", "type": "date"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = _load_contracts(path)

    assert [item.calendar_response_max_age_seconds for item in loaded] == [45, None]


def test_catalog_loader_parses_typed_quote_metric_source_contracts(tmp_path: Path) -> None:
    """The existing catalog initializer preserves exact provider metric semantics."""

    source_rule = {
        "provider_source": "vendor-main",
        "source_field": "reported_pct",
        "origin": "vendor_reported",
        "source_unit": "basis_points",
        "canonical_unit": "percent",
        "scale_numerator": 1,
        "scale_denominator": 100,
        "reference_session": "vendor_quote_observation",
        "action_basis": "vendor_adjustment_basis_unverified",
    }
    path = tmp_path / "contracts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "owner": "data-platform",
                "contracts": [
                    {
                        "dataset_key": "equity.quote.snapshot",
                        "contract_version": "2.0",
                        "schema_version": "2.0",
                        "frequency": "intraday",
                        "decision_critical": True,
                        "fields": [
                            {
                                "name": "change_pct",
                                "type": "decimal",
                                "unit": "percent",
                                "nullable": True,
                                "zero_allowed": True,
                                "source_contracts": [source_rule],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = _load_contracts(path)

    assert loaded[0].fields[0].source_contracts == (QuoteMetricSourceContract(**source_rule),)


def test_catalog_loader_rejects_boolean_metric_scale(tmp_path: Path) -> None:
    """A JSON bool cannot masquerade as an exact source conversion integer."""

    path = tmp_path / "contracts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "owner": "data-platform",
                "contracts": [
                    {
                        "dataset_key": "equity.quote.snapshot",
                        "contract_version": "2.0",
                        "schema_version": "2.0",
                        "frequency": "intraday",
                        "decision_critical": True,
                        "fields": [
                            {
                                "name": "change_pct",
                                "type": "decimal",
                                "unit": "percent",
                                "nullable": True,
                                "zero_allowed": True,
                                "source_contracts": [
                                    {
                                        "provider_source": "vendor-main",
                                        "source_field": "reported_pct",
                                        "origin": "vendor_reported",
                                        "source_unit": "percent",
                                        "canonical_unit": "percent",
                                        "scale_numerator": True,
                                        "scale_denominator": 1,
                                        "reference_session": "vendor_quote_observation",
                                        "action_basis": "vendor_basis_unverified",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="scale must use integer values"):
        _load_contracts(path)


def test_dataset_contract_exposes_calendar_response_ttl_independently() -> None:
    """The calendar response-age budget has an independent typed contract field."""

    contract = DatasetContract(
        key=DatasetKey("test.calendar", "1.0", "1.0"),
        owner="data-platform",
        frequency="daily",
        decision_critical=True,
        fields=(
            DatasetFieldContract(
                name="calendar_date",
                value_type="date",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
        ),
        freshness_seconds=86_400,
        execution_freshness_seconds=60,
        calendar_response_max_age_seconds=45,
    )

    assert contract.calendar_response_max_age_seconds == 45


@pytest.mark.parametrize("value", [True, 1.0, 1.5, "5", 0, -1, 2**63])
def test_catalog_loader_rejects_noncanonical_execution_ttl(tmp_path: Path, value: object) -> None:
    """Execution TTL accepts only a positive signed 64-bit JSON integer."""

    path = tmp_path / "contracts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "owner": "data-platform",
                "contracts": [
                    {
                        "dataset_key": "equity.quote.snapshot",
                        "contract_version": "2.0",
                        "schema_version": "1.0",
                        "frequency": "intraday",
                        "decision_critical": True,
                        "execution_freshness_seconds": value,
                        "fields": [{"name": "snapshot_at", "type": "datetime"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="execution_freshness_seconds"):
        _load_contracts(path)


@pytest.mark.parametrize("value", [True, 1.0, 1.5, "5", 0, -1, 2**63])
def test_catalog_loader_rejects_noncanonical_calendar_response_ttl(
    tmp_path: Path,
    value: object,
) -> None:
    """Calendar response TTL accepts only a positive signed-64-bit JSON integer."""

    path = tmp_path / "contracts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "owner": "data-platform",
                "contracts": [
                    {
                        "dataset_key": "test.calendar",
                        "contract_version": "1.0",
                        "schema_version": "1.0",
                        "frequency": "daily",
                        "decision_critical": True,
                        "calendar_response_max_age_seconds": value,
                        "fields": [{"name": "calendar_date", "type": "date"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="calendar_response_max_age_seconds"):
        _load_contracts(path)


@pytest.mark.parametrize("value", [True, 1.0, 1.5, "5", 0, -1, 2**63])
def test_dataset_contract_rejects_invalid_calendar_response_ttl(value: object) -> None:
    """The Domain contract rejects bools, coercions, zero, and overflow."""

    with pytest.raises(ValueError, match="calendar_response_max_age_seconds"):
        _contract(calendar_response_max_age_seconds=value)  # type: ignore[arg-type]


def test_dataset_contract_accepts_maximum_catalog_ttl_for_each_independent_clock() -> None:
    contract = _contract(
        execution_freshness_seconds=MAX_CATALOG_TTL_SECONDS,
        calendar_response_max_age_seconds=MAX_CATALOG_TTL_SECONDS,
    )

    assert contract.execution_freshness_seconds == MAX_CATALOG_TTL_SECONDS
    assert contract.calendar_response_max_age_seconds == MAX_CATALOG_TTL_SECONDS


@pytest.mark.parametrize("value", [True, 1.5, "5", 0, -1, 2**63])
def test_dataset_contract_model_rejects_invalid_execution_ttl_before_domain_cast(
    value: object,
) -> None:
    """ORM conversion must not normalize malformed TTL values with int()."""

    model = DatasetContractModel(
        dataset_key="test.catalog",
        contract_version="1.0",
        schema_version="1.0",
        owner="data-platform",
        frequency="intraday",
        decision_critical=True,
        fields=[{"name": "snapshot_at", "value_type": "datetime"}],
        execution_freshness_seconds=cast(int | None, value),
    )

    with pytest.raises(ValueError, match="execution_freshness_seconds"):
        model.to_domain()


@pytest.mark.parametrize("value", [True, 1.0, 1.5, "5", 0, -1, 2**63])
def test_dataset_contract_model_rejects_invalid_calendar_ttl_before_domain_cast(
    value: object,
) -> None:
    """ORM conversion must not normalize malformed calendar TTL values with int()."""

    model = DatasetContractModel(
        dataset_key="test.calendar",
        contract_version="1.0",
        schema_version="1.0",
        owner="data-platform",
        frequency="daily",
        decision_critical=True,
        fields=[{"name": "calendar_date", "value_type": "date"}],
        calendar_response_max_age_seconds=cast(int | None, value),
    )

    with pytest.raises(ValueError, match="calendar_response_max_age_seconds"):
        model.to_domain()


def test_contract_repository_rejects_execution_ttl_mutation_in_same_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing version identity cannot be reused to change execution freshness."""

    class _Query:
        def select_for_update(self) -> _Query:
            return self

        def filter(self, **_filters: object) -> _Query:
            return self

        def first(self) -> SimpleNamespace:
            return SimpleNamespace(
                execution_freshness_seconds=None,
                calendar_response_max_age_seconds=None,
            )

    manager = _Query()
    monkeypatch.setattr(
        catalog_runtime_repositories,
        "DatasetContractModel",
        SimpleNamespace(_default_manager=manager),
    )
    monkeypatch.setattr(
        catalog_runtime_repositories.transaction,
        "atomic",
        lambda: nullcontext(),
    )

    with pytest.raises(ValueError, match="new contract version"):
        DatasetContractRepository().save(_contract("1.0", execution_freshness_seconds=30))


def test_contract_repository_rechecks_ttl_after_concurrent_same_version_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent create cannot turn a same-version TTL into an update."""

    update_arguments: dict[str, object] = {}

    class _Query:
        def select_for_update(self) -> _Query:
            return self

        def filter(self, **_filters: object) -> _Query:
            return self

        def exclude(self, **_filters: object) -> _Query:
            return self

        def first(self) -> None:
            return None

        def update(self, **_values: object) -> int:
            return 0

    class _Manager:
        def select_for_update(self) -> _Query:
            return _Query()

        def filter(self, **_filters: object) -> _Query:
            return _Query()

        def update_or_create(self, **kwargs: object) -> tuple[SimpleNamespace, bool]:
            update_arguments.update(kwargs)
            return (
                SimpleNamespace(
                    execution_freshness_seconds=15,
                    calendar_response_max_age_seconds=15,
                ),
                False,
            )

    monkeypatch.setattr(
        catalog_runtime_repositories,
        "DatasetContractModel",
        SimpleNamespace(_default_manager=_Manager()),
    )
    monkeypatch.setattr(
        catalog_runtime_repositories.transaction,
        "atomic",
        lambda: nullcontext(),
    )

    with pytest.raises(ValueError, match="new contract version"):
        DatasetContractRepository().save(_contract("1.0", execution_freshness_seconds=30))

    defaults = cast(dict[str, object], update_arguments["defaults"])
    create_defaults = cast(dict[str, object], update_arguments["create_defaults"])
    assert "execution_freshness_seconds" not in defaults
    assert "calendar_response_max_age_seconds" not in defaults
    assert create_defaults["execution_freshness_seconds"] == 30
    assert create_defaults["calendar_response_max_age_seconds"] is None


def test_contract_repository_rechecks_calendar_ttl_after_concurrent_same_version_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent row cannot turn a same-version calendar TTL into an update."""

    update_arguments: dict[str, object] = {}

    class _Query:
        def select_for_update(self) -> _Query:
            return self

        def filter(self, **_filters: object) -> _Query:
            return self

        def exclude(self, **_filters: object) -> _Query:
            return self

        def first(self) -> None:
            return None

        def update(self, **_values: object) -> int:
            return 0

    class _Manager:
        def select_for_update(self) -> _Query:
            return _Query()

        def filter(self, **_filters: object) -> _Query:
            return _Query()

        def update_or_create(self, **kwargs: object) -> tuple[SimpleNamespace, bool]:
            update_arguments.update(kwargs)
            return (
                SimpleNamespace(
                    execution_freshness_seconds=None,
                    calendar_response_max_age_seconds=15,
                ),
                False,
            )

    monkeypatch.setattr(
        catalog_runtime_repositories,
        "DatasetContractModel",
        SimpleNamespace(_default_manager=_Manager()),
    )
    monkeypatch.setattr(
        catalog_runtime_repositories.transaction,
        "atomic",
        lambda: nullcontext(),
    )

    with pytest.raises(ValueError, match="calendar_response_max_age_seconds.*new contract version"):
        DatasetContractRepository().save(_contract("1.0", calendar_response_max_age_seconds=30))

    defaults = cast(dict[str, object], update_arguments["defaults"])
    create_defaults = cast(dict[str, object], update_arguments["create_defaults"])
    assert "calendar_response_max_age_seconds" not in defaults
    assert create_defaults["calendar_response_max_age_seconds"] == 30


@pytest.mark.django_db
def test_dataset_contract_repository_supersedes_old_active_version() -> None:
    """Saving a new version leaves one active runtime contract per dataset."""

    repository = DatasetContractRepository()
    repository.save(_contract("1.0"))
    repository.save(_contract("2.0"))

    active = repository.list_active()
    assert [(item.key.value, item.key.contract_version) for item in active] == [
        ("test.catalog", "2.0")
    ]


@pytest.mark.django_db
def test_execution_freshness_cannot_change_within_one_contract_version() -> None:
    """Changing the execution budget requires a new versioned contract row."""

    repository = DatasetContractRepository()
    repository.save(_contract("1.0", execution_freshness_seconds=None))

    with pytest.raises(ValueError, match="new contract version"):
        repository.save(_contract("1.0", execution_freshness_seconds=30))

    active = repository.save(_contract("2.0", execution_freshness_seconds=30))
    assert active.key.contract_version == "2.0"
    assert active.execution_freshness_seconds == 30


@pytest.mark.django_db
def test_calendar_response_ttl_is_immutable_within_a_contract_version() -> None:
    """Changing the local response-age clock requires a new catalog version."""

    repository = DatasetContractRepository()
    repository.save(_contract("1.0", calendar_response_max_age_seconds=None))

    with pytest.raises(ValueError, match="calendar_response_max_age_seconds.*new contract version"):
        repository.save(_contract("1.0", calendar_response_max_age_seconds=30))

    active = repository.save(_contract("2.0", calendar_response_max_age_seconds=30))
    assert active.key.contract_version == "2.0"
    assert active.calendar_response_max_age_seconds == 30


@pytest.mark.django_db
def test_catalog_bootstrap_is_idempotent_and_public_ports_are_typed() -> None:
    """Reviewed governance projections become runtime rows on repeatable bootstrap."""

    first = StringIO()
    call_command("initialize_data_center_catalog", stdout=first)
    second = StringIO()
    call_command("initialize_data_center_catalog", stdout=second)

    assert "contracts=10" in first.getvalue()
    assert first.getvalue() == second.getvalue()
    assert len(list_active_dataset_contracts()) == 10
    assert len(list_active_provider_bindings()) == 15
    fallback_bindings = {
        item.dataset.value: item.provider
        for item in list_active_provider_bindings()
        if item.provider == "akshare"
    }
    assert {
        "equity.price.bar",
        "equity.financial.fact",
        "equity.valuation.fact",
    } <= set(fallback_bindings)
    assert get_active_dataset_contract("equity.quote.snapshot") is not None
    assert all(
        contract.calendar_response_max_age_seconds is None
        for contract in list_active_dataset_contracts()
    )
    assert get_active_publication_policy("equity.quote.snapshot") is not None
    assert len(list_active_data_owner_registrations()) == 10


@pytest.mark.django_db
def test_owner_repository_round_trip() -> None:
    """Owner registrations are persisted through an application-owned repository."""

    saved = DataOwnerRegistryRepository().save(
        DataOwnerRegistration(
            dataset_key="test.owner",
            data_platform_owner="data-platform",
            business_owner="equity",
            acceptance_owner="data-platform",
        )
    )
    assert saved.dataset_key == "test.owner"
    assert DataOwnerRegistryRepository().list_active()[0] == saved
