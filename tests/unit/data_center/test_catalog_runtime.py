"""Runtime Dataset Catalog persistence and bootstrap contracts."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.data_center.application.public import (
    get_active_dataset_contract,
    get_active_publication_policy,
    list_active_data_owner_registrations,
    list_active_dataset_contracts,
    list_active_provider_bindings,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DataOwnerRegistryRepository,
    DatasetContractRepository,
)


def _contract(version: str = "test-1") -> DatasetContract:
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
    )


def test_owner_registration_requires_all_accountability_roles() -> None:
    """A catalog row cannot omit the platform, business or acceptance owner."""

    with pytest.raises(ValueError, match="acceptance_owner"):
        DataOwnerRegistration(
            dataset_key="test.catalog",
            data_platform_owner="data-platform",
            business_owner="equity",
            acceptance_owner="",
        )


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
