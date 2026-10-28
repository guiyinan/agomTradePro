"""Persisted codec policy constraints and rollback protection on real databases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from importlib import import_module

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.publication_member_codec import (
    PriceLimitNullableMemberCodecVersion,
)
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = ("data_center", "0105_price_limit_snapshot")
AFTER = ("data_center", "0106_price_limit_member_codec_policy")
PRICE_CODEC = "price-limit-nullable-member-v1"


def _price_policy(*, policy_version: str = "1") -> PublicationPolicy:
    """Return a valid explicit price-limit codec policy for repository tests."""

    return PublicationPolicy(
        dataset=DatasetKey("equity.price.limit", "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "raw_payload_hash",
            "fetched_at",
            "raw_payload_scope",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version=policy_version,
        member_codec_version=PriceLimitNullableMemberCodecVersion.V1,
    )


def _create_policy_row(
    *,
    dataset_key: str,
    policy_version: str,
    member_codec_version: str | None,
) -> DatasetPublicationPolicyModel:
    """Insert one inactive row so the check constraint is isolated from activation."""

    return DatasetPublicationPolicyModel.objects.create(
        dataset_key=dataset_key,
        contract_version="1.0",
        schema_version="1.0",
        policy_version=policy_version,
        member_codec_version=member_codec_version,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source", "fetched_at", "fact_content_hash"],
        retention_days=3650,
        active=False,
    )


def _record_database_identity(record_property: Callable[[str, str], None]) -> None:
    """Attach the actual backend and database name to the JUnit test case."""

    record_property("database_vendor", connection.vendor)
    if connection.vendor == "postgresql":
        actual_name = assert_native_postgres_test_database()
    else:
        actual_name = str(connection.settings_dict.get("NAME", ""))
    record_property("database_name", actual_name)


def test_publication_policy_repository_round_trips_and_keeps_versions_immutable() -> None:
    repository = PublicationPolicyRepository()
    policy = _price_policy()

    saved = repository.save(policy)

    assert saved == policy
    assert repository.get_active("equity.price.limit") == policy
    with pytest.raises(ValueError, match="content is immutable"):
        repository.save(
            PublicationPolicy(
                dataset=policy.dataset,
                minimum_coverage_ratio=0.9,
                allow_partial=policy.allow_partial,
                conflict_action=policy.conflict_action,
                required_evidence=policy.required_evidence,
                retention_days=policy.retention_days,
                policy_version=policy.policy_version,
                member_codec_version=policy.member_codec_version,
            )
        )
    with pytest.raises(ValueError, match="content is immutable"):
        repository.save(replace(policy, member_codec_version=None))
    assert repository.get_active("equity.price.limit") == policy


def test_member_codec_database_constraint_keeps_calendar_scope_and_binds_price_scope(
    record_property: Callable[[str, str], None],
) -> None:
    _record_database_identity(record_property)

    valid_price = _create_policy_row(
        dataset_key="equity.price.limit",
        policy_version="price-v1",
        member_codec_version=PRICE_CODEC,
    )
    assert valid_price.to_domain().member_codec_version is PriceLimitNullableMemberCodecVersion.V1
    calendar_row = _create_policy_row(
        dataset_key="test.calendar-compatible.dataset",
        policy_version="calendar-v1",
        member_codec_version="calendar-nullable-member-v1",
    )
    assert calendar_row.member_codec_version == "calendar-nullable-member-v1"

    invalid_rows = (
        ("equity.price.bar", "wrong-dataset", PRICE_CODEC),
        ("equity.price.limit", "legacy", PRICE_CODEC),
        ("equity.price.limit", "unknown-codec", "unknown-nullable-member-v1"),
    )
    for dataset_key, policy_version, codec in invalid_rows:
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _create_policy_row(
                    dataset_key=dataset_key,
                    policy_version=policy_version,
                    member_codec_version=codec,
                )


def test_policy_codec_migration_allows_empty_reverse_and_refuses_any_history(
    record_property: Callable[[str, str], None],
) -> None:
    _record_database_identity(record_property)
    initial_targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
    migration = import_module("apps.data_center.migrations.0106_price_limit_member_codec_policy")
    try:
        MigrationExecutor(connection).migrate([BEFORE])
        assert not DatasetPublicationPolicyModel.objects.filter(
            member_codec_version=PRICE_CODEC
        ).exists()
        old_rows = (
            _create_policy_row(
                dataset_key="test.policy.codec-null",
                policy_version="legacy",
                member_codec_version=None,
            ),
            _create_policy_row(
                dataset_key="test.policy.calendar-codec",
                policy_version="calendar-v1",
                member_codec_version="calendar-nullable-member-v1",
            ),
        )
        old_row_values = tuple(
            DatasetPublicationPolicyModel.objects.filter(pk__in=[row.pk for row in old_rows])
            .order_by("dataset_key")
            .values()
        )
        MigrationExecutor(connection).migrate([AFTER])
        assert AFTER in MigrationRecorder(connection).applied_migrations()
        MigrationExecutor(connection).migrate([BEFORE])
        assert AFTER not in MigrationRecorder(connection).applied_migrations()
        assert (
            tuple(
                DatasetPublicationPolicyModel.objects.filter(pk__in=[row.pk for row in old_rows])
                .order_by("dataset_key")
                .values()
            )
            == old_row_values
        )
        MigrationExecutor(connection).migrate([AFTER])
        assert AFTER in MigrationRecorder(connection).applied_migrations()
        assert (
            tuple(
                DatasetPublicationPolicyModel.objects.filter(pk__in=[row.pk for row in old_rows])
                .order_by("dataset_key")
                .values()
            )
            == old_row_values
        )

        retained = _create_policy_row(
            dataset_key="equity.price.limit",
            policy_version="inactive-retained-policy",
            member_codec_version=PRICE_CODEC,
        )
        assert retained.active is False
        retained_values = (
            DatasetPublicationPolicyModel.objects.filter(pk=retained.pk).values().get()
        )
        with pytest.raises(IrreversibleError, match="codec history"):
            MigrationExecutor(connection).migrate([BEFORE])
        assert AFTER in MigrationRecorder(connection).applied_migrations()
        assert (
            DatasetPublicationPolicyModel.objects.filter(pk=retained.pk).values().get()
            == retained_values
        )

        second_valid = _create_policy_row(
            dataset_key="equity.price.limit",
            policy_version="second-valid-policy",
            member_codec_version=PRICE_CODEC,
        )
        assert second_valid.member_codec_version == PRICE_CODEC
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _create_policy_row(
                    dataset_key="equity.price.bar",
                    policy_version="wrong-scope-after-refusal",
                    member_codec_version=PRICE_CODEC,
                )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _create_policy_row(
                    dataset_key="equity.price.limit",
                    policy_version="legacy",
                    member_codec_version=PRICE_CODEC,
                )

        state = MigrationExecutor(connection).loader.project_state([AFTER])
        with connection.schema_editor(atomic=False) as schema_editor:
            with pytest.raises(IrreversibleError, match="atomic schema transaction"):
                migration.preserve_price_limit_codec_history(state.apps, schema_editor)
        assert DatasetPublicationPolicyModel.objects.get(pk=retained.pk).member_codec_version == (
            PRICE_CODEC
        )
    finally:
        MigrationExecutor(connection).migrate(initial_targets)
