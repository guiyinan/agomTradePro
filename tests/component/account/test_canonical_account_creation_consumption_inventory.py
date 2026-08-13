"""Component evidence for the per-alias creation-consumption inventory."""

from __future__ import annotations

import hashlib
import json

import pytest
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from apps.account.infrastructure.canonical_account_creation_consumption_inventory import (
    CanonicalAccountCreationConsumptionInventoryService,
    CanonicalAccountCreationConsumptionInventoryUnavailable,
    inventory_canonical_account_creation_consumption,
)


def _record_required_migrations(*, include_contract: bool = False) -> None:
    MigrationRecorder.Migration.objects.filter(app="account").delete()
    names = [
        "0045_canonical_account_creation_ledger",
        "0046_allocated_physical_account_row_observation_v3_ledger",
        "0047_canonical_account_creation_consumption_expand",
    ]
    if include_contract:
        names.append("0048_canonical_account_creation_consumption_contract")
    for name in names:
        MigrationRecorder.Migration.objects.get_or_create(app="account", name=name)


@pytest.mark.django_db(transaction=True)
def test_empty_but_complete_schema_is_a_stable_explicit_alias_snapshot() -> None:
    _record_required_migrations()

    first = inventory_canonical_account_creation_consumption(using="default")
    second = CanonicalAccountCreationConsumptionInventoryService(using="default").inspect()

    assert first == second
    assert first.database_alias == "default"
    assert first.backend == "sqlite"
    assert first.snapshot_isolation == "sqlite_atomic_read_snapshot_read_only_unenforced"
    assert first.closed_world_validated is True
    assert [ledger.ledger for ledger in first.ledgers] == [
        "allocation",
        "binding_v1",
        "consumption_claim",
        "binding_v2",
        "physical_v3_root",
    ]
    assert all(ledger.row_count == 0 for ledger in first.ledgers)
    assert first.consistency.is_consistent is True
    payload = json.loads(first.to_json())
    digest_payload = dict(payload)
    digest_payload.pop("snapshot_hash")
    stable = json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert first.snapshot_hash == hashlib.sha256(stable.encode("utf-8")).hexdigest()


@pytest.mark.django_db(transaction=True)
def test_expand_inventory_does_not_require_contract_migration() -> None:
    _record_required_migrations(include_contract=False)

    report = inventory_canonical_account_creation_consumption(using="default")

    assert not any(name.startswith("0048_") for name in report.applied_migrations)


@pytest.mark.django_db(transaction=True)
def test_missing_expand_migration_fails_closed_instead_of_returning_zero() -> None:
    _record_required_migrations(include_contract=False)
    MigrationRecorder.Migration.objects.filter(app="account", name__startswith="0047_").delete()

    with pytest.raises(
        CanonicalAccountCreationConsumptionInventoryUnavailable,
        match="0047_canonical_account_creation_consumption_expand",
    ):
        inventory_canonical_account_creation_consumption(using="default")


@pytest.mark.django_db(transaction=True)
def test_lookalike_expand_migration_name_fails_closed() -> None:
    _record_required_migrations()
    MigrationRecorder.Migration.objects.filter(
        app="account", name="0047_canonical_account_creation_consumption_expand"
    ).update(name="0047_lookalike")

    with pytest.raises(
        CanonicalAccountCreationConsumptionInventoryUnavailable,
        match="0047_canonical_account_creation_consumption_expand",
    ):
        inventory_canonical_account_creation_consumption(using="default")


@pytest.mark.django_db(transaction=True)
def test_missing_named_constraint_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_required_migrations()
    original = connection.introspection.get_constraints

    def without_claim_identity(cursor: object, table_name: str) -> dict[str, dict[str, object]]:
        constraints = dict(original(cursor, table_name))
        if table_name == "canonical_account_creation_consumption_claim_ledger":
            constraints.pop("acct_create_cons_claim_uq")
        return constraints

    monkeypatch.setattr(connection.introspection, "get_constraints", without_claim_identity)
    with pytest.raises(
        CanonicalAccountCreationConsumptionInventoryUnavailable,
        match="acct_create_cons_claim_uq",
    ):
        inventory_canonical_account_creation_consumption(using="default")


@pytest.mark.django_db(transaction=True)
def test_missing_required_column_fails_before_closed_world_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_required_migrations()
    original = connection.introspection.get_table_description

    def without_content_hash(cursor: object, table_name: str) -> list[object]:
        description = list(original(cursor, table_name))
        if table_name == "canonical_account_creation_consumption_claim_ledger":
            return [column for column in description if column.name != "content_hash"]
        return description

    monkeypatch.setattr(connection.introspection, "get_table_description", without_content_hash)
    with pytest.raises(
        CanonicalAccountCreationConsumptionInventoryUnavailable,
        match="content_hash",
    ):
        inventory_canonical_account_creation_consumption(using="default")


def test_using_is_mandatory_and_unknown_alias_fails_closed() -> None:
    with pytest.raises(ValueError, match="using"):
        CanonicalAccountCreationConsumptionInventoryService(using=" ")
    with pytest.raises(
        CanonicalAccountCreationConsumptionInventoryUnavailable,
        match="unknown database alias",
    ):
        inventory_canonical_account_creation_consumption(using="absent")
    with pytest.raises(ValueError, match="using"):
        CanonicalAccountCreationConsumptionInventoryService(using=1)  # type: ignore[arg-type]
