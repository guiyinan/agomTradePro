"""Test-only exact Tushare batch publication for the ASH07 Owner journey."""

from __future__ import annotations

from datetime import UTC, date
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.config_center.application.runtime_public import get_active_runtime_profile
from apps.data_center.application.m1_reference_price_batch_publication import (
    M1ReferencePriceBatchPublicationCommand,
    M1ReferencePriceBatchPublicationResult,
)
from apps.data_center.application.m1_reference_price_publication import (
    M1_REFERENCE_PRICE_DATABASE_ALIAS,
    M1_REFERENCE_PRICE_DATASET_KEY,
)
from apps.data_center.application.market_calendar import latest_completed_cn_market_session
from apps.data_center.composition import (
    get_data_owner_registry_repository,
    get_dataset_contract_repository,
    get_provider_binding_repository,
    get_publication_policy_repository,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.infrastructure.catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.m1_reference_price_publication_composition import (
    build_m1_reference_price_batch_publication_use_case,
)
from apps.data_center.management.commands.initialize_data_center_catalog import (
    _load_bindings,
    _load_contracts,
    _load_owners,
    _load_policies,
)
from apps.simulated_trading.infrastructure.published_close_price_reader import (
    PublishedClosePriceReader,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database


def ensure_m1_price_publication_catalog() -> None:
    """Create only missing exact M1 price catalog rows from approved manifests.

    Existing active rows must match the reviewed governance projection exactly.
    Historical inactive rows are never reactivated or rewritten, and the broad
    catalog synchronizer is deliberately not used by this target-scoped helper.
    """

    assert_native_postgres_test_database()
    alias = M1_REFERENCE_PRICE_DATABASE_ALIAS
    if alias != "default":
        raise AssertionError("M1 publication catalog bootstrap requires the default alias")

    root = Path(__file__).resolve().parents[2]
    governance = root / "governance"
    contracts_path = governance / "dataset_contracts.json"
    bindings_path = governance / "provider_bindings.json"
    policies_path = governance / "publication_policies.json"
    owners_path = governance / "data_ownership_contracts.json"
    all_contracts = _load_contracts(contracts_path)
    contracts_by_key = {item.key.value: item for item in all_contracts}
    expected_contracts = tuple(
        item for item in all_contracts if item.key.value == M1_REFERENCE_PRICE_DATASET_KEY
    )
    expected_bindings = tuple(
        item
        for item in _load_bindings(bindings_path, contracts_by_key)
        if item.dataset.value == M1_REFERENCE_PRICE_DATASET_KEY
    )
    expected_policies = tuple(
        item
        for item in _load_policies(policies_path, contracts_by_key)
        if item.dataset.value == M1_REFERENCE_PRICE_DATASET_KEY
    )
    expected_owners = tuple(
        item
        for item in _load_owners(owners_path, contracts_by_key)
        if item.dataset_key == M1_REFERENCE_PRICE_DATASET_KEY
    )
    if (
        len(expected_contracts) != 1
        or not expected_bindings
        or len(expected_policies) != 1
        or len(expected_owners) != 1
    ):
        raise AssertionError("reviewed M1 price catalog projection is incomplete or ambiguous")
    expected_contract = expected_contracts[0]
    expected_policy = expected_policies[0]
    expected_owner = expected_owners[0]

    with transaction.atomic(using=alias):
        contract_rows = list(
            DatasetContractModel._default_manager.using(alias).filter(
                dataset_key=M1_REFERENCE_PRICE_DATASET_KEY
            )
        )
        binding_rows = list(
            DatasetProviderBindingModel._default_manager.using(alias).filter(
                dataset_key=M1_REFERENCE_PRICE_DATASET_KEY
            )
        )
        policy_rows = list(
            DatasetPublicationPolicyModel._default_manager.using(alias).filter(
                dataset_key=M1_REFERENCE_PRICE_DATASET_KEY
            )
        )
        owner_rows = list(
            DataOwnerRegistrationModel._default_manager.using(alias).filter(
                dataset_key=M1_REFERENCE_PRICE_DATASET_KEY
            )
        )

        create_contract = _create_only_contract_state(contract_rows, expected_contract)
        create_bindings = _create_only_binding_state(binding_rows, expected_bindings)
        create_policy = _create_only_policy_state(policy_rows, expected_policy)
        create_owner = _create_only_owner_state(owner_rows, expected_owner)

        contract_repository = get_dataset_contract_repository()
        binding_repository = get_provider_binding_repository()
        policy_repository = get_publication_policy_repository()
        owner_repository = get_data_owner_registry_repository()
        if create_contract:
            contract_repository.save(expected_contract)
        for binding in create_bindings:
            binding_repository.save(binding)
        if create_policy:
            policy_repository.save(expected_policy)
        if create_owner:
            owner_repository.save(expected_owner)

        active_contract = contract_repository.get_active_for_execution(
            M1_REFERENCE_PRICE_DATASET_KEY
        )
        if active_contract != expected_contract:
            raise AssertionError("active M1 price Dataset Contract differs from governance")
        if set(binding_repository.list_active(M1_REFERENCE_PRICE_DATASET_KEY)) != set(
            expected_bindings
        ):
            raise AssertionError("active M1 price provider bindings differ from governance")
        if policy_repository.get_active(M1_REFERENCE_PRICE_DATASET_KEY) != expected_policy:
            raise AssertionError("active M1 price publication policy differs from governance")
        active_owners = tuple(
            item
            for item in owner_repository.list_active()
            if item.dataset_key == M1_REFERENCE_PRICE_DATASET_KEY
        )
        if active_owners != (expected_owner,):
            raise AssertionError("active M1 price ownership differs from governance")


def _create_only_contract_state(
    rows: list[DatasetContractModel],
    expected: DatasetContract,
) -> bool:
    """Return whether the exact reviewed contract may be newly inserted."""

    active_rows = [row for row in rows if row.active]
    if len(active_rows) > 1:
        raise AssertionError("M1 price contract has multiple active versions")
    target_rows = [
        row
        for row in rows
        if row.contract_version == expected.key.contract_version
        and row.schema_version == expected.key.schema_version
    ]
    if len(target_rows) > 1:
        raise AssertionError("M1 price contract version is duplicated")
    if target_rows:
        if target_rows[0].to_domain() != expected:
            raise AssertionError("stored M1 price contract differs from governance")
        if not target_rows[0].active or active_rows != target_rows:
            raise AssertionError("inactive M1 price contract will not be reactivated implicitly")
        return False
    if active_rows:
        raise AssertionError("another active M1 price contract will not be superseded implicitly")
    return True


def _create_only_binding_state(
    rows: list[DatasetProviderBindingModel],
    expected: tuple[ProviderBinding, ...],
) -> tuple[ProviderBinding, ...]:
    """Return only missing bindings and reject active or historical drift."""

    expected_by_identity = {
        (
            item.dataset.contract_version,
            item.dataset.schema_version,
            item.provider,
            item.capability,
        ): item
        for item in expected
    }
    active_rows = [row for row in rows if row.enabled]
    unexpected_active = [
        row
        for row in active_rows
        if (
            row.contract_version,
            row.schema_version,
            row.provider,
            row.capability,
        )
        not in expected_by_identity
    ]
    if unexpected_active:
        raise AssertionError("unexpected active M1 price provider binding exists")

    missing: list[ProviderBinding] = []
    for identity, binding in expected_by_identity.items():
        matches = [
            row
            for row in rows
            if (
                row.contract_version,
                row.schema_version,
                row.provider,
                row.capability,
            )
            == identity
        ]
        if len(matches) > 1:
            raise AssertionError("M1 price provider binding identity is duplicated")
        if not matches:
            missing.append(binding)
            continue
        if matches[0].to_domain() != binding:
            raise AssertionError("stored M1 price provider binding differs from governance")
        if not matches[0].enabled:
            raise AssertionError("inactive M1 price binding will not be reactivated implicitly")
    return tuple(missing)


def _create_only_policy_state(
    rows: list[DatasetPublicationPolicyModel],
    expected: PublicationPolicy,
) -> bool:
    """Return whether the exact reviewed policy may be newly inserted."""

    active_rows = [row for row in rows if row.active]
    if len(active_rows) > 1:
        raise AssertionError("M1 price policy has multiple active versions")
    target_rows = [row for row in rows if row.policy_version == expected.policy_version]
    if len(target_rows) > 1:
        raise AssertionError("M1 price policy version is duplicated")
    if target_rows:
        if target_rows[0].to_domain() != expected:
            raise AssertionError("stored M1 price policy differs from governance")
        if not target_rows[0].active or active_rows != target_rows:
            raise AssertionError("inactive M1 price policy will not be reactivated implicitly")
        return False
    if active_rows:
        raise AssertionError("another active M1 price policy will not be superseded implicitly")
    return True


def _create_only_owner_state(
    rows: list[DataOwnerRegistrationModel],
    expected: DataOwnerRegistration,
) -> bool:
    """Return whether the exact reviewed owner record may be newly inserted."""

    if not rows:
        return True
    if len(rows) != 1 or rows[0].to_domain() != expected or not rows[0].active:
        raise AssertionError("existing M1 price owner record differs or is inactive")
    return False


def publish_and_verify_tushare_close_batch(
    *,
    asset_codes: tuple[str, ...],
    target_trade_date: date,
) -> M1ReferencePriceBatchPublicationResult:
    """Publish exact same-session Tushare bars and verify both through the close reader.

    The caller must finish every ConfigCenter profile change and establish the real,
    current Account/SystemAudit authorities before calling this helper. The M1
    composition performs its own required audit preflight and authority capture.
    This helper never substitutes an authority, provider, clock, or price value.
    """

    assert_native_postgres_test_database()
    if type(target_trade_date) is not date:
        raise TypeError("target_trade_date must be an exact date")
    if type(asset_codes) is not tuple or len(asset_codes) < 2:
        raise ValueError("asset_codes must be an explicit tuple of at least two securities")

    ensure_m1_price_publication_catalog()

    profile_before = get_active_runtime_profile("development")
    if profile_before is None:
        raise AssertionError("the final development ConfigCenter profile is not active")

    cutoff = timezone.now().astimezone(UTC)
    completed_session = latest_completed_cn_market_session(cutoff)
    if completed_session != target_trade_date:
        raise AssertionError(
            "M1 batch date must be the exact latest completed published market session"
        )

    providers = ProviderConfigRepository()
    active_tushare = providers.get_active_by_type("tushare")
    if len(active_tushare) != 1:
        raise AssertionError("exactly one active Tushare provider must be selected")
    provider = active_tushare[0]
    if provider.id is None or provider.id < 1:
        raise AssertionError("the active Tushare provider identity is incomplete")

    use_case = build_m1_reference_price_batch_publication_use_case(
        provider_repository=providers,
        environment="development",
    )
    result = use_case.execute(
        M1ReferencePriceBatchPublicationCommand(
            provider_id=provider.id,
            asset_codes=asset_codes,
            target_trade_date=target_trade_date,
        )
    )
    if (
        result.publication.selected_source != "tushare"
        or result.publication.member_count != len(asset_codes)
        or result.publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    ):
        raise AssertionError("the exact Tushare batch did not produce one qualified M1 group")
    stored_asset_codes = {
        asset_code
        for sync_result in result.sync_results
        for asset_code in sync_result.stored_asset_codes
    }
    if stored_asset_codes != set(asset_codes):
        raise AssertionError("the M1 batch did not store exactly the requested securities")

    profile_after = get_active_runtime_profile("development")
    if (
        profile_after is None
        or profile_after.profile_id != profile_before.profile_id
        or profile_after.version != profile_before.version
    ):
        raise AssertionError("ConfigCenter changed during M1 publication")

    read_at = timezone.now().astimezone(UTC)
    if latest_completed_cn_market_session(read_at) != target_trade_date:
        raise AssertionError("the latest completed market session changed during publication")
    reader = PublishedClosePriceReader()
    for asset_code in asset_codes:
        read = reader.read(asset_code=asset_code, cutoff=read_at)
        publication = read.publication
        if (
            read.blocked_reason is not None
            or read.price_result is None
            or publication is None
            or publication.bar_date != target_trade_date
            or publication.publication_id != result.publication.publication_id
            or publication.publication_hash != result.publication.publication_hash
            or publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        ):
            raise AssertionError(
                "published_close did not read the same qualified batch for every security"
            )
    return result


__all__ = ("ensure_m1_price_publication_catalog", "publish_and_verify_tushare_close_batch")
